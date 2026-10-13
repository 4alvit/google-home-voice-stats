"""Download the fixed Apache-2.0 Nano model during image build, never at request time."""
import hashlib
from pathlib import Path
import urllib.request

REVISION = "84781d74e29ee25217551556398b42f80593a813"
FILES = {'kitten_tts_nano_v0_8.onnx': 'f7b0afcbee92870b32b8e0276d855b954dc25470c9f051b376ac7eee537c76fc', 'config.json': 'b66006ccbeccd4de5fc3c9272059c47f5725df7215fd889785c03602652fab64', 'voices.npz': '8aa7cee235abb0739cb51e6559685f65a4dacd95568833d05699b1633f519b3f'}
root = Path("/models/nano")
root.mkdir(parents=True, exist_ok=True)
for name, checksum in FILES.items():
    url = f"https://huggingface.co/KittenML/kitten-tts-nano-0.8-int8/resolve/{REVISION}/{name}"
    with urllib.request.urlopen(url, timeout=90) as response:
        data = response.read(32_000_000)
    if hashlib.sha256(data).hexdigest() != checksum:
        raise RuntimeError("Nano model checksum mismatch")
    (root / name).write_bytes(data)
