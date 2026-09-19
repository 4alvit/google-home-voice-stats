"""Copy optional HA blueprints into a reviewable staging directory."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import sysconfig

from .__main__ import write_files

BLUEPRINT_NAMES = ("battery_reserve.yaml", "energy_condition.yaml", "daily_briefing.yaml")
BLUEPRINT_ROOT = Path("blueprints/automation/igw")


def render_files() -> dict[Path, str]:
    files = {}
    for name in BLUEPRINT_NAMES:
        relative = BLUEPRINT_ROOT / name
        candidates = (
            Path(__file__).resolve().parent.parent / relative,
            Path(sysconfig.get_path("data")) / "share/igw-google-voice" / relative,
        )
        source = next((path for path in candidates if path.is_file()), None)
        if source is None:
            raise ValueError("Automation blueprint asset is missing; reinstall the complete package.")
        files[relative] = source.read_text(encoding="utf-8")
    files[Path("INSTALL.md")] = (
        "# Optional Home Energy automations\n\n"
        "No automation or notification has been enabled.\n\n"
        "Copy blueprints/automation/igw into your HA configuration and reload blueprints.\n"
        "Create only the automations you want using HA's blueprint UI.\n"
        "For alerts, select authoritative, freshness-qualified entities and a dedicated\n"
        "restoring input_boolean helper for each notification episode. Configure thresholds,\n"
        "allowed hours and an existing notification service. Never infer grid loss from zero watts.\n"
        "The default notification stays inside HA; phone delivery needs the intended named\n"
        "notify service accepting title and message. Recipients are never selected automatically.\n"
        "For a briefing, choose the existing public report script, time and weekdays.\n"
        "Playback goes to its configured display and can interrupt current media.\n\n"
        "Read docs/automations.md in the repository for configuration, testing and limitations.\n"
    )
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        write_files(args.output, render_files())
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Optional automation blueprints rendered; nothing was enabled in Home Assistant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
