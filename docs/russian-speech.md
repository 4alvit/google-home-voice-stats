# Russian speech: a separate Piper service and optional KittenTTS 2 pilot

This optional service adds Russian speech for Home Assistant Assist and future
Russian energy reports. It does not change the existing English KittenTTS Nano
image, voice, endpoints, or Cast defaults. Speech synthesis does not supply Home
Assistant tools, energy facts, speech recognition, or wake-word detection; those
remain separate parts of the voice pipeline.

The deployed baseline is **Piper Denis medium**, a small CPU model. **KittenTTS 2**
is a larger, optional quality experiment. Do not select the larger model as the
interactive default merely because it supports Russian: measure its latency and
listen to the actual output first.

## Request path and limits

Home Assistant's Wyoming integration sends Russian text to TCP port `10601`.
The adapter advertises `Local Russian Speech`, voice `piper-ru-denis`, and languages
`ru` and `ru-RU`. It calls a private authenticated HTTPS `/v1/speech` endpoint,
then returns mono 24 kHz 16-bit PCM in Wyoming audio events. The HTTP contract
remains `{"text":"..."}` to `audio/wav`, allowing the same service to be used by a
future Russian Cast renderer. The existing English renderer must not silently
use a Russian voice.

The model is loaded once and warmed with a synthetic phrase before HTTP health
becomes ready. The example runs one inference worker, two CPU threads, and a
1 GiB memory limit. Startup has a 180-second worker deadline and a Kubernetes
startup probe budget of approximately 200 seconds. A healthy TCP listener alone
is not proof of working speech: test a complete synthesis after deployment.

Wyoming admits at most **one active request and one waiting request**. A third
is rejected. The default 30-second deadline covers both queue wait and the full
HTTPS operation; disconnect cancels a waiting request or its active HTTP child.
Audio writes have a separate 10-second bound. There are at most eight connected
clients. HTTP inference also has a 30-second deadline and restarts its worker
after a failure. Canceling a Wyoming caller does not immediately interrupt an
already-running HTTP model invocation; the server deadline still bounds it.
The adapter retries only explicit HTTP 503
busy responses with a bounded backoff inside the original request deadline, so
a follow-up can wait for the canceled synthesis to release the worker.
A direct HTTPS caller can contend with Wyoming and receive HTTP 503.

Text is limited to 1,200 characters before and after normalization. Output must
be finite mono audio, at most 115 seconds. Logs contain fixed failure categories,
not input text or generated audio. No microphone is opened or recorded.

`russian_text.py` spells out signed integers, decimal fractions and common energy
units (`W`, `kW`, `kWh`, `V`, `A`, `%`, and degrees Celsius, including Russian
spellings). This preserves values such as `-0.25 kW` rather than rounding them.
It is not a general-purpose date, time, currency or abbreviation normalizer.
Callers should produce unambiguous Russian prose. Markup/control instructions
are rejected; this endpoint accepts plain speech text only.

## Build and deploy an additive baseline

The image embeds hash-verified Denis weights. It needs no model downloads at
runtime. Build for the target node's architecture and push to a private registry:

```sh
docker build -f Dockerfile.russian-speech -t REGISTRY/russian-speech:VERSION .
docker run --rm --network none --memory 1g --cpus 2 \
  --read-only --tmpfs /tmp:size=64m,exec --cap-drop ALL \
  --security-opt no-new-privileges \
  -v "$PWD/tests/smoke_russian_speech.py:/app/smoke_russian_speech.py:ro" \
  REGISTRY/russian-speech:VERSION python /app/smoke_russian_speech.py
docker push REGISTRY/russian-speech:VERSION
```

Use the registry's **manifest digest**, not a mutable tag, in the renderer below.
Create credentials outside version control. The TLS helper refuses to overwrite
an existing directory and creates an owner-only directory. Its leaf certificate
has SANs for `127.0.0.1` and `russian-speech.igw-speech.svc.cluster.local`.
Use matching `--service`/`--namespace` if changing those names. The CA lasts five
years; the leaf lasts one year. Keep the CA private key on the operator machine.
Renew the leaf and restart this deployment before expiry.

