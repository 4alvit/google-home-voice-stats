# IGW energy reports on Google Home / Nest

Ask Google for battery charge, solar power, today's solar energy, an energy
summary, or active alarms. Home Assistant fetches a current report from the Inverter Gateway (IGW)
and speaks the gateway's text on a selected Nest speaker.

The data path is **Victron/MQTT → IGW → read-only API**. IGW owns source
selection, units, battery and solar statistics, freshness, and report wording.
Home Assistant is an optional voice adapter: it does not collect or calculate
those measurements. Google Assistant invokes one of five HA scripts as a scene;
a shared queued script fetches and speaks the requested report.

This repository contains an installable HA script blueprint, a configuration
renderer, and tests. It does not contain a new Google cloud integration. Use the
existing [HA Google Assistant integration](https://www.home-assistant.io/integrations/google_assistant/)
or Home Assistant Cloud to link HA and Google. Ordinary device control remains
available through that integration independently of this read-only adapter.

## Requirements

- An IGW deployment serving authenticated `GET /v1/energy` over HTTPS with a valid
  certificate, or explicitly opted-in HTTP within a trusted private network, and
  the contract in [docs/igw-contract.md](docs/igw-contract.md).
- A scoped IGW read bearer token. The HA adapter supports bearer authentication
  only. Do not put Cloudflare Access service-token headers in a REST command:
  HA follows redirects and forwards those custom headers to another origin.
- Home Assistant 2024.8 or newer, a working `tts.*` provider, and a Google Cast
  `media_player.*` entity. CI validates configuration against HA 2026.9.2; older
  supported syntax still needs verification on your installation.
- A linked Google Home household. The recommended linking path is Home Assistant
  Cloud. Manual Google account linking is also supported by HA.
- Python 3.11+ for the renderer. Runtime Python dependencies: none.

## Render a configuration

Clone this repository and run the renderer from its root. Find the actual speech
provider and Nest entity in HA's entity list; first confirm `tts.speak` works with
those two entities in HA's Actions tool. Set these non-secret variables to your
real values:

```bash
export IGW_ENERGY_URL='https://your-real-gateway-host/v1/energy'
export HA_TTS_ENTITY='tts.your_existing_provider'
export HA_NEST_ENTITY='media_player.your_existing_nest'
python3 -m igw_google_voice render-config \
  --igw-url "$IGW_ENERGY_URL" \
  --tts-entity "$HA_TTS_ENTITY" \
  --media-player "$HA_NEST_ENTITY" \
  --output ./rendered
```

Replace the example values before running: entity placeholders and incomplete,
insecure, or credential-bearing URLs are rejected. Use `--max-response-age 60` only if you intentionally
need a different envelope age limit; the default is 30 seconds. The renderer
validates input syntax, writes a new staging directory, and refuses overwrites.
It does not connect to HA or verify that entities exist.

For HA and IGW in the same trusted Kubernetes cluster, use the internal service
route and explicitly allow local HTTP:

```bash
python3 -m igw_google_voice render-config \
  --igw-url http://inverter-gateway.synology-apps.svc.cluster.local:8080/v1/energy \
  --allow-local-http \
  --tts-entity "$HA_TTS_ENTITY" \
  --media-player "$HA_NEST_ENTITY" \
  --output ./rendered-local
```

The opt-in accepts only RFC1918 private IPs, loopback/localhost, IPv6 unique-local
addresses, and Kubernetes service names ending in `.svc` or `.svc.cluster.local`.
Public HTTP and arbitrary DNS hostnames remain rejected. This validates the URL
shape, not network isolation: the operator must trust cluster DNS and routing.
HTTP carries the scoped read token without transport encryption; use it only
inside that trusted network, or use direct HTTPS bearer authentication instead.
An Access-protected public endpoint requiring custom service-token headers is
not supported by HA's REST command. Configure a direct private route for HA;
do not weaken the public Access policy. The endpoint should serve a direct
response without redirects.

To install the CLI itself, use `python3 -m pip install .` in a virtual environment;
then `igw-google-voice render-config` is available outside the checkout.

The generated files are:

- `packages/igw_google_voice.yaml`: authenticated REST command, a private
  dispatcher instance, and five public report scripts.
- `blueprints/script/igw/announce_energy.yaml`: reusable script blueprint with
  selectors for the TTS provider and Cast speaker.
- `igw.secrets.example.yaml`: credential keys to merge into your existing
  `secrets.yaml`; this is an incomplete example, kept outside `packages/`.
- `INSTALL.md`: installation checklist.

## Install in Home Assistant

1. Back up the HA configuration, then copy the generated `packages/` and
   `blueprints/` files into its configuration directory. This adapter uses fixed
   `igw_*` names; install only one copy per HA instance.
2. Merge the generated secret keys into HA's existing `secrets.yaml`. Set
   `igw_energy_authorization` to `Bearer ` followed by the scoped read token.
   Replace all credential placeholders, keep the real file outside Git, and
   restrict it to its owner.
   Do not copy the example secrets file into the package directory.
3. Enable [HA packages](https://www.home-assistant.io/docs/configuration/packages/)
   in `configuration.yaml`, merging with your existing `homeassistant` section:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

4. Keep the generated `logger.logs.homeassistant.components.rest_command: warning`
   setting. The HA REST integration logs request headers at DEBUG, which would
   include authentication. Merge or remove any conflicting logger override in
   your existing configuration. The adapter stores no script traces, passes no
   credentials in script arguments, and does not put tokens in URLs.
5. Run **Check configuration** in HA before restarting. On HA OS/Supervised,
   `ha core check` is the equivalent CLI check. On Container/Core, run
   `python -m homeassistant --script check_config --config /config` in the HA
   runtime, using your actual config path. Then restart HA to load the REST
   command and blueprint scripts.
6. In HA's Actions tool, call `script.igw_google_battery`,
   `script.igw_google_solar`, `script.igw_google_solar_today`, and
   `script.igw_google_status`, and `script.igw_announce_alarms`. Each should speak its own current report.
7. Expose only these five wrapper scripts to Google Assistant, assign their room,
   sync devices, and set up the voice phrases in [docs/routines.md](docs/routines.md).
   Keep `script.igw_google_energy_dispatch` private.

The selected Nest is the output for every report, regardless of which speaker
hears the request. This adapter does not identify the requesting speaker. Its
shared queue waits for playback with bounded timeouts to reduce interruptions;
external music, other TTS automations, or a speaker that fails to report playback
can still interfere. Cast must be able to fetch HA's generated audio URL; see
[HA's Cast/TTS troubleshooting](https://www.home-assistant.io/integrations/tts/#google-cast-devices).

## Failure behavior

Every queued request performs its own authenticated GET when execution begins. There are
no cached HA energy sensors. The response must have HTTP 200, schema version 1,
the expected envelope fields, a recent numeric Unix timestamp, and a recognized
report status with nonempty text. The timestamp may be at most five seconds in
the future to tolerate minor clock skew; keep HA and IGW clocks synchronized.

The adapter speaks IGW's central `fresh`, `stale`, `unavailable`, or `unconfigured`
report text. It never substitutes zero for absent data. An expired API envelope,
timeout, authentication failure, HTML login page, or malformed report produces
the blueprint's fallback message. If the Nest or TTS provider itself is down,
speech cannot be delivered; HA reports that action failure.

## Verification

```bash
python3 -m pip install '.[test]'
python3 -m unittest discover -s tests -v
python3 tests/make_ha_fixture.py ./rendered/ha-check
docker run --rm --entrypoint python \
  -v "$PWD/rendered/ha-check:/config" \
  ghcr.io/home-assistant/home-assistant:2026.9.2 \
  -m homeassistant --script check_config --config /config
```

The tests execute the shipped response template, validate generated YAML and
script wiring, and cover gateway warnings, missing data, bad schemas, stale and
future timestamps, HTTP failures, output collisions, and invalid inputs. The
container fixture uses fake credentials and does not invoke the API or speakers.
CI runs both tests and the HA configuration check. Physical voice recognition,
Google account linking, actual gateway access, and audible Nest playback require
the installation smoke tests in [docs/testing.md](docs/testing.md).

License: MIT.
