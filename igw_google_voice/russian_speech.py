"""Optional offline Russian TTS workers behind the existing private HTTPS API."""
from __future__ import annotations

import hashlib
import io
import json
import multiprocessing as mp
import os
from pathlib import Path
import signal
import sys
import wave

from .kitten_service import SpeechServer, Synthesizer, server_tls_context
from .russian_text import normalize_russian
from .russian_voices import BACKENDS, PIPER_VOICES, asset_bundles, select_voice

RATE = 24000


def verify_assets(root, backend, voice=None):
    """Refuse changed/incomplete weights, including pickled codec components."""
    root = Path(root).resolve(strict=True)
    manifest = json.loads(Path(__file__).with_name('russian-speech-models.json').read_text())
    selected = asset_bundles(backend, voice)
    for bundle in selected:
        for item in manifest['bundles'][bundle]['files']:
            path = (root / bundle / item['path']).resolve(strict=True)
            if not path.is_relative_to(root) or path.stat().st_size != item['size']:
                raise ValueError('Speech assets do not match the manifest')
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            if digest.hexdigest() != item['sha256']:
                raise ValueError('Speech assets do not match the manifest')


def to_wav(samples, rate):
    import numpy as np
    from scipy.signal import resample_poly
    from math import gcd
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim != 1 or not 0 < len(samples) <= rate * 115 or not np.isfinite(samples).all():
        raise ValueError('Invalid generated audio')
    if rate != RATE:
        factor = gcd(rate, RATE)
        samples = resample_poly(samples, RATE // factor, rate // factor)
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())
    return output.getvalue()


class RussianModel:
    def __init__(self, root, backend, threads=4, voice=None):
        self.voice = select_voice(backend, voice)
        verify_assets(root, backend, self.voice)
        root = Path(root).resolve()
        self.backend = backend
        if backend == 'kitten2':
            import torch
            from unittest.mock import patch
            from kittenml import KittenTTS
            from kittenml.kittentts2 import vocoder
            torch.set_num_threads(threads)
            torch.set_num_interop_threads(1)
            def local_codec(*args, **kwargs):
                if kwargs.get('repo_id') != 'ResembleAI/chatterbox-turbo' or kwargs.get('filename') != 's3gen_meanflow.safetensors':
                    raise ValueError('Unreviewed codec requested')
                return str(root / 'codec/s3gen_meanflow.safetensors')
            # The pinned upstream codec otherwise resolves mutable Hub main.
            # Only its exact known request is redirected to our verified asset.
            with patch.object(vocoder, 'hf_hub_download', side_effect=local_codec):
                self.model = KittenTTS(str(root / 'kitten2'), device='cpu', backend='torch', weights='packed')
        else:
            import onnxruntime as ort
            from piper import PiperVoice
            from piper.config import PiperConfig
            ort.disable_telemetry_events()
            bundle, model_path = PIPER_VOICES[self.voice]
            path = root / bundle / model_path
            config = json.loads(Path(str(path) + '.json').read_text())
            if config.get('phoneme_type', 'espeak') != 'espeak' or config.get('num_speakers') != 1 or config.get('espeak', {}).get('voice') != 'ru':
                raise ValueError('Expected the reviewed Russian eSpeak voice')
            options = ort.SessionOptions()
            options.intra_op_num_threads = threads
            options.inter_op_num_threads = 1
            self.model = PiperVoice(config=PiperConfig.from_dict(config),
                                    session=ort.InferenceSession(str(path), sess_options=options,
                                                                providers=['CPUExecutionProvider']))

    def generate(self, text):
        import numpy as np
        text = normalize_russian(text)
        if self.backend == 'kitten2':
            samples = self.model.generate(text, voice='Russian', normalize=False,
                                          preset='stable', max_new_tokens=1000,
                                          advanced={'seed': 42, 'use_emotion': False})
            return to_wav(samples, self.model.sample_rate)
        output = io.BytesIO()
        with wave.open(output, 'wb') as wav:
            self.model.synthesize_wav(text, wav)
        with wave.open(io.BytesIO(output.getvalue()), 'rb') as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise ValueError('Unexpected Piper output format')
            return to_wav(np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32) / 32768,
                          wav.getframerate())


def russian_worker(connection, root, threads, backend, voice):
    # Libraries may print prompts. Silence only this expendable inference child.
    with open(os.devnull, 'w') as null:
        os.dup2(null.fileno(), 1)
        os.dup2(null.fileno(), 2)
    os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                      TRANSFORMERS_OFFLINE='1', TOKENIZERS_PARALLELISM='false',
                      OMP_NUM_THREADS=str(threads), OPENBLAS_NUM_THREADS='1')
    try:
        model = RussianModel(root, backend, threads, voice)
        model.generate('Готово.')
        connection.send(True)
        while True:
            text = connection.recv()
            try:
                connection.send_bytes(model.generate(text))
            except Exception:
                connection.send_bytes(b'')
    except (EOFError, BrokenPipeError):
        pass
    except Exception:
        # Startup diagnostics expose a fixed category, never library payloads.
        try:
            connection.send(False)
        except (OSError, EOFError):
            pass
    finally:
        connection.close()


class RussianSynthesizer(Synthesizer):
    def __init__(self, model_dir, backend='piper', timeout=30, threads=4, voice=None):
        if backend not in BACKENDS or not 1 <= timeout <= 120:
            raise ValueError('Invalid Russian speech configuration')
        self.backend = backend
        self.voice = select_voice(backend, voice)
        super().__init__(model_dir, timeout=timeout, threads=threads)

    def _start(self):
        self.ready.clear()
        context = mp.get_context('spawn')
        parent, child = context.Pipe()
        self.connection = parent
        self.process = context.Process(target=russian_worker,
                                       args=(child, self.model_dir, self.threads, self.backend, self.voice), daemon=True)
        self.process.start()
        child.close()
        if not parent.poll(180) or parent.recv() is not True:
            self.close()
            raise RuntimeError('Russian speech worker failed to start')
        self.ready.set()

    def generate(self, text):
        # Validate before IPC: malformed text must not trigger an expensive reload.
        normalized = normalize_russian(text)
        return super().generate(normalized)


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    token = Path(os.environ['KITTEN_TOKEN_FILE']).read_text().strip()
    if len(token) < 32 or any(c.isspace() for c in token):
        raise SystemExit('Invalid speech service token')
    context = server_tls_context(os.environ['KITTEN_TLS_CERT_FILE'], os.environ['KITTEN_TLS_KEY_FILE'])
    synth = RussianSynthesizer(os.environ['RUSSIAN_MODEL_ROOT'],
                               backend=os.environ.get('RUSSIAN_TTS_BACKEND', 'piper'),
                               voice=os.environ.get('RUSSIAN_SPEECH_VOICE'),
                               timeout=float(os.environ.get('RUSSIAN_TTS_TIMEOUT', '30')),
                               threads=int(os.environ.get('KITTEN_THREADS', '4')))
    server = None
    try:
        server = SpeechServer((os.environ.get('KITTEN_BIND_HOST', '127.0.0.1'),
                               int(os.environ.get('KITTEN_PORT', '8093'))), synth, token, tls_context=context)
        server.serve_forever()
    finally:
        if server is not None:
            server.server_close()
        synth.close()


if __name__ == '__main__':
    main()
