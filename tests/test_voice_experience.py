"""Exercise additive IGW fields, transient retries and offline voice fallback."""

from copy import deepcopy
from email.message import Message
import io
import json
from pathlib import Path
import socket
import ssl
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from igw_google_voice import cast_media
from igw_google_voice.cast_gateway import GatewayError, fetch_snapshot, validate_snapshot
from igw_google_voice.cast_config import CastConfig
from igw_google_voice.cast_ha import render_cast_trigger_files, PACKAGE_PATH
from igw_google_voice.__main__ import render_package
from test_cast_media import write_silence
from test_cast_service import config, fixture
from test_adapter import load_yaml
import test_adapter


class AdditiveReportTests(unittest.TestCase):
    def test_shared_rust_serializer_fixture(self):
        body = json.loads((Path(__file__).parent / 'fixtures/energy-flow-v1.json').read_text())
        reports = validate_snapshot(body, now=body['generated_at'])['reports']
        self.assertEqual(reports['status']['brief_text'], body['reports']['status']['brief_text'])
        self.assertEqual(reports['flow']['text'], body['reports']['flow']['text'])
        self.assertEqual(reports['flow']['metrics']['load_power']['value'], 1250)

    def test_brief_is_optional_and_full_warnings_are_retained(self):
        body = fixture()
        body['reports']['status']['brief_text'] = 'Battery 74 percent. Check the gateway warning.'
        parsed = validate_snapshot(body, now=time.time())
        self.assertEqual(parsed['reports']['status']['brief_text'], body['reports']['status']['brief_text'])
        self.assertEqual(parsed['reports']['status']['text'], body['reports']['status']['text'])
        for bad in (None, {}, True, ' ', 'x' * 1201, 'private\0text'):
            body['reports']['status']['brief_text'] = bad
            parsed = validate_snapshot(body, now=time.time())
            self.assertNotIn('brief_text', parsed['reports']['status'])

    def test_metrics_are_strict_optional_and_never_expose_sources(self):
        body = fixture()
        body['metrics']['battery_soc'].update(age_seconds=2, sources=['private/source'])
        parsed = validate_snapshot(body, now=time.time())
        metric = parsed['reports']['battery']['metrics']['battery_soc']
        self.assertEqual(metric, dict(value=74, unit='%', status='fresh', age_seconds=2))
        self.assertNotIn('private', json.dumps(parsed))
        for change in ({'value': True}, {'value': '74'}, {'value': -1}, {'value': 101},
                       {'value': float('nan')}, {'value': 10**1000}, {'unit': 'W'}, {'status': []}):
            damaged = deepcopy(body)
            damaged['metrics']['battery_soc'].update(change)
            result = validate_snapshot(damaged, now=time.time())['reports']['battery']
            self.assertNotIn('metrics', result)
            self.assertEqual(result['text'], body['reports']['battery']['text'])
        for age in (None, True, -1, 2.5, 10**100):
            damaged = deepcopy(body)
            damaged['metrics']['battery_soc']['age_seconds'] = age
            metric = validate_snapshot(damaged, now=time.time())['reports']['battery']['metrics']['battery_soc']
            self.assertNotIn('age_seconds', metric)

    def test_flow_is_optional_and_directions_come_from_central_contract(self):
        body = fixture()
        parsed = validate_snapshot(body, now=time.time())
        self.assertEqual(parsed['reports']['flow']['status'], 'unconfigured')
        body['reports']['flow'] = {'status': 'fresh', 'text': 'Grid export is 500 watts. Battery is charging.'}
        for key, value in [('load_power', 1250), ('grid_power', -500), ('battery_power', 750)]:
            body['metrics'][key] = dict(value=value, unit='W', status='fresh', age_seconds=2)
        reports = validate_snapshot(body, now=time.time())['reports']
        cards = cast_media._layout_pages('flow', reports)[0]
        self.assertEqual([card.value for card in cards[:3]], ['1.25 kW', '500 W export', '750 W charging'])
        self.assertEqual(' '.join(cards[-1].lines), body['reports']['flow']['text'])
        self.assertTrue(all(card.receipt_age == 'Data age at snapshot: 2 s' for card in cards[:3]))

    def test_numeric_pages_keep_all_warning_text_and_never_use_envelope_age(self):
        body = fixture()
        warning = ('Central warning about monitored sources. ' * 20).strip()
        body['reports']['battery']['text'] = warning
        reports = validate_snapshot(body, now=time.time())['reports']
        pages = cast_media._layout_pages('status', reports)
        cards = [next(card for card in page if card.key == 'battery') for page in pages]
        self.assertEqual(' '.join(line for card in cards for line in card.lines), warning)
        self.assertTrue(all(card.value == '74%' for card in cards))
        self.assertTrue(all(card.receipt_age == 'Data age at snapshot: unknown' for card in cards))

    def test_stale_values_cannot_become_current_numbers(self):
        body = fixture()
        body['reports']['battery']['status'] = 'stale'
        body['metrics']['battery_soc'].update(status='stale', value=None, age_seconds=600)
        reports = validate_snapshot(body, now=time.time())['reports']
        card = cast_media._layout_pages('battery', reports)[0][0]
        self.assertEqual(card.value, '')
        self.assertEqual(card.receipt_age, 'Data age at snapshot: 10 min')

    def test_flow_generation_is_explicit_and_preserves_existing_scripts(self):
        for renderer in (lambda opt: render_cast_trigger_files('http://192.168.50.8:8091', include_flow=opt)[PACKAGE_PATH],
                         lambda opt: render_package('tts.local', 'media_player.kitchen', 30, include_flow=opt)):
            old = load_yaml(renderer(False))['script']
            new = load_yaml(renderer(True))['script']
            self.assertEqual(set(new) - set(old), {'igw_google_flow'})
            for key in old:
                if key != 'igw_google_energy_dispatch':
                    self.assertEqual(new[key], old[key])
            self.assertEqual(new['igw_google_flow']['sequence'][0]['data']['report_key'], 'flow')


