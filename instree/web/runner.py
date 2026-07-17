"""Exécution des scans en arrière-plan pour l'interface web."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass

from instree.config import load_settings
from instree.errors import ScanCancelled
from instree.scan import run_scan
from instree.session import connect

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


_lock = threading.Lock()
_cancel = threading.Event()
_job = ScanJob()


def job_status() -> dict:
    with _lock:
        return asdict(_job)


def start_scan(*, init: bool = False) -> None:
    with _lock:
        if _job.state in _ACTIVE_STATES:
            raise RuntimeError("Un scan est déjà en cours")

    _cancel.clear()
    thread = threading.Thread(target=_worker, args=(init,), daemon=True)
    thread.start()


def cancel_scan() -> bool:
    """Demande l'arrêt du scan en cours. Retourne False si aucun scan actif."""
    with _lock:
        if _job.state not in _ACTIVE_STATES:
            return False
        _job.state = "stopping"
        _job.message_key = "job.stopping"
        _job.message = "Arrêt demandé…"
        _job.cooldown_until = 0.0
    _cancel.set()
    return True


def _worker(init: bool) -> None:
    global _job

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
                _job.watch_current = current
                _job.watch_total = total
                _job.watch_user = username
                _job.watch_phase = phase
            else:
                _job.progress_current = current
                _job.progress_total = total
                _job.progress_user = username
                _job.progress_phase = phase

    def on_cooldown(until: float) -> None:
        with _lock:
            _job.cooldown_until = float(until or 0)
            if until and until > 0:
                _job.message_key = "job.rateLimited"
                _job.message = "Instagram limite les requêtes — pause…"
                if _job.progress_phase != "mutuals":
                    _job.progress_phase = "cooldown"
            else:
                if _job.message_key == "job.rateLimited":
                    _job.message_key = ""
                    _job.message = ""
                if _job.progress_phase == "cooldown":
                    _job.progress_phase = ""

    def should_cancel() -> bool:
        return _cancel.is_set()

    with _lock:
        _job = ScanJob(state="running")

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
            _job.state = "done"
            _job.cooldown_until = 0.0
            _job.result = {"scan_id": summary.scan_id}
            if summary.unchanged:
                _job.message_key = "job.unchanged"
                _job.message = "Inchangé"
            else:
                _job.message_key = "job.done"
                _job.message = f"Scan #{summary.scan_id} terminé"
    except ScanCancelled:
        with _lock:
            _job.state = "cancelled"
            _job.cooldown_until = 0.0
            _job.message_key = "job.cancelled"
            _job.message = "Scan annulé"
    except Exception as e:
        with _lock:
            _job.state = "error"
            _job.cooldown_until = 0.0
            _job.message_key = ""
            _job.message = str(e)
    finally:
        _cancel.clear()


def reset_job() -> None:
    """Remet l'état à idle après affichage du résultat."""
    global _job
    with _lock:
        if _job.state not in _ACTIVE_STATES:
            _job = ScanJob()
