# KittenTTS Nano with a second server

The standalone Google Cast adapter can request English speech from two private
CPU-only servers, in order. The primary and secondary both preload KittenTTS
Nano 0.8 INT8, using the Jasper voice. The NAS continues to fetch the authoritative
IGW report, draw its cards, encode H.264/AAC video and deliver it to Google Cast.
Neither Home Assistant TTS, FCC nor Homeway participates in this speech path.

## Request path

1. The Cast renderer sends the original report text to the primary `/v1/speech`.
2. Connection failure, timeout, an HTTP error, or invalid/truncated audio causes
   an attempt on the secondary, with the same text.
3. If both fail, the existing local eSpeak voice reads the same report.

Each remote attempt has an independent hard subprocess deadline (eight seconds
by default, maximum ten). A partial response is removed before trying another
provider. Redirects and environment HTTP proxies are not followed. The existing
report freshness check still runs after rendering; failover never authorizes an
outdated report. `/v1/status` reports `kitten_primary`, `kitten_secondary`, or
`espeak` under `tts_provider` after a render.

No numerical values are invented or rewritten by an LLM. IGW should continue to
spell out units such as “watts” and “kilowatt hours”. The selected model is for
English, not multilingual KittenTTS 2.

## Reproducible service image

Build `Dockerfile.kitten` on each required architecture, or with a suitable
multi-platform builder. Publish to your private registry and use the resulting
image digests. The image contains the model; running it needs no model download. ONNX Runtime telemetry is disabled before model initialization.

```sh
docker build -f Dockerfile.kitten -t REGISTRY/igw-kitten:VERSION .
docker push REGISTRY/igw-kitten:VERSION
```

The Python base image and Python distributions are pinned, with distribution
hashes. `requirements-kitten.lock` contains only the ONNX runtime dependencies.
`requirements-kitten-package.lock` installs the upstream `kittenml` wheel using
`--no-deps`, deliberately excluding its unrelated Torch/KittenTTS 2 dependencies.
Consequently a generic `pip check` reports those intentionally absent optional
backends; service import, actual inference and HTTP tests validate this backend.
Do not run an unqualified `pip install kittenml` in this image.

The model is pinned to Hugging Face revision
`84781d74e29ee25217551556398b42f80593a813`. `scripts/download-nano.py` verifies
SHA-256 hashes of the graph, voices and configuration. The upstream
[model card](https://huggingface.co/KittenML/kitten-tts-nano-0.8-int8)
lists Apache-2.0 licensing. Preserve upstream attribution when redistributing.

The model graph is about 24 MB, but the process needs substantially more RAM.
The example deployment allows 768 MiB, one CPU, and a 64 MiB temporary filesystem.
It requests 500 millicores for the primary and 100 for the secondary; override
these with `--primary-cpu-millicores` and `--secondary-cpu-millicores` to fit the
nodes. Reserve enough primary CPU for prompt replies under competing workloads.
Health probes use HTTP directly rather than repeatedly starting Python processes.
The temporary mount must permit executable mappings (`--tmpfs /tmp:size=64m,exec`
for Docker): phonemizer copies its eSpeak shared library there before loading it.
The Kubernetes memory-backed `emptyDir` has this behavior by default.
ONNX explicitly uses one intra-op and one inter-op thread. A supervised child
preloads and warms the model before readiness, handles one request at a time,
and is terminated/reloaded if generation exceeds twelve seconds. Busy requests
receive 503 so the caller can use the other server. Text/audio are not retained;
access logs and upstream text-printing wrappers are not used.

## Kubernetes deployment

Use private addresses actually assigned to each node. The service binds only to
that address, not all interfaces. Permit TCP 8092 only over your trusted LAN/VPN;
do not create an Internet ingress. The example uses host networking to let a NAS
outside Kubernetes reach each specific server directly, without load balancing
away the primary/secondary order. Both services require the same dedicated
bearer token. It is separate from the Cast and IGW API tokens.

```sh
umask 077
python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > speech-token
kubectl create namespace igw-speech
kubectl -n igw-speech create secret generic igw-kitten-token --from-file=token=speech-token
python3 scripts/render-kitten-deployment.py \
  --primary-node PRIMARY_NODE --primary-address PRIMARY_PRIVATE_IP \
  --primary-image REGISTRY/igw-kitten@sha256:PRIMARY_DIGEST \
  --secondary-node SECONDARY_NODE --secondary-address SECONDARY_PRIVATE_IP \
  --secondary-image REGISTRY/igw-kitten@sha256:SECONDARY_DIGEST > deployment.private.json
kubectl apply -f deployment.private.json
```

Keep the token and site-specific manifest out of source control. Mounting the
secret as a file keeps it out of process arguments. Token changes require a
rollout restart of both services and an update to the Cast environment.

Configure the Cast container, with primary first:

```dotenv
CAST_TTS_PROVIDER=kitten
CAST_KITTEN_ENDPOINTS=http://PRIMARY_PRIVATE_IP:8092/v1/speech,http://SECONDARY_PRIVATE_IP:8092/v1/speech
CAST_KITTEN_TOKEN=YOUR_DEDICATED_LONG_RANDOM_TOKEN
CAST_KITTEN_TIMEOUT=8
```

Recreate the Cast container using an image containing this integration. Keep its
existing IGW credentials, media address, Cast device, and eSpeak installation.
The NAS needs no ONNX or model dependencies.

## Validation and troubleshooting

- Check `/healthz` on each server, then synthesize a fixed non-private sentence
  from the NAS. A successful response is 24 kHz mono PCM16 WAV.
- Render one complete report. Check the authenticated Cast `/v1/status` provider
  and confirm the receiver actually starts playback.
- Temporarily scale only the primary speech deployment to zero, synthesize via
  the normal client and confirm `kitten_secondary`. Restore the primary and
  wait for readiness. Never stop a whole host for a failover test.
- Test both endpoints unavailable with an isolated client configuration to
  confirm local eSpeak fallback without disrupting production services.
- If latency exceeds the deadline, inspect CPU load, model readiness and VPN
  routing. Do not disable report freshness checks to hide slow generation.
- A 401 indicates a token mismatch; 503 means warming up or busy; 502 means the
  worker failed and is being recovered. Logs omit report text and credentials.
- To roll back the speech choice, set `CAST_TTS_PROVIDER=espeak` and recreate only
  the Cast container. The two Nano deployments can remain idle or be scaled down.

Run `python -m unittest discover -s tests -v` in the project's test environment.
Tests cover ordered failover, partial audio deletion, transport validation,
credentials, input limits and hard timeouts. Hardware timings and actual Cast
playback require separate deployment verification.
