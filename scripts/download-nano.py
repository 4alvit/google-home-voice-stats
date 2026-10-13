"""Download the fixed Apache-2.0 Nano model during image build, never at request time."""
import argparse
import hashlib
from pathlib import Path
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--variant', choices=['int8', 'fp32'], default='int8')
parser.add_argument('--output', type=Path, default=Path('/models/nano'))
args = parser.parse_args()
REVISION = "84781d74e29ee25217551556398b42f80593a813"
FILES = {'kitten_tts_nano_v0_8.onnx': 'f7b0afcbee92870b32b8e0276d855b954dc25470c9f051b376ac7eee537c76fc', 'config.json': 'b66006ccbeccd4de5fc3c9272059c47f5725df7215fd889785c03602652fab64', 'voices.npz': '8aa7cee235abb0739cb51e6559685f65a4dacd95568833d05699b1633f519b3f'}
if args.variant == 'fp32':
    REVISION = '7a1db645b1f3ab9420761d87428e042b9cec3f26'
    FILES['kitten_tts_nano_v0_8.onnx'] = '320564d2615f235de972ca27a7f39551c94185cfa24ca85b07a29084135f1e5e'
root = args.output
root.mkdir(parents=True, exist_ok=True)
for name, checksum in FILES.items():
    url = f"https://huggingface.co/KittenML/kitten-tts-nano-0.8-{args.variant}/resolve/{REVISION}/{name}"
    with urllib.request.urlopen(url, timeout=90) as response:
        data = response.read(64_000_000)
    if hashlib.sha256(data).hexdigest() != checksum:
        raise RuntimeError("Nano model checksum mismatch")
    (root / name).write_bytes(data)
