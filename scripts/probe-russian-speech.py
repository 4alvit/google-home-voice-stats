#!/usr/bin/env python3
"""Measure two concurrent synthetic Wyoming requests; keep output in private storage."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time
import wave

from wyoming.event import Event, async_read_event, async_write_event


async def synthesize(args, index):
    started = time.monotonic()
    reader, writer = await asyncio.open_connection(args.host, args.port)
    pcm = bytearray()
    audio_format = None
    try:
        async with asyncio.timeout(45):
            await async_write_event(Event(type='synthesize', data={
                'text': 'Батарея заряжена на 63%. Дом потребляет 420 Вт.',
                'voice': {'language': 'ru'}}), writer)
            while True:
                event = await async_read_event(reader)
                if event is None or event.type == 'error':
                    raise RuntimeError('Wyoming synthesis failed')
                if event.type == 'audio-start':
                    audio_format = tuple(event.data[k] for k in ('rate', 'width', 'channels'))
                    if audio_format != (24000, 2, 1):
                        raise RuntimeError('Unexpected audio format')
                elif event.type == 'audio-chunk':
                    pcm.extend(event.payload or b'')
                    if len(pcm) > 24000 * 2 * 115:
                        raise RuntimeError('Audio exceeds limit')
                elif event.type == 'audio-stop':
                    if not pcm or audio_format is None:
                        raise RuntimeError('Missing audio')
                    break
    finally:
        writer.close()
        await writer.wait_closed()
    elapsed = time.monotonic() - started
    path = args.output / f'paired-{index}.wav'
    with wave.open(str(path), 'wb') as wav:
        wav.setframerate(24000)
        wav.setsampwidth(2)
        wav.setnchannels(1)
        wav.writeframes(pcm)
    return {'request': index, 'seconds': elapsed, 'audio_seconds': len(pcm) / 48000}


async def run(args):
    async with asyncio.timeout(50):
        return await asyncio.gather(*(synthesize(args, index) for index in (1, 2)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=10601)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=True)
    rows = asyncio.run(run(args))
    (args.output / 'paired.private.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(json.dumps(rows))


if __name__ == '__main__':
    main()
