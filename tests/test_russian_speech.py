"""Russian number fidelity, pinned assets and the TTS-only Wyoming protocol."""
import asyncio
import json
import io
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wyoming.event import async_read_event, async_write_event, Event
from igw_google_voice.russian_text import normalize_russian, number_words
from igw_google_voice.russian_speech import RussianSynthesizer, verify_assets
from igw_google_voice.russian_voices import asset_bundles, select_voice
from igw_google_voice.wyoming_speech import Config, SpeechService, HTTPSProvider, read_event
from igw_google_voice.kitten_service import SpeechServer, BusyError, server_tls_context


class RussianTextTests(unittest.TestCase):
    def test_numbers_units_and_negative_fraction_keep_their_value(self):
        cases = {
            '1 Вт, 2 Вт, 5 Вт, 11 Вт, 21 Вт.': 'один ватт, два ватта, пять ватт, одиннадцать ватт, двадцать один ватт.',
            'Батарея 63%.': 'Батарея шестьдесят три процента.',
            'За день 12,5 кВт⋅ч.': 'За день двенадцать целых пять десятых киловатт-часа.',
            'Мощность −0.25 кВт.': 'Мощность минус ноль целых двадцать пять сотых киловатта.',
            'Солнце: 1\u202f234 Вт.': 'Солнце: одна тысяча двести тридцать четыре ватта.',
            'Ответ 4.': 'Ответ четыре.',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(normalize_russian(text), expected)
                self.assertEqual(normalize_russian(expected), expected)

    def test_large_numbers_and_fraction_digits(self):
        self.assertEqual(number_words('1000001'), 'один миллион один')
        self.assertEqual(number_words('0.0000001'), 'ноль запятая ноль ноль ноль ноль ноль ноль один')
        self.assertEqual(number_words('2.01'), 'две целых одна сотая')

    def test_empty_markup_controls_and_expansion_limit_are_rejected(self):
        for text in ('', ' ', 'a\x00b', '<laugh>привет', '[joyful]привет', '(((привет)))', '1' * 16,
                     ('123456789 Вт. ' * 70)):
            with self.subTest(text=text[:25]), self.assertRaises(ValueError):
                normalize_russian(text)


class AssetTests(unittest.TestCase):
    def test_voice_selection_preserves_defaults_and_rejects_cross_backend_names(self):
        self.assertEqual(select_voice('piper'), 'piper-ru-denis')
        self.assertEqual(select_voice('kitten2'), 'kitten2-russian')
        self.assertEqual(select_voice('silero'), 'silero-ru-baya')
        self.assertEqual(asset_bundles('silero', 'silero-ru-baya'), ('silero',))
        self.assertEqual(asset_bundles('piper'), ('piper',))
        self.assertEqual(asset_bundles('piper', 'piper-ru-irina'), ('piper-irina',))
        for backend, voice in (('piper', 'kitten2-russian'), ('kitten2', 'piper-ru-irina'),
                               ('piper', 'unreviewed'), ('piper', ''),
                               ('piper', 'silero-ru-baya'), ('silero', 'piper-ru-irina')):
            with self.subTest(backend=backend, voice=voice), self.assertRaises(ValueError):
                select_voice(backend, voice)

    def test_irina_is_verified_independently_and_never_falls_back_to_denis(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = {'bundles': {name: {'files': [{'path': 'test.bin', 'size': 3,
                'sha256': 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'}]}
                for name in ('piper', 'piper-irina')}}
            denis = Path(root) / 'piper' / 'test.bin'
            denis.parent.mkdir()
            denis.write_bytes(b'abc')
            with patch('igw_google_voice.russian_speech.json.loads', return_value=manifest):
                with self.assertRaises(FileNotFoundError):
                    verify_assets(root, 'piper', 'piper-ru-irina')
                irina = Path(root) / 'piper-irina' / 'test.bin'
                irina.parent.mkdir()
                irina.write_bytes(b'abc')
                denis.write_bytes(b'bad')
                verify_assets(root, 'piper', 'piper-ru-irina')
                irina.write_bytes(b'bad')
                with self.assertRaises(ValueError):
                    verify_assets(root, 'piper', 'piper-ru-irina')

    def test_renderer_keeps_inference_and_discovery_voice_in_sync(self):
        for voice in ('piper-ru-denis', 'piper-ru-irina', 'silero-ru-baya'):
            result = subprocess.run([sys.executable, 'scripts/render-russian-speech.py',
                '--node', 'test-node', '--image', 'registry.example/speech@sha256:' + 'a' * 64,
                '--voice', voice], check=True, capture_output=True, text=True)
            containers = json.loads(result.stdout)['items'][0]['spec']['template']['spec']['containers']
            self.assertEqual(len(containers), 2)
            for container in containers:
                env = {item['name']: item['value'] for item in container['env']}
                self.assertEqual(env['RUSSIAN_SPEECH_VOICE'], voice)
                self.assertEqual(env['RUSSIAN_TTS_BACKEND'],
                                 'silero' if voice == 'silero-ru-baya' else 'piper')

    def test_missing_or_changed_asset_is_refused_before_loading_a_model(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(FileNotFoundError):
                verify_assets(root, 'piper')
            with self.assertRaises(ValueError):
                verify_assets(root, 'unreviewed')
            asset = Path(root) / 'piper' / 'test.bin'
            asset.parent.mkdir()
            asset.write_bytes(b'abc')
            manifest = {'bundles': {'piper': {'files': [{'path': 'test.bin', 'size': 3,
                'sha256': 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'}]}}}
            with patch('igw_google_voice.russian_speech.json.loads', return_value=manifest):
                verify_assets(root, 'piper')
                for changed in (b'def', b'abcd'):
                    asset.write_bytes(changed)
                    with self.assertRaises(ValueError):
                        verify_assets(root, 'piper')

    def test_bad_config_and_input_never_start_or_reload_a_worker(self):
        with patch.object(RussianSynthesizer, '_start') as start:
            for options in ({'backend': 'unknown'}, {'timeout': 121}, {'threads': 8},
                            {'voice': 'kitten2-russian'}, {'voice': 'unreviewed'}):
                with self.assertRaises(ValueError):
                    RussianSynthesizer('/unused', **options)
            start.assert_not_called()
            synth = RussianSynthesizer('/unused')
            self.assertEqual(synth.voice, 'piper-ru-denis')
            with patch.object(synth, 'close') as close, self.assertRaises(ValueError):
                synth.generate('<laugh>')
            close.assert_not_called()


class WyomingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        ca = Path(self.directory.name) / 'ca.crt'
        ca.touch()
        self.config = Config('https://127.0.0.1:8093/v1/speech', 't' * 40, str(ca), timeout=1)
        self.calls = []
        outer = self
        class Provider:
            async def synthesize(self, text):
                outer.calls.append(text)
                return b'\x01\x00' * 4800
        self.service = SpeechService(self.config, Provider())
        self.server = await asyncio.start_server(self.service.handle_client, '127.0.0.1', 0, limit=4096)
        self.addAsyncCleanup(self.stop_server)

    async def stop_server(self):
        self.server.close()
        await self.server.wait_closed()

    async def connect(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.server.sockets[0].getsockname()[1])
        self.addCleanup(writer.close)
        return reader, writer

    async def test_discovery_and_synthesis_advertise_ru_and_valid_audio(self):
        reader, writer = await self.connect()
        await async_write_event(Event(type='describe'), writer)
        info = await asyncio.wait_for(async_read_event(reader), 2)
        voice = info.data['tts'][0]['voices'][0]
        self.assertTrue(info.data['tts'][0]['supports_synthesize_streaming'])
        self.assertEqual(voice['languages'], ['ru', 'ru-RU'])
        self.assertEqual(voice['name'], 'piper-ru-denis')
        await async_write_event(Event(type='synthesize', data={'text': 'Батарея 63%.', 'voice': {'language': 'ru'}}), writer)
        events = [await asyncio.wait_for(async_read_event(reader), 2) for _ in range(3)]
        self.assertEqual([e.type for e in events], ['audio-start', 'audio-chunk', 'audio-stop'])
        self.assertEqual({k: events[0].data[k] for k in ('rate', 'width', 'channels')},
                         {'rate': 24000, 'width': 2, 'channels': 1})
        self.assertEqual(len(events[1].payload), 9600)
        self.assertEqual(self.calls, ['Батарея шестьдесят три процента.'])

    async def test_invalid_voice_and_huge_length_do_not_call_provider(self):
        for raw in (b'{"type":"synthesize","data_length":999999999}\n',
                    json.dumps({'type': 'synthesize', 'data': {'text': 'hello', 'voice': {'language': 'en'}}}).encode() + b'\n'):
            reader, writer = await self.connect()
            writer.write(raw)
            await writer.drain()
            event = await asyncio.wait_for(async_read_event(reader), 2)
            self.assertEqual(event.type, 'error')
            self.assertEqual(event.data['code'], 'invalid-request')
        self.assertEqual(self.calls, [])

    async def test_irina_discovery_accepts_irina_and_rejects_old_voice_name(self):
        self.service.config = Config(self.config.endpoint, self.config.token,
                                     self.config.ca_file, voice='piper-ru-irina', timeout=1)
        reader, writer = await self.connect()
        await async_write_event(Event(type='describe'), writer)
        info = await asyncio.wait_for(async_read_event(reader), 2)
        self.assertEqual([v['name'] for v in info.data['tts'][0]['voices']], ['piper-ru-irina'])
        await async_write_event(Event(type='synthesize', data={'text': 'Я готова.',
            'voice': {'name': 'piper-ru-irina', 'language': 'ru'}}), writer)
        events = [await asyncio.wait_for(async_read_event(reader), 2) for _ in range(3)]
        self.assertEqual(events[-1].type, 'audio-stop')
        await async_write_event(Event(type='synthesize', data={'text': 'Я готова.',
            'voice': {'name': 'piper-ru-denis'}}), writer)
        error = await asyncio.wait_for(async_read_event(reader), 2)
        self.assertEqual(error.data['code'], 'invalid-request')
        self.assertEqual(self.calls, ['Я готова.'])

    async def test_baya_discovery_synthesizes_russian_and_refuses_stale_irina(self):
        self.service.config = Config(self.config.endpoint, self.config.token,
                                     self.config.ca_file, voice='silero-ru-baya', timeout=1)
        reader, writer = await self.connect()
        await async_write_event(Event(type='describe'), writer)
        info = await asyncio.wait_for(async_read_event(reader), 2)
        self.assertEqual([v['name'] for v in info.data['tts'][0]['voices']], ['silero-ru-baya'])
        self.assertTrue(info.data['tts'][0]['supports_synthesize_streaming'])
        await async_write_event(Event(type='synthesize', data={'text': 'Батарея 63%.',
            'voice': {'name': 'silero-ru-baya', 'language': 'ru'}}), writer)
        events = [await asyncio.wait_for(async_read_event(reader), 2) for _ in range(3)]
        self.assertEqual(events[-1].type, 'audio-stop')
        self.assertEqual(self.calls, ['Батарея шестьдесят три процента.'])
        await async_write_event(Event(type='synthesize', data={'text': 'Привет!',
            'voice': {'name': 'piper-ru-irina'}}), writer)
        error = await asyncio.wait_for(async_read_event(reader), 2)
        self.assertEqual(error.data['code'], 'invalid-request')
        self.assertEqual(len(self.calls), 1)

    async def test_stream_speaks_before_input_ends_and_never_duplicates_full_text(self):
        reader, writer = await self.connect()
        await async_write_event(Event(type='synthesize-start', data={'voice': {'language': 'ru'}}), writer)
        # A decimal and its unit can span multiple input chunks.
        for chunk in ('Мощность 1.', '5 кВт. ', 'Батарея '):
            await async_write_event(Event(type='synthesize-chunk', data={'text': chunk}), writer)
        first = [await asyncio.wait_for(async_read_event(reader), 1) for _ in range(2)]
        self.assertEqual([e.type for e in first], ['audio-start', 'audio-chunk'])
        self.assertEqual(self.calls, [normalize_russian('Мощность 1.5 кВт.')])
        await async_write_event(Event(type='synthesize-chunk', data={'text': '63%.'}), writer)
        await async_write_event(Event(type='synthesize', data={'text': 'Мощность 1.5 кВт. Батарея 63%.'}), writer)
        await async_write_event(Event(type='synthesize-stop'), writer)
        tail = [await asyncio.wait_for(async_read_event(reader), 1) for _ in range(3)]
        self.assertEqual([e.type for e in tail], ['audio-chunk', 'audio-stop', 'synthesize-stopped'])
        self.assertEqual(self.calls, [normalize_russian('Мощность 1.5 кВт.'),
                                     normalize_russian('Батарея 63%.')])

    async def test_stream_without_compatibility_event_flushes_last_sentence(self):
        reader, writer = await self.connect()
        for kind, data in [('synthesize-start', {}), ('synthesize-chunk', {'text': 'Я готова'}),
                           ('synthesize-stop', {})]:
            await async_write_event(Event(type=kind, data=data), writer)
        events = [await asyncio.wait_for(async_read_event(reader), 1) for _ in range(4)]
        self.assertEqual([e.type for e in events],
                         ['audio-start', 'audio-chunk', 'audio-stop', 'synthesize-stopped'])
        self.assertEqual(self.calls, ['Я готова'])

    async def test_invalid_streams_do_not_synthesize(self):
        cases = [
            [('synthesize-chunk', {'text': 'x' * 1201})],
            [('synthesize-chunk', {'text': 'Текст'}), ('synthesize', {'text': 'Другой'})],
            [('synthesize-stop', {})],
            [('synthesize-start', {})],
            [('synthesize-chunk', {'text': '<speak>Текст</speak>'})],
        ]
        for events in cases:
            reader, writer = await self.connect()
            await async_write_event(Event(type='synthesize-start'), writer)
            for kind, data in events:
                await async_write_event(Event(type=kind, data=data), writer)
            error = await asyncio.wait_for(async_read_event(reader), 1)
            self.assertEqual(error.type, 'error')
            self.assertEqual(error.data['code'], 'invalid-request')
        self.assertEqual(self.calls, [])

    async def test_stream_disconnect_cancels_inference_after_input_stop(self):
        began, cancelled = asyncio.Event(), asyncio.Event()
        async def blocked(text):
            began.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        self.service.provider.synthesize = blocked
        reader, writer = await self.connect()
        for kind, data in [('synthesize-start', {}), ('synthesize-chunk', {'text': 'Привет.'}),
                           ('synthesize-stop', {})]:
            await async_write_event(Event(type=kind, data=data), writer)
        await asyncio.wait_for(began.wait(), 1)
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(cancelled.wait(), 1)
        for _ in range(20):
            if self.service.admitted == 0:
                break
            await asyncio.sleep(.01)
        self.assertEqual(self.service.admitted, 0)

    async def test_idle_stream_deadline_releases_admission(self):
        with patch('igw_google_voice.wyoming_speech.STREAM_TIMEOUT', .05):
            reader, writer = await self.connect()
            await async_write_event(Event(type='synthesize-start'), writer)
            error = await asyncio.wait_for(async_read_event(reader), 1)
        self.assertEqual(error.data['code'], 'timeout')
        self.assertEqual(self.service.admitted, 0)

    async def test_disconnect_cancels_request_and_releases_lease(self):
        began = asyncio.Event()
        cancelled = asyncio.Event()
        async def blocked(text):
            began.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        self.service.provider.synthesize = blocked
        reader, writer = await self.connect()
        await async_write_event(Event(type='synthesize', data={'text': 'Привет.'}), writer)
        await asyncio.wait_for(began.wait(), 1)
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(cancelled.wait(), 1)
        for _ in range(20):
            if self.service.admitted == 0:
                break
            await asyncio.sleep(.01)
        self.assertEqual(self.service.admitted, 0)

    async def test_pair_queues_in_order_and_third_request_is_rejected(self):
        release = asyncio.Event()
        active = []
        async def blocked(text):
            active.append(text)
            await release.wait()
            return b'\x01\x00' * 4800
        self.service.provider.synthesize = blocked
        clients = [await self.connect() for _ in range(3)]
        for index, (reader, writer) in enumerate(clients):
            await async_write_event(Event(type='synthesize', data={'text': f'Ответ {index}.'}), writer)
            if index < 2:
                for _ in range(20):
                    if self.service.admitted == index + 1:
                        break
                    await asyncio.sleep(.01)
        denied = await asyncio.wait_for(async_read_event(clients[2][0]), 1)
        self.assertEqual(denied.data['code'], 'unavailable')
        self.assertEqual(active, ['Ответ ноль.'])
        release.set()
        for reader, writer in clients[:2]:
            events = [await asyncio.wait_for(async_read_event(reader), 1) for _ in range(3)]
            self.assertEqual(events[-1].type, 'audio-stop')
        self.assertEqual(active, ['Ответ ноль.', 'Ответ один.'])
        self.assertEqual(self.service.admitted, 0)

    async def test_queued_disconnect_never_enters_provider(self):
        release = asyncio.Event()
        active = []
        async def blocked(text):
            active.append(text)
            await release.wait()
            return b'\x01\x00' * 4800
        self.service.provider.synthesize = blocked
        first = await self.connect()
        second = await self.connect()
        for reader, writer in (first, second):
            await async_write_event(Event(type='synthesize', data={'text': 'Привет.'}), writer)
        for _ in range(20):
            if self.service.admitted == 2:
                break
            await asyncio.sleep(.01)
        second[1].close()
        await second[1].wait_closed()
        for _ in range(20):
            if self.service.admitted == 1:
                break
            await asyncio.sleep(.01)
        self.assertEqual(self.service.admitted, 1)
        release.set()
        for _ in range(3):
            await asyncio.wait_for(async_read_event(first[0]), 1)
        self.assertEqual(active, ['Привет.'])

    async def test_deadline_bounds_wait_and_active_inference(self):
        cancelled = asyncio.Event()
        async def blocked(text):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        self.service.provider.synthesize = blocked
        reader, writer = await self.connect()
        await async_write_event(Event(type='synthesize', data={'text': 'Привет.'}), writer)
        event = await asyncio.wait_for(async_read_event(reader), 1.5)
        self.assertEqual(event.data['code'], 'timeout')
        self.assertTrue(cancelled.is_set())
        self.assertEqual(self.service.admitted, 0)

    async def test_queue_time_counts_toward_the_same_deadline(self):
        began = asyncio.Event()
        async def slow(text):
            began.set()
            await asyncio.sleep(.7)
            return b'\x01\x00' * 4800
        self.service.provider.synthesize = slow
        first, second = await self.connect(), await self.connect()
        for reader, writer in (first, second):
            await async_write_event(Event(type='synthesize', data={'text': 'Привет.'}), writer)
            await asyncio.wait_for(began.wait(), .5)
        first_events = [await asyncio.wait_for(async_read_event(first[0]), 1.2) for _ in range(3)]
        self.assertEqual(first_events[-1].type, 'audio-stop')
        second_event = await asyncio.wait_for(async_read_event(second[0]), .6)
        self.assertEqual(second_event.data['code'], 'timeout')
        self.assertEqual(self.service.admitted, 0)

    async def test_real_tls_busy_after_cancel_recovers_for_followup(self):
        root = Path(self.directory.name) / 'real-tls'
        subprocess.run([sys.executable, 'scripts/create-russian-speech-tls.py', '--output', str(root)],
                       check=True, capture_output=True)
        output = io.BytesIO()
        with wave.open(output, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(b'\x01\x00' * 4800)
        class Synth:
            ready = threading.Event()
            lock = threading.Lock()
            began = threading.Event()
            busy_count = 0
            def generate(inner, text):
                if not inner.lock.acquire(False):
                    inner.busy_count += 1
                    raise BusyError()
                try:
                    inner.began.set()
                    time.sleep(.6)
                    return output.getvalue()
                finally:
                    inner.lock.release()
        synth = Synth()
        synth.ready.set()
        server = SpeechServer(('127.0.0.1', 0), synth, 't' * 40,
                              tls_context=server_tls_context(root / 'server.crt', root / 'server.key'))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addAsyncCleanup(asyncio.to_thread, server.shutdown)
        config = Config(f'https://127.0.0.1:{server.server_port}/v1/speech', 't' * 40,
                        str(root / 'ca.crt'), timeout=3)
        self.service.config = config
        self.service.provider = HTTPSProvider(config)
        first_reader, first_writer = await self.connect()
        await async_write_event(Event(type='synthesize', data={'text': 'Привет.'}), first_writer)
        self.assertTrue(await asyncio.to_thread(synth.began.wait, 1))
        first_writer.close()
        await first_writer.wait_closed()
        for _ in range(30):
            if self.service.admitted == 0:
                break
            await asyncio.sleep(.01)
        reader, writer = await self.connect()
        await async_write_event(Event(type='synthesize', data={'text': 'Повтор.'}), writer)
        events = [await asyncio.wait_for(async_read_event(reader), 3) for _ in range(3)]
        self.assertEqual(events[-1].type, 'audio-stop')
        self.assertGreater(synth.busy_count, 0)

    async def test_payload_and_bool_lengths_are_rejected(self):
        for header in ({'type': 'synthesize', 'payload_length': 1},
                       {'type': 'describe', 'data_length': True}):
            reader = asyncio.StreamReader()
            reader.feed_data(json.dumps(header).encode() + b'\n')
            with self.assertRaises(ValueError):
                await read_event(reader)


if __name__ == '__main__':
    unittest.main()
