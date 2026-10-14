"""Run in the Piper image without network access; uses only synthetic text."""
import io
import time
import wave
from igw_google_voice.russian_speech import RussianSynthesizer


def main():
    started = time.monotonic()
    synth = RussianSynthesizer('/models', backend='piper', threads=2, timeout=30)
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
        print('Offline Russian model and supervised generation passed')
    finally:
        synth.close()


if __name__ == '__main__':
    main()
