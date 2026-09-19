"""One bounded local English synthesis job; no voice discovery or downloads."""

from __future__ import annotations

import json
from pathlib import Path
import resource
import sys
import wave


MAX_INPUT_BYTES = 4800
MAX_MODEL_BYTES = 512 * 1024 * 1024


def synthesize(model_name: str, output_name: str) -> None:
    # Apply limits before importing the optional inference engine.
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    model = Path(model_name)
    config_path = Path(str(model) + ".json")
    if (not model.is_absolute() or model.suffix != ".onnx" or not model.is_file()
        or not 0 < model.stat().st_size <= MAX_MODEL_BYTES
        or not config_path.is_file() or config_path.stat().st_size > 1024 * 1024):
        raise ValueError("Invalid local voice files")
    data = json.loads(config_path.read_text())
    # Other Piper phonemizers may fetch extra models. Restrict this English adapter
    # to bundled eSpeak phonemization before importing or loading a model.
    if (not isinstance(data, dict) or data.get("phoneme_type") != "espeak" or data.get("num_speakers") != 1
        or not isinstance(data.get("espeak"), dict)
        or data["espeak"].get("voice") not in {"en-us", "en-gb", "en"}):
        raise ValueError("Use a local English eSpeak-based Piper voice")
    text = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if not 0 < len(text) <= MAX_INPUT_BYTES:
        raise ValueError("Invalid speech input")
    text = text.decode("utf-8")
    if len(text) > 1200:
        raise ValueError("Speech input exceeds the limit")
    import onnxruntime
    from piper import PiperVoice
    from piper.config import PiperConfig
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
    voice = PiperVoice(config=PiperConfig.from_dict(data),
                       session=onnxruntime.InferenceSession(str(model), sess_options=options,
                                                           providers=["CPUExecutionProvider"]))
    with wave.open(output_name, "wb") as output:
        voice.synthesize_wav(text, output)


def main() -> int:
    try:
        if len(sys.argv) != 3:
            return 1
        synthesize(sys.argv[1], sys.argv[2])
    except Exception:
        # Parent uses only the exit status; paths, input and library errors stay private.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
