"""Contract, privacy and real HTTP checks for the standalone Cast boundary."""

from dataclasses import replace
from email.message import Message
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import logging
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID

from igw_google_voice.cast_config import CastConfig
from igw_google_voice.cast_gateway import FALLBACK, GatewayError, fetch_snapshot, fetch_snapshot_bounded, validate_snapshot
from igw_google_voice.cast_service import CastPlayback, CastServer, ReportEngine, silence_cast_logs


def config():
    return CastConfig("https://gateway.test/v1/energy", "r" * 40, "a" * 40,
                      "192.168.50.20", UUID(int=1), "http://192.168.50.10:8091")


def fixture():
    body = json.loads((Path(__file__).parent / "fixtures/energy.json").read_text())
    body["generated_at"] = time.time()
    return body


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.env = dict(IGW_URL="https://gateway.test/v1/energy", IGW_READ_TOKEN="r" * 40,
                        CAST_API_TOKEN="a" * 40, CAST_HOST="192.168.50.20",
                        CAST_UUID=str(UUID(int=1)), CAST_MEDIA_BASE_URL="http://192.168.50.10:8091")

    def test_private_bind_and_secret_free_repr(self):
        result = CastConfig.from_env(self.env)
        self.assertEqual(result.bind_host, "192.168.50.10")
        self.assertNotIn("r" * 40, repr(result))
        self.assertNotIn("192.168", repr(result))

    def test_reject_public_media_credential_urls_and_partial_access_pair(self):
        for changes in (
            {"CAST_MEDIA_BASE_URL": "http://203.0.113.1:8091"},
            {"CAST_MEDIA_BASE_URL": "http://192.168.50.10:8091/private"},
            {"CAST_MEDIA_BASE_URL": "http://user:pass@192.168.50.10:8091"},
            {"CAST_HOST": "8.8.8.8"}, {"CAST_API_TOKEN": "short"},
            {"CF_ACCESS_CLIENT_ID": "client"},
            {"IGW_URL": "http://192.168.50.5/v1/energy"},
        ):
            with self.subTest(changes=tuple(changes)):
                with self.assertRaises(ValueError):
                    CastConfig.from_env(self.env | changes)

    def test_private_gateway_requires_explicit_opt_in(self):
        result = CastConfig.from_env(self.env | {
            "IGW_URL": "http://192.168.50.5/v1/energy", "IGW_ALLOW_LOCAL_HTTP": "true"})
        self.assertTrue(result.igw_url.startswith("http://"))

    def test_rejects_piper_relative_model_port_mismatch_and_age_bounds(self):
        cases = (
            {"CAST_TTS_PROVIDER": "piper", "CAST_PIPER_MODEL": "model.onnx"},
            {"CAST_TTS_PROVIDER": "piper", "CAST_PIPER_MODEL": "/tmp/model.txt"},
            {"CAST_PORT": "8092"},
            {"IGW_MAX_RESPONSE_AGE": "4"},
            {"IGW_MAX_RESPONSE_AGE": "301"},
            {"CAST_BIND_HOST": "::1"},
        )
        for changes in cases:
            with self.subTest(changes=tuple(changes.items())):
                with self.assertRaises(ValueError):
                    CastConfig.from_env(self.env | changes)


class TestGateway(unittest.TestCase):
    def test_warning_text_preserved_and_no_zero_defaults(self):
        body = fixture()
        body["mqtt_connected"] = False
        for report in body["reports"].values():
            report.update(status="unavailable", text="Measurements are unavailable.")
        parsed = validate_snapshot(body, now=time.time())
        self.assertEqual({key: parsed["reports"][key] for key in body["reports"]}, body["reports"])
        self.assertEqual(parsed["reports"]["flow"]["status"], "unconfigured")
        self.assertNotIn("metrics", parsed)

    def test_stale_envelope_and_contradictory_fresh_reports_rejected(self):
        for changes in ({"generated_at": time.time() - 31}, {"generated_at": time.time() + 10},
                        {"generated_at": True}, {"generated_at": float("nan")},
                        {"generated_at": 10 ** 1000}, {"schema_version": True},
                        {"mqtt_connected": False}, {"reports": {}}):
            with self.subTest(changes=tuple(changes)):
                with self.assertRaises(GatewayError):
                    validate_snapshot(fixture() | changes, now=time.time())

    def test_redirect_never_forwards_credential_and_proxy_is_ignored(self):
        hits = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/credential-trap")
                self.end_headers()
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            cfg = replace(config(), igw_url=f"http://127.0.0.1:{server.server_port}/v1/energy")
            with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1", "no_proxy": ""}):
                with self.assertRaisesRegex(GatewayError, "http_failure"):
                    fetch_snapshot(cfg)
            self.assertEqual(hits, ["/v1/energy"])
        finally:
            server.shutdown()
            server.server_close()

    def test_total_deadline_terminates_a_slow_response(self):
        entered = threading.Event()
        class SlowHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                entered.set()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                for _ in range(60):
                    try:
                        self.wfile.write(b" ")
                        self.wfile.flush()
                    except OSError:
                        break
                    time.sleep(0.2)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            cfg = replace(config(), igw_url=f"http://127.0.0.1:{server.server_port}/v1/energy")
            start = time.monotonic()
            with self.assertRaisesRegex(GatewayError, "transport_failure"):
                # Allow process startup on a small, single-CPU NAS while ensuring
                # the ongoing response is terminated well before its 12s stream.
                fetch_snapshot_bounded(cfg, deadline_seconds=3)
            self.assertTrue(entered.is_set())
            self.assertLess(time.monotonic() - start, 5)
        finally:
            server.shutdown()
            server.server_close()

    def test_oversized_or_non_json_response_rejected(self):
        class Response(io.BytesIO):
            status = 200
            headers = Message()
        class Opener:
            def open(self, *args, **kwargs):
                return response
        for payload, mime in ((b"x" * 262145, "application/json"), (b"{}", "text/html")):
            response = Response(payload)
            response.headers = Message()
            response.headers["Content-Type"] = mime
            with self.assertRaisesRegex(GatewayError, "invalid_response"):
                fetch_snapshot(config(), opener=Opener())


