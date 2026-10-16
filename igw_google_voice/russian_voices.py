"""Reviewed Russian voices shared by asset, inference and discovery code."""

BACKENDS = ('kitten2', 'piper', 'silero')
PIPER_VOICES = {
    'piper-ru-denis': ('piper', 'ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx'),
    'piper-ru-irina': ('piper-irina', 'ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx'),
}
SILERO_VOICES = {'silero-ru-baya': ('silero', 'v5_6_ru.pt', 'baya')}
VOICES = (*PIPER_VOICES, *SILERO_VOICES, 'kitten2-russian')


def select_voice(backend, voice=None):
    """Keep the original defaults, rejecting cross-backend or unknown names."""
    if backend not in BACKENDS:
        raise ValueError('Unknown Russian speech backend')
    if voice is None:
        voice = {'kitten2': 'kitten2-russian', 'piper': 'piper-ru-denis',
                 'silero': 'silero-ru-baya'}[backend]
    allowed = {'kitten2': ('kitten2-russian',), 'piper': PIPER_VOICES,
               'silero': SILERO_VOICES}[backend]
    if voice not in allowed:
        raise ValueError('Voice does not match the Russian speech backend')
    return voice


def asset_bundles(backend, voice=None):
    voice = select_voice(backend, voice)
    if backend == 'kitten2':
        return ('kitten2', 'codec')
    voices = SILERO_VOICES if backend == 'silero' else PIPER_VOICES
    return (voices[voice][0],)
