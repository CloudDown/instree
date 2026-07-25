"""Scan automatique toutes les N minutes pendant que le serveur web tourne."""

from __future__ import annotations

import threading
import time

from instree.core.config import (
    is_web_mode,
    load_settings,
    reset_current_user,
    set_current_user,
)
from instree.web.runner import job_status, start_scan

_stop = threading.Event()
_thread: threading.Thread | None = None
_last_run: dict[str, float] = {}


def _tick_user(user_id: str | None) -> None:
    """Déclenche un scan si l'intervalle du compte / local est écoulé."""
    key = user_id or "local"
    token = set_current_user(user_id) if user_id else None
    try:
        settings = load_settings()
        interval = settings.schedule_interval_minutes
        if interval <= 0:
            return
        now = time.time()
        last = _last_run.get(key, 0.0)
        if now - last < interval * 60:
            return
        if job_status(user_id).get("state") in ("running", "stopping"):
            return
        start_scan(init=False, user_id=user_id)
        _last_run[key] = now
    except RuntimeError:
        pass
    finally:
        if token is not None:
            reset_current_user(token)


def _loop() -> None:
    while not _stop.is_set():
        if is_web_mode():
            try:
                from instree.web.accounts import list_user_ids

                for uid in list_user_ids():
                    if _stop.is_set():
                        break
                    _tick_user(uid)
            except Exception:
                pass
        else:
            _tick_user(None)
        if _stop.wait(timeout=60):
            break


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