```sh
umask 077
python3 scripts/create-russian-speech-tls.py --output /PRIVATE/PATH/russian-tls
kubectl -n igw-speech create secret generic russian-speech-token \
  --from-file=token=/PRIVATE/PATH/russian-tls/token
kubectl -n igw-speech create secret tls russian-speech-tls \
  --cert=/PRIVATE/PATH/russian-tls/server.crt \
  --key=/PRIVATE/PATH/russian-tls/server.key
kubectl -n igw-speech create configmap russian-speech-ca \
  --from-file=ca.crt=/PRIVATE/PATH/russian-tls/ca.crt
python3 scripts/render-russian-speech.py --node YOUR_NODE \
  --image REGISTRY/russian-speech@sha256:YOUR_MANIFEST_DIGEST \
  > /PRIVATE/PATH/russian-speech.json
kubectl apply -f /PRIVATE/PATH/russian-speech.json
kubectl -n igw-speech rollout status deployment/russian-speech --timeout=240s
```

This adds a new Deployment, two containers, a ClusterIP Service, two Secrets and
one ConfigMap. It does not update existing Nano workloads. The Service exposes
Wyoming on `10601` and authenticated HTTPS on `8093` within the cluster. No public
ingress or host port is created. The HTTPS sidecar connection verifies the
private CA; native Kubernetes HTTPS probes skip certificate verification and
carry no credentials. Authorized HTTPS clients receive the token and public CA certificate.
The server private key stays in the server Secret; the CA signing key is never
deployed.

Wyoming itself has no TLS or authentication. Keep its ClusterIP reachable only
from trusted workloads/HA, using the cluster's network policies if other tenants
share the network. Do not expose port `10601` to the Internet. A Home Assistant
outside this network needs a separately secured private route; changing the
Service to a public LoadBalancer is not an appropriate shortcut.

## Home Assistant enrollment and verification

1. In **Settings → Devices & services → Add integration**, select **Wyoming
   Protocol**. Enter `russian-speech.igw-speech.svc.cluster.local`, port `10601`,
   when HA can resolve and route to Kubernetes Services. Otherwise use its
   reachable private service address through the established trusted route.
2. In **Settings → Voice assistants**, create or edit an Assist pipeline. Set
   its language to Russian, choose the existing Russian-capable speech-to-text
   and conversation providers, and choose **Local Russian Speech / piper-ru-denis**
   for text-to-speech. Do not change wake words as part of this operation.
3. First test the TTS entity with synthetic Russian text in Developer Tools.
   Then test the complete Assist pipeline and select it for each satellite.
   The exact TTS entity ID is assigned by HA; do not assume a fixed ID.
4. Test two requests together. Both should return valid audio. Test spoken
   numbers, negative grid flow, fractions, and stale/unavailable energy data.
   A valid WAV and a green health probe do not establish natural pronunciation
   or acoustical quality on an Echo speaker.

For a synthetic paired-request check from an operator machine, temporarily run
`kubectl -n igw-speech port-forward service/russian-speech 10601:10601` in one
terminal. In another, use an environment with the pinned `wyoming` dependency:

```sh
python scripts/probe-russian-speech.py --host 127.0.0.1 --port 10601 \
  --output /PRIVATE/PATH/paired-check
```

The probe sends two identical synthetic requests together, verifies the PCM
format, and saves their WAVs and timings privately. Stop the port forward after
the check. It is a transport/inference check, not microphone or playback proof.

Rollback means selecting the previous TTS provider/pipeline in HA first, then
removing the added Deployment/Service and, if no longer needed, its three
credential objects. Existing English Nano remains available throughout.

## Optional larger KittenTTS 2 experiment

KittenTTS 2 attribution: **Powered by Stellon Labs**. Downloaded model files retain
the upstream `LICENSE.md`; redistribution also requires the license’s Notice file.

Use an isolated Python 3.11 environment; do not install these dependencies in
the Nano runtime. The pinned manifest contains only the Russian voice assets,
model/tokenizer, speaker encoder and required Chatterbox codec. Every file is
verified against a fixed revision, size and SHA-256 hash. The downloaded files
are roughly 2 GB together; the approximately 947 MiB packed language-model file
is not the total download or resident memory requirement.

```sh
python3.11 -m venv /PRIVATE/PATH/tts2-venv
/PRIVATE/PATH/tts2-venv/bin/pip install --require-hashes \
  -r requirements-russian-kitten.lock
python3 scripts/download-russian-speech.py --backend kitten2 \
  --output /PRIVATE/PATH/models
/PRIVATE/PATH/tts2-venv/bin/python scripts/benchmark-russian-speech.py \
  --backend kitten2 --model-root /PRIVATE/PATH/models \
  --output /PRIVATE/PATH/benchmark --threads 4 --repeat 1 --wall-timeout 600
```

