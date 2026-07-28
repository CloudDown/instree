"""Planificateur Instree Web — baseline à l'inscription + scan quotidien."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from instree.core.config import (
    is_web_mode,
    load_server_schedule_settings,
    load_settings,
    reset_current_user,
    set_current_user,
)
from instree.core.store import has_scans, scan_resume_info
from instree.web.accounts import (
    clear_pending_baseline,
    get_pending_baseline,
    list_user_ids,
    set_pending_baseline,
)
from instree.web.runner import job_status, start_scan
from instree.web.schedule_state import last_daily_date, mark_daily_run

_stop = threading.Event()
_thread: threading.Thread | None = None
_ACTIVE = frozenset({"running", "stopping"})


def _user_has_session(user_id: str) -> bool:
    token = set_current_user(user_id)
    try:
        return bool(load_settings().sessionid)
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


def _tick_daily(user_id: str, *, daily_hour: int, timezone: str) -> None:
    if get_pending_baseline(user_id):
        return
    if not _user_has_session(user_id):
        return
    if job_status(user_id).get("state") in _ACTIVE:
        return

    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("UTC")

    now = datetime.now(tz)
    if now.hour != daily_hour:
        return

    today = now.date().isoformat()
    if last_daily_date(user_id) == today:
        return

    token = set_current_user(user_id)
    try:
        if not has_scans():
            start_scan(init=True, user_id=user_id)
        else:
            start_scan(init=False, user_id=user_id)
        mark_daily_run(user_id, today)
    except RuntimeError:
        pass
    finally:
        reset_current_user(token)


def _tick_user(user_id: str) -> None:
    schedule = load_server_schedule_settings()
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
                pass
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
