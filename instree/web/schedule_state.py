"""État planificateur par compte Web (persistant après redémarrage)."""

from __future__ import annotations

import json

from instree.core.config import user_home


def _read(user_id: str) -> dict:
    path = user_home(user_id) / "schedule_state.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(user_id: str, state: dict) -> None:
    path = user_home(user_id) / "schedule_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def last_daily_date(user_id: str) -> str | None:
    raw = _read(user_id).get("last_daily_date")
    return str(raw) if raw else None


def mark_daily_run(user_id: str, date_iso: str) -> None:
    state = _read(user_id)
    state["last_daily_date"] = date_iso
    _write(user_id, state)
