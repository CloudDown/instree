"""Exécution des scans en arrière-plan pour l'interface web."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field

from instree.core.config import (
    current_user_id,
    is_web_mode,
    load_settings,
    reset_current_user,
    set_current_user,
)
from instree.core.errors import ScanCancelled
from instree.core.log import get_logger
from instree.core.scan import run_scan
from instree.core.session import connect

log = get_logger("runner")

_ACTIVE_STATES = frozenset({"running", "stopping"})


def _is_session_error(message: str) -> bool:
    msg = message.lower()
    return any(
        token in msg
        for token in (
            "session toml invalide",
            "expirée",
            "expired",
            "login_required",
            "pas de session configurée",
        )
    )


def _persist_session_alert(user_key: str, message: str) -> None:
    if not is_web_mode() or user_key == "local":
        return
    if not _is_session_error(message):
        return
    from datetime import datetime, timezone

    from instree.core.config import active_profile_id
    from instree.web.schedule_state import set_scan_alert

    set_scan_alert(
        user_key,
        {
            "kind": "session_expired",
            "message": message,
            "at": datetime.now(timezone.utc).isoformat(),
            "profile_id": active_profile_id(),
        },
    )


@dataclass
class ScanJob:
    state: str = "idle"
    is_baseline: bool = False
    progress_current: int = 0
    progress_total: int = 0
    progress_user: str = ""
    progress_phase: str = ""
    watch_current: int = 0
    watch_total: int = 0
    watch_user: str = ""
    watch_phase: str = ""
    message: str = ""
    message_key: str = ""
    cooldown_until: float = 0.0
    result: dict | None = None


@dataclass
class _JobSlot:
    job: ScanJob = field(default_factory=ScanJob)
    cancel: threading.Event = field(default_factory=threading.Event)


_lock = threading.Lock()
_slots: dict[str, _JobSlot] = {}
_threads: dict[str, threading.Thread] = {}


def _reconcile_job(user_id: str | None = None) -> None:
    """Remet le job à idle si le thread de scan n'existe plus."""
    try:
        key = _user_key(user_id)
    except RuntimeError:
        return
    slot = _slot(user_id)
    thread = _threads.get(key)
    with _lock:
        if slot.job.state in _ACTIVE_STATES and (
            thread is None or not thread.is_alive()
        ):
            slot.job = ScanJob()
            _threads.pop(key, None)


def _user_key(user_id: str | None = None) -> str:
    if user_id:
        return user_id
    if is_web_mode():
        uid = current_user_id()
        if not uid:
            raise RuntimeError("utilisateur requis")
        return uid
    return "local"


def _slot(user_id: str | None = None) -> _JobSlot:
    key = _user_key(user_id)
    with _lock:
        if key not in _slots:
            _slots[key] = _JobSlot()
        return _slots[key]


def job_status(user_id: str | None = None) -> dict:
    _reconcile_job(user_id)
    slot = _slot(user_id)
    with _lock:
        return asdict(slot.job)


def start_scan(*, init: bool = False, user_id: str | None = None) -> None:
    key = _user_key(user_id)
    slot = _slot(key)
    with _lock:
        if slot.job.state in _ACTIVE_STATES:
            raise RuntimeError("Un scan est déjà en cours")

    is_baseline = init
    token = None
    if key != "local":
        token = set_current_user(key)
    try:
        if init:
            from instree.core.store import reset_baseline_state

            reset_baseline_state()
        else:
            from instree.core.store import (
                clear_scan_history,
                get_scan_draft,
                has_scans,
                scan_resume_info,
            )

            info = scan_resume_info()
            if info.get("can_resume") and info.get("is_baseline") and has_scans():
                clear_scan_history()
            draft = get_scan_draft()
            is_baseline = bool(
                (draft and draft.is_baseline) or info.get("is_baseline")
            )
    finally:
        if token is not None:
            reset_current_user(token)

    slot.cancel.clear()
    thread = threading.Thread(
        target=_worker,
        args=(init, key, is_baseline),
        daemon=True,
        name=f"instree-scan-{key}",
    )
    _threads[key] = thread
    log.info(
        "scan démarré  user=%s  init=%s  baseline=%s",
        key,
        init,
        is_baseline,
    )
    thread.start()


