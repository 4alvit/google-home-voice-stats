# TLS keys and supported speech configuration

Owned HTTPS clients now verify certificate chains and hostnames and then check every certificate in the verified chain, including the selected trust anchor, before sending application data. RSA keys must have at least 2048 significant bits; EC keys at least 224 bits; DSA p/q at least 2048/224 bits. Ed25519 and Ed448 are accepted by the decoder; unsupported algorithms fail closed. TLS 1.2 is the minimum and stronger operator cipher/protocol settings are retained. OpenSSL security level 2 alone does not enforce an exact RSA-2048 boundary.

The policy covers the IGW gateway client, authenticated speech client (including Wyoming's HTTPS subprocess), and both model download helpers. Model redirects must remain HTTPS; pinned SHA-256 hashes and size limits still apply. A speech server checks every configured PEM certificate before loading its private key and opening the listener. The standard generators create RSA-3072 CAs and RSA-2048 leaf keys. Generated secrets stay outside source control.

CPython 3.11+ uses its verified-chain API (the internal SSL object on 3.11/3.12). Linux and Apple Silicon use the hash-locked cryptography package. Intel macOS retains the native Security.framework decoder from the reviewed Amazon voice policy because current cryptography wheels do not support that platform; unsupported native key encodings fail closed. The code is adapted under MIT from 4alvit/amazon-echo-home-voice and preserves its attribution.

The synthetic suite tests TLS 1.2 and 1.3, strong RSA/EC, RSA-2047 leaves and roots, weak leaves/intermediates/roots, untrusted chains and wrong hostnames through the real clients. Each usable fixture has a low-strength calibration; a specifically diagnosed native EC192 decode limitation still requires product rejection. Tests assert that rejected peers receive no HTTP bytes. Separate tests reject weak configured server certificates and HTTP model redirects.

## Complete supported standalone speech workflow

The existing direct speech API accepts plain text and returns a WAV file independently of Home Assistant or Cast. The following configuration uses the maintained Russian Piper service with pinned Denis/Irina models, private authenticated HTTPS, and the first-party speech client. It is useful for generating local spoken energy messages without exposing a public service. It does not start Wyoming, Cast or an HA integration.

From a source checkout, build the documented image and create a fresh private directory outside the checkout:

```sh
docker build -f Dockerfile.russian-speech -t local-russian-speech:reviewed .
python3 scripts/create-russian-speech-tls.py --output /PRIVATE/russian-tls
python3 -m venv .speech-client
.speech-client/bin/python -m pip install --require-hashes -r requirements-tls.lock
docker run --rm --name local-russian-speech --read-only \
  --tmpfs /tmp:size=64m,exec --cap-drop ALL --security-opt no-new-privileges \
  --memory 1g --cpus 2 -p 127.0.0.1:8093:8093 \
  -v /PRIVATE/russian-tls/server.crt:/run/tls/server.crt:ro \
  -v /PRIVATE/russian-tls/server.key:/run/tls/server.key:ro \
  -v /PRIVATE/russian-tls/token:/run/tls/token:ro \
  -e KITTEN_TLS_CERT_FILE=/run/tls/server.crt \
  -e KITTEN_TLS_KEY_FILE=/run/tls/server.key -e KITTEN_TOKEN_FILE=/run/tls/token \
  -e KITTEN_BIND_HOST=0.0.0.0 -e KITTEN_PORT=8093 \
  -e RUSSIAN_SPEECH_VOICE=piper-ru-irina local-russian-speech:reviewed
```

The service runs as UID 10001. Grant that UID read access only to the mounted server leaf/key/token (for example through a dedicated deployment directory/group); never mount `ca.key`. Keep the host port bound to loopback. On platforms where a loopback port mapping is not isolated as expected, use an equivalent private container network and a matching certificate SAN.

In a second terminal, use the source client with the public CA and private token. The token is read from a file, not written into shell history:

```sh
.speech-client/bin/python - <<'PYTHON'
from pathlib import Path
from igw_google_voice.kitten_client import fetch_audio
root = Path('/PRIVATE/russian-tls')
audio = fetch_audio('https://127.0.0.1:8093/v1/speech',
                    (root / 'token').read_text().strip(),
                    'Батарея заряжена на 63 процента.', str(root / 'ca.crt'),
                    read_timeout=31)
Path('/PRIVATE/report.wav').write_bytes(audio)
PYTHON
```

The offline image smoke test exercises the actual Piper model, guarded server and client, valid and invalid bearer tokens and complete WAV output, with external networking disabled. This is not a physical speaker or microphone acceptance test. Runtime inference uses already verified local weights and does not fetch remote models.

## Other deployments and release tooling

Cast device transport remains owned by PyChromecast, whose self-signed device TLS does not validate a public CA chain. Generated HA transport belongs to the selected HA runtime. Wyoming TCP and private-LAN Cast media are intentionally not encrypted and must remain isolated. Those optional deployments are not qualified by the standalone speech key-length result. They remain in source/static analysis and dependency review.

Release helpers delegate GitHub transport to `gh`; see RELEASE_TLS_PROFILE.md for a versioned individual-command profile. A successful key-length test is separate from vulnerability status: current Go binary advisories are being assessed for affected function, severity and age. Do not infer a clean dependency audit or a Passing award from this document.
