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


def daily_queue(user_id: str) -> list[str]:
    raw = _read(user_id).get("daily_queue")
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if str(x).strip()]


def daily_restore_active(user_id: str) -> str | None:
    raw = _read(user_id).get("daily_restore_active")
    return str(raw) if raw else None


def daily_inflight(user_id: str) -> str | None:
    raw = _read(user_id).get("daily_inflight")
    return str(raw) if raw else None


def set_daily_batch(
    user_id: str,
    *,
    queue: list[str],
    restore_active: str | None,
) -> None:
    state = _read(user_id)
    state["daily_queue"] = list(queue)
    state.pop("daily_inflight", None)
    if restore_active:
        state["daily_restore_active"] = restore_active
    elif "daily_restore_active" in state:
        del state["daily_restore_active"]
    _write(user_id, state)


def begin_daily_item(user_id: str, profile_id: str) -> list[str]:
    """Passe la tête de file en « en cours » (atomique)."""
    state = _read(user_id)
    queue = [str(x) for x in (state.get("daily_queue") or []) if str(x).strip()]
    if not queue or queue[0] != profile_id:
        return queue
    state["daily_queue"] = queue[1:]
    state["daily_inflight"] = profile_id
    _write(user_id, state)
    return list(state["daily_queue"])


def clear_daily_inflight(user_id: str) -> None:
    state = _read(user_id)
    if "daily_inflight" not in state:
        return
    state.pop("daily_inflight", None)
    _write(user_id, state)


def clear_daily_restore(user_id: str) -> str | None:
    """Enlève et renvoie le profil à restaurer après le lot quotidien."""
    state = _read(user_id)
    restore = state.pop("daily_restore_active", None)
    _write(user_id, state)
    return str(restore) if restore else None
