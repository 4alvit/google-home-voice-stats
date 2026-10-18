"""Settings persist atomically and reach inference without accepting raw markup."""
import asyncio
import http.client
import json
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from igw_google_voice.speech_settings import DEFAULTS, SettingsStore, silero_arguments, validate_patch
from igw_google_voice.speech_api import RussianSpeechHandler
from igw_google_voice.kitten_client import fetch_settings
from igw_google_voice.kitten_service import SpeechServer, server_tls_context
from igw_google_voice.wyoming_speech import Config, HTTPSProvider


class SettingsTests(unittest.TestCase):
    def test_updates_survive_reload_and_invalid_changes_do_not_touch_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            settings = SettingsStore(path)
            settings.update({'voice': 'silero-ru-xenia', 'rate': 110})
            self.assertEqual(SettingsStore(path).snapshot()['voice'], 'silero-ru-xenia')
            before = path.read_bytes()
            for invalid in ({'rate': True}, {'pitch': 11}, {'rate': 99.5}, {'sentence_pause_ms': 51},
                            {'voice': 'unreviewed'}, {'emotion': 'happy'}, {'auto_yo': 'false'},
                            {'emphasis_words': '<break/>'}, {'emphasis_words': 'two words'},
                            {'emphasis_words': ','.join(['word'] * 11)}, []):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    settings.update(invalid)
                self.assertEqual(path.read_bytes(), before)
            with patch('igw_google_voice.speech_settings.os.replace', side_effect=OSError):
                with self.assertRaises(OSError):
                    settings.update({'rate': 120})
            self.assertEqual(settings.snapshot()['rate'], 110)
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_disjoint_concurrent_updates_and_request_overrides(self):
        settings = SettingsStore()
        threads = [threading.Thread(target=settings.update, args=(p,))
                   for p in ({'rate': 115}, {'pitch': 3}, {'auto_stress': False})]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        captured = settings.snapshot({'voice': 'silero-ru-eugene'})
        settings.update({'rate': 100})
        self.assertEqual((captured['rate'], captured['pitch'], captured['auto_stress']), (115, 3, False))
        self.assertEqual(settings.snapshot()['voice'], 'silero-ru-baya')

    def test_model_arguments_prosody_focus_and_auto_defaults(self):
        plain = silero_arguments('Привет! Всё хорошо.', DEFAULTS)
        self.assertEqual(plain['text'], 'Привет! Всё хорошо.')
        self.assertNotIn('type_str', plain)
        changed = silero_arguments('Привет & мир! Батарея заряжена.', dict(DEFAULTS,
            rate=110, pitch=2, sentence_pause_ms=250, intonation='exclamation',
            emphasis_words='батарея', auto_yo=False))
        xml = ElementTree.fromstring(changed['ssml_text'])
        self.assertEqual(xml.find('prosody').attrib, {'rate': '110%', 'pitch': '+2%'})
        self.assertEqual(len(xml.findall('.//break')), 2)
        self.assertIn('**Батарея**', changed['ssml_text'])
        self.assertFalse(changed['put_yo'])
        self.assertFalse(changed['put_yo_homo'])
        self.assertEqual(changed['type_str'], 'exclam|exclam')
        self.assertEqual(silero_arguments('**Привет**', DEFAULTS)['text'], 'Привет')


class SettingsAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        tls = root / 'tls'
        subprocess.run([sys.executable, 'scripts/create-russian-speech-tls.py', '--output', str(tls)],
                       check=True, capture_output=True)
        self.settings = SettingsStore(root / 'settings.json')
        outer = self
        class Synth:
            ready = threading.Event()
            settings = outer.settings
            def generate(self, text, options=None):
                outer.received = self.settings.snapshot(options)
                return b'audio'
        self.server = SpeechServer(('127.0.0.1', 0), Synth(), 'test-' + 'x' * 40,
            tls_context=server_tls_context(tls/'server.crt', tls/'server.key'),
            handler_class=RussianSpeechHandler)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.ca = str(tls/'ca.crt')
        self.endpoint = f'https://127.0.0.1:{self.server.server_port}/v1/speech'

    def request(self, method, path, body=None, authorized=True):
        connection = http.client.HTTPSConnection('127.0.0.1', self.server.server_port,
                                                context=ssl.create_default_context(cafile=self.ca))
        headers = {'Content-Type': 'application/json'}
        if authorized:
            headers['Authorization'] = 'Bearer ' + self.server.token
        try:
            connection.request(method, path, None if body is None else json.dumps(body), headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_authentication_validation_and_per_request_selection(self):
        self.assertEqual(self.request('GET', '/v1/settings', authorized=False)[0], 401)
        self.assertEqual(self.request('PATCH', '/v1/settings', {'rate': 120}, authorized=False)[0], 401)
        self.assertEqual(self.settings.snapshot()['rate'], 100)
        self.assertEqual(self.request('PATCH', '/v1/settings', {'rate': 999})[0], 400)
        self.assertEqual(self.request('PATCH', '/v1/settings', {'rate': 110})[0], 200)
        status, data = self.request('GET', '/v1/settings')
        self.assertEqual(json.loads(data)['settings']['rate'], 110)
        self.assertEqual(self.request('POST', '/v1/speech', {'text': 'Привет', 'options': {'voice': 'silero-ru-aidar'}})[0], 200)
        self.assertEqual(self.received['voice'], 'silero-ru-aidar')
        self.assertEqual(self.settings.snapshot()['voice'], 'silero-ru-baya')
        self.assertEqual(self.request('POST', '/v1/speech', {'text': 'Привет', 'options': []})[0], 400)

    def test_wyoming_captures_defaults_once_and_explicit_voice_wins(self):
        config = Config(self.endpoint, self.server.token, self.ca, voice='silero-ru-baya')
        provider = HTTPSProvider(config)
        self.settings.update({'rate': 111, 'voice': 'silero-ru-kseniya'})
        first = asyncio.run(provider.prepare('silero-ru-default'))
        self.settings.update({'rate': 100})
        second = asyncio.run(provider.prepare('silero-ru-eugene'))
        self.assertEqual((first['voice'], first['rate']), ('silero-ru-kseniya', 111))
        self.assertEqual((second['voice'], second['rate']), ('silero-ru-eugene', 100))
        self.assertEqual(fetch_settings(self.endpoint, self.server.token, self.ca)['rate'], 100)
        async def pair():
            return await asyncio.gather(provider.prepare('silero-ru-aidar'),
                                        provider.prepare('silero-ru-xenia'))
        voices = asyncio.run(pair())
        self.assertEqual([v['voice'] for v in voices], ['silero-ru-aidar', 'silero-ru-xenia'])
        self.assertEqual(self.settings.snapshot()['voice'], 'silero-ru-kseniya')


if __name__ == '__main__':
    unittest.main()
