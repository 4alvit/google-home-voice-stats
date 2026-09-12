"""Exercise the shipped HA template and generated config, not a Python replica."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment
import yaml

from igw_google_voice.__main__ import (
    BLUEPRINT_RELATIVE_PATH,
    REPORTS,
    SCRIPT_IDS,
    main,
    render_files,
    render_package,
    validate_entity,
    validate_url,
    write_files,
)


ROOT = Path(__file__).resolve().parent.parent
NOW = 1789257600
FALLBACK = "Connection failed."


class HALoader(yaml.SafeLoader):
    pass


for tag in ("!input", "!secret"):
    HALoader.add_constructor(tag, lambda loader, node: (node.tag, loader.construct_scalar(node)))


def load_yaml(text):
    return yaml.load(text, Loader=HALoader)


class ResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blueprint = load_yaml((ROOT / BLUEPRINT_RELATIVE_PATH).read_text())
        text = cls.blueprint["sequence"][2]["variables"]["spoken_report"]
        env = SandboxedEnvironment(undefined=StrictUndefined)
        env.globals.update(now=lambda: datetime.fromtimestamp(NOW, timezone.utc), as_timestamp=lambda dt: dt.timestamp())
        cls.template = env.from_string(text)
        cls.fixture = json.loads((ROOT / "tests/fixtures/energy.json").read_text())

    def speak(self, body=None, *, status=200, report="status", response=None):
        if response is None:
            response = {"status": status, "content": self.fixture if body is None else body}
        return self.template.render(
            igw_response=response, selected_report=report, maximum_age=30, fallback=FALLBACK,
        )

    def test_each_report_uses_gateway_text_verbatim(self):
        for key in REPORTS:
            with self.subTest(report=key):
                self.assertEqual(self.speak(report=key), self.fixture["reports"][key]["text"])

    def test_gateway_failure_statuses_preserve_central_warning(self):
        for state in ("stale", "unavailable", "unconfigured"):
            body = deepcopy(self.fixture)
            body["mqtt_connected"] = False
            body["reports"]["battery"] = {"status": state, "text": f"Gateway says battery is {state}."}
            self.assertEqual(self.speak(body, report="battery"), f"Gateway says battery is {state}.")

    def test_disconnected_gateway_cannot_claim_fresh_report(self):
        body = deepcopy(self.fixture)
        body["mqtt_connected"] = False
        for key in REPORTS:
            with self.subTest(report=key):
                self.assertEqual(self.speak(body, report=key), FALLBACK)

    def test_http_auth_server_and_redirect_failures(self):
        for code in (301, 401, 403, 429, 500, 503):
            with self.subTest(status=code):
                self.assertEqual(self.speak(status=code), FALLBACK)

    def test_timeout_missing_and_non_json_response(self):
        for response in ({}, None, "", [], {"status": 200, "content": "<html>Login</html>"}, {"status": 200}):
            result = self.template.render(igw_response=response, selected_report="status", maximum_age=30, fallback=FALLBACK)
            self.assertEqual(result, FALLBACK)
        self.assertEqual(self.template.render(selected_report="status", maximum_age=30, fallback=FALLBACK), FALLBACK)

    def test_stale_and_future_envelopes(self):
        for timestamp in (NOW - 31, NOW + 6, "2026-09-12", True, None, float("nan"), float("inf")):
            body = deepcopy(self.fixture)
            body["generated_at"] = timestamp
            with self.subTest(timestamp=timestamp):
                self.assertEqual(self.speak(body), FALLBACK)
        for timestamp in (NOW - 30, NOW, NOW + 5):
            body = deepcopy(self.fixture)
            body["generated_at"] = timestamp
            self.assertEqual(self.speak(body), body["reports"]["status"]["text"])

    def test_invalid_schema_and_mqtt_flags(self):
        for value in (0, 2, True, "1", 1.0, None):
            body = deepcopy(self.fixture)
            body["schema_version"] = value
            self.assertEqual(self.speak(body), FALLBACK)
        for value in (0, 1, "true", None):
            body = deepcopy(self.fixture)
            body["mqtt_connected"] = value
            self.assertEqual(self.speak(body), FALLBACK)

    def test_missing_contract_fields(self):
        for key in self.fixture:
            body = deepcopy(self.fixture)
            del body[key]
            self.assertEqual(self.speak(body), FALLBACK)
        for key in ("battery_soc", "solar_power", "solar_today"):
            body = deepcopy(self.fixture)
            del body["metrics"][key]
            self.assertEqual(self.speak(body), FALLBACK)

    def test_bad_report_types_and_content(self):
        for report in (None, [], "text", {}, {"status": "invalid", "text": "Fine"},
                       {"status": "fresh", "text": " "}, {"status": "fresh", "text": 0},
                       {"status": "fresh", "text": "x" * 1201}):
            body = deepcopy(self.fixture)
            body["reports"]["status"] = report
            self.assertEqual(self.speak(body), FALLBACK)
        for key in ("unknown", [], {}, None, 12):
            self.assertEqual(self.speak(report=key), FALLBACK)

    def test_metrics_are_not_recalculated_or_coerced(self):
        body = deepcopy(self.fixture)
        body["metrics"] = {"battery_soc": None, "solar_power": None, "solar_today": None}
        body["reports"]["battery"] = {"status": "unavailable", "text": "Battery information is unavailable."}
        self.assertEqual(self.speak(body, report="battery"), "Battery information is unavailable.")

    def test_shared_queue_fetches_inside_run_and_targets_tts_provider(self):
        blueprint = self.blueprint
        self.assertEqual(blueprint["mode"], "queued")
        self.assertEqual(blueprint["trace"]["stored_traces"], 0)
        request = blueprint["sequence"][1]
        self.assertEqual(request["action"], "rest_command.igw_energy_report")
        self.assertEqual(request["response_variable"], "igw_response")
        self.assertTrue(request["continue_on_error"])
        speak = blueprint["sequence"][3]
        self.assertEqual(speak["action"], "tts.speak")
        self.assertEqual(speak["target"]["entity_id"], ("!input", "tts_entity"))
        self.assertEqual(speak["data"]["media_player_entity_id"], ("!input", "media_player"))
        self.assertFalse(speak["data"]["cache"])
        self.assertIn("wait_template", blueprint["sequence"][4])
        self.assertIn("wait_template", blueprint["sequence"][5])


class RendererTests(unittest.TestCase):
    def files(self, **changes):
        options = {"igw_url": "https://igw.home.test/v1/energy", "tts_entity": "tts.google_translate_en_com", "media_player": "media_player.kitchen_nest"}
        options.update(changes)
        return render_files(**options)

    def test_package_contract_and_authentication(self):
        for use_local in (False, True):
            package = load_yaml(self.files(allow_local_http=use_local)[Path("packages/igw_google_voice.yaml")])
            rest = package["rest_command"]["igw_energy_report"]
            self.assertEqual(rest["method"], "GET")
            self.assertTrue(rest["verify_ssl"])
            self.assertEqual(rest["url"], ("!secret", "igw_energy_url"))
            self.assertEqual(rest["headers"]["Authorization"], ("!secret", "igw_energy_authorization"))
            self.assertEqual(rest["headers"]["User-Agent"], "IGWEnergyVoice/1.0 (+https://github.com/victron-venus/inverter-gateway)")
            self.assertFalse(any(key.startswith("CF-Access") for key in rest["headers"]))
            self.assertEqual(package["logger"]["logs"]["homeassistant.components.rest_command"], "warning")
            self.assertNotIn("sensor", package)
            self.assertNotIn("template", package)
            scripts = package["script"]
            self.assertEqual(len(scripts), 6)
            for key in REPORTS:
                script = scripts[SCRIPT_IDS[key]]
                self.assertEqual(script["mode"], "queued")
                self.assertEqual(script["sequence"], [{"action": "script.igw_google_energy_dispatch", "data": {"report_key": key}}])
            self.assertEqual(scripts["igw_google_energy_dispatch"]["use_blueprint"]["path"], "igw/announce_energy.yaml")

    def test_rejects_insecure_or_incomplete_urls(self):
        for url in ("http://igw.home.test/v1/energy", "https://example.com/v1/energy", "https://host/", "https://host/v1/energy?token=secret", "https://user:secret@host/v1/energy", "https://REPLACE_WITH_IGW_HOST/v1/energy", "https://host/v1/energy#fragment", "https://host/{{token}}/v1/energy"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)

    def test_private_http_requires_explicit_opt_in(self):
        for host in ("127.0.0.1", "localhost", "10.12.1.2", "172.16.2.3", "192.168.1.10", "[::1]", "[fd00::1]", "inverter-gateway.synology-apps.svc.cluster.local", "inverter-gateway.synology-apps.svc"):
            url = f"http://{host}:8080/v1/energy"
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    validate_url(url)
                self.assertEqual(validate_url(url, allow_local_http=True), url)

    def test_private_http_opt_in_never_accepts_public_or_ambiguous_hosts(self):
        for host in ("8.8.8.8", "172.32.0.1", "169.254.169.254", "[2001:4860:4860::8888]", "public.net", "igw.home.test", "localhost.public.net", "service.svc.cluster.local.public.net", "svc.cluster.local", "bad_name.namespace.svc.cluster.local"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                validate_url(f"http://{host}/v1/energy", allow_local_http=True)

    def test_private_http_renderer_uses_only_scoped_bearer(self):
        url = "http://inverter-gateway.synology-apps.svc.cluster.local:8080/v1/energy"
        files = self.files(igw_url=url, allow_local_http=True)
        headers = load_yaml(files[Path("packages/igw_google_voice.yaml")])["rest_command"]["igw_energy_report"]["headers"]
        self.assertEqual(set(headers), {"Authorization", "Accept", "User-Agent", "Cache-Control"})
        self.assertNotIn("igw_cf", files[Path("igw.secrets.example.yaml")])

    def test_rejects_invalid_entities(self):
        for entity in ("media_player.YOUR_NEST", "media_player.your_nest", "media_player.example", "light.kitchen", "media_player.{{nest}}", "media_player.kitchen\nlogger:"):
            with self.subTest(entity=entity), self.assertRaises(ValueError):
                validate_entity(entity, "media_player")

    def test_rejects_invalid_age(self):
        for age in (0, 4, 301, True):
            with self.assertRaises(ValueError):
                render_package("tts.speech", "media_player.nest", age)

    def test_writes_only_expected_files_and_protects_secret_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "rendered"
            files = self.files()
            write_files(destination, files)
            self.assertEqual({p.relative_to(destination) for p in destination.rglob("*") if p.is_file()}, set(files))
            self.assertEqual((destination / "igw.secrets.example.yaml").stat().st_mode & 0o777, 0o600)
            before = (destination / "packages/igw_google_voice.yaml").read_text()
            with self.assertRaises(ValueError):
                write_files(destination, self.files(media_player="media_player.bedroom"))
            self.assertEqual((destination / "packages/igw_google_voice.yaml").read_text(), before)

    def test_refuses_symlink_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real"
            real.mkdir()
            link = Path(tmp) / "link"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaises(ValueError):
                write_files(link, self.files())
            self.assertEqual(list(real.iterdir()), [])

    def test_cli_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = main(["render-config", "--igw-url", "https://igw.home.test/v1/energy", "--tts-entity", "tts.speech", "--media-player", "media_player.nest", "--output", str(Path(tmp) / "staged")])
            self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
