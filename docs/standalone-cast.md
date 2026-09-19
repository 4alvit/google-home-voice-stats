# Standalone Cast display and speech

The service reads IGW and plays a short dashboard snapshot on one configured Cast
display. Home Assistant is optional. A Linux host on the display's LAN, such as a
NAS or small server, runs the service; do not install the renderer on a Cerbo GX.

Data flow: **IGW read API → local renderer → Google default media receiver**.
An optional voice trigger adds **Google → Matter bridge or cloud scene → HA →
authenticated local POST**.
IGW remains responsible for measurements, units, freshness and report wording.

## What the display shows

The status report shows battery, solar power, today's solar energy and alarms.
Individual reports show one larger card. Every card retains IGW's freshness
status. Validated numeric measurements add large battery charge, solar power and
today's generation values. Missing or invalid optional numbers stay absent, and
stale/unavailable values never become zero or a current measurement. The gateway
receipt age is shown when supplied; it is not sensor measurement time or the
`generated_at` envelope timestamp. Age labels are fixed for this video snapshot.

Status speech uses IGW's optional `reports.status.brief_text`; older gateways fall
back to the full `text`. Other reports speak the full central text. The screen
continues to show the full report wording and paginates long warnings. eSpeak NG
is the default offline voice; [optional local Piper](local-speech.md) adds a neural
voice with bounded synthesis and eSpeak fallback. Neither voice uses Google's
cloud TTS service.

The output is a 1280×720 H.264/AAC MP4 snapshot, not a live or interactive dashboard.
It remains visible through the speech and a short reading interval, then normal
Cast playback ends. Each request fetches new data. There is no continuous polling
or always-on display. Playback can replace the display's current media; device
volume is left unchanged.

