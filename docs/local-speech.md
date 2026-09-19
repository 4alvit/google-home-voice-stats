# Optional local Piper speech

The default renderer uses eSpeak NG and needs no voice download. Piper is an
optional neural voice on the NAS, not on the Cerbo GX. Both providers run locally;
no speech subscription, cloud API key or paid plan is required. The Google voice
recognizer still follows your existing Google/Matter or account-linking route.

## Install a local voice deliberately

This adapter pins [Piper 1.8.0](https://pypi.org/project/piper-tts/1.8.0/). The
[upstream engine](https://github.com/OHF-Voice/piper1-gpl/tree/v1.8.0) is licensed
under GPL-3.0-or-later. Voice models have their own licensing terms: inspect the
selected voice's `MODEL_CARD` and retain its notices before downloading or
redistributing it. No model is included in this repository or container image.
For example, the [LJ Speech voice model card](https://huggingface.co/rhasspy/piper-voices/blob/v1.0.0/en/en_US/ljspeech/high/MODEL_CARD)
identifies its training dataset as public domain; this does not replace reviewing
all terms applicable to your selected model and distribution.

Use a single-speaker English voice with Piper's `espeak` phonemizer. Place its
`.onnx` and matching `.onnx.json` files in a private host directory as `voice.onnx`
and `voice.onnx.json`. Record their checksums in your private installation notes.
Keep the directory readable by container UID 10001 and mount it read-only. The
service neither searches a voice catalogue nor downloads missing voice resources.
Non-English phonemizers are rejected because some load additional resources.

Set `CAST_PIPER_VOICE_DIR` in `.env` to that existing host directory, then run:

```bash
docker compose -f compose.cast.yaml -f compose.piper.yaml build
docker compose -f compose.cast.yaml -f compose.piper.yaml up -d
```

The override installs the optional dependency at image build time, mounts the two
voice files at `/voices`, selects `piper`, and raises the container memory ceiling
from 384 MiB to 1 GiB. This is a deployment limit, not measured memory consumption.
The existing CPU affinity and PIDs cap remain. Do not start the default and Piper
stacks simultaneously: they are configurations of the same service.

For a non-container installation, install `.[cast,piper]`, set
`CAST_TTS_PROVIDER=piper`, and set `CAST_PIPER_MODEL` to the absolute `.onnx` path.
The adjacent file must have the same name plus `.json`. Keep `ffmpeg` and
`espeak-ng` installed for media encoding and fallback. Use an OS service manager
with a memory limit when running outside the supplied container.

## Runtime bounds and fallback

Each request starts at most one Piper child process. Text travels on standard
input, never in executable arguments. The worker accepts at most 1200 characters,
uses one ONNX inference thread, a 20-second CPU cap, a 16 MiB output-file cap, and
no core dumps. `CAST_PIPER_TIMEOUT` sets its wall-clock limit (default 10 seconds,
allowed 1–20). Model files are limited to 512 MiB and their JSON to 1 MiB. These
file limits do not predict inference memory; the container enforces memory.

A missing model/package, failed synthesis, timeout or invalid audio causes one
local eSpeak attempt with the same complete spoken report. Logs contain only the
fixed `piper_unavailable` category. Raw model paths, speech, credentials and tool
errors are not logged. No stale report or prior audio is reused. If rendering
outlives the IGW envelope's accepted age, playback is rejected rather than calling
it current. A shorter central status brief helps both responsiveness and speech
length; central warnings are retained.

The base image remains eSpeak-only. To roll back, use only `compose.cast.yaml`
and set `CAST_TTS_PROVIDER=espeak` / `CAST_INSTALL_PIPER=false`, rebuild, and
recreate this service. Keep the local model files for recovery if desired.

## Compare before enabling

Measure a cold invocation and repeated requests on your actual NAS with a
synthetic report. Compare wall time, peak resident memory, generated audio length,
and listening quality for both voices. Also test a missing model and a forced
Piper timeout. The service must play the eSpeak fallback, preserve warnings and
continue rejecting concurrent requests with HTTP 409. Do not infer device audio
quality or NAS performance from a desktop benchmark. Verify one real report on
the selected display after changing the voice.

A synthetic local check with Piper 1.8.0 and `en_US-ljspeech-high` produced
6.014 seconds of mono 22,050 Hz audio. On a macOS ARM64 development host, a first
cold attempt exceeded 25 seconds; two subsequent isolated jobs completed in
17.868 and 13.159 seconds with a 20-second wall limit. Observed child peak RSS was
about 245–270 MiB. This is not a NAS or playback benchmark, and it does not justify
changing the default voice: the default 10-second Piper limit would have fallen
back on that host. Native eSpeak was unavailable there, so no comparative voice,
latency or memory advantage is claimed. Synthetic WAV creation, fallback tests,
and H.264/AAC encoding are distinct from listening acceptance on the display.
