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
from instree.core.scan import run_scan
from instree.core.session import connect

_ACTIVE_STATES = frozenset({"running", "stopping"})


@dataclass
class ScanJob:
    state: str = "idle"
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
    slot = _slot(user_id)
    with _lock:
        return asdict(slot.job)


def start_scan(*, init: bool = False, user_id: str | None = None) -> None:
    key = _user_key(user_id)
    slot = _slot(key)
    with _lock:
        if slot.job.state in _ACTIVE_STATES:
            raise RuntimeError("Un scan est déjà en cours")

    slot.cancel.clear()
    thread = threading.Thread(
        target=_worker, args=(init, key), daemon=True, name=f"instree-scan-{key}"
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


def _worker(init: bool, user_key: str) -> None:
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
            else:
                if slot.job.message_key == "job.rateLimited":
                    slot.job.message_key = ""
                    slot.job.message = ""
                if slot.job.progress_phase == "cooldown":
                    slot.job.progress_phase = ""

    def should_cancel() -> bool:
        return slot.cancel.is_set()

    with _lock:
        slot.job = ScanJob(state="running")

    try:
        settings = load_settings()
        ig, _source, _note = connect()
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
    except ScanCancelled:
        with _lock:
            slot.job.state = "cancelled"
            slot.job.cooldown_until = 0.0
            slot.job.message_key = "job.cancelled"
            slot.job.message = "Scan annulé"
    except Exception as e:
        with _lock:
            slot.job.state = "error"
            slot.job.cooldown_until = 0.0
            slot.job.message_key = ""
            slot.job.message = str(e)
    finally:
        slot.cancel.clear()
        if token is not None:
            reset_current_user(token)


def reset_job(user_id: str | None = None) -> None:
    """Remet l'état à idle après affichage du résultat."""
    slot = _slot(user_id)
    with _lock:
        if slot.job.state not in _ACTIVE_STATES:
            slot.job = ScanJob()
