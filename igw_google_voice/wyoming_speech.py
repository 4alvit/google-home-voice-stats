"""Bounded TTS-only Wyoming adapter for the private Russian HTTPS endpoint."""
import asyncio
import contextlib
from dataclasses import dataclass, field
import io
import json
import logging
import os
from pathlib import Path
import re
import sys
import wave

from wyoming.audio import AudioStart, AudioChunk, AudioStop
from wyoming.error import Error
from wyoming.event import Event, async_write_event
from wyoming.info import Attribution, Info, TtsProgram, TtsVoice
from wyoming.tts import SynthesizeStopped

from .kitten_client import MAX_AUDIO
from .russian_text import MAX_TEXT, normalize_russian
from .russian_voices import VOICES, SILERO_VOICES, SILERO_DEFAULT

VERSION = '0.3.0'
STREAM_TIMEOUT = 120
SENTENCE_END = re.compile(r'(?<=[.!?…])\s+')


@dataclass(frozen=True)
class Config:
    endpoint: str
    token: str = field(repr=False)
    ca_file: str
    voice: str = 'piper-ru-denis'
    timeout: float = 30

    def __post_init__(self):
        from urllib.parse import urlsplit
        from .__main__ import local_http_host
        url = urlsplit(self.endpoint)
        if (url.scheme != 'https' or not url.hostname or not local_http_host(url.hostname)
                or url.path != '/v1/speech' or url.username or url.password or url.query or url.fragment):
            raise ValueError('Expected a private HTTPS speech endpoint')
        if len(self.token) < 32 or any(c.isspace() for c in self.token):
            raise ValueError('Invalid speech credential')
        if not Path(self.ca_file).is_absolute() or not Path(self.ca_file).is_file():
            raise ValueError('Expected an installed private CA file')
        if self.voice not in VOICES or not 1 <= self.timeout <= 120:
            raise ValueError('Invalid speech voice/deadline')

    @classmethod
    def from_env(cls):
        return cls(os.environ['RUSSIAN_SPEECH_ENDPOINT'],
                   Path(os.environ['KITTEN_TOKEN_FILE']).read_text().strip(),
                   os.environ['KITTEN_CA_FILE'], os.environ.get('RUSSIAN_SPEECH_VOICE', 'piper-ru-denis'),
                   float(os.environ.get('RUSSIAN_TTS_TIMEOUT', '30')))


def service_info(config):
    attribution = Attribution(name='IGW Russian Speech', url='https://github.com/4alvit/google-home-voice-stats')
    return Info(tts=[TtsProgram(name='Local Russian Speech', description='Private Russian speech; no cloud inference',
                               attribution=attribution, installed=True, version=VERSION,
                               supports_synthesize_streaming=True,
                               voices=[TtsVoice(name=name, description=('Follow service settings' if name == SILERO_DEFAULT else 'Russian local voice'),
                                                attribution=attribution, installed=True, version=VERSION,
                                                languages=['ru', 'ru-RU']) for name in available_voices(config)])])


def available_voices(config):
    return (SILERO_DEFAULT, *SILERO_VOICES) if config.voice in SILERO_VOICES else (config.voice,)


async def read_event(reader):
    line = await reader.readline()
    if not line:
        return None
    if len(line) > 4096 or not line.endswith(b'\n'):
        raise ValueError('Invalid event')
    header = json.loads(line)
    if not isinstance(header, dict) or header.get('type') not in (
            'describe', 'synthesize', 'synthesize-start', 'synthesize-chunk', 'synthesize-stop'):
        raise ValueError('Invalid event')
    length = header.get('data_length', 0)
    payload = header.get('payload_length', 0)
    if type(length) is not int or not 0 <= length <= 8192 or type(payload) is not int or payload != 0:
        raise ValueError('Invalid event length')
    data = header.get('data', {})
    if not isinstance(data, dict):
        raise ValueError('Invalid event data')
    if length:
        extra = json.loads(await reader.readexactly(length))
        if not isinstance(extra, dict):
            raise ValueError('Invalid event data')
        data.update(extra)
    return Event(type=header['type'], data=data)