The benchmark is synthetic, records complete-WAV latency and peak process RSS,
and kills its isolated process group at the overall deadline. Keep its audio and
JSON results private. It does not measure microphone recognition, playback,
network or total assistant response time. The dependency lock includes platform
alternatives; Linux Torch can bring large CUDA dependencies even when this
adapter selects CPU. Review package size before installing on a small host.

To run the same HTTPS service with this backend, set `RUSSIAN_TTS_BACKEND=kitten2`,
`RUSSIAN_MODEL_ROOT`, `KITTEN_TOKEN_FILE`, `KITTEN_TLS_CERT_FILE`, and
`KITTEN_TLS_KEY_FILE`, then run `python -m igw_google_voice.russian_speech`.
For a Wyoming adapter to this service set `RUSSIAN_SPEECH_VOICE=kitten2-russian`.
The supplied Kubernetes renderer is intentionally sized for Piper, not Kitten2;
allocate and measure a separate larger workload before trying Kitten2 there.

The implementation explicitly uses `voice="Russian"`, `normalize=False`, and
the stable preset. Russian numbers are expanded by this repository before model
inference. The pinned upstream codec loader is redirected only for its known
request to the locally verified codec, preventing resolution of mutable Hub
`main` at runtime. The service operates offline after assets are downloaded.

## Licensing and upstream references

Piper's runtime is GPL-3.0; the pinned Denis model card identifies its dataset as
CC0. Preserve runtime and model notices when redistributing an image. The
runtime license and a voice model's terms are different things; Denis was chosen
instead of a voice whose card listed unknown licensing.

KittenTTS source and weights have different licenses. KittenTTS 2 weights use the
Stellon Labs community license, not the Apache license associated with the old
Nano model. Review the pinned license before commercial use or redistribution;
its attribution and redistribution conditions apply. This repository does not
publish model files, generated test audio, private CA keys or deployment tokens.

- [KittenTTS and current model documentation](https://github.com/KittenML/KittenTTS)
- [Russian voice and normalization guidance](https://github.com/KittenML/KittenTTS/blob/main/docs/voices-and-expression.md)
- [Pinned KittenTTS 2 weights and license](https://huggingface.co/KittenML/kitten-tts-2/tree/f2eee74f4467855ad58fe16f1fb7b7df473263fd)
- [Pinned Denis voice card](https://huggingface.co/rhasspy/piper-voices/blob/c10ece1aade47bb51c153c893d14e5bf8e5b7117/ru/ru_RU/denis/medium/MODEL_CARD)
- [Piper runtime](https://github.com/OHF-Voice/piper1-gpl)

## Measurements

On 2026-10-14 an isolated Apple M5 Pro CPU test with two inference threads loaded
Denis in 0.74 seconds. The first short synthesis took 0.77 seconds; the warm repeat
took 0.055 seconds for 1.87 seconds of audio. A synthetic energy report produced
12.6–12.8 seconds of audio in 0.32–0.33 seconds. A longer prose response took
0.19–0.20 seconds. These are local model timings, not production SLA measurements
or a claim of verified Russian pronunciation. Measure the deployment host before
choosing an interactive default.

The same M5 Pro, using four CPU inference threads, loaded the pinned KittenTTS 2
model in 21.69 seconds. Its first short phrase took 14.24 seconds for 2.08 seconds
of audio. After that, the synthetic energy report took 34.57 seconds for 17.60
seconds of audio; the prose answer took 17.58 seconds for 7.32 seconds of audio.
Peak process RSS was approximately 7.21 GiB. This CPU implementation therefore
remains an optional quality experiment, not the interactive default. A larger
model alone did not provide an acceptable response latency on this host. These
measurements do not establish performance of the separate C++ or GPU backends.

A separate offline test in the same Piper image on a heavily contended two-core
NAS was unsuitable: warm startup took 124.5 seconds, the first short phrase took
7.65 seconds, and the next report exceeded the 30-second worker deadline. The
worker was observed waiting on disk I/O. This is why the deployment target must
be measured independently; the M5 result is not a promise for a NAS or VM.

As a secondary check, the synthetic energy clips were transcribed by the existing
Parakeet recognizer. The Denis transcript preserved the four numeric values
(63, 1.5, 420 and 12.5), but omitted the watt unit after 420 and contained several
word errors. The Kitten2 transcript repeated
the solar-power clause and rendered the final decimal ambiguously. This is an
ASR round-trip check, not a listening test: it cannot distinguish a synthesis
error from a recognition error. Neither result establishes pronunciation
quality. In particular, Kitten2 is not qualified for authoritative energy
narration; review generated speech by ear before selecting either voice.
