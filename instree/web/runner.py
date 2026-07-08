"""Exécution des scans en arrière-plan pour l'interface web."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import datetime

from instree.config import load_settings
from instree.errors import ScanCancelled
from instree.scan import ScanSummary, run_scan
from instree.session import connect


@dataclass
class ScanJob:
    state: str = "idle"
    mode: str = ""
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
    result: dict | None = None
    started_at: str | None = None
    finished_at: str | None = None


_lock = threading.Lock()
_cancel = threading.Event()
_job = ScanJob()


def _summary_dict(s: ScanSummary) -> dict:
    return {
        "scan_id": s.scan_id,
        "username": s.username,
        "tracked": s.tracked,
        "following_count": s.following_count,
        "added": s.added,
        "removed": s.removed,
        "counts": s.counts,
        "person_added": s.person_added,
        "person_removed": s.person_removed,
        "unchanged": s.unchanged,
        "journal_path": s.journal_path,
    }


def job_status() -> dict:
    with _lock:
        return asdict(_job)


def start_scan(*, init: bool = False) -> None:
    with _lock:
        if _job.state == "running":
            raise RuntimeError("Un scan est déjà en cours")

    _cancel.clear()
    mode = "init" if init else "incremental"
    thread = threading.Thread(target=_worker, args=(init, mode), daemon=True)
    thread.start()


def cancel_scan() -> bool:
    """Demande l'arrêt du scan en cours. Retourne False si aucun scan actif."""
    with _lock:
        if _job.state != "running":
            return False
    _cancel.set()
    return True


def _worker(init: bool, mode: str) -> None:
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

    def should_cancel() -> bool:
        return _cancel.is_set()

    with _lock:
        _job = ScanJob(
            state="running",
            mode=mode,
            started_at=datetime.now().isoformat(timespec="seconds"),
        )

    try:
        settings = load_settings()
        ig, _source, _note = connect()
        summary = run_scan(
            ig,
            settings,
            init=init,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
        with _lock:
            _job.state = "done"
            _job.result = _summary_dict(summary)
            if summary.unchanged:
                _job.message_key = "job.unchanged"
                _job.message = "Inchangé"
            else:
                _job.message_key = "job.done"
                _job.message = f"Scan #{summary.scan_id} terminé"
            _job.finished_at = datetime.now().isoformat(timespec="seconds")
    except ScanCancelled:
        with _lock:
            _job.state = "cancelled"
            _job.message_key = "job.cancelled"
            _job.message = "Scan annulé"
            _job.finished_at = datetime.now().isoformat(timespec="seconds")
    except Exception as e:
        with _lock:
            _job.state = "error"
            _job.message_key = ""
            _job.message = str(e)
            _job.finished_at = datetime.now().isoformat(timespec="seconds")
    finally:
        _cancel.clear()


def reset_job() -> None:
    """Remet l'état à idle après affichage du résultat."""
    global _job
    with _lock:
        if _job.state != "running":
            _job = ScanJob()
