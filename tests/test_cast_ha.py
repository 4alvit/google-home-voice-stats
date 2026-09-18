"""Verify the optional HA trigger preserves voice scenes and rejects unsafe input."""

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment
import yaml

from igw_google_voice.__main__ import REPORTS, SCRIPT_IDS, write_files
from igw_google_voice.cast_ha import (
    PACKAGE_PATH, SECRETS_PATH, main, render_cast_trigger_files, validate_service_url,
)


class HALoader(yaml.SafeLoader):
    pass


HALoader.add_constructor("!secret", lambda loader, node: (node.tag, loader.construct_scalar(node)))


def package():
    return yaml.load(render_cast_trigger_files("http://192.168.50.8:8090")[PACKAGE_PATH], Loader=HALoader)


class CastHATriggerTests(unittest.TestCase):
    def setUp(self):
        self.env = SandboxedEnvironment(undefined=StrictUndefined)

    def test_only_private_ipv4_http_origins_are_allowed(self):
        for url in ("http://10.1.2.3", "http://172.16.0.1:80", "http://172.31.255.254:65535", "http://192.168.50.8:8090"):
            with self.subTest(url=url):
                self.assertEqual(validate_service_url(url), url)
        for url in (
            "https://192.168.50.8", "http://8.8.8.8", "http://127.0.0.1", "http://169.254.169.254",
            "http://172.32.0.1", "http://[fd00::1]", "http://cast.local", "http://service.ns.svc",
            "http://user:secret@192.168.50.8", "http://192.168.50.8/", "http://192.168.50.8/v1",
            "http://192.168.50.8?token=private", "http://192.168.50.8?", "http://192.168.50.8#",
            "http://192.168.50.8:0", "http://192.168.50.8:65536", "http://192.168.50.8:",
            "http://192.168.050.8", "http://192.168.50.8:08090", "http://192.168.50.8\n",
            "http://{{ host }}", "HTTP://192.168.50.8", None,
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_service_url(url)

    def test_preserves_all_five_scene_ids_aliases_and_private_dispatcher(self):
        scripts = package()["script"]
        self.assertEqual(set(scripts), {*SCRIPT_IDS.values(), "igw_google_energy_dispatch"})
        for key, alias in REPORTS.items():
            script = scripts[SCRIPT_IDS[key]]
            self.assertEqual(script["alias"], alias)
            self.assertEqual(script["trace"]["stored_traces"], 0)
            self.assertEqual(script["sequence"], [{"action": "script.igw_google_energy_dispatch", "data": {"report_key": key}}])
        dispatcher = scripts["igw_google_energy_dispatch"]
        self.assertEqual(dispatcher["mode"], "queued")
        self.assertEqual(dispatcher["trace"]["stored_traces"], 0)
        self.assertNotIn("use_blueprint", dispatcher)

    def test_request_has_only_local_bearer_and_no_body(self):
        config = package()
        request = config["rest_command"]["igw_cast_report"]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["timeout"], 10)
        self.assertEqual(request["headers"]["Authorization"], ("!secret", "igw_cast_authorization"))
        self.assertNotIn("payload", request)
        self.assertNotIn("Content-Length", request["headers"])
        self.assertNotIn("Content-Type", request["headers"])
        self.assertEqual(config["logger"]["logs"]["homeassistant.components.rest_command"], "warning")
        files = render_cast_trigger_files("http://192.168.50.8:8090")
        self.assertEqual(set(files), {PACKAGE_PATH, SECRETS_PATH, Path("INSTALL.md")})
        self.assertNotIn("igw_energy_authorization", files[PACKAGE_PATH])
        self.assertNotIn("tts.speak", files[PACKAGE_PATH])
        self.assertNotIn("REPLACE_WITH", files[PACKAGE_PATH])
        self.assertNotIn("http://", files[SECRETS_PATH])

    def test_invalid_direct_dispatcher_calls_stop_before_network_action(self):
        sequence = package()["script"]["igw_google_energy_dispatch"]["sequence"]
        guard = sequence[0]["if"][0]
        self.assertEqual(guard["condition"], "template")
        template = self.env.from_string(guard["value_template"])
        for key in REPORTS:
            self.assertEqual(template.render(report_key=key), "False")
        for key in ("unknown", "../status", "status?token=secret", "{{ states }}", [], None, 1):
            with self.subTest(key=key):
                self.assertEqual(template.render(report_key=key), "True")
        self.assertEqual(template.render(), "True")
        self.assertTrue(sequence[0]["then"][0]["error"])
        self.assertEqual(sequence[2]["action"], "rest_command.igw_cast_report")

    def test_rest_url_itself_cannot_render_an_injected_path(self):
        template = self.env.from_string(package()["rest_command"]["igw_cast_report"]["url"])
        for key in REPORTS:
            self.assertEqual(template.render(report_key=key), f"http://192.168.50.8:8090/v1/reports/{key}")
        for key in ("../private", "status?token=x", None, [], 1):
            self.assertEqual(template.render(report_key=key), "http://192.168.50.8:8090/v1/reports/invalid")
        self.assertEqual(template.render(), "http://192.168.50.8:8090/v1/reports/invalid")

    def test_only_accepted_and_busy_responses_stop_successfully(self):
        response_handling = package()["script"]["igw_google_energy_dispatch"]["sequence"][3]
        choices = response_handling["choose"]
        for status in (202, 409):
            matched = [choice for choice in choices if self.env.from_string(choice["conditions"]).render(cast_response={"status": status}) == "True"]
            self.assertEqual(len(matched), 1)
            self.assertNotIn("error", matched[0]["sequence"][0])
        for response in ({}, None, "bad", {"status": 200}, {"status": 401}, {"status": 500}, {"status": "202"}):
            self.assertTrue(all(self.env.from_string(choice["conditions"]).render(cast_response=response) == "False" for choice in choices))
        self.assertTrue(response_handling["default"][0]["error"])

    def test_secret_example_is_protected_outside_packages_and_collisions_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "generated"
            files = render_cast_trigger_files("http://192.168.50.8:8090")
            write_files(output, files)
            self.assertEqual((output / SECRETS_PATH).stat().st_mode & 0o777, 0o600)
            self.assertEqual(list((output / "packages").iterdir()), [output / PACKAGE_PATH])
            with self.assertRaises(ValueError):
                write_files(output, files)

    def test_cli_writes_expected_files_and_hides_invalid_url_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "generated"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--service-url", "http://192.168.50.8:8090", "--output", str(output)]), 0)
            self.assertTrue((output / PACKAGE_PATH).is_file())
            captured = io.StringIO()
            with redirect_stderr(captured), self.assertRaises(SystemExit):
                main(["--service-url", "http://user:private-value@192.168.50.8", "--output", str(output)])
            self.assertNotIn("private-value", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
