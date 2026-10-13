"""Bounded private HTTP speech request; run in an expendable subprocess."""
import http.client
import io
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
import wave

MAX_AUDIO = 6_000_000


def fetch_audio(endpoint, token, text):
    parsed = urlsplit(endpoint)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=2)
    try:
        connection.connect()
        # The parent enforces the configured total budget (at most ten seconds).
        # Allow a nine-second response for slower native hosts using that budget.
        connection.sock.settimeout(9)
        connection.request("POST", parsed.path, json.dumps({"text": text}).encode(), {
            "Authorization": "Bearer " + token, "Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200 or response.getheader("Content-Type") != "audio/wav":
            raise ValueError("speech response rejected")
        if response.getheader("Content-Encoding") not in (None, "identity"):
            raise ValueError("speech encoding rejected")
        data = response.read(MAX_AUDIO + 1)
        if len(data) > MAX_AUDIO:
            raise ValueError("speech response too large")
        with wave.open(io.BytesIO(data), "rb") as audio:
            if (audio.getnchannels() != 1 or audio.getsampwidth() != 2
                    or audio.getframerate() != 24000
                    or not 0 < audio.getnframes() <= 24000 * 115
                    or len(audio.readframes(audio.getnframes())) != audio.getnframes() * 2):
                raise ValueError("invalid speech audio")
        return data
    finally:
        connection.close()


def main():
    try:
        request = json.loads(sys.stdin.buffer.read(16384))
        data = fetch_audio(request["endpoint"], request["token"], request["text"])
        Path(sys.argv[1]).write_bytes(data)
    except Exception:
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