class RetryTests(unittest.TestCase):
    def opener(self, failures):
        class Response(io.BytesIO):
            status = 200
            headers = Message()
        class Opener:
            calls = 0
            timeouts = []
            def open(self, request, timeout):
                self.calls += 1
                self.timeouts.append(timeout)
                if self.calls <= len(failures):
                    raise failures[self.calls - 1]
                response = Response(json.dumps(fixture()).encode())
                response.headers = Message()
                response.headers['Content-Type'] = 'application/json'
                return response
        return Opener()

    def test_exactly_one_retry_for_classified_transients(self):
        for failure in (URLError(TimeoutError()), URLError(ConnectionResetError()),
                        URLError(socket.gaierror(socket.EAI_AGAIN, 'temporary')),
                        HTTPError('https://private', 503, 'private', {}, None)):
            opener = self.opener([failure])
            self.assertIn('reports', fetch_snapshot(config(), opener=opener))
            self.assertEqual(opener.calls, 2)
            self.assertTrue(all(timeout <= 5 for timeout in opener.timeouts))
        opener = self.opener([TimeoutError(), TimeoutError()])
        with self.assertRaises(GatewayError):
            fetch_snapshot(config(), opener=opener)
        self.assertEqual(opener.calls, 2)

    def test_auth_redirect_tls_rate_limit_invalid_and_permanent_dns_are_not_retried(self):
        for failure in (*[HTTPError('https://private', code, 'private', {}, None) for code in (301, 401, 403, 429, 500)],
                        URLError(ssl.SSLCertVerificationError('private')),
                        URLError(socket.gaierror(socket.EAI_NONAME, 'private'))):
            opener = self.opener([failure])
            with self.assertRaises(GatewayError) as error:
                fetch_snapshot(config(), opener=opener)
            self.assertEqual(opener.calls, 1)
            self.assertNotIn('private', str(error.exception))

    def test_retry_does_not_extend_deadline(self):
        opener = self.opener([TimeoutError()])
        clock = iter([0, 0, 13])
        with self.assertRaises(GatewayError):
            fetch_snapshot(config(), opener=opener, clock=lambda: next(clock))
        self.assertEqual(opener.calls, 1)