class HTTPSProvider:
    def __init__(self, config):
        self.config = config

    async def prepare(self, voice):
        if self.config.voice not in SILERO_VOICES:
            return None
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-m', 'igw_google_voice.kitten_client', '-',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            request = dict(operation='settings', endpoint=self.config.endpoint,
                           token=self.config.token, ca_file=self.config.ca_file)
            async with asyncio.timeout(5):
                output, _ = await process.communicate(json.dumps(request).encode())
            if process.returncode or len(output) > 4096:
                raise RuntimeError('Speech settings unavailable')
            options = json.loads(output)
            if voice and voice != SILERO_DEFAULT:
                options['voice'] = voice
            return options
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()

    async def synthesize(self, text, options=None):
        # A canceled caller can leave the HTTP model finishing its bounded work.
        # Retry only explicit busy responses, within this original total budget.
        delay = .1
        async with asyncio.timeout(self.config.timeout):
            while True:
                result = await self._attempt(text, options)
                if result is not None:
                    return result
                await asyncio.sleep(delay)
                delay = min(.8, delay * 2)

    async def _attempt(self, text, options=None):
        # A separate process makes cancellation bound the entire HTTPS operation,
        # including DNS, TLS and a server that dribbles bytes indefinitely.
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-m', 'igw_google_voice.kitten_client', '-',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        request = dict(endpoint=self.config.endpoint, token=self.config.token, text=text,
                       ca_file=self.config.ca_file, read_timeout=self.config.timeout + 1)
        if options is not None:
            request['options'] = options
        try:
            output, _ = await process.communicate(json.dumps(request).encode())
            if process.returncode == 75:
                return None
            if process.returncode != 0 or not 0 < len(output) <= MAX_AUDIO:
                raise RuntimeError('Speech provider failed')
            with wave.open(io.BytesIO(output), 'rb') as wav:
                if (wav.getframerate(), wav.getsampwidth(), wav.getnchannels()) != (24000, 2, 1):
                    raise RuntimeError('Invalid provider audio')
                pcm = wav.readframes(wav.getnframes())
                if not pcm or len(pcm) != wav.getnframes() * 2:
                    raise RuntimeError('Truncated provider audio')
            return pcm
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()


