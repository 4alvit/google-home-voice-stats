"""Bounded Silero settings, persisted independently of model workers."""
from __future__ import annotations

from copy import deepcopy
from html import escape
import json
import os
from pathlib import Path
import re
import tempfile
import threading

from .russian_voices import SILERO_VOICES

DEFAULTS = {
    'voice': 'silero-ru-baya', 'rate': 100, 'pitch': 0,
    'sentence_pause_ms': 0, 'intonation': 'auto',
    'emphasis_words': '', 'emphasis_intensity': 3,
    'auto_stress': True, 'auto_yo': True,
}
SCHEMA = {
    'voice': {'type': 'select', 'options': list(SILERO_VOICES)},
    'rate': {'type': 'number', 'min': 80, 'max': 130, 'step': 1, 'unit': '%'},
    'pitch': {'type': 'number', 'min': -10, 'max': 10, 'step': 1, 'unit': '%'},
    'sentence_pause_ms': {'type': 'number', 'min': 0, 'max': 1000, 'step': 50, 'unit': 'ms'},
    'intonation': {'type': 'select', 'options': ['auto', 'statement', 'question', 'exclamation']},
    'emphasis_words': {'type': 'text', 'max': 160},
    'emphasis_intensity': {'type': 'number', 'min': 1, 'max': 3, 'step': 1},
    'auto_stress': {'type': 'switch'}, 'auto_yo': {'type': 'switch'},
}
SENTENCES = re.compile(r'(?<=[.!?…])\s+')
WORD = re.compile(r"[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё]+)*")


def validate_patch(patch):
    if not isinstance(patch, dict) or not patch.keys() <= DEFAULTS.keys():
        raise ValueError('Unknown speech setting')
    for key, value in patch.items():
        field = SCHEMA[key]
        kind = field['type']
        if kind == 'select':
            valid = isinstance(value, str) and value in field['options']
        elif kind == 'switch':
            valid = type(value) is bool
        elif kind == 'number':
            valid = (type(value) is int and field['min'] <= value <= field['max']
                     and (value - field['min']) % field['step'] == 0)
        else:
            valid = isinstance(value, str) and len(value) <= field['max']
            if valid:
                words = [w.strip() for w in value.split(',') if w.strip()]
                valid = len(words) <= 10 and all(WORD.fullmatch(w) for w in words)
        if not valid:
            raise ValueError('Invalid speech setting: ' + key)
    return dict(patch)


class SettingsStore:
    def __init__(self, path=None, voice='silero-ru-baya'):
        self.path = Path(path) if path else None
        self.lock = threading.Lock()
        self.values = dict(DEFAULTS, voice=voice)
        if self.path and self.path.exists():
            data = self.path.read_bytes()
            if len(data) > 4096:
                raise ValueError('Oversized speech settings')
            self.values.update(validate_patch(json.loads(data)))

    def snapshot(self, patch=None):
        patch = validate_patch({} if patch is None else patch)
        with self.lock:
            return dict(self.values, **patch)

    def describe(self):
        return {'version': 1, 'backend': 'silero', 'model': 'v5_6_ru',
                'persistent': self.path is not None, 'settings': self.snapshot(),
                'defaults': dict(DEFAULTS), 'schema': deepcopy(SCHEMA)}

    def update(self, patch):
        patch = validate_patch(patch)
        with self.lock:
            values = dict(self.values, **patch)
            if self.path:
                # Atomic replacement, same filesystem; never publish unpersisted values.
                with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix='.speech-', delete=False) as stream:
                    tmp = Path(stream.name)
                    try:
                        stream.write(json.dumps(values, ensure_ascii=False).encode())
                        stream.flush()
                        os.fsync(stream.fileno())
                        os.replace(tmp, self.path)
                    finally:
                        tmp.unlink(missing_ok=True)
            self.values = values
        return self.describe()


def silero_arguments(text, settings):
    """Generate our own SSML. Callers cannot inject model markup or file paths."""
    settings = dict(DEFAULTS, **validate_patch(settings))
    # Markdown from a conversation agent must not become Silero focus markup.
    text = text.replace('*', '')
    words = {w.strip().casefold() for w in settings['emphasis_words'].split(',') if w.strip()}
    marked = WORD.sub(lambda m: '**' + m[0] + '**' if m[0].casefold() in words else m[0], text)
    kwargs = {'speaker': SILERO_VOICES[settings['voice']][2], 'sample_rate': 24000,
              'put_accent': settings['auto_stress'], 'put_stress_homo': settings['auto_stress'],
              'put_yo': settings['auto_yo'], 'put_yo_homo': settings['auto_yo'],
              'intensity': settings['emphasis_intensity']}
    types = {'statement': 'st', 'question': 'general_q', 'exclamation': 'exclam'}
    if settings['intonation'] != 'auto':
        kwargs['type_str'] = '|'.join([types[settings['intonation']]] * len(SENTENCES.split(text)))
    if settings['rate'] == 100 and settings['pitch'] == 0 and settings['sentence_pause_ms'] == 0:
        kwargs['text'] = marked
    else:
        content = escape(marked, quote=False)
        if settings['sentence_pause_ms']:
            # Also append after a streamed final sentence, so streaming has the same gaps.
            pause = '<break time="' + str(settings['sentence_pause_ms']) + 'ms"/>'
            content = (pause + ' ').join(SENTENCES.split(content)) + pause
        kwargs['ssml_text'] = (f'<speak><prosody rate="{settings["rate"]}%" '
                              f'pitch="{settings["pitch"]:+d}%">{content}</prosody></speak>')
    return kwargs
