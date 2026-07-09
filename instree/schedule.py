"""Installation du timer systemd depuis instree.toml."""

import shutil
import sys
from pathlib import Path

from instree.config import Settings, project_root


def times_to_on_calendar(times: tuple[str, ...]) -> list[str]:
    """Convertit des heures HH:MM en lignes OnCalendar systemd."""
    by_minute: dict[str, list[int]] = {}
    for t in times:
        h, m = t.split(":")
        by_minute.setdefault(m, []).append(int(h))
    lines = []
    for minute in sorted(by_minute, key=int):
        hours = ",".join(f"{h:02d}" for h in sorted(set(by_minute[minute])))
        lines.append(f"*-*-* {hours}:{minute}:00")
    return lines


def resolve_scan_command(root: Path) -> str:
    """Chemin/commande absolue pour `instree scan -q` (systemd)."""
    candidates = [
        root / ".venv" / "bin" / "instree",
        Path(sys.executable).parent / "instree",
    ]
    for binary in candidates:
        if binary.is_file():
            return f"{binary} scan -q"

    on_path = shutil.which("instree")
    if on_path:
        return f"{on_path} scan -q"

    for py in (root / ".venv" / "bin" / "python", Path(sys.executable)):
        if py.is_file():
            return f"{py} -m instree.cli scan -q"

    raise RuntimeError(
        "instree introuvable — depuis le dépôt : uv sync (ou pip install -e .)"
    )


def render_service(root: Path, exec_start: str) -> str:
    log = root / "data" / "scheduler.log"
    return f"""[Unit]
Description=Instree — scan abonnements Instagram
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory={root}
ExecStart={exec_start}
StandardOutput=append:{log}
StandardError=append:{log}

[Install]
WantedBy=default.target
"""


def render_timer(times: tuple[str, ...], interval_minutes: int = 0) -> str:
    timer_lines: list[str] = []
    desc_parts: list[str] = []
    if times:
        calendars = times_to_on_calendar(times)
        timer_lines.extend(f"OnCalendar={c}" for c in calendars)
        desc_parts.append(", ".join(times))
    if interval_minutes > 0:
        timer_lines.append(f"OnUnitActiveSec={interval_minutes}min")
        desc_parts.append(f"toutes les {interval_minutes} min")
    if not timer_lines:
        raise ValueError("aucune planification (heures ou intervalle)")
    label = " + ".join(desc_parts)
    calendar_lines = "\n".join(timer_lines)
    return f"""[Unit]
Description=Instree — scan planifié ({label})

[Timer]
{calendar_lines}
Persistent=true
Unit=instree-scan.service

[Install]
WantedBy=timers.target
"""


def install_systemd(settings: Settings) -> tuple[Path, Path, str]:
    """Écrit les unités dans ~/.config/systemd/user/."""
    if not settings.schedule_times and settings.schedule_interval_minutes <= 0:
        raise RuntimeError(
            "[schedule] times vide et interval_minutes = 0 dans instree.toml"
        )

    root = project_root().resolve()
    if not (root / "instree.toml").is_file():
        raise RuntimeError(
            f"instree.toml introuvable dans {root} — lance la commande depuis le dépôt cloné"
        )

    exec_start = resolve_scan_command(root)
    (root / "data").mkdir(parents=True, exist_ok=True)

    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)

    service_path = unit_dir / "instree-scan.service"
    timer_path = unit_dir / "instree-scan.timer"

    service_path.write_text(render_service(root, exec_start), encoding="utf-8")
    timer_path.write_text(
        render_timer(settings.schedule_times, settings.schedule_interval_minutes),
        encoding="utf-8",
    )

    return unit_dir, root, exec_start
