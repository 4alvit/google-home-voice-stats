"""Private-LAN IGW report playback with expiring media and no HA dependency."""

from __future__ import annotations

import hmac
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import re
import secrets
import signal
import shutil
import tempfile
import threading
import time

from .cast_config import CastConfig
from .cast_gateway import FALLBACK, GatewayError, REPORT_KEYS, fetch_snapshot_bounded

LOG = logging.getLogger("igw_cast")
MEDIA_TTL = 180


def silence_cast_logs():
    """Cover current and future child loggers, whose errors may contain URLs."""
    logger = logging.getLogger("pychromecast")
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False


class CastPlayback:
    """Use Google's default receiver without changing volume or account setup."""

    def __init__(self, config):
        self.config = config

    def play(self, url, duration, stop):
        import pychromecast
        from pychromecast.const import CAST_TYPE_CHROMECAST
        from pychromecast.controllers.media import DefaultMediaReceiverController
        from pychromecast.models import CastInfo, HostServiceInfo
        # Library failures can include media URLs; only our fixed categories are logged.
        silence_cast_logs()
        cast = None
        try:
            info = CastInfo(
                {HostServiceInfo(self.config.cast_host, 8009)}, self.config.cast_uuid,
                None, "Energy display", self.config.cast_host, 8009, CAST_TYPE_CHROMECAST, None,
            )
            cast = pychromecast.Chromecast(
                info,
                tries=1, retry_wait=1, timeout=5,
            )
            cast.wait(timeout=10)
            controller = DefaultMediaReceiverController()
            cast.register_handler(controller)
            controller.play_media(url, "video/mp4", title="Home Energy", stream_type="BUFFERED")
            deadline = time.monotonic() + 20
            started = False
            while not stop.wait(0.5) and time.monotonic() < deadline:
                status = cast.media_controller.status
                if status.content_id == url and status.player_state == "PLAYING":
                    started = True
                    break
            if not started:
                raise RuntimeError("playback_not_observed")
            deadline = time.monotonic() + min(duration + 10, 135)
            while not stop.wait(0.5) and time.monotonic() < deadline:
                status = cast.media_controller.status
                if status.content_id != url or status.player_state == "IDLE":
                    break
        finally:
            if cast is not None:
                cast.disconnect(timeout=5)


class ReportEngine:
    def __init__(self, config, *, fetcher=fetch_snapshot_bounded, renderer=None, player=None, clock=time.monotonic):
        if renderer is None:
            from .cast_media import render_report_video
            renderer = partial(render_report_video, tts_provider=config.tts_provider,
                               piper_model=config.piper_model, piper_timeout=config.piper_timeout)
        self.config, self.fetcher, self.renderer = config, fetcher, renderer
        self.player = player or CastPlayback(config)
        self.clock = clock
        self.root = Path(tempfile.mkdtemp(prefix="igw-cast-"))
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.worker = None
        self.busy = False
        self.state = {"state": "idle", "result": "none"}
        self.media = {}

    def submit(self, key):
        if key not in REPORT_KEYS:
            return False
        with self.lock:
            if self.busy or self.stop.is_set():
                return False
            self.busy = True
            self.state = {"state": "running", "result": "pending"}
            self.worker = threading.Thread(target=self._run, args=(key,), daemon=True)
            self.worker.start()
            return True

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def prune(self):
        with self.lock:
            for token, (path, expires) in list(self.media.items()):
                if self.clock() >= expires:
                    path.unlink(missing_ok=True)
                    self.media.pop(token, None)

    def media_file(self, token):
        self.prune()
        with self.lock:
            item = self.media.get(token)
            if item is None:
                return None
            # Open under the same lock as pruning; an already-open stream may finish.
            try:
                return item[0].open("rb")
            except FileNotFoundError:
                return None

    def _run(self, key):
        result, path = "internal_failure", None
        try:
            self.prune()
            fallback = False
            try:
                snapshot = self.fetcher(self.config)
                reports = snapshot["reports"]
            except GatewayError as exc:
                # GatewayError is generated only with fixed categories in cast_gateway.
                category = str(exc) if str(exc) in {"http_failure", "transport_failure", "invalid_response"} else "gateway_failure"
                LOG.warning("gateway_report_failed category=%s", category)
                reports = {name: {"text": FALLBACK, "status": "unavailable"} for name in REPORT_KEYS}
                fallback = True
            token = secrets.token_urlsafe(24)
            path = self.root / (token + ".mp4")
            rendered = self.renderer(key, reports, path)
            if not fallback and time.time() - snapshot["generated_at"] > self.config.max_age:
                result = "snapshot_expired"
                return
            with self.lock:
                self.media[token] = (path, self.clock() + MEDIA_TTL)
            self.player.play(self.config.media_base_url + "/media/" + token + ".mp4",
                             rendered["duration_seconds"], self.stop)
            result = "fallback_played" if fallback else "report_played"
        except Exception:
            # Never include exception strings, URLs, household telemetry or traceback.
            result = "playback_or_render_failure"
            LOG.warning("report_failed category=playback_or_render_failure")
        finally:
            if path is not None:
                with self.lock:
                    published = any(item[0] == path for item in self.media.values())
                if not published:
                    path.unlink(missing_ok=True)
            with self.lock:
                self.state = {"state": "idle", "result": result}
                self.busy = False

    def close(self):
        self.stop.set()
        if self.worker:
            self.worker.join(timeout=30)
        shutil.rmtree(self.root, ignore_errors=True)


class CastServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, engine):
        self.engine = engine
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, CastHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        LOG.warning("request_failed category=request_failure")


class CastHandler(BaseHTTPRequestHandler):
    server_version = "IGWCast"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass  # Request paths contain short-lived media capabilities.

    def _json(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _authorized(self):
        expected = "Bearer " + self.server.engine.config.api_token
        actual = self.headers.get("Authorization", "")
        return hmac.compare_digest(actual.encode(), expected.encode())

    def do_POST(self):
        if not self._authorized():
            self._json(401, {"error": "unauthorized"})
            return
        key = self.path.removeprefix("/v1/reports/")
        if not self.path.startswith("/v1/reports/") or key not in REPORT_KEYS:
            self._json(404, {"error": "not_found"})
            return
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length", "0") != "0":
            self._json(400, {"error": "body_not_supported"})
            return
        accepted = self.server.engine.submit(key)
        self._json(202 if accepted else 409, {"accepted": accepted})

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
        elif self.path == "/v1/status":
            if self._authorized():
                self._json(200, self.server.engine.snapshot())
            else:
                self._json(401, {"error": "unauthorized"})
        elif re.fullmatch(r"/media/[A-Za-z0-9_-]{32}\.mp4", self.path):
            self._media()
        else:
            self._json(404, {"error": "not_found"})

    def do_OPTIONS(self):
        if not re.fullmatch(r"/media/[A-Za-z0-9_-]{32}\.mp4", self.path):
            self._json(404, {"error": "not_found"})
            return
        self.send_response(204)
        self._media_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _media_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Accept-Ranges", "bytes")

    def _media(self):
        token = self.path.split("/")[-1][:-4]
        stream = self.server.engine.media_file(token)
        if stream is None:
            self._json(404, {"error": "not_found"})
            return
        with stream:
            size = stream.seek(0, 2)
            start, end, status = 0, size - 1, 200
            header = self.headers.get("Range")
            if header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
                try:
                    if not match or not any(match.groups()):
                        raise ValueError()
                    first, last = match.groups()
                    if not first:
                        count = int(last)
                        if count <= 0:
                            raise ValueError()
                        start = max(0, size - count)
                    else:
                        start = int(first)
                        end = min(int(last), end) if last else end
                    if not 0 <= start <= end < size:
                        raise ValueError()
                    status = 206
                except ValueError:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            self.send_response(status)
            self._media_headers()
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(end - start + 1))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command == "HEAD":
                return
            stream.seek(start)
            remaining = end - start + 1
            try:
                while remaining:
                    chunk = stream.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass


def main():
    logging.basicConfig(level=logging.WARNING, format="%(name)s %(message)s")
    try:
        config = CastConfig.from_env()
        if not all(shutil.which(name) for name in ("ffmpeg", "espeak-ng")):
            raise ValueError("Install ffmpeg and espeak-ng, or use the provided container.")
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    engine = ReportEngine(config)
    server = CastServer((config.bind_host, config.port), engine)
    signal.signal(signal.SIGTERM, lambda *_: engine.stop.set())
    try:
        server.timeout = 1
        while not engine.stop.is_set():
            server.handle_request()
            engine.prune()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        engine.close()


if __name__ == "__main__":
    main()
