import sys
import types
from pathlib import Path

import atheris

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("igw_google_voice")
package.__path__ = [str(ROOT / "igw_google_voice")]
sys.modules[package.__name__] = package

with atheris.instrument_imports():
    from igw_google_voice.__main__ import local_http_host, validate_url


def test_one_input(data: bytes) -> None:
    from urllib.parse import urlsplit

    value = data.decode("utf-8", errors="replace")
    for permit_local in (False, True):
        try:
            accepted = validate_url(value, allow_local_http=permit_local)
        except ValueError:
            continue
        parsed = urlsplit(accepted)
        assert parsed.path == "/v1/energy"  # nosec B101 - intentional test oracle
        assert parsed.username is None and parsed.password is None  # nosec B101 - intentional test oracle
        assert not parsed.query and not parsed.fragment  # nosec B101 - intentional test oracle
        assert parsed.scheme == "https" or (
            permit_local
            and parsed.scheme == "http"
            and local_http_host(parsed.hostname)
        )  # nosec B101 - intentional test oracle


if __name__ == "__main__":
    atheris.Setup(sys.argv, atheris.instrument_func(test_one_input))
    atheris.Fuzz()
