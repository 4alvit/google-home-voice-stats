# IGW energy reports on Google Home / Nest

Show and speak battery charge, solar power, today's solar energy, an energy
summary, or active alarms on a Google Cast display. The standalone adapter fetches
a current Inverter Gateway (IGW) report and generates a short dashboard video with
offline English speech. It uses Google's default media receiver: no custom Cast
registration, paid TTS service, or Home Assistant installation is required for output.

**Start with the [standalone Cast setup](docs/standalone-cast.md).** Home Assistant
can optionally forward Google voice commands to this service through an existing
Matter bridge or a cloud account link. Its five report names remain unchanged.
Cast alone does not add "Hey Google" commands. For a subscription-free voice
entry point with a compatible Google hub, see the [Matter setup](docs/matter.md).

The original HA speech-only adapter remains available below for installations
that prefer their existing TTS voice or use audio-only speakers.

The data path is **Victron/MQTT → IGW → read-only API**. IGW owns source
selection, units, battery and solar statistics, freshness, and report wording.
The standalone Cast adapter handles report presentation and transport. In the
original speech-only mode, HA performs that role. Neither calculates energy
statistics. IGW runs its data pipeline independently of HA. With the optional HA
trigger, Google invokes one of five scripts through Matter or as a cloud scene,
and HA requests playback from the standalone service.

This repository contains the standalone service, container deployment, offline
video renderer, optional HA trigger renderer, original HA blueprint, and tests.
**There is no Google skill or store app to install.** Home Assistant Matter Hub
can expose the scripts as momentary on/off devices; Google-to-HA cloud account
linking can expose them as scenes. Ordinary device control remains available
independently of this read-only adapter.

<!-- ci-release-process:start -->
## CI and deployment

See [CI and deployment workflow](docs/release-workflow.md) for required checks and local commands. This repository uses validation-only policy; application release channels do not apply.
<!-- ci-release-process:end -->


## Requirements for the original HA speech adapter

- An IGW deployment serving authenticated `GET /v1/energy` over HTTPS with a valid
  certificate, or explicitly opted-in HTTP within a trusted private network, and
  the contract in [docs/igw-contract.md](docs/igw-contract.md).
- A scoped IGW read bearer token. The HA adapter supports bearer authentication
  only. Do not put Cloudflare Access service-token headers in a REST command:
  HA follows redirects and forwards those custom headers to another origin.
- Home Assistant 2024.8 or newer, a working `tts.*` provider, and a Google Cast
  `media_player.*` entity. CI validates configuration against HA 2026.9.2; older
  supported syntax still needs verification on your installation.
- A Google Home household and either a paired Home Assistant Matter Hub bridge
  with a compatible Google hub, or an HA-to-Google cloud account link, as
  described below. Matter needs no Homeway or Nabu Casa subscription; a cloud
  linking provider may require one.
- Python 3.11+ for the renderer. Runtime Python dependencies: none.

## Setup order

1. Prepare IGW, a working HA TTS provider, and a Cast speaker.
2. Render and install the adapter using the next two sections; test its scripts
   from HA before configuring voice commands.
