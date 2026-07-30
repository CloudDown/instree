"""Planificateur Instree Web — baseline à l'inscription + scan quotidien."""

from __future__ import annotations

import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from instree.core.config import (
    active_profile_id,
    is_web_mode,
    list_profiles,
    load_server_schedule_settings,
    load_settings,
    reset_current_user,
    set_active_profile,
    set_current_user,
)
from instree.core.log import get_logger
from instree.core.store import has_scans, scan_resume_info
from instree.web.accounts import (
    clear_pending_baseline,
    get_pending_baseline,
    list_user_ids,
    set_pending_baseline,
)
from instree.web.runner import job_status, start_scan
from instree.web.schedule_state import (
    begin_daily_item,
    clear_daily_inflight,
    clear_daily_restore,
    daily_inflight,
    daily_queue,
    daily_restore_active,
    last_daily_date,
    mark_daily_run,
    set_daily_batch,
)

_stop = threading.Event()
_thread: threading.Thread | None = None
_ACTIVE = frozenset({"running", "stopping"})
log = get_logger("scheduler")


def _user_has_session(user_id: str) -> bool:
    token = set_current_user(user_id)
    try:
        return bool(load_settings().sessionid)
    finally:
        reset_current_user(token)


def _user_has_any_session(user_id: str) -> bool:
    token = set_current_user(user_id)
    try:
        return any(p.get("sessionid_set") for p in list_profiles())
    finally:
        reset_current_user(token)


def try_start_pending_baseline(user_id: str) -> bool:
    """Lance la baseline initiale si le compte l'attend et la session IG est prête."""
    if not is_web_mode():
        return False
    if not get_pending_baseline(user_id):
        return False
    token = set_current_user(user_id)
    try:
        if scan_resume_info().get("can_resume"):
            return False
    finally:
        reset_current_user(token)
    if not _user_has_session(user_id):
        return False
    if job_status(user_id).get("state") in _ACTIVE:
        return False
    log.info("baseline initiale  user=%s", user_id)
    start_scan(init=True, user_id=user_id)
    return True


def _needs_initial_baseline() -> bool:
    """True si aucun scan, ou dernier scan vide (0 mutuel tracké)."""
    if not has_scans():
        return True
    from instree.core.store import list_scans

    scans = list_scans()
    if not scans:
        return True
    latest = scans[-1] if isinstance(scans[-1], dict) else None
    if not latest:
        return True
    return int(latest.get("tracked_count") or 0) <= 0


def try_start_baseline_after_session(user_id: str) -> bool:
    """Après enregistrement de session : reprendre un brouillon, ou lancer
    une baseline si le compte n'a pas encore de données utiles.
    """
    if not is_web_mode():
        return False
    if not _user_has_session(user_id):
        return False
    if job_status(user_id).get("state") in _ACTIVE:
        return False

    token = set_current_user(user_id)
    try:
        can_resume = bool(scan_resume_info().get("can_resume"))
        needs_baseline = _needs_initial_baseline()
    finally:
        reset_current_user(token)

    if can_resume:
        return try_resume_interrupted_scan(user_id)

    # Pas de données utiles : re-armer pending (session recollée, baseline vide…).
    if needs_baseline:
        set_pending_baseline(user_id, True)
    return try_start_pending_baseline(user_id)


def try_resume_interrupted_scan(user_id: str) -> bool:
    """Reprend un scan interrompu (pas de bouton manuel en mode web)."""
    token = set_current_user(user_id)
    try:
        can = bool(scan_resume_info().get("can_resume"))
    finally:
        reset_current_user(token)
    if not can:
        return False
    if not _user_has_session(user_id):
        return False
    if job_status(user_id).get("state") in _ACTIVE:
        return False
    start_scan(init=False, user_id=user_id)
    return True


def _restore_active_if_batch_done(user_id: str) -> None:
    """Remet la session active d'origine une fois le lot quotidien terminé."""
    if daily_queue(user_id) or daily_inflight(user_id):
        return
    if not daily_restore_active(user_id):
        return
    restore = clear_daily_restore(user_id)
    if not restore:
        return
    token = set_current_user(user_id)
    try:
        set_active_profile(restore)
    except ValueError:
        pass
    finally:
        reset_current_user(token)


