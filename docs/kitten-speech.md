# KittenTTS Nano with a second server

The standalone Google Cast adapter can request English speech from two private
CPU-only servers, in order. Both preload KittenTTS Nano 0.8, using the Jasper
voice. Linux containers default to INT8; a native Intel Mac can use FP32. The NAS continues to fetch the authoritative
IGW report, draw its cards, encode H.264/AAC video and deliver it to Google Cast.
Neither Home Assistant TTS, FCC nor Homeway participates in this speech path.

## Request path

1. The Cast renderer verifies the primary server’s TLS certificate against the
   dedicated speech CA and sends the original text to its HTTPS `/v1/speech`.
2. Connection failure, a TLS verification error, timeout, an HTTP error, or invalid/truncated audio causes
   an attempt on the secondary, with the same text.
3. If both fail, the existing local eSpeak voice reads the same report.

Each remote attempt has an independent hard subprocess deadline (eight seconds
by default, maximum fifteen). A partial response is removed before trying another
provider. Redirects and environment HTTP proxies are not followed. The existing
report freshness check still runs after rendering; failover never authorizes an
outdated report. `/v1/status` reports `kitten_primary`, `kitten_secondary`, or
`espeak` under `tts_provider` after a render.

No numerical values are invented or rewritten by an LLM. IGW should continue to
spell out units such as “watts” and “kilowatt hours”. The selected model is for
English, not multilingual KittenTTS 2.

## Encrypted transport and certificates

HTTPS is mandatory on both endpoints, including when using a VPN. A private
destination address alone does not guarantee an encrypted route: a NAS may reach
a VPN address through a router over an unencrypted LAN first. TLS starts in the
Cast process, so bearer credentials, report text and audio remain encrypted all
the way to the speech process. There is no HTTP or unverified-TLS fallback.

The client trusts only the PEM CA bundle at `CAST_KITTEN_CA_FILE`, verifies the
certificate's validity and IP subject alternative name (SAN), and requires
TLS 1.2 or newer. Common-name-only certificates are not accepted. Each server
has its own key; the CA signing key must never be deployed to either server or
the NAS. Use addresses from the actual configured URLs when issuing certificates.

Create certificates on the operator's machine with Python and OpenSSL, outside
the checkout. The output directory must not already exist:

```sh
umask 077
python3 scripts/create-speech-tls.py --output /PRIVATE/OPERATOR/PATH/speech-tls \
  --primary-address PRIMARY_PRIVATE_IP --secondary-address SECONDARY_PRIVATE_IP
```

The directory and files are private to their owner. Transfer files over SSH:
`ca.crt` to the NAS, `primary.crt`/`primary.key` to the primary, and
`secondary.crt`/`secondary.key` to the secondary. Keep the remaining CA material
in protected operator storage. Never commit keys, site certificates, tokens or
rendered manifests. Leaves last 365 days; the CA lasts five years. See renewal
below. Servers refuse to start without a valid certificate/key pair.

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
Health probes use HTTPS directly rather than repeatedly starting Python processes.
Kubernetes' native HTTPS probes skip certificate verification; they carry no
token or report text and indicate readiness only. Always validate trust separately
from the NAS with the real CA, as shown below.
The temporary mount must permit executable mappings (`--tmpfs /tmp:size=64m,exec`
for Docker): phonemizer copies its eSpeak shared library there before loading it.
The Kubernetes memory-backed `emptyDir` has this behavior by default.
ONNX defaults to one intra-op and one inter-op thread. `KITTEN_THREADS` permits
one to four intra-op threads when the host has capacity. A supervised child
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
kubectl -n igw-speech create secret tls kitten-primary-tls \
  --cert=/PRIVATE/OPERATOR/PATH/speech-tls/primary.crt \
  --key=/PRIVATE/OPERATOR/PATH/speech-tls/primary.key
kubectl -n igw-speech create secret tls kitten-secondary-tls \
  --cert=/PRIVATE/OPERATOR/PATH/speech-tls/secondary.crt \
  --key=/PRIVATE/OPERATOR/PATH/speech-tls/secondary.key
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
The per-server TLS secrets mount read-only at `/run/speech-tls`; private keys
are readable only by root and the service group. With a native Mac primary,
create only the secondary TLS secret and deploy only the secondary workload.

