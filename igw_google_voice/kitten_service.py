"""Private, CPU-only Nano speech endpoint with a preloaded, bounded worker."""
from __future__ import annotations

import hmac
import io
import json
import logging
import multiprocessing as mp
import os
import signal
import sys
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .tls_policy import server_context
import wave

LOG = logging.getLogger("igw_kitten")
MAX_TEXT = 1200
MAX_BODY = 8192
MAX_AUDIO = 6_000_000


def valid_text(text):
    return (isinstance(text, str) and 0 < len(text.strip()) <= MAX_TEXT
            and not any(ord(c) < 32 and c not in "\n\r\t" for c in text))


def _worker(connection, model_dir, threads):
    # Import only in the supervised child. The parent can terminate a stuck native call.
    os.environ.update(HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                      OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    import numpy as np
    import onnxruntime as ort
    ort.disable_telemetry_events()
    from unittest.mock import patch
    from kittenml import KittenTTS
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    original = ort.InferenceSession
    with patch.object(ort, "InferenceSession",
                      side_effect=lambda *a, **kw: original(*a, sess_options=options, **kw)):
        model = KittenTTS(model_dir, backend="cpu")
    # Call the underlying ONNX model: the convenience wrapper prints private input text.
    model.model.generate("Speech service is ready.", voice="Jasper", clean_text=False)
    connection.send(True)
    while True:
        try:
            text = connection.recv()
        except EOFError:
            return
        try:
            samples = model.model.generate(text, voice="Jasper", speed=1.0, clean_text=False)
            if (samples.ndim != 1 or not 0 < len(samples) <= 24000 * 115
                    or not np.isfinite(samples).all()):
                raise ValueError("invalid audio")
            output = io.BytesIO()
            with wave.open(output, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
            connection.send_bytes(output.getvalue())
        except Exception:
            # No text, paths or model exception details in logs or responses.
            connection.send_bytes(b"")


class BusyError(RuntimeError):
    pass


class Synthesizer:
    def __init__(self, model_dir, timeout=12, threads=1):
        if not isinstance(threads, int) or not 1 <= threads <= 4:
            raise ValueError("Speech threads must be between one and four")
        self.threads = threads
        self.model_dir, self.timeout = model_dir, timeout
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.process = self.connection = None
        self._start()

    def _start(self):
        self.ready.clear()
        context = mp.get_context("spawn")
        parent, child = context.Pipe()
        self.connection = parent
        self.process = context.Process(target=_worker, args=(child, self.model_dir, self.threads), daemon=True)
        self.process.start()
        child.close()
        if not parent.poll(90) or parent.recv() is not True:
            self.close()
            raise RuntimeError("speech worker did not start")
        self.ready.set()

    def close(self):
        self.ready.clear()
        if self.process is not None:
            self.process.terminate()
            self.process.join(2)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(2)
        if self.connection is not None:
            self.connection.close()

    def _recover(self):
        try:
            self._start()
        except Exception:
            LOG.error("speech_worker_restart_failed")
            # Both Kubernetes and launchd restart the process after a failed recovery.
            os.kill(os.getpid(), signal.SIGTERM)
        finally:
            self.lock.release()

    def generate(self, text):
        if not self.ready.is_set() or not self.lock.acquire(blocking=False):
            raise BusyError("speech worker unavailable")
        recover = False
        try:
            self.connection.send(text)
            if not self.connection.poll(self.timeout):
                raise TimeoutError()
            audio = self.connection.recv_bytes(MAX_AUDIO)
            if not audio:
                raise RuntimeError("speech generation failed")
            return audio
        except Exception:
            recover = True
            self.close()
            threading.Thread(target=self._recover, daemon=True).start()
            raise RuntimeError("speech worker failed") from None
        finally:
            if not recover:
                self.lock.release()


class SpeechServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, synthesizer, token, *, tls_context, handler_class=None):
        self.synthesizer, self.token = synthesizer, token
        self.tls_context = tls_context
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, handler_class or SpeechHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            # Handshake inside the bounded worker, never in the accept loop.
            request.settimeout(5)
            try:
                secure = self.tls_context.wrap_socket(request, server_side=True)
            except OSError:
                return
            super().process_request_thread(secure, client_address)
        finally:
            request.close()
            self.slots.release()

    def handle_error(self, request, client_address):
        LOG.warning("speech_request_failed")


class SpeechHandler(BaseHTTPRequestHandler):
    server_version = "IGWSpeech"
    sys_version = ""
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass

    def _send(self, status, body=b"", content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/healthz":
            self._send(404)
        else:
            ready = self.server.synthesizer.ready.is_set()
            self._send(200 if ready else 503, json.dumps({"ready": ready}).encode())

    def do_POST(self):
        if not hmac.compare_digest(self.headers.get("Authorization", "").encode(),
                                   ("Bearer " + self.server.token).encode()):
            self._send(401)
            return
        if self.path != "/v1/speech":
            self._send(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if (self.headers.get("Transfer-Encoding") or not 0 < length <= MAX_BODY
                    or self.headers.get_content_type() != "application/json"):
                raise ValueError()
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError()
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) != {"text"} or not valid_text(body["text"]):
                raise ValueError()
        except (ValueError, UnicodeError, TimeoutError):
            self._send(400)
            return
        try:
            audio = self.server.synthesizer.generate(body["text"])
        except ValueError:
            self._send(400)
        except BusyError:
            self._send(503)
        except RuntimeError:
            self._send(502)
        else:
            self._send(200, audio, "audio/wav")


def server_tls_context(cert_file, key_file):
    return server_context(cert_file, key_file)


def main():
    # A container PID 1 must install an explicit termination handler.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    token = Path(os.environ["KITTEN_TOKEN_FILE"]).read_text().strip()
    if len(token) < 32 or any(c.isspace() for c in token):
        raise SystemExit("Invalid speech service token")
    context = server_tls_context(os.environ["KITTEN_TLS_CERT_FILE"],
                                 os.environ["KITTEN_TLS_KEY_FILE"])
    synth = Synthesizer(os.environ.get("KITTEN_MODEL_DIR", "/models/nano"),
                        threads=int(os.environ.get("KITTEN_THREADS", "1")))
    server = None
    try:
        server = SpeechServer((os.environ.get("KITTEN_BIND_HOST", "127.0.0.1"),
                               int(os.environ.get("KITTEN_PORT", "8092"))), synth, token,
                              tls_context=context)
        server.serve_forever()
    finally:
        if server is not None:
            server.server_close()
        synth.close()


if __name__ == "__main__":
    main()