class PiperTests(unittest.TestCase):
    def test_real_missing_model_worker_falls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'speech.wav'
            with patch.object(cast_media, '_synthesize_speech', return_value=2) as fallback, \
                 self.assertLogs('igw_cast', level='WARNING') as logs:
                result = cast_media._speech('Synthetic energy report.', output, 'espeak-ng',
                                           provider='piper', model=str(Path(temporary) / 'absent.onnx'), timeout=1)
            self.assertEqual(result, (2, 'espeak'))
            fallback.assert_called_once()
            self.assertNotIn(temporary, ''.join(logs.output))

    def test_piper_configuration_is_explicit_bounded_and_private(self):
        from test_cast_service import TestConfig
        env = TestConfig()
        env.setUp()
        self.assertEqual(CastConfig.from_env(env.env).tts_provider, 'espeak')
        cfg = CastConfig.from_env(env.env | {'CAST_TTS_PROVIDER': 'piper', 'CAST_PIPER_MODEL': '/private/model.onnx'})
        self.assertNotIn('/private', repr(cfg))
        for change in ({'CAST_TTS_PROVIDER': 'cloud'},
                       {'CAST_TTS_PROVIDER': 'piper', 'CAST_PIPER_MODEL': 'relative.onnx'},
                       {'CAST_TTS_PROVIDER': 'piper', 'CAST_PIPER_MODEL': '/private/model.json'},
                       {'CAST_PIPER_TIMEOUT': '0'}, {'CAST_PIPER_TIMEOUT': '21'}):
            with self.assertRaises(ValueError):
                CastConfig.from_env(env.env | change)

    def test_offline_subprocess_uses_stdin_fixed_module_and_bounded_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'speech.wav'
            def run(command, **kwargs):
                self.assertEqual(command[1:3], ['-m', 'igw_google_voice.piper_worker'])
                self.assertNotIn('Private report.', command)
                self.assertEqual(kwargs['input_bytes'], b'Private report.')
                self.assertEqual(kwargs['timeout'], 7)
                write_silence(output)
            with patch.object(cast_media, '_run', side_effect=run):
                duration, provider = cast_media._speech('Private report.', output, 'espeak-ng',
                                                        provider='piper', model='/voices/local.onnx', timeout=7)
            self.assertEqual(provider, 'piper')
            self.assertAlmostEqual(duration, .2)

    def test_missing_failed_timed_out_or_invalid_audio_falls_back_without_private_logs(self):
        for failure in (RuntimeError('private path'), None):
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / 'speech.wav'
                def run(*args, **kwargs):
                    if failure:
                        raise failure
                    output.write_bytes(b'bad audio')
                with patch.object(cast_media, '_run', side_effect=run), \
                     patch.object(cast_media, '_synthesize_speech', return_value=2) as fallback, \
                     self.assertLogs('igw_cast', level='WARNING') as logs:
                    self.assertEqual(cast_media._speech('Private report.', output, 'espeak-ng',
                                     provider='piper', model='/private/model.onnx', timeout=10), (2, 'espeak'))
                fallback.assert_called_once_with('Private report.', output, 'espeak-ng')
                self.assertNotIn('private', ''.join(logs.output).lower())
                self.assertFalse(output.exists())


class BlueprintAdditiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_adapter.ResponseTests.setUpClass.__func__(cls)

    speak = test_adapter.ResponseTests.speak
    def test_optional_status_brief_and_missing_flow(self):
        body = deepcopy(self.fixture)
        body['reports']['status']['brief_text'] = 'Short central overview with all warnings.'
        self.assertEqual(self.speak(body), body['reports']['status']['brief_text'])
        self.assertIn('not configured', self.speak(body, report='flow'))
        for invalid in (None, [], '', 'x' * 1201):
            body['reports']['status']['brief_text'] = invalid
            self.assertEqual(self.speak(body), body['reports']['status']['text'])
