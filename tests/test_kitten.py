"""Speech failover, transport validation and the private service contract."""
from dataclasses import replace
import io
import json
import os
import plistlib
import signal
import socket
import ssl
import time
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave
from http.client import HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from igw_google_voice import cast_media
from igw_google_voice.cast_config import CastConfig
from igw_google_voice.kitten_client import fetch_audio
from igw_google_voice.kitten_service import SpeechServer, BusyError, Synthesizer, server_tls_context


def wav_bytes():
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
        wav.writeframes(b'\0\0' * 2400)
    return out.getvalue()


class KittenConfigTests(unittest.TestCase):
    def setUp(self):
        self.env = dict(IGW_URL='https://gateway.test/v1/energy', IGW_READ_TOKEN='r' * 40,
                        CAST_API_TOKEN='a' * 40, CAST_HOST='192.168.50.20',
                        CAST_UUID='00000000-0000-0000-0000-000000000001',
                        CAST_MEDIA_BASE_URL='http://192.168.50.10:8091')

    def test_private_pair_and_redacted_credentials(self):
        env = self.env | {'CAST_TTS_PROVIDER':'kitten', 'CAST_KITTEN_TOKEN':'k' * 40, 'CAST_KITTEN_CA_FILE':'/run/speech-ca/ca.crt',
                         'CAST_KITTEN_ENDPOINTS':'https://192.168.50.11:8092/v1/speech,https://192.168.50.12:8092/v1/speech'}
        config = CastConfig.from_env(env)
        self.assertEqual(len(config.kitten_endpoints), 2)
        self.assertNotIn('k' * 40, repr(config))
        self.assertEqual(CastConfig.from_env(env | {'CAST_KITTEN_TIMEOUT':'15'}).kitten_timeout, 15)
        for ca_file in ('', 'relative.crt'):
            with self.assertRaises(ValueError):
                CastConfig.from_env(env | {'CAST_KITTEN_CA_FILE':ca_file})
        for value in ('0', '16'):
            with self.assertRaises(ValueError):
                CastConfig.from_env(env | {'CAST_KITTEN_TIMEOUT':value})
        for endpoint in ['http://192.168.1.1:8092/v1/speech', 'https://8.8.8.8:8092/v1/speech',
                         'https://user:pw@192.168.1.1:8092/v1/speech',
                         'https://192.168.1.1:8092/v1/speech?x=1','https://192.168.1.1:8092/wrong']:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                CastConfig.from_env(env | {'CAST_KITTEN_ENDPOINTS': endpoint + ',https://192.168.50.12:8092/v1/speech'})

    def test_kubernetes_uses_https_and_separate_tls_secrets(self):
        command = [sys.executable, 'scripts/render-kitten-deployment.py']
        for role, address in [('primary', '192.168.50.11'), ('secondary', '192.168.50.12')]:
            command += ['--'+role+'-node', role, '--'+role+'-address', address,
                        '--'+role+'-image', 'example/image@sha256:'+'a'*64]
        document = json.loads(subprocess.check_output(command))
        for deployment in document['items'][1:]:
            pod = deployment['spec']['template']['spec']
            container = pod['containers'][0]
            for probe in ('startupProbe', 'readinessProbe', 'livenessProbe'):
                self.assertEqual(container[probe]['httpGet']['scheme'], 'HTTPS')
            tls = next(v for v in pod['volumes'] if v['name'] == 'tls')
            self.assertEqual(tls['secret']['secretName'], deployment['metadata']['name']+'-tls')
            self.assertEqual(tls['secret']['defaultMode'], 0o440)

    def test_launchd_passes_only_certificate_paths(self):
        document = plistlib.loads(subprocess.check_output([
            sys.executable, 'scripts/render-kitten-launchd.py', '--root', '/private/runtime',
            '--user', 'speech', '--address', '192.168.50.11']))
        env = document['EnvironmentVariables']
        self.assertEqual(env['KITTEN_TLS_CERT_FILE'], '/private/runtime/tls/server.crt')
        self.assertEqual(env['KITTEN_TLS_KEY_FILE'], '/private/runtime/tls/server.key')


