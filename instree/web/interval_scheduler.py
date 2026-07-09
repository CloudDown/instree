"""Scan automatique toutes les N minutes pendant que le serveur web tourne."""

from __future__ import annotations

import threading

from instree.config import load_settings
from instree.web.runner import job_status, start_scan

_stop = threading.Event()
_thread: threading.Thread | None = None


def _loop() -> None:
    while not _stop.is_set():
        settings = load_settings()
        interval = settings.schedule_interval_minutes
        if interval <= 0:
            if _stop.wait(timeout=60):
                break
            continue
        if _stop.wait(timeout=interval * 60):
            break
        if _stop.is_set():
            break
        if job_status().get("state") == "running":
            continue
        try:
            start_scan(init=False)
        except RuntimeError:
            pass


def start_interval_scheduler() -> None:
    global _thread
    _stop.clear()
    if _thread is not None and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, name="instree-interval", daemon=True)
    _thread.start()


def stop_interval_scheduler() -> None:
    _stop.set()
    if _thread is not None and _thread.is_alive():
        _thread.join(timeout=2)