3. [Link Google and expose the report scenes](#link-google-and-expose-the-report-scenes).
4. [Try all five voice commands](#use-the-reports), then add optional short routines.

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
route and explicitly allow local HTTP. This example uses a generic service and
namespace; substitute your own:

```bash
python3 -m igw_google_voice render-config \
  --igw-url http://inverter-gateway.energy.svc.cluster.local:8080/v1/energy \
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
   `script.igw_google_solar`, `script.igw_google_solar_today`,
   `script.igw_google_status`, and `script.igw_announce_alarms`. Each should speak
   its own current report.
7. Continue with Matter or cloud exposure below.

The selected Nest is the output for every report, regardless of which speaker
hears the request. This adapter does not identify the requesting speaker. Its
shared queue waits for playback with bounded timeouts to reduce interruptions;
external music, other TTS automations, or a speaker that fails to report playback
can still interfere. Cast must be able to fetch HA's generated audio URL; see
[HA's Cast/TTS troubleshooting](https://www.home-assistant.io/integrations/tts/#google-cast-devices).

## Link Google and expose the report scenes

Choose **one** route for these scripts. Reuse an existing working bridge or
account link when available; exposing the same scripts twice creates ambiguous
report names.

**Matter: no voice-integration subscription.** Use the maintained
[Home Assistant Matter Hub](https://riddix.github.io/home-assistant-matter-hub/)
to expose only the five public scripts as on/off plug endpoints. Turning one on
runs its report; it immediately reads as off again. A compatible Google Matter
hub and a bridge paired to the intended Google Home are required. Follow the
[exact entity filter, pairing, and validation steps](docs/matter.md). An existing
Python Matter Server alone is a controller, not an HA entity-export bridge.
For this route say **"Hey Google, turn on Energy status report."** The cloud
linking, scene exposure, and sync instructions below do not apply to Matter.

**Cloud scenes: choose one provider if using this route.**

- **Home Assistant Cloud by Nabu Casa — optional paid service.** It requires a
  subscription after its trial. In HA, set up Cloud, enable Google Assistant
  under **Settings → Voice assistants**, and expose the report entities on the
  **Expose** tab. In Google Home, open **Works with Google Home**, choose
  **Home Assistant Cloud by Nabu Casa**, and sign in. Follow the
  [official Cloud setup](https://support.nabucasa.com/hc/en-us/articles/25619376817053-Google-Assistant)
  and [subscription information](https://www.home-assistant.io/integrations/google_assistant/#automatic-setup-via-home-assistant-cloud).
- **Manual Home Assistant Google Assistant integration — no Home Assistant Cloud
  subscription.** This requires an externally reachable HA HTTPS address and
  your own Google Home Developer Console Cloud-to-cloud project with account
  linking. An HTTPS address or Cloudflare Tunnel alone does not create that link.
  Follow the
  [complete official manual setup](https://www.home-assistant.io/integrations/google_assistant/#manual-setup-if-you-dont-have-home-assistant-cloud)
  for account linking and YAML configuration. In Google Home's **Works with
  Google Home** list, choose your **[test]** project and sign in to HA. Hosting
  and domain costs, if any, are separate.
- **An existing Homeway link.** Homeway currently lists Google Assistant access
  as a [paid Supporter feature](https://homeway.io/assistant); its free remote
  access does not imply free voice integration. If you already use it, follow
  [Homeway's Google setup](https://help.homeway.io/help-docs/home-assistant/google-home-and-alexa/google-home-integration):
  configure its HA add-on or [manual alternative](https://help.homeway.io/help-docs/home-assistant/google-home-and-alexa/manual-setup-guide),
  open Google Home's **Works with Google** settings, select **Homeway**, and
  sign in. Use Homeway's
  Assistant Device Control to select the report scripts.

Google Home menu labels vary by app version: **Works with Google Home** is
available in the add-device flow or Home settings. Use the Google account and
Home that contain the Nest you will speak to.

For the cloud route, expose these five adapter entities, keeping their generated names:

- `script.igw_google_battery` — **Battery report**.
- `script.igw_google_solar` — **Solar power report**.
- `script.igw_google_solar_today` — **Solar today report**.
- `script.igw_google_status` — **Energy status report**.
- `script.igw_announce_alarms` — **Energy alarms report**.

Keep `script.igw_google_energy_dispatch` unexposed. Preserve existing exposure
for other household devices. For manual YAML, merge these entities with
`expose: true` and the dispatcher with `expose: false` into the existing
`google_assistant.entity_config`; keep its account configuration and exposure
policy. See [the merge example](docs/routines.md#manual-yaml-exposure).

Assign the scripts to an HA area and the corresponding Google room, then say
**"Hey Google, sync my devices."** Scripts appear to Google as scenes and may
not have dashboard tiles. Room assignment matters for access by other household
members; see [HA's room guidance](https://www.home-assistant.io/integrations/google_assistant/#roomarea-support).

## Use the reports

After [Matter setup](docs/matter.md), say these English commands:

- **"Hey Google, turn on Battery report."**
- **"Hey Google, turn on Solar power report."**
- **"Hey Google, turn on Solar today report."**
- **"Hey Google, turn on Energy status report."**
- **"Hey Google, turn on Energy alarms report."**

For the cloud scene route, after account linking, exposure, and sync, use:

- **"Hey Google, activate Battery report."**
- **"Hey Google, activate Solar power report."**
- **"Hey Google, activate Solar today report."**
- **"Hey Google, activate Energy status report."**
- **"Hey Google, activate Energy alarms report."**

Use the corresponding report name if you renamed it in Google. Each command
fetches a current IGW report and plays it on the **fixed Nest selected when
rendering the configuration**. Speaking to another Nest does not change the
output speaker. The commands only read reports; they do not control the inverter.

For the shorter Matter command **"Hey Google, turn on Energy"**, set the display
name of `script.igw_google_status` to **Energy** in HA while keeping its entity
ID unchanged. Follow the [short-name setup and verification](docs/matter.md#use-a-shorter-name).
This direct command needs no Google routine. The bare phrase **"Hey Google,
energy"** requires a routine with that voice starter.

For shorter phrases, optionally create a Google Home automation/routine with a
voice starter such as **"battery status"**, and an action turning on the Matter
device **Battery report** or activating the cloud scene of that name. Repeat with
**"solar power"**, **"solar today"**, **"energy status"**, and **"energy alarms"**
for their matching reports. Where a custom Assistant
action is available, use the direct command you verified in your installation,
such as **"turn on Battery report"** for Matter. The short phrases work only after you create these routines; they are
not registered automatically. See [routine details](docs/routines.md) and
[Google's automation setup](https://support.google.com/googlehome/answer/16214649?hl=en).

## Troubleshooting

- **Google cannot find a report:** for Matter, check the bridge's exact entity
  filter, live connection to Google, and report devices in the intended Home;
  test "turn on Energy status report". See [Matter diagnostics](docs/matter.md#verify-the-complete-path).
  For cloud scenes, confirm the account link, script exposure, names and room,
  then sync again and test "activate Energy status report". An absent cloud
  scene dashboard tile alone does not indicate failure.
- **It works for one person only:** check Google Home membership and room
  assignment. Manual Google projects also require the
  [additional-user setup](https://www.home-assistant.io/integrations/google_assistant/#allow-other-users).
- **Google responds but no report plays:** call the wrapper in HA's Actions tool.
  For standalone Cast, follow [its playback checks](docs/standalone-cast.md#verification-and-rollback).
  For the original speech adapter, test `tts.speak` with the selected provider
  and speaker and check that Cast can retrieve HA's audio URL. Listen to the
  configured output device.
- **A connection-error sentence plays:** verify the IGW URL, scoped token, direct
  HTTP 200 JSON response, and clock synchronization. A spoken stale/unavailable
  warning instead comes from IGW; investigate the gateway's data sources.
- **Google integration fails to load:** inspect its setup error and follow the
  chosen provider's instructions. Manual linking requires its YAML configuration
  as well as the Google project; importing this adapter does not create either.

Use [the smoke tests](docs/testing.md) to distinguish API, speech, and Google
voice-route failures. Keep credentials and private diagnostics outside Git.

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
Google routing through Matter or account linking, actual gateway access, and
audible Nest playback require
the installation smoke tests in [docs/testing.md](docs/testing.md).

See [the anonymized validation record](docs/deployment-validation.md) for the
verified scope and the remaining physical voice checks. A successful
Cast action alone does not establish human audibility or Google microphone access.

License: MIT.