def cancel_scan(user_id: str | None = None) -> bool:
    """Demande l'arrêt du scan en cours. Retourne False si aucun scan actif."""
    slot = _slot(user_id)
    with _lock:
        if slot.job.state not in _ACTIVE_STATES:
            return False
        slot.job.state = "stopping"
        slot.job.message_key = "job.stopping"
        slot.job.message = "Arrêt demandé…"
        slot.job.cooldown_until = 0.0
    slot.cancel.set()
    return True


def _worker(init: bool, user_key: str, is_baseline: bool = False) -> None:
    slot = _slot(user_key)
    token = None
    if user_key != "local":
        token = set_current_user(user_key)

    def on_progress(
        current: int,
        total: int,
        username: str,
        phase: str = "profile",
        *,
        track: str = "profiles",
    ) -> None:
        with _lock:
            if track == "watch":
                slot.job.watch_current = current
                slot.job.watch_total = total
                slot.job.watch_user = username
                slot.job.watch_phase = phase
            else:
                slot.job.progress_current = current
                slot.job.progress_total = total
                slot.job.progress_user = username
                slot.job.progress_phase = phase

    def on_cooldown(until: float) -> None:
        with _lock:
            slot.job.cooldown_until = float(until or 0)
            if until and until > 0:
                slot.job.message_key = "job.rateLimited"
                slot.job.message = "Instagram limite les requêtes — pause…"
                if slot.job.progress_phase != "mutuals":
                    slot.job.progress_phase = "cooldown"
                log.warning(
                    "rate limit Instagram  user=%s  pause=%.0fs  phase=%s",
                    user_key,
                    until,
                    slot.job.progress_phase or "?",
                )
            else:
                if slot.job.message_key == "job.rateLimited":
                    slot.job.message_key = ""
                    slot.job.message = ""
                if slot.job.progress_phase == "cooldown":
                    slot.job.progress_phase = ""

    def should_cancel() -> bool:
        return slot.cancel.is_set()

    with _lock:
        slot.job = ScanJob(state="running", is_baseline=bool(is_baseline or init))

    ig_user = "?"
    try:
        settings = load_settings()
        ig, _source, _note = connect()
        try:
            ig_user = ig.account_info().username
        except Exception:
            pass
        log.info(
            "scan en cours  user=%s  @%s  init=%s  baseline=%s",
            user_key,
            ig_user,
            init,
            is_baseline,
        )
        summary = run_scan(
            ig,
            settings,
            init=init,
            on_progress=on_progress,
            should_cancel=should_cancel,
            on_cooldown=on_cooldown,
        )
        with _lock:
            slot.job.state = "done"
            slot.job.cooldown_until = 0.0
            slot.job.result = {"scan_id": summary.scan_id}
            if summary.unchanged:
                slot.job.message_key = "job.unchanged"
                slot.job.message = "Inchangé"
            else:
                slot.job.message_key = "job.done"
                slot.job.message = f"Scan #{summary.scan_id} terminé"
        log.info(
            "scan OK  user=%s  @%s  scan_id=%s  unchanged=%s  journal=%s",
            user_key,
            summary.username,
            summary.scan_id,
            summary.unchanged,
            summary.journal_path or "-",
        )
        if init and is_web_mode() and user_key != "local":
            from instree.web.web_scheduler import on_baseline_completed

            on_baseline_completed(user_key)
    except ScanCancelled:
        try:
            from instree.core.store import abandon_interrupted_scan

            abandon_interrupted_scan()
        except Exception:
            pass
        with _lock:
            slot.job.state = "cancelled"
            slot.job.cooldown_until = 0.0
            slot.job.message_key = "job.cancelled"
            slot.job.message = "Scan annulé"
        log.warning("scan annulé  user=%s  @%s", user_key, ig_user)
    except Exception as e:
        msg = str(e)
        is_session = _is_session_error(msg)
        with _lock:
            slot.job.state = "error"
            slot.job.cooldown_until = 0.0
            slot.job.message_key = "job.sessionExpired" if is_session else ""
            slot.job.message = msg
        if is_session:
            _persist_session_alert(user_key, msg)
        log.error("scan échoué  user=%s  @%s  %s: %s", user_key, ig_user, type(e).__name__, e)
    finally:
        slot.cancel.clear()
        _threads.pop(user_key, None)
        if token is not None:
            reset_current_user(token)


def reset_job(user_id: str | None = None) -> None:
    """Remet l'état à idle après affichage du résultat."""
    slot = _slot(user_id)
    with _lock:
        if slot.job.state not in _ACTIVE_STATES:
            slot.job = ScanJob()