class SpeechService:
    def __init__(self, config, provider=None):
        self.config = config
        self.provider = provider or HTTPSProvider(config)
        self.serial = asyncio.Lock()
        self.admitted = 0
        self.connections = 0

    def validate_voice(self, event):
        voice = event.data.get('voice') or {}
        if (not isinstance(voice, dict) or voice.get('name') not in (None, '', *available_voices(self.config))
                or voice.get('language') not in (None, '', 'ru', 'ru-RU')
                or voice.get('speaker') is not None
                or event.data.get('text_format') not in (None, '', 'text')):
            raise ValueError('Invalid voice')
        return voice.get('name')

    async def stream(self, reader, writer, voice=None):
        """Synthesize complete sentences while HA continues sending text.

        One bounded reader owns the socket, including disconnect detection after
        synthesize-stop. The shared model lock is held only during inference.
        HA's compatibility synthesize event is checked, never spoken twice.
        """
        if self.admitted >= 2:
            raise RuntimeError('busy')
        self.admitted += 1
        sentences = asyncio.Queue()

        async def receive():
            text = pending = ''
            compatibility_seen = False
            for _ in range(4096):
                event = await read_event(reader)
                if event is None:
                    raise ConnectionError('Client disconnected')
                if event.type == 'synthesize-chunk' and not compatibility_seen:
                    chunk = event.data.get('text')
                    if not isinstance(chunk, str) or len(text) + len(chunk) > MAX_TEXT:
                        raise ValueError('Invalid streamed text')
                    text += chunk
                    pending += chunk
                    if text.strip():
                        normalize_russian(text)  # Same input policy as a complete request.
                    while match := SENTENCE_END.search(pending):
                        sentence, pending = pending[:match.start()], pending[match.end():]
                        if sentence.strip():
                            sentences.put_nowait(normalize_russian(sentence))
                elif event.type == 'synthesize' and not compatibility_seen:
                    compatibility_voice = self.validate_voice(event)
                    if compatibility_voice and compatibility_voice != voice:
                        raise ValueError('Stream compatibility voice differs')
                    if event.data.get('text') != text:
                        raise ValueError('Stream compatibility text differs')
                    compatibility_seen = True
                elif event.type == 'synthesize-stop':
                    normalize_russian(text)  # Reject an empty stream as well.
                    if pending.strip():
                        sentences.put_nowait(normalize_russian(pending))
                    sentences.put_nowait(None)
                    # Keep cancellation prompt while the last sentences render.
                    await reader.read(1)
                    raise ConnectionError('Client ended or pipelined the stream')
                else:
                    raise ValueError('Invalid stream event order')
            raise ValueError('Too many stream events')

        async def speak():
            started = False
            total_bytes = 0
            options = await self.provider.prepare(voice)
            while (text := await sentences.get()) is not None:
                async with asyncio.timeout(self.config.timeout):
                    async with self.serial:
                        pcm = await self.provider.synthesize(text, options)
                total_bytes += len(pcm)
                if not pcm or len(pcm) % 2 or total_bytes > 24000 * 2 * 115:
                    raise RuntimeError('Invalid audio')
                if not started:
                    await async_write_event(AudioStart(rate=24000, width=2, channels=1).event(), writer)
                    started = True
                for offset in range(0, len(pcm), 9600):
                    await async_write_event(AudioChunk(rate=24000, width=2, channels=1,
                                                       audio=pcm[offset:offset + 9600]).event(), writer)
            await async_write_event(AudioStop().event(), writer)
            await async_write_event(SynthesizeStopped().event(), writer)

        receiving = asyncio.create_task(receive())
        speaking = asyncio.create_task(speak())
        try:
            async with asyncio.timeout(STREAM_TIMEOUT):
                done, _ = await asyncio.wait((receiving, speaking), return_when=asyncio.FIRST_COMPLETED)
                # A malformed/disconnected input takes precedence over completion.
                if receiving in done:
                    await receiving
                await speaking
        finally:
            for task in (receiving, speaking):
                if not task.done():
                    task.cancel()
            await asyncio.gather(receiving, speaking, return_exceptions=True)
            self.admitted -= 1

    async def request(self, reader, text, voice=None):
        # At most one active synthesis and one waiting caller. A single deadline
        # covers queue wait and inference, and disconnect cancels either stage.
        if self.admitted >= 2:
            raise RuntimeError('busy')
        self.admitted += 1
        async def serial_synthesis():
            options = await self.provider.prepare(voice)
            async with self.serial:
                return await self.provider.synthesize(text, options)
        operation = asyncio.create_task(serial_synthesis())
        disconnect = asyncio.create_task(reader.read(1))
        try:
            async with asyncio.timeout(self.config.timeout):
                done, _ = await asyncio.wait((operation, disconnect), return_when=asyncio.FIRST_COMPLETED)
                if disconnect in done:
                    raise ConnectionError('Client ended or pipelined the request')
                return await operation
        finally:
            for task in (operation, disconnect):
                if not task.done():
                    task.cancel()
            await asyncio.gather(operation, disconnect, return_exceptions=True)
            self.admitted -= 1

    async def handle_client(self, reader, writer):
        self.connections += 1
        code = None
        try:
            if self.connections > 8:
                raise RuntimeError('busy')
            while True:
                event = await asyncio.wait_for(read_event(reader), 10)
                if event is None:
                    break
                if event.type == 'describe':
                    await asyncio.wait_for(async_write_event(service_info(self.config).event(), writer), 5)
                    continue
                voice = self.validate_voice(event)
                if event.type == 'synthesize-start':
                    await self.stream(reader, writer, voice)
                    continue
                if event.type != 'synthesize':
                    raise ValueError('Expected synthesis request')
                text = normalize_russian(event.data.get('text'))
                pcm = await self.request(reader, text, voice)
                if not pcm or len(pcm) % 2 or len(pcm) > 24000 * 2 * 115:
                    raise RuntimeError('Invalid audio')
                async with asyncio.timeout(10):
                    await async_write_event(AudioStart(rate=24000, width=2, channels=1).event(), writer)
                    for offset in range(0, len(pcm), 9600):
                        await async_write_event(AudioChunk(rate=24000, width=2, channels=1,
                                                           audio=pcm[offset:offset + 9600]).event(), writer)
                    await async_write_event(AudioStop().event(), writer)
        except (ValueError, UnicodeError, RecursionError):
            code = 'invalid-request'
        except TimeoutError:
            code = 'timeout'
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception:
            code = 'unavailable'
        finally:
            self.connections -= 1
            if code:
                logging.warning('RUSSIAN_SPEECH_FAILURE %s', code)
                with contextlib.suppress(ConnectionError, TimeoutError):
                    await asyncio.wait_for(async_write_event(Error(text='Русский голосовой сервис недоступен.', code=code).event(), writer), 2)
            writer.close()
            with contextlib.suppress(ConnectionError, TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), 2)


async def run():
    service = SpeechService(Config.from_env())
    server = await asyncio.start_server(service.handle_client,
                                        os.environ.get('WYOMING_HOST', '127.0.0.1'),
                                        int(os.environ.get('WYOMING_PORT', '10601')), limit=4096)
    async with server:
        await server.serve_forever()


def main():
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(run())


if __name__ == '__main__':
    main()
