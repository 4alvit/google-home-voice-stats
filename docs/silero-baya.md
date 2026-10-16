# Local Russian speech with Baya

`silero-ru-baya` selects the Baya speaker in Silero `v5_6_ru`. It is intended
for operators who prefer this voice to Piper Irina. Listen to the same short
phrase in both voices before choosing; expressiveness is a listening preference,
not a property established by model size. The upstream model supports Russian
stress, homographs, questions, emphasis and exclamations. This service accepts
plain text only; arbitrary SSML and emotion-control markup remain rejected.

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
then select **silero-ru-baya** in each Assist pipeline that uses this TTS service.
Keep its Russian language, conversation agent and speech recognition settings.
Check any direct TTS callers that explicitly name the previous voice. A shared
service affects every client using it, including displays as well as Dots.

The voice name must agree in inference, Wyoming discovery and the HA pipeline.
A stale `piper-ru-irina` request is deliberately rejected. The output remains
mono 24 kHz, 16-bit PCM. Sentence streaming, cancellation, bounded concurrency,
text normalization and request deadlines use the existing adapter unchanged.

## Acceptance and rollback

Validate speech generation without activating household microphones. Then make
one short audible announcement on the speaker authorized by the operator.
For the documented household, audible tests are restricted to the Audiocenter
Dot; do not test all satellites just because they share the service.

For rollback, restore the saved Piper image, `RUSSIAN_TTS_BACKEND=piper` and
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
