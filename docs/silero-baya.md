# Local Russian speech with Baya

`silero-ru-baya` selects the Baya speaker in Silero `v5_6_ru`. It is intended
for operators who prefer this voice to Piper Irina. Listen to the same short
phrase in both voices before choosing; expressiveness is a listening preference,
not a property established by model size. The upstream model supports Russian
stress, homographs, questions, emphasis and exclamations. This service accepts
plain text only; arbitrary SSML and emotion-control markup remain rejected.
The service can build validated prosody markup itself from the settings below.

The model and its license are pinned by size and SHA-256 in the asset manifest.
They are checked before the PyTorch package loader executes any model code.
There is no runtime model download, cloud inference, or microphone recording.
The dedicated image uses a hash-locked CPU PyTorch wheel for Python 3.11 on
Linux x86-64. The existing Piper image and its defaults remain available.

## Build and verify

```sh
docker build -f Dockerfile.russian-silero -t local/russian-baya:VERSION .
docker run --rm --network none --memory 1g --cpus 2 \
  --read-only --tmpfs /tmp:size=64m,exec --cap-drop ALL \
  --security-opt no-new-privileges \
  -v "$PWD/tests/smoke_russian_speech.py:/app/smoke_russian_speech.py:ro" \
  local/russian-baya:VERSION python /app/smoke_russian_speech.py
```

Push to your private registry and resolve the resulting manifest digest. Keep
the previous deployment, pipeline voice settings and image digest privately
before changing an existing installation. Use a separate canary Pod on the
actual target host to check discovery, complete WAV output, numbers, two queued
requests and audio arriving before the input stream closes. Mac timings do not
qualify a NUC's performance.

```sh
python3 scripts/render-russian-speech.py --node YOUR_NODE \
  --voice silero-ru-baya \
  --image REGISTRY/russian-baya@sha256:YOUR_MANIFEST_DIGEST \
  > /PRIVATE/PATH/russian-baya.json
```

Use the existing private TLS/token resources described in
[Russian speech](russian-speech.md). The renderer selects `silero` and
`silero-ru-baya` in both containers. Apply only after the canary passes.
Once ready, reload the corresponding Wyoming integration in Home Assistant,
then select **silero-ru-default** in each Assist pipeline that should follow
the live service settings. An explicit **silero-ru-baya** pins that speaker.
Keep its Russian language, conversation agent and speech recognition settings.
Check any direct TTS callers that explicitly name the previous voice. A shared
service affects every client using it, including displays as well as Dots.

Wyoming advertises five installed speakers and the `silero-ru-default` alias.
A stale `piper-ru-irina` request is deliberately rejected. Each utterance captures
the current settings once; every streamed sentence uses that same snapshot. The output remains
mono 24 kHz, 16-bit PCM. Sentence streaming, cancellation, bounded concurrency,
text normalization and request deadlines remain bounded in the adapter.

## Live settings and all available voices

The service exposes authenticated `GET /v1/settings` and `PATCH /v1/settings`.
`POST /v1/speech` accepts an optional `options` object using the same keys, for
one request only. These settings are available on the Silero backend:

- `voice`: `silero-ru-baya` (default), `silero-ru-kseniya`, `silero-ru-xenia`,
  `silero-ru-aidar`, or `silero-ru-eugene`. All share the pinned `v5_6_ru.pt` file.
- `rate`: integer 80–130 percent, default 100.
- `pitch`: integer −10–+10 percent, default 0.
- `sentence_pause_ms`: 0–1000 milliseconds in steps of 50, default 0. Adds a
  pause after sentences and after the final segment; natural pauses remain.
- `intonation`: `auto` (default), `statement`, `question`, or `exclamation`.
  A forced intonation applies to every sentence and is not an emotion model.
- `emphasis_words`: an empty string by default, or up to ten comma-separated
  whole words (160 characters total). Exact case-insensitive matching; list
  grammatical forms separately. Numbers have already been expanded to words.
- `emphasis_intensity`: integer 1–3, default 3; affects only matched words.
- `auto_stress` and `auto_yo`: booleans, both true by default. These also
  control their corresponding homograph preprocessing options.