class TestServer(unittest.TestCase):
    def setUp(self):
        self.playing = threading.Event()
        self.release = threading.Event()
        self.captured = {}
        parent = self
        class Player:
            def play(self, url, duration, stop):
                parent.captured["url"] = url
                parent.playing.set()
                parent.release.wait(3)
        def render(key, reports, path):
            self.captured["reports"] = reports
            path.write_bytes(b"0123456789")
            return {"duration_seconds": 1}
        self.now = [10.0]
        self.engine = ReportEngine(config(), fetcher=lambda _: fixture(), renderer=render,
                                   player=Player(), clock=lambda: self.now[0])
        self.server = CastServer(("127.0.0.1", 0), self.engine)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.engine.close()

    def request(self, method, path, *, auth=False, headers=None, body=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        values = dict(headers or {})
        if auth:
            values["Authorization"] = "Bearer " + config().api_token
        conn.request(method, path, body=body, headers=values)
        response = conn.getresponse()
        result = response.status, dict(response.headers), response.read()
        conn.close()
        return result

    def launch(self):
        self.assertEqual(self.request("POST", "/v1/reports/status", auth=True)[0], 202)
        self.assertTrue(self.playing.wait(2))
        return self.captured["url"].split(":8091")[1]

    def test_authentication_fixed_routes_and_busy_boundary(self):
        self.assertEqual(self.request("POST", "/v1/reports/status")[0], 401)
        self.assertEqual(self.request("POST", "/v1/reports/anything", auth=True)[0], 404)
        self.assertEqual(self.request("POST", "/v1/reports/status", auth=True, body=b"{}")[0], 400)
        self.launch()
        current_url = self.captured["url"]
        self.assertEqual(self.request("POST", "/v1/reports/battery", auth=True)[0], 409)
        self.assertEqual(self.request("POST", "/v1/reports/status", auth=True)[0], 409)
        self.assertEqual(self.captured["url"], current_url)
        self.assertFalse(self.engine.stop.is_set())
        self.assertEqual(self.request("GET", "/v1/status")[0], 401)
        self.assertEqual(json.loads(self.request("GET", "/v1/status", auth=True)[2])["state"], "running")

    def test_media_range_head_and_expiration(self):
        path = self.launch()
        status, headers, body = self.request("GET", path, headers={"Range": "bytes=2-5"})
        self.assertEqual((status, body), (206, b"2345"))
        self.assertEqual(headers["Content-Range"], "bytes 2-5/10")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.request("HEAD", path)[2], b"")
        self.assertEqual(self.request("GET", path, headers={"Range": "bytes=-3"})[2], b"789")
        for value in ("bytes=12-", "bytes=1-0", "bytes=-0", "bytes=0-1,3-4"):
            self.assertEqual(self.request("GET", path, headers={"Range": value})[0], 416)
        self.now[0] += 181
        self.assertEqual(self.request("GET", path)[0], 404)
        self.assertEqual(list(self.engine.root.glob("*.mp4")), [])

    def test_failure_speaks_fallback_without_logging_secret(self):
        def fail(_):
            raise GatewayError("https://secret.invalid/private?token=DO_NOT_LOG")
        self.engine.fetcher = fail
        with self.assertLogs("igw_cast", level="WARNING") as logs:
            self.launch()
        self.assertNotIn("DO_NOT_LOG", "".join(logs.output))
        self.assertTrue(all(r["status"] == "unavailable" for r in self.captured["reports"].values()))

    def _wait_idle(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            snap = json.loads(self.request("GET", "/v1/status", auth=True)[2])
            if snap["state"] == "idle":
                return snap
            time.sleep(0.05)
        self.fail("engine did not return to idle")

    def test_gateway_failure_recovers_idle_for_manual_retry(self):
        """Only a later explicit request completes fresh playback after fallback."""
        fetches, renders, playbacks = [], [], []
        original_renderer, original_player = self.engine.renderer, self.engine.player

        def fetch(_):
            fetches.append(None)
            if len(fetches) == 1:
                raise GatewayError("transport_failure")
            body = fixture()
            body["reports"]["battery"]["text"] = "Fresh battery response."
            return validate_snapshot(body, now=time.time(), max_age=config().max_age)

        def render(key, reports, path):
            renders.append((key, json.loads(json.dumps(reports))))
            return original_renderer(key, reports, path)

        def play(url, duration, stop):
            playbacks.append(url)
            return original_player.play(url, duration, stop)

        self.engine.fetcher = fetch
        self.engine.renderer = render
        self.engine.player = SimpleNamespace(play=play)
        self.assertEqual(self.request("POST", "/v1/reports/status", auth=True)[0], 202)
        self.assertTrue(self.playing.wait(2))
        self.assertEqual(renders[0][0], "status")
        self.assertTrue(renders[0][1])
        self.assertTrue(all(report["text"] == FALLBACK for report in renders[0][1].values()))
        self.release.set()
        self.assertEqual(self._wait_idle()["result"], "fallback_played")
        self.assertFalse(self.engine.busy)
        self.assertEqual((len(fetches), len(renders), len(playbacks)), (1, 1, 1))
        self.playing.clear()
        self.release.clear()
        self.assertEqual(self.request("POST", "/v1/reports/battery", auth=True)[0], 202)
        self.assertTrue(self.playing.wait(2))
        self.assertEqual(renders[1][0], "battery")
        self.assertEqual(renders[1][1]["battery"]["text"], "Fresh battery response.")
        self.assertNotEqual(playbacks[0], playbacks[1])
        self.release.set()
        self.assertEqual(self._wait_idle()["result"], "report_played")
        self.assertFalse(self.engine.busy)
        self.assertEqual((len(fetches), len(renders), len(playbacks)), (2, 2, 2))

    def test_fresh_snapshot_expiring_during_render_is_not_published(self):
        """Rendering can exhaust a snapshot that passed gateway validation."""
        generated = time.time()
        current_time = [generated]
        validated = []
        original_renderer = self.engine.renderer

        def fresh(_):
            body = fixture()
            body["generated_at"] = generated
            snapshot = validate_snapshot(body, now=current_time[0], max_age=config().max_age)
            validated.append(snapshot)
            return snapshot

        def render(key, reports, path):
            result = original_renderer(key, reports, path)
            current_time[0] += config().max_age + 1
            return result

        self.engine.fetcher = fresh
        self.engine.renderer = render
        # Replace only the engine module's time reference, leaving HTTP/test clocks real.
        with patch("igw_google_voice.cast_service.time", SimpleNamespace(time=lambda: current_time[0])):
            self.assertEqual(self.request("POST", "/v1/reports/status", auth=True)[0], 202)
            self.assertEqual(self._wait_idle()["result"], "snapshot_expired")
        self.assertEqual(len(validated), 1)
        self.assertEqual(validated[0]["generated_at"], generated)
        self.assertFalse(self.playing.is_set())
        self.assertFalse(self.engine.busy)
        self.assertEqual(list(self.engine.root.glob("*.mp4")), [])
        self.assertEqual(self.engine.media, {})

    def test_handler_error_never_logs_client_identity(self):
        with self.assertLogs("igw_cast", level="WARNING") as logs:
            self.server.handle_error(None, ("sensitive-peer.invalid", 1234))
        self.assertEqual(logs.output, ["WARNING:igw_cast:request_failed category=request_failure"])


class TestCastPlayback(unittest.TestCase):
    def test_forces_default_receiver_and_uses_real_media_status(self):
        from pychromecast.controllers.media import DefaultMediaReceiverController
        from pychromecast.config import APP_MEDIA_RECEIVER
        from pychromecast.const import CAST_TYPE_CHROMECAST
        url = "http://192.168.50.10:8091/media/opaque.mp4"
        observed = {}
        class FakeCast:
            # Match PyChromecast's separation: Default controller has no status.
            media_controller = SimpleNamespace(status=SimpleNamespace(content_id=url, player_state="PLAYING"))
            status = SimpleNamespace(app_id="different-media-app")
            def __init__(self, info, **kwargs):
                observed["info"] = info
            def wait(self, timeout):
                pass
            def register_handler(self, controller):
                observed["controller"] = controller
            def disconnect(self, timeout):
                observed["disconnected"] = True
        class FastStop:
            calls = 0
            def wait(self, timeout):
                self.calls += 1
                return self.calls > 1
        def load(controller, target, *args, **kwargs):
            self.assertEqual(target, url)
            self.assertEqual(controller.supporting_app_id, APP_MEDIA_RECEIVER)
            self.assertTrue(controller.app_must_match)
        with patch("pychromecast.Chromecast", FakeCast), patch.object(DefaultMediaReceiverController, "play_media", load):
            CastPlayback(config()).play(url, 1, FastStop())
        self.assertEqual(observed["info"].cast_type, CAST_TYPE_CHROMECAST)
        self.assertTrue(observed["disconnected"])

    def test_future_library_child_logs_never_reach_root(self):
        silence_cast_logs()
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            logging.getLogger("pychromecast.created.after.setup").warning("DO_NOT_LOG http://private/media/token")
        finally:
            root.removeHandler(handler)
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