Google documents H.264 at 720p for [Nest Hub and Nest Hub Max](https://developers.google.com/cast/docs/media).
Other Cast displays need a real-device playback check. Audio-only Google speakers
should continue using the original HA speech adapter; this service sends video.

The [default media receiver](https://developers.google.com/cast/docs/web_receiver#default_media_web_receiver)
does not require developer registration. This design adds no Google Cast
registration fee, paid TTS API, Cloudflare plan change or hosted voice subscription.
Existing electricity, hardware and network costs remain. It does not create a
custom conversational Action or make the project eligible for a Google store listing.

## Install on a Linux Docker host

1. Clone the repository on the host and copy `.env.example` to `.env`.
   Run `chmod 600 .env` before adding credentials. Keep the file outside Git.
2. Set `IGW_URL` and `IGW_READ_TOKEN` for an existing read-only IGW endpoint.
   Use a directly responding HTTPS URL ending in `/v1/energy`. If its existing
   Cloudflare Access policy requires service credentials, set both optional
   `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET`. Redirects are rejected,
   certificate verification is enabled, and environment HTTP proxies are ignored.
   An explicitly trusted private HTTP route requires `IGW_ALLOW_LOCAL_HTTP=true`;
   never send Cloudflare service credentials over HTTP.
3. Set `CAST_HOST` to the display's private IP and `CAST_UUID` to its Cast UUID.
   These identify the fixed playback target. Obtain them from existing Cast device
   information or a local [PyChromecast discovery](https://github.com/home-assistant-libs/pychromecast#how-to-use).
   Reserve the display's address in DHCP. The API cannot override the target.
4. Set `CAST_MEDIA_BASE_URL` to the Docker host's reachable private IPv4 address,
   for example `http://192.168.50.10:8091`. Set `CAST_BIND_HOST` to that same local
   interface and `CAST_PORT` to its port. Nest must retrieve media from this address.
   Host networking requires a Linux Docker host; the service is not designed for
   Docker Desktop's isolated default network.
5. Generate a separate `CAST_API_TOKEN`, for example with
   `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`.
   Use at least 32 characters. This authorizes playback only; it is not the IGW token.
6. Choose one available logical CPU with `CAST_CPUSET` (default `0`). CPU affinity
   works on NAS kernels that lack Docker CPU CFS quotas. Check
   `docker info --format '{{.CPUSet}} {{.PidsLimit}} {{.MemoryLimit}}'`.
   If the PIDs controller is unavailable, set `CAST_PIDS_LIMIT=0`; otherwise keep
   the default limit of 96. HTTP concurrency and report subprocesses remain bounded
   by the application, but a kernel without this controller cannot enforce a
   container-wide PIDs cap. Memory limits and CPU affinity must be supported.
7. Build and start:

   ```bash
   docker compose -f compose.cast.yaml build
   docker compose -f compose.cast.yaml up -d
   docker compose -f compose.cast.yaml ps
   ```

The container runs without root, with a read-only filesystem, dropped capabilities,
one CPU and a 384 MiB memory limit. The limits are deployment bounds, not measured
resource usage. Temporary media uses a 128 MiB memory-backed directory. No database,
MQTT consumer, browser engine or cloud speech service is needed.

The listener belongs on a trusted home LAN. Do not publish it through a tunnel or
router port forward. HTTP carries the playback token and media on that LAN.
The standalone service needs outbound HTTPS to IGW and local connectivity to the
display on Cast port 8009; the display needs inbound access to the media port.

## Call the service without HA

Provide the token through your shell's private environment, not a pasted literal
in shell history. For example, after setting `CAST_API_TOKEN` securely:

```bash
curl --fail-with-body --request POST \
  --header "Authorization: Bearer $CAST_API_TOKEN" \
  http://192.168.50.10:8091/v1/reports/status
```

No request body is accepted. Supported paths end in `battery`, `solar`,
`solar_today`, `status`, `alarms` or `flow`. `202` means the request was accepted for
processing, not that playback succeeded. `409` means a report is already running;
wait instead of repeatedly interrupting the display.

Authenticated `GET /v1/status` returns `running`/`idle` and a fixed result category.
`report_played` means the Cast receiver reported playback of this request's media;
it is not proof of human audibility or a visual inspection. `fallback_played`
means the connection-error report played. Failures have fixed categories without
URLs, device IDs, credentials or report text. `GET /healthz` checks that the service
is responding; it does not check IGW, the network or the display.

Gateway fetches have a total 12-second deadline, including stuck DNS or slow reads.
One retry is allowed for HTTP 502/503/504, temporary DNS failure, a timeout or a
reset connection, within that same deadline. Authentication/authorization,
redirects, TLS verification, rate limits and invalid JSON are never retried.
Old envelopes and contradictory fresh/disconnected reports are rejected. A gateway
failure produces an unavailable message instead of zero measurements. Rendering
and playback are bounded, and only one report is processed at a time.

Media URLs contain random, short-lived access capabilities because Cast cannot
attach the API authorization header. They expire after three minutes. Paths are
not logged; temporary files are removed on expiry and container removal. Do not
share a media URL. The service supports HEAD and byte ranges for Cast playback.

## Optional flow report

`POST /v1/reports/flow` speaks the authoritative IGW flow report and shows the
configured consumption, grid and battery power alongside the full report text.
The IGW contract defines positive grid power as import and negative as export;
positive battery power means charging and negative means discharging. This is
read-only reporting, not inverter control. Configure the exact sources centrally
in IGW; the adapter does not guess meters, infer whole-home coverage or reconstruct
flows by subtracting unrelated measurements.

An older IGW response without `reports.flow` produces a useful "not configured"
report. Existing battery/solar/status reports continue to work. Missing flow
measurements stay absent, not zero. To add a sixth public script deliberately,
pass `--include-flow` to `igw-cast-ha` (or to the original
`igw-google-voice render-config` generator), then expose only
`script.igw_google_flow` in addition to the existing five scripts. Default generated
configuration keeps the existing scripts and Matter endpoint identities unchanged.
Preserve your HA entity-name override such as `Energy`. Say "Hey Google, turn on
Energy flow report" through Matter, or use the equivalent cloud scene command.
Adding the script alone does not configure IGW sources or establish Google routing.

## Optional existing Google voice commands

Use an existing Matter bridge paired to Google Home, or a working Google-to-HA
cloud account link. The standalone service does not establish either route or
add direct Google voice command handling. See the [subscription-free Matter
setup](matter.md) for exact script exposure and prerequisites.

Render the smaller HA package:

```bash
python3 -m igw_google_voice.cast_ha \
  --service-url http://192.168.50.10:8091 \
  --output ./rendered-cast-trigger
```

Back up the existing HA package and secrets first. Read the generated `INSTALL.md`,
replace the old `packages/igw_google_voice.yaml` with the new file, and merge
`igw_cast_authorization` into `secrets.yaml` as `Bearer ` followed by the service
API token. Do not install both packages under different filenames: their script
IDs intentionally match. Preserve existing unrelated HA settings and secrets.

Validate the complete HA configuration and restart/reload through the normal HA
procedure. The generated package disables stored script traces and keeps REST
logging at warning level because HA DEBUG logs can include credentials. It needs
neither the IGW token nor a TTS provider. Keep existing report entity IDs and
names. With Matter, say **"Hey Google, turn on Energy status report"**, or
substitute another report name. With cloud scene exposure, use:

- "Hey Google, activate Battery report."
- "Hey Google, activate Solar power report."
- "Hey Google, activate Solar today report."
- "Hey Google, activate Energy status report."
- "Hey Google, activate Energy alarms report."

An installation with the `logger.set_level`, `rest_command.reload` and
`script.reload` actions can load this replacement without restarting all of HA.
After backing up and validating the complete configuration, call
`logger.set_level` with `homeassistant.components.rest_command: warning`, then
`rest_command.reload` and `script.reload`. The logger action applies the privacy
setting to the running process; the generated package preserves it across
restarts. Verify that `rest_command.igw_cast_report` and all five report scripts
are present before invoking `script.igw_google_status`. Do not treat a successful
reload or HTTP 202 as playback proof: check that this invocation transitions the
Cast service through `running` to `idle` with result `report_played`, and confirm
cards and speech on the selected display. If the required reload actions are
unavailable, use HA's normal validated restart procedure.

All requests go to the configured display, regardless of which microphone hears
the command. A short phrase such as "energy status" still needs a Google Routine.
See [Matter or cloud setup](../README.md#link-google-and-expose-the-report-scenes).
Existing HA exposure or Matter commissioning alone does not prove that Google's
microphone route works.

## Verification and rollback

Run `python3 -m pip install '.[test,cast]'` and `python3 -m unittest discover -s tests -v`.
The full media tests require `ffmpeg`, `ffprobe`, `espeak-ng` and DejaVu fonts.
CI installs them. Synthetic tests do not contact IGW or play on a Cast device.

Before switching voice commands, verify the actual IGW endpoint, a generated
video's codecs and duration, then one real display invocation. Confirm cards and
speech on the device. Also test an unavailable gateway and a second request while
one is running. Preserve the existing HA speech package until acceptance.

To roll back, stop only this service with `docker compose -f compose.cast.yaml down`
and restore the backed-up HA package if it was changed. The service does not modify
IGW, Google account linking, other containers, inverter settings, or Cloudflare.
Keep detailed installation receipts private and publish only anonymized outcomes.