def _tick_daily(user_id: str, *, daily_hour: int, timezone: str) -> None:
    """À l'heure prévue : enfile toutes les sessions avec cookies, puis les
    enchaîne une par une (un job par compte à la fois).
    """
    if get_pending_baseline(user_id):
        return
    if not _user_has_any_session(user_id):
        return

    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("UTC")

    now = datetime.now(tz)
    today = now.date().isoformat()

    if job_status(user_id).get("state") in _ACTIVE:
        return

    # Scan quotidien précédent terminé (job idle).
    if daily_inflight(user_id):
        inflight_pid = daily_inflight(user_id)
        status = job_status(user_id)
        state = status.get("state", "idle")
        clear_daily_inflight(user_id)
        if not daily_queue(user_id):
            if state == "done":
                mark_daily_run(user_id, today)
                log.info(
                    "scan quotidien OK  user=%s  profile=%s  scan_id=%s  msg=%s",
                    user_id,
                    inflight_pid,
                    (status.get("result") or {}).get("scan_id"),
                    status.get("message") or "-",
                )
            elif state == "error":
                log.error(
                    "scan quotidien échoué  user=%s  profile=%s  erreur=%s",
                    user_id,
                    inflight_pid,
                    status.get("message") or "?",
                )
            elif state == "cancelled":
                log.warning(
                    "scan quotidien annulé  user=%s  profile=%s",
                    user_id,
                    inflight_pid,
                )
            else:
                log.warning(
                    "scan quotidien état inattendu  user=%s  profile=%s  state=%s",
                    user_id,
                    inflight_pid,
                    state,
                )
            _restore_active_if_batch_done(user_id)
            return

    queue = daily_queue(user_id)

    # Lot du jour déjà terminé.
    if last_daily_date(user_id) == today and not queue and not daily_inflight(user_id):
        _restore_active_if_batch_done(user_id)
        return

    # Nouvelle journée à l'heure du scan : construire la file.
    if not queue and not daily_inflight(user_id):
        if now.hour != daily_hour:
            return
        if last_daily_date(user_id) == today:
            return
        token = set_current_user(user_id)
        try:
            restore = active_profile_id()
            queue = [p["id"] for p in list_profiles() if p.get("sessionid_set")]
            if not queue:
                log.warning(
                    "scan quotidien ignoré  user=%s  raison=pas_de_session_IG",
                    user_id,
                )
                mark_daily_run(user_id, today)
                return
            log.info(
                "scan quotidien planifié  user=%s  profiles=%s  heure=%02d:00 %s",
                user_id,
                queue,
                daily_hour,
                timezone,
            )
            set_daily_batch(user_id, queue=queue, restore_active=restore)
        finally:
            reset_current_user(token)
        queue = daily_queue(user_id)

    if not queue:
        return

    pid = queue[0]
    token = set_current_user(user_id)
    try:
        set_active_profile(pid)
        # Reprise d'un brouillon sur cette session si besoin.
        can_resume = bool(scan_resume_info().get("can_resume"))
        init = (not can_resume) and (not has_scans())
        begin_daily_item(user_id, pid)
        log.info(
            "scan quotidien démarré  user=%s  profile=%s  init=%s",
            user_id,
            pid,
            init,
        )
        start_scan(init=init, user_id=user_id)
    except (RuntimeError, ValueError) as e:
        log.error(
            "scan quotidien non démarré  user=%s  profile=%s  %s",
            user_id,
            pid,
            e,
        )
        # Remettre en tête si le démarrage a échoué.
        remaining = daily_queue(user_id)
        set_daily_batch(
            user_id,
            queue=[pid, *remaining],
            restore_active=daily_restore_active(user_id),
        )
        clear_daily_inflight(user_id)
    finally:
        reset_current_user(token)


def _tick_user(user_id: str) -> None:
    schedule = load_server_schedule_settings()
    # Pendant un lot quotidien, ne pas laisser la reprise voler une autre session.
    if daily_queue(user_id) or daily_inflight(user_id):
        if try_resume_interrupted_scan(user_id):
            return
        _tick_daily(
            user_id,
            daily_hour=schedule["daily_hour"],
            timezone=schedule["timezone"],
        )
        return
    if try_resume_interrupted_scan(user_id):
        return
    if try_start_pending_baseline(user_id):
        return
    _tick_daily(
        user_id,
        daily_hour=schedule["daily_hour"],
        timezone=schedule["timezone"],
    )


def _loop() -> None:
    while not _stop.is_set():
        if is_web_mode():
            try:
                for uid in list_user_ids():
                    if _stop.is_set():
                        break
                    _tick_user(uid)
            except Exception:
                log.exception("erreur planificateur")
        if _stop.wait(timeout=60):
            break


def start_web_scheduler() -> None:
    global _thread
    if not is_web_mode():
        return
    _stop.clear()
    if _thread is not None and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, name="instree-web-schedule", daemon=True)
    _thread.start()


def stop_web_scheduler() -> None:
    _stop.set()
    if _thread is not None and _thread.is_alive():
        _thread.join(timeout=2)


def on_baseline_completed(user_id: str) -> None:
    if get_pending_baseline(user_id):
        clear_pending_baseline(user_id)
