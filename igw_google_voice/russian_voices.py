"""Reviewed Russian voices shared by asset, inference and discovery code."""

BACKENDS = ('kitten2', 'piper')
PIPER_VOICES = {
    'piper-ru-denis': ('piper', 'ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx'),
    'piper-ru-irina': ('piper-irina', 'ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx'),
}
VOICES = (*PIPER_VOICES, 'kitten2-russian')


def select_voice(backend, voice=None):
    """Keep the original defaults, rejecting cross-backend or unknown names."""
    if backend not in BACKENDS:
        raise ValueError('Unknown Russian speech backend')
    if voice is None:
        voice = 'kitten2-russian' if backend == 'kitten2' else 'piper-ru-denis'
    allowed = ('kitten2-russian',) if backend == 'kitten2' else PIPER_VOICES
    if voice not in allowed:
        raise ValueError('Voice does not match the Russian speech backend')
    return voice


def asset_bundles(backend, voice=None):
    voice = select_voice(backend, voice)
    return ('kitten2', 'codec') if backend == 'kitten2' else (PIPER_VOICES[voice][0],)
