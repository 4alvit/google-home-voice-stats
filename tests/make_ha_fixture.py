"""Write a disposable HA check_config fixture; do not point at an active config."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from igw_google_voice.__main__ import render_files, write_files  # noqa: E402


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 tests/make_ha_fixture.py NEW_OUTPUT_DIRECTORY")
    files = render_files(
        igw_url="http://inverter-gateway.energy.svc.cluster.local:8080/v1/energy",
        tts_entity="tts.test_provider",
        media_player="media_player.test_nest",
        allow_local_http=True,
    )
    files[Path("configuration.yaml")] = (
        "homeassistant:\n"
        "  name: IGW offline schema validation\n"
        "  time_zone: UTC\n"
        "  packages: !include_dir_named packages\n"
    )
    files[Path("secrets.yaml")] = (
        'igw_energy_url: "http://inverter-gateway.energy.svc.cluster.local:8080/v1/energy"\n'
        'igw_energy_authorization: "Bearer offline-test-not-a-credential"\n'
    )
    write_files(Path(sys.argv[1]), files)
    print("Wrote an offline HA validation fixture with fake credentials.")


if __name__ == "__main__":
    main()