class FailoverTests(unittest.TestCase):
    def test_failed_primary_is_discarded_before_secondary(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'speech.wav'
            seen=[]
            def run(command, input_bytes, timeout):
                request=json.loads(input_bytes);seen.append(request)
                self.assertNotIn('secret-token', ' '.join(command))
                if len(seen)==1:
                    output.write_bytes(b'partial response')
                    raise RuntimeError('timeout')
                self.assertFalse(output.exists())
                output.write_bytes(wav_bytes())
            with patch.object(cast_media, '_run', side_effect=run), patch.object(cast_media, '_synthesize_speech') as espeak:
                duration,provider=cast_media._speech('Solar unavailable.',output,'espeak',provider='kitten',model='',timeout=10,
                    kitten_endpoints=('primary','secondary'),kitten_token='secret-token',kitten_ca_file='/ca.crt')
            self.assertEqual(provider,'kitten_secondary');self.assertEqual(duration,.1)
            self.assertEqual([x['endpoint'] for x in seen],['primary','secondary'])
            self.assertTrue(all(x['ca_file']=='/ca.crt' for x in seen))
            self.assertTrue(all(x['text']=='Solar unavailable.' for x in seen));espeak.assert_not_called()

    def test_both_fail_then_local_speech_receives_original_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'speech.wav'
            with patch.object(cast_media,'_run',side_effect=RuntimeError()), patch.object(cast_media,'_synthesize_speech',return_value=1.0) as local:
                self.assertEqual(cast_media._speech('Grid export 250 watts.',output,'espeak',provider='kitten',model='',timeout=10,
                    kitten_endpoints=('primary','secondary')), (1.0,'espeak'))
                local.assert_called_once_with('Grid export 250 watts.',output,'espeak')


class TLSFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name) / 'tls'
        subprocess.run([sys.executable, 'scripts/create-speech-tls.py', '--output', str(cls.root),
                        '--primary-address', '127.0.0.1', '--secondary-address', '127.0.0.2'],
                       check=True, capture_output=True)
        cls.ca = str(cls.root / 'ca.crt')
        # Use explicit past dates, supported by both OpenSSL and macOS LibreSSL.
        (cls.root / 'index').touch()
        (cls.root / 'serial').write_text('01\n')
        (cls.root / 'expired-ca.cnf').write_text(
            '[ca]\ndefault_ca=issuer\n[issuer]\n'
            f'database={cls.root}/index\nserial={cls.root}/serial\nnew_certs_dir={cls.root}\n'
            'default_md=sha256\npolicy=policy\n[policy]\ncommonName=supplied\n')
        subprocess.run(['openssl', 'ca', '-batch', '-notext', '-in', str(cls.root / 'primary.csr'),
                        '-cert', cls.ca, '-keyfile', str(cls.root / 'ca.key'),
                        '-config', str(cls.root / 'expired-ca.cnf'),
                        '-startdate', '200101000000Z', '-enddate', '200102000000Z',
                        '-extfile', str(cls.root / 'primary.cnf'),
                        '-out', str(cls.root / 'expired.crt')], check=True, capture_output=True)
        subprocess.run(['openssl', 'req', '-x509', '-key', str(cls.root / 'primary.key'),
                        '-config', str(cls.root / 'ca.cnf'), '-days', '1',
                        '-out', str(cls.root / 'other-ca.crt')], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def context(self, role='primary'):
        return server_tls_context(self.root / (role + '.crt'),
                                  self.root / ('primary.key' if role == 'expired' else role + '.key'))

    def client_context(self):
        return ssl.create_default_context(cafile=self.ca)

    def tls_http_server(self, handler, role='primary'):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        server.socket = self.context(role).wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server


class TransportTests(TLSFixture):
    def test_invalid_tls_never_sends_credentials_or_text(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(self.headers.get('Authorization'))
            def log_message(self, *args): pass
        for role, ca in [('secondary', self.ca), ('expired', self.ca),
                         ('primary', str(self.root / 'other-ca.crt'))]:
            with self.subTest(role=role, ca=ca):
                server = self.tls_http_server(Handler, role)
                with self.assertRaises(ssl.SSLCertVerificationError):
                    fetch_audio(f'https://127.0.0.1:{server.server_port}/v1/speech',
                                'secret-token', 'private report', ca)
        self.assertEqual(requests, [])

    def test_http_and_missing_ca_are_rejected_before_connect(self):
        with patch('http.client.HTTPSConnection') as connect:
            with self.assertRaises(ValueError):
                fetch_audio('http://127.0.0.1:8092/v1/speech', 'secret', 'private', self.ca)
            with self.assertRaises(OSError):
                fetch_audio('https://127.0.0.1:8092/v1/speech', 'secret', 'private', '/missing/ca.crt')
            connect.assert_not_called()

    def test_tls_failure_uses_secondary_then_local_voice(self):
        class Synth:
            ready = threading.Event()
            def generate(self, text): return wav_bytes()
        synth = Synth()
        synth.ready.set()
        servers = []
        for role in ('secondary', 'primary'):
            server = SpeechServer(('127.0.0.1', 0), synth, 't'*40, tls_context=self.context(role))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            servers.append(server)
        endpoints = tuple(f'https://127.0.0.1:{s.server_port}/v1/speech' for s in servers)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'speech.wav'
            args = dict(provider='kitten', model='', timeout=10, kitten_endpoints=endpoints,
                        kitten_token='t'*40, kitten_ca_file=self.ca)
            self.assertEqual(cast_media._speech('hello', output, 'espeak', **args), (.1, 'kitten_secondary'))
            args['kitten_ca_file'] = str(self.root / 'other-ca.crt')
            with patch.object(cast_media, '_synthesize_speech', return_value=1.0) as local:
                self.assertEqual(cast_media._speech('hello', output, 'espeak', **args), (1.0, 'espeak'))
                local.assert_called_once_with('hello', output, 'espeak')

    def test_reject_redirect_wrong_content_and_truncated_wav(self):
        response = {'status':200,'content':'audio/wav','data':wav_bytes()}
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append((self.path,self.headers.get('Authorization')))
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(response['status'])
                self.send_header('Content-Type',response['content'])
                self.send_header('Location','/trap')
                self.send_header('Content-Length',str(len(response['data'])))
                self.end_headers();self.wfile.write(response['data'])
            def log_message(self,*args):pass
        server=self.tls_http_server(Handler)
        try:
            url=f'https://127.0.0.1:{server.server_port}/v1/speech'
            self.assertEqual(fetch_audio(url,'token','hello',self.ca),wav_bytes())
            for status,content,data in [(302,'audio/wav',wav_bytes()),(200,'application/json',b'{}'),(200,'audio/wav',wav_bytes()[:-10])]:
                response.update(status=status,content=content,data=data)
                with self.assertRaises(ValueError):fetch_audio(url,'token','hello',self.ca)
            self.assertEqual(len(requests),4)
            self.assertTrue(all(path=='/v1/speech' for path,_ in requests))
        finally:server.shutdown();server.server_close()

    def test_request_process_has_a_hard_deadline(self):
        entered=threading.Event()
        release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):entered.set();release.wait(3)
            def log_message(self,*args):pass
        server=self.tls_http_server(Handler)
        try:
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(RuntimeError):
                cast_media._run([sys.executable,'-m','igw_google_voice.kitten_client',str(Path(tmp)/'test.wav')],
                    input_bytes=json.dumps({'endpoint':f'https://127.0.0.1:{server.server_port}/v1/speech','token':'secret','text':'hello','ca_file':self.ca}).encode(),timeout=.5)
            self.assertTrue(entered.is_set())
        finally:release.set();server.shutdown();server.server_close()


class ServiceTests(TLSFixture):
    def test_incomplete_tls_handshake_does_not_block_other_clients(self):
        class Synth:
            ready = threading.Event()
            def generate(self, text): return wav_bytes()
        synth = Synth()
        synth.ready.set()
        server = SpeechServer(('127.0.0.1', 0), synth, 't'*40, tls_context=self.context())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        stalled = socket.create_connection(server.server_address, timeout=1)
        self.addCleanup(stalled.close)
        started = time.monotonic()
        self.assertEqual(fetch_audio(f'https://127.0.0.1:{server.server_port}/v1/speech',
                                    't'*40, 'hello', self.ca), wav_bytes())
        self.assertLess(time.monotonic() - started, 2)

    def test_failed_recovery_exits_for_supervisor_and_releases_lock(self):
        with patch.object(Synthesizer, '_start'):
            synth = Synthesizer('/unused')
        synth.lock.acquire()
        with patch.object(synth, '_start', side_effect=RuntimeError()), patch('os.kill') as kill:
            synth._recover()
        kill.assert_called_once_with(os.getpid(), signal.SIGTERM)
        self.assertFalse(synth.lock.locked())

    def test_invalid_thread_count_never_starts_a_worker(self):
        with patch.object(Synthesizer, '_start') as start:
            for threads in (0, 5, -1, '4'):
                with self.subTest(threads=threads), self.assertRaises(ValueError):
                    Synthesizer('/unused', threads=threads)
            start.assert_not_called()

    def test_auth_validation_audio_and_busy_response(self):
        class Synth:
            ready=threading.Event()
            busy=False
            def generate(self,text):
                if self.busy:raise BusyError()
                return wav_bytes()
        synth=Synth();synth.ready.set()
        server=SpeechServer(('127.0.0.1',0),synth,'t'*40,tls_context=self.context())
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(body,authorized=True):
            connection=HTTPSConnection('127.0.0.1',server.server_port,timeout=2,context=self.client_context())
            headers={'Content-Type':'application/json'}
            if authorized:headers['Authorization']='Bearer '+'t'*40
            connection.request('POST','/v1/speech',json.dumps(body),headers)
            response=connection.getresponse();result=(response.status,response.read());connection.close();return result
        try:
            self.assertEqual(request({'text':'hello'},False)[0],401)
            for body in [{'text':''},{'text':'a'*1201},{'text':'hello','voice':'other'},{'text':42},[]]:
                self.assertEqual(request(body)[0],400)
            self.assertEqual(request({'text':'Solar 1200 watts.'}),(200,wav_bytes()))
            synth.busy=True;self.assertEqual(request({'text':'hello'})[0],503)
        finally:server.shutdown();server.server_close()
