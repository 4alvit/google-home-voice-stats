#!/usr/bin/env python3
"""Measure synthetic Russian speech only; keep audio and results in private/."""
import argparse
import io
import json
from pathlib import Path
import resource
import os
import signal
import subprocess
import sys
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from igw_google_voice.russian_speech import RussianModel

PHRASES = {
    'short': 'Четыре. Всё работает.',
    'energy': 'Заряд батареи 63%. Солнце вырабатывает 1,5 кВт. Дом потребляет 420 Вт. За сегодня получено 12,5 кВт⋅ч.',
    'answer': 'Сейчас батарея заряжается. Солнечной энергии хватает для дома, а оставшаяся мощность поступает в аккумулятор.',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('piper', 'kitten2'), required=True)
    parser.add_argument('--model-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--repeat', type=int, default=2)
    parser.add_argument('--wall-timeout', type=int, default=600)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.threads <= 4 or not 1 <= args.repeat <= 3:
        parser.error('Use 1–4 threads and 1–3 repetitions')
    if not 30 <= args.wall_timeout <= 1800:
        parser.error('Use a wall timeout of 30–1800 seconds')
    args.output.mkdir(parents=True, exist_ok=True)
    if not args.worker:
        child = subprocess.Popen([sys.executable, __file__, *sys.argv[1:], '--worker'], start_new_session=True)
        try:
            raise SystemExit(child.wait(timeout=args.wall_timeout))
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            (args.output / 'deadline.private.json').write_text(json.dumps({'wall_timeout_seconds': args.wall_timeout}) + '\n')
            raise SystemExit('Benchmark exceeded its wall deadline; partial measurements were preserved')
    started = time.monotonic()
    model = RussianModel(args.model_root, args.backend, args.threads)
    report = {'backend': args.backend, 'threads': args.threads, 'load_seconds': time.monotonic() - started, 'samples': []}
    print(json.dumps({'load_seconds': report['load_seconds']}), flush=True)
    for name, phrase in PHRASES.items():
        for repeat in range(args.repeat):
            started = time.monotonic()
            audio = model.generate(phrase)
            elapsed = time.monotonic() - started
            with wave.open(io.BytesIO(audio), 'rb') as wav:
                duration = wav.getnframes() / wav.getframerate()
            path = args.output / f'{name}-{repeat + 1}.wav'
            path.write_bytes(audio)
            row = dict(name=name, repeat=repeat + 1, seconds=elapsed, audio_seconds=duration,
                       real_time_factor=elapsed / duration)
            report['samples'].append(row)
            report['max_rss_native'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            report['max_rss_unit'] = 'bytes' if sys.platform == 'darwin' else 'KiB'
            (args.output / 'benchmark.private.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
