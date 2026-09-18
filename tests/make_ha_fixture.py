"""Write a disposable HA check_config fixture; do not point at an active config."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from igw_google_voice.__main__ import render_files, write_files  # noqa: E402
from igw_google_voice.cast_ha import render_cast_trigger_files  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New disposable fixture directory.")
    parser.add_argument("--adapter", choices=("tts", "cast"), default="tts",
                        help="Validate the original TTS adapter or the optional Cast service trigger.")
    args = parser.parse_args()
    if args.adapter == "cast":
        files = render_cast_trigger_files("http://192.168.50.8:8090")
        secrets = 'igw_cast_authorization: "Bearer offline-test-not-a-credential"\n'
    else:
        files = render_files(
            igw_url="http://inverter-gateway.energy.svc.cluster.local:8080/v1/energy",
            tts_entity="tts.test_provider",
            media_player="media_player.test_nest",
            allow_local_http=True,
        )
        secrets = (
            'igw_energy_url: "http://inverter-gateway.energy.svc.cluster.local:8080/v1/energy"\n'
            'igw_energy_authorization: "Bearer offline-test-not-a-credential"\n'
        )
    files[Path("configuration.yaml")] = (
        "homeassistant:\n"
        "  name: IGW offline schema validation\n"
        "  time_zone: UTC\n"
        "  packages: !include_dir_named packages\n"
    )
    files[Path("secrets.yaml")] = secrets
    write_files(args.output, files)
    (args.output / "secrets.yaml").chmod(0o600)
    print(f"Wrote an offline HA {args.adapter} validation fixture with fake credentials.")


if __name__ == "__main__":
    main()
