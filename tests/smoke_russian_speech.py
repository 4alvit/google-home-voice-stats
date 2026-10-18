"""Run in a Russian speech image without network; uses only synthetic text."""
import io
import ipaddress
from pathlib import Path
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from igw_google_voice.kitten_client import fetch_audio
from igw_google_voice.kitten_service import SpeechServer
from igw_google_voice.tls_policy import server_context
import os
import time
import wave
from igw_google_voice.russian_speech import RussianSynthesizer
from igw_google_voice.speech_api import RussianSpeechHandler
from igw_google_voice.russian_voices import SILERO_VOICES


def main():
    started = time.monotonic()
    synth = RussianSynthesizer(os.environ.get('RUSSIAN_MODEL_ROOT', '/models'),
                               backend=os.environ.get('RUSSIAN_TTS_BACKEND', 'piper'), threads=2, timeout=30,
                               voice=os.environ.get('RUSSIAN_SPEECH_VOICE'))
    print(f'Voice: {synth.voice}', flush=True)
    print(f'Warm startup: {time.monotonic() - started:.3f}s', flush=True)
    try:
        for text in ('Четыре. Всё работает.', 'Батарея заряжена на 63%. Дом потребляет 420 Вт.'):
            started = time.monotonic()
            data = synth.generate(text)
            with wave.open(io.BytesIO(data), 'rb') as audio:
                assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 24000)
                assert audio.getnframes() > 24000
                duration = audio.getnframes() / 24000
            print(f'Synthesis: {time.monotonic() - started:.3f}s, audio: {duration:.3f}s', flush=True)
        if synth.backend == 'silero':
            cases = [{'voice': name} for name in SILERO_VOICES]
            cases += [dict(rate=110, pitch=2, sentence_pause_ms=250, emphasis_words='Батарея',
                           emphasis_intensity=level, intonation=intonation)
                      for level, intonation in ((1, 'statement'), (2, 'question'), (3, 'exclamation'))]
            cases += [dict(rate=80, pitch=-10), dict(rate=130, pitch=10),
                      dict(auto_stress=False, auto_yo=False)]
            for options in cases:
                audio = synth.generate('Батарея заряжена. Всё хорошо!', options)
                with wave.open(io.BytesIO(audio), 'rb') as wav:
                    assert wav.getnframes() > 2400
                    assert any(wav.readframes(wav.getnframes()))
                print('Settings inference passed: ' + repr(options), flush=True)
        with tempfile.TemporaryDirectory(prefix="speech-smoke-") as directory:
            root = Path(directory)
            key = rsa.generate_private_key(65537, 2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Disposable speech smoke")])
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
                    .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
                    .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
                    .sign(key, hashes.SHA256()))
            certificate, private_key = root / "server.crt", root / "server.key"
            certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            private_key.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            private_key.chmod(0o600)
            token = "disposable-synthetic-token-for-smoke-only"
            server = SpeechServer(("127.0.0.1", 0), synth, token,
                                  tls_context=server_context(certificate, private_key),
                                  handler_class=RussianSpeechHandler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                endpoint = f"https://127.0.0.1:{server.server_port}/v1/speech"
                data = fetch_audio(endpoint, token, "Батарея заряжена на 63 процента.", str(certificate), read_timeout=31)
                with wave.open(io.BytesIO(data), "rb") as audio:
                    assert audio.getframerate() == 24000 and audio.getnframes() > 24000
                try:
                    fetch_audio(endpoint, "incorrect-token", "test", str(certificate))
                except ValueError:
                    pass
                else:
                    raise AssertionError("Wrong token was accepted")
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)
                assert not worker.is_alive()
        print('Offline Russian model, authenticated HTTPS and complete speech output passed')
    finally:
        synth.close()


if __name__ == '__main__':
    main()
