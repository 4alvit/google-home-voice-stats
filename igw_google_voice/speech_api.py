"""Authenticated Russian speech settings and synthesis API."""
import hmac
import json

from .kitten_service import SpeechHandler, BusyError, MAX_BODY, valid_text


class RussianSpeechHandler(SpeechHandler):
    def authorized(self):
        if hmac.compare_digest(self.headers.get('Authorization', '').encode(),
                               ('Bearer ' + self.server.token).encode()):
            return True
        self._send(401)
        return False

    def body(self):
        length = int(self.headers.get('Content-Length', '0'))
        if (self.headers.get('Transfer-Encoding') or not 0 < length <= MAX_BODY
                or self.headers.get_content_type() != 'application/json'):
            raise ValueError('Invalid body')
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError('Truncated body')
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError('Expected object')
        return body

    def do_GET(self):
        if self.path != '/v1/settings':
            return super().do_GET()
        if not self.authorized():
            return
        settings = self.server.synthesizer.settings
        if settings is None:
            self._send(404)
        else:
            self._send(200, json.dumps(settings.describe()).encode())

    def do_PATCH(self):
        if not self.authorized():
            return
        if self.path != '/v1/settings' or self.server.synthesizer.settings is None:
            self._send(404)
            return
        try:
            result = self.server.synthesizer.settings.update(self.body())
        except (ValueError, UnicodeError, TimeoutError):
            self._send(400)
        except OSError:
            self._send(503)
        else:
            self._send(200, json.dumps(result).encode())

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != '/v1/speech':
            self._send(404)
            return
        try:
            body = self.body()
            if (not {'text'} <= body.keys() <= {'text', 'options'} or not valid_text(body['text'])
                    or ('options' in body and not isinstance(body['options'], dict))):
                raise ValueError('Invalid request')
            audio = self.server.synthesizer.generate(body['text'], body.get('options'))
        except (ValueError, UnicodeError, TimeoutError):
            self._send(400)
        except BusyError:
            self._send(503)
        except RuntimeError:
            self._send(502)
        else:
            self._send(200, audio, 'audio/wav')
