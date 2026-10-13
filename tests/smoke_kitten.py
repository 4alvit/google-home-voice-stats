"""Run inside the built image to verify the actual offline model and supervisor."""
import io
import wave
from igw_google_voice.kitten_service import Synthesizer


def main():
    synth = Synthesizer('/models/nano')
    try:
        data = synth.generate('Battery charge is seventy four percent. No active alarms.')
        with wave.open(io.BytesIO(data), 'rb') as audio:
            assert audio.getnchannels() == 1
            assert audio.getsampwidth() == 2
            assert audio.getframerate() == 24000
            assert audio.getnframes() > 24000
        print('Offline Nano model and supervised generation passed')
    finally:
        synth.close()


if __name__ == '__main__':
    main()
