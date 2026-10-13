"""Speech failover, transport validation and the private service contract."""
from dataclasses import replace
import io
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from igw_google_voice import cast_media
from igw_google_voice.cast_config import CastConfig
from igw_google_voice.kitten_client import fetch_audio
from igw_google_voice.kitten_service import SpeechServer, BusyError


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
        env = self.env | {'CAST_TTS_PROVIDER':'kitten', 'CAST_KITTEN_TOKEN':'k' * 40,
                         'CAST_KITTEN_ENDPOINTS':'http://192.168.50.11:8092/v1/speech,http://192.168.50.12:8092/v1/speech'}
        config = CastConfig.from_env(env)
        self.assertEqual(len(config.kitten_endpoints), 2)
        self.assertNotIn('k' * 40, repr(config))
        for endpoint in ['http://8.8.8.8:8092/v1/speech', 'http://user:pw@192.168.1.1:8092/v1/speech',
                         'http://192.168.1.1:8092/v1/speech?x=1','http://192.168.1.1:8092/wrong']:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                CastConfig.from_env(env | {'CAST_KITTEN_ENDPOINTS': endpoint + ',http://192.168.50.12:8092/v1/speech'})


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
                    kitten_endpoints=('primary','secondary'),kitten_token='secret-token')
            self.assertEqual(provider,'kitten_secondary');self.assertEqual(duration,.1)
            self.assertEqual([x['endpoint'] for x in seen],['primary','secondary'])
            self.assertTrue(all(x['text']=='Solar unavailable.' for x in seen));espeak.assert_not_called()

    def test_both_fail_then_local_speech_receives_original_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'speech.wav'
            with patch.object(cast_media,'_run',side_effect=RuntimeError()), patch.object(cast_media,'_synthesize_speech',return_value=1.0) as local:
                self.assertEqual(cast_media._speech('Grid export 250 watts.',output,'espeak',provider='kitten',model='',timeout=10,
                    kitten_endpoints=('primary','secondary')), (1.0,'espeak'))
                local.assert_called_once_with('Grid export 250 watts.',output,'espeak')


class TransportTests(unittest.TestCase):
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
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=f'http://127.0.0.1:{server.server_port}/v1/speech'
            self.assertEqual(fetch_audio(url,'token','hello'),wav_bytes())
            for status,content,data in [(302,'audio/wav',wav_bytes()),(200,'application/json',b'{}'),(200,'audio/wav',wav_bytes()[:-10])]:
                response.update(status=status,content=content,data=data)
                with self.assertRaises(ValueError):fetch_audio(url,'token','hello')
            self.assertEqual(len(requests),4)
            self.assertTrue(all(path=='/v1/speech' for path,_ in requests))
        finally:server.shutdown();server.server_close()

    def test_request_process_has_a_hard_deadline(self):
        entered=threading.Event()
        release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):entered.set();release.wait(3)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(RuntimeError):
                cast_media._run([sys.executable,'-m','igw_google_voice.kitten_client',str(Path(tmp)/'test.wav')],
                    input_bytes=json.dumps({'endpoint':f'http://127.0.0.1:{server.server_port}/v1/speech','token':'secret','text':'hello'}).encode(),timeout=.5)
            self.assertTrue(entered.is_set())
        finally:release.set();server.shutdown();server.server_close()


class ServiceTests(unittest.TestCase):
    def test_auth_validation_audio_and_busy_response(self):
        class Synth:
            ready=threading.Event()
            busy=False
            def generate(self,text):
                if self.busy:raise BusyError()
                return wav_bytes()
        synth=Synth();synth.ready.set()
        server=SpeechServer(('127.0.0.1',0),synth,'t'*40)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(body,authorized=True):
            connection=HTTPConnection('127.0.0.1',server.server_port,timeout=2)
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
