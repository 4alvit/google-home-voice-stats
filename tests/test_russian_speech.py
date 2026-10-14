"""Russian number fidelity, pinned assets and the TTS-only Wyoming protocol."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wyoming.event import async_read_event, async_write_event, Event
from igw_google_voice.russian_text import normalize_russian, number_words
from igw_google_voice.russian_speech import RussianSynthesizer, verify_assets
from igw_google_voice.wyoming_speech import Config, SpeechService, read_event


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
    def test_missing_or_changed_asset_is_refused_before_loading_a_model(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(FileNotFoundError):
                verify_assets(root, 'piper')
            with self.assertRaises(ValueError):
                verify_assets(root, 'unreviewed')

    def test_bad_config_and_input_never_start_or_reload_a_worker(self):
        with patch.object(RussianSynthesizer, '_start') as start:
            for options in ({'backend': 'unknown'}, {'timeout': 121}, {'threads': 8}):
                with self.assertRaises(ValueError):
                    RussianSynthesizer('/unused', **options)
            start.assert_not_called()
            synth = RussianSynthesizer('/unused')
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
        for _ in range(20):
            if self.service.admitted == 2:
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
        async def slow(text):
            await asyncio.sleep(.7)
            return b'\x01\x00' * 4800
        self.service.provider.synthesize = slow
        first, second = await self.connect(), await self.connect()
        for reader, writer in (first, second):
            await async_write_event(Event(type='synthesize', data={'text': 'Привет.'}), writer)
        first_events = [await asyncio.wait_for(async_read_event(first[0]), 1.2) for _ in range(3)]
        self.assertEqual(first_events[-1].type, 'audio-stop')
        second_event = await asyncio.wait_for(async_read_event(second[0]), .6)
        self.assertEqual(second_event.data['code'], 'timeout')
        self.assertEqual(self.service.admitted, 0)

    async def test_payload_and_bool_lengths_are_rejected(self):
        for header in ({'type': 'synthesize', 'payload_length': 1},
                       {'type': 'describe', 'data_length': True}):
            reader = asyncio.StreamReader()
            reader.feed_data(json.dumps(header).encode() + b'\n')
            with self.assertRaises(ValueError):
                await read_event(reader)


if __name__ == '__main__':
    unittest.main()