Configure the Cast container, with primary first:

```dotenv
CAST_TTS_PROVIDER=kitten
CAST_KITTEN_ENDPOINTS=https://PRIMARY_PRIVATE_IP:8092/v1/speech,https://SECONDARY_PRIVATE_IP:8092/v1/speech
CAST_KITTEN_CA_FILE=/run/speech-ca/ca.crt
CAST_KITTEN_TOKEN=YOUR_DEDICATED_LONG_RANDOM_TOKEN
CAST_KITTEN_TIMEOUT=8
```

Recreate the Cast container using an image containing this integration. Keep its
existing IGW credentials, media address, Cast device, and eSpeak installation.
The NAS needs no ONNX or model dependencies.
Mount the NAS directory containing only `ca.crt` read-only at `/run/speech-ca`.
For Compose, add a volume such as `./speech-ca:/run/speech-ca:ro`. Do not mount
the operator's entire certificate directory or its signing/private keys.

## Native Intel Mac primary

The native service permits only an IPv4 loopback bind. NAS-to-Mac requests must
use an encrypted SSH tunnel as described below. A private IP address and bearer
token do not encrypt report text, audio or credentials. Do not expose port 8092
on the Mac's LAN interface or forward it from a router.

Measure the actual deployment host before selecting a format. On a tested older
Intel Mac, a busy Linux VM took about 74 seconds to synthesize a 5.5-second
sentence with INT8. Native macOS with FP32 and four threads reduced that to about
three seconds. These are observations, not a performance guarantee. The FP32
graph is about 57 MB plus the 3.3 MB voice file; the complete Python environment
uses additional disk and memory. Both formats are the same Nano model family.

For macOS 12 on Intel, use the separate compatibility lock below. Its ONNX
Runtime 1.19.2 wheel supports that OS; newer Intel wheels require macOS 13 or
later. The Linux image continues to use its current, separate runtime lock.
Do not install the Mac compatibility lock into the Linux image.

From a checkout of this repository, under an existing unprivileged service user:

```sh
SPEECH_ROOT="$HOME/.local/share/igw-speech"
mkdir -p "$SPEECH_ROOT/app"
chmod 700 "$SPEECH_ROOT"
python3.11 -m venv "$SPEECH_ROOT"
"$SPEECH_ROOT/bin/python" -m pip install --require-hashes --only-binary=:all: \
  -r requirements-kitten-macos-intel.lock
"$SPEECH_ROOT/bin/python" -m pip install --no-deps --require-hashes --only-binary=:all: \
  -r requirements-kitten-package.lock
cp -R igw_google_voice "$SPEECH_ROOT/app/"
python3 scripts/download-nano.py --variant fp32 --output "$SPEECH_ROOT/models/nano-fp32"
install -m 600 speech-token "$SPEECH_ROOT/speech-token"
mkdir -p "$SPEECH_ROOT/tls"
chmod 700 "$SPEECH_ROOT/tls"
install -m 600 /PRIVATE/OPERATOR/PATH/speech-tls/primary.crt "$SPEECH_ROOT/tls/server.crt"
install -m 600 /PRIVATE/OPERATOR/PATH/speech-tls/primary.key "$SPEECH_ROOT/tls/server.key"
python3 scripts/render-kitten-launchd.py --root "$SPEECH_ROOT" \
  --user "$(id -un)" --threads 4 > primary.private.plist
plutil -lint primary.private.plist
sudo install -o root -g wheel -m 644 primary.private.plist \
  /Library/LaunchDaemons/org.igw.kitten-primary.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/org.igw.kitten-primary.plist
```

Use the same dedicated `speech-token` as the secondary. `launchd` starts the
service on `127.0.0.1:8092` after reboot and runs it as the specified user.
Logs remain in the private runtime
directory and do not include request text. Four threads are a parallelism bound,
not a macOS CPU quota; choose fewer on a smaller or busier host.

### Required NAS-to-Mac SSH tunnel

Enable macOS Remote Login for the unprivileged service user and configure a
dedicated SSH key for the NAS tunnel process. Verify the physical Mac's SSH host
key through a separate trusted channel and provision it in that NAS user's
`known_hosts` before starting the tunnel. Do not disable host-key checks.