For example, PATCH `{"rate":110,"pitch":0}`. To synthesize once with another
speaker, POST `{"text":"Готова помочь.","options":{"voice":"silero-ru-xenia"}}`.
The API rejects unknown keys and wrong types instead of passing arbitrary
arguments into the model. Input text stays plain text; the service creates
escaped SSML internally. Markdown asterisks cannot inject emphasis.

Set `RUSSIAN_SPEECH_SETTINGS_FILE=/state/settings.json` and mount persistent
storage writable by UID 10001 at `/state`. The renderer creates a 64 MiB PVC
for Silero. Without this variable the service reports `persistent: false` and
settings reset when the process restarts. A bad stored file prevents startup;
a failed save returns 503 and does not change the active settings. Keep the
file private because emphasis words can contain household names.

Install the companion
[HA controls](https://github.com/ha-homelab/ha-echomuse/blob/main/docs/speech-settings.md)
and use `silero-ru-default` in Assist pipelines to follow the live voice selector.
The controls include a reset button and English, Russian, German, Spanish and
French labels. The integration clears HA's TTS cache on changes; direct API
clients must manage their own cache. Settings affect every client of this
service, not just one satellite. Explicit Wyoming voice names override only
the `voice` setting. The remaining prosody settings still apply.

Piper Denis and Irina remain available in the separate Piper image; the
KittenTTS 2 Russian backend remains an optional pilot. They cannot be selected
in this running Silero instance. See [Russian speech](russian-speech.md) for
their asset, hardware and licensing requirements.

## Acceptance and rollback

Validate speech generation without activating household microphones. Then make
one short audible announcement on the speaker authorized by the operator.
For the documented household, audible tests are restricted to the Audiocenter
Dot; do not test all satellites just because they share the service.

Before rolling back to a pre-settings Silero image, restore explicit
`silero-ru-baya` pipeline voices; older images do not know the default alias.
Disable the HA settings integration when its API is unavailable. Preserve
the settings PVC.

For a Piper rollback, restore the saved Piper image, `RUSSIAN_TTS_BACKEND=piper` and
`RUSSIAN_SPEECH_VOICE=piper-ru-irina` in both containers. Reload Wyoming and
restore the saved pipeline voice names. Do not reset, re-pair or flash a Dot.

## Verified deployment example (2026-10-16)

On an Intel Core i5-5300U NUC, with the inference container limited to two
CPUs and 1 GiB RAM, two simultaneous synthetic requests completed in 3.19
and 5.51 seconds. Each produced 6.90 seconds of mono 24 kHz audio. A streamed
request delivered its first audio in 2.17 seconds, before the client sent
`synthesize-stop`. The container used approximately 731 MiB at the end of
the probe. These are individual acceptance measurements, not latency guarantees.

The tested image also completed synthetic inference with networking disabled,
a read-only root filesystem, a 64 MiB temporary directory, and no capabilities.
The build host could not enforce CPU quotas; the NUC canary enforced the actual
production CPU and memory limits. On a heavily reserved node, the temporary
canary used smaller scheduling requests while retaining the same hard limits;
production reservations were unchanged. No ambient audio was recorded.

## Attribution

The [Silero project](https://github.com/snakers4/silero-models) publishes the
model under [CC BY-NC-SA 4.0](https://github.com/snakers4/silero-models/blob/e382298387332f2bf461fe6eadfde99104611b0c/LICENSE).
Keep the bundled license and attribution with redistributed model artifacts;
do not treat the weights as covered by this repository's code license. The
model's noncommercial restriction applies independently of where inference runs.
Weights, speech samples, tokens and deployment receipts are not committed here.

## Settings rollout — October 16, 2026

The pinned model generated valid audio for all five installed voices. On the
NUC, the final image passed two concurrent Wyoming requests in 3.50 and 5.80
seconds (6.90 seconds of output each). Its streaming probe delivered first audio
in 2.32 seconds, before input ended. The inference container retained its two-CPU,
1 GiB limit; the adapter retained its 250m CPU and 128 MiB limits.

The probe exercised speech-rate and pitch boundaries, all three emphasis levels,
forced sentence types, pauses, and disabled pronunciation aids. Settings were
saved on a persistent volume. These are generated-audio and protocol checks,
not a listening preference test or an end-to-end microphone latency measurement.