Run on the NAS, replacing `SPEECH_USER` and `MAC_PRIVATE_IP` with that user and
the physical Mac's address:

```sh
ssh -NT -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 \
  -o ServerAliveCountMax=3 \
  -L 127.0.0.1:18092:127.0.0.1:8092 SPEECH_USER@MAC_PRIVATE_IP
```

Configure the NAS service manager to run this command as an unprivileged user,
start it after networking at boot, and restart it on exit. Both ends of the
forward bind to loopback; SSH encrypts traffic crossing the network. The supplied
Cast Compose service uses Linux host networking, so it can reach the NAS's
loopback forward. A Cast process in another network namespace needs the tunnel
in that same namespace; do not expose the forward on a LAN address.

Replace the primary endpoint in the Cast environment:

```dotenv
CAST_KITTEN_ENDPOINTS=http://127.0.0.1:18092/v1/speech,http://SECONDARY_PRIVATE_IP:8092/v1/speech
```

Check `http://127.0.0.1:18092/healthz` from the NAS before recreating Cast. Verify
that `http://MAC_PRIVATE_IP:8092/healthz` cannot be reached from the NAS. When the
tunnel is stopped, the primary request must fail and normal secondary/eSpeak
fallback applies; never substitute the Mac's LAN address as a fallback endpoint.
For an existing installation, regenerate and reinstall the plist, then boot out
and bootstrap the LaunchDaemon to replace its old LAN listener.

If measured long-report timings require it, set `CAST_KITTEN_TIMEOUT=15` on the
Cast client. This allows the server's twelve-second inference deadline plus
connection and process overhead. The overall report freshness check still
applies after rendering; a sufficiently slow failover is rejected as stale.

To update, reinstall from the lock files, copy the updated package, verify the
model hashes, then run `sudo launchctl kickstart -k system/org.igw.kitten-primary`.
To test failover, run `sudo launchctl bootout system/org.igw.kitten-primary`,
verify `kitten_secondary` from the Cast client, and bootstrap the plist again.
Keep only the secondary Kubernetes deployment when using a native primary.

## Validation and troubleshooting

- From the NAS, run `curl --fail --cacert /PATH/TO/ca.crt https://SERVER_PRIVATE_IP:8092/healthz`
  on each server, then synthesize a fixed non-private sentence
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
- For certificate failures, check the CA mount, leaf expiry, host clocks and SAN.
  A changed server IP requires a reissued certificate. Never use `curl -k`, disable
  hostname verification, or change the endpoint back to HTTP. A failed TLS check
  sends no bearer or report text and invokes the normal secondary/local fallback.
- If worker recovery fails, the service exits and Kubernetes or `launchd`
  restarts it. The other endpoint continues to provide speech during recovery.
- To roll back the speech choice, set `CAST_TTS_PROVIDER=espeak` and recreate only
  the Cast container. The two Nano deployments can remain idle or be scaled down.

Run `python -m unittest discover -s tests -v` in the project's test environment.
Tests cover ordered failover, partial audio deletion, transport validation,
credentials, input limits and hard timeouts. Hardware timings and actual Cast
playback require separate deployment verification.

## Certificate renewal

Check expiry at least 30 days in advance with
`openssl x509 -checkend 2592000 -noout -in SERVER.crt`
(a nonzero result means renewal is needed). On the protected operator machine,
re-sign each retained CSR with its matching SAN configuration:

```sh
openssl x509 -req -in primary.csr -CA ca.crt -CAkey ca.key \
  -set_serial "0x$(openssl rand -hex 16)" -days 365 -sha256 \
  -extfile primary.cnf -out primary-renewed.crt
```

Repeat for the secondary. Replace the corresponding leaf certificate securely
and restart only that speech process, one server at a time; verify from the NAS
before proceeding. The CA file on the NAS stays unchanged for leaf renewal. If
rotating the CA, first distribute a bundle containing the old and new CA, replace
and verify both server certificates, and finally remove the old CA. Keep all
private keys outside source control and retain the old working configuration
until verified; rolling back must not reintroduce plaintext transport.
