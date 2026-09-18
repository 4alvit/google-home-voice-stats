# Google voice reports through Matter

Use Home Assistant Matter Hub to expose the five public report scripts to
Google Home. This route requires no Homeway or Nabu Casa subscription and no
public HA URL. Google voice recognition still depends on Google's services.

The standalone path is **Google command → Matter bridge → HA script → local
Cast service → configured display**. IGW remains the source of energy reports.
Matter carries the trigger; the existing Cast service supplies speech and the
dashboard video. The original HA adapter instead supplies speech through HA TTS.
Matter does not make energy statistics or a dashboard queryable by Google.

## Prerequisites

- A working [standalone Cast service and optional HA trigger](standalone-cast.md),
  or the original HA speech adapter. Test `script.igw_google_status` directly in
  HA first.
- The maintained [RiDDiX Home Assistant Matter Hub](https://riddix.github.io/home-assistant-matter-hub/)
  connected to HA. Version 2.0.56 was used for this installation. The separate
  Python Matter Server used by HA is a Matter controller; it does not by itself
  export HA entities to Google.
- A [compatible Google Matter hub](https://support.google.com/googlehome/answer/12391458)
  in the same Google Home as the microphone device. Google Home Mini is one
  supported Matter-over-Wi-Fi hub. The Cast display itself need not be the hub.
- Working local Matter networking between the bridge and the Google hub,
  including the IPv6/mDNS connectivity required by your deployment. Preserve a
  working network setup; do not change Kubernetes networking merely to match an
  example manifest.

## Add only the public scripts

1. Back up the bridge configuration and persistent Matter storage privately.
   Storage contains pairing identities and credentials; restrict its permissions
   and keep it out of Git. Record existing endpoints so you can check preservation.
2. Open the existing bridge in Matter Hub. Preserve its name, port, existing
   include/exclude rules, pairing identity and fabrics. Do not replace or
   reset/re-pair an already working bridge. If this is a new installation with
   no bridge, [create an initial bridge](https://riddix.github.io/home-assistant-matter-hub/getting-started/bridge-configuration)
   using only the filter below and keep it unpaired until its endpoints are
   verified. No broad default domain exposure is needed.
3. **Append** the following rules to the corresponding filter lists. This is a
   fragment to merge, not a replacement bridge configuration. Exact `pattern`
   values without wildcards select only the named entities. If an existing
   exclusion matches one of these scripts, resolve that specific conflict
   without broadly removing exclusions.

   ```json
   {
     "include": [
       {"type": "pattern", "value": "script.igw_google_battery"},
       {"type": "pattern", "value": "script.igw_google_solar"},
       {"type": "pattern", "value": "script.igw_google_solar_today"},
       {"type": "pattern", "value": "script.igw_google_status"},
       {"type": "pattern", "value": "script.igw_announce_alarms"}
     ],
     "exclude": [
       {"type": "pattern", "value": "script.igw_google_energy_dispatch"}
     ]
   }
   ```

   Keep the parameterized dispatcher private. Do not expose the whole script
   domain. See the upstream [bridge filter reference](https://riddix.github.io/home-assistant-matter-hub/getting-started/bridge-configuration).
4. Save through Matter Hub's supported configuration interface and confirm the
   original endpoints remain alongside the five new reports. On the verified
   version, an update to a healthy bridge refreshes endpoints without restarting
   it. Do not edit its running storage files by hand.
5. If the bridge is not yet paired to Google, use Google Home's Matter setup
   with a pairing code obtained privately from Matter Hub. Pair it to the Home
   containing the intended microphone and Google hub. For an already paired
   bridge, allow Google to discover the added endpoints; do not reset pairing
   just because discovery is delayed.
6. In Google Home, confirm **Battery report**, **Solar power report**, **Solar
   today report**, **Energy status report**, and **Energy alarms report**. Assign
   suitable rooms and keep these names unique. Avoid exposing the same reports
   through a cloud integration as well.

Matter Hub maps HA scripts to [`OnOffPlugInUnit` devices](https://riddix.github.io/home-assistant-matter-hub/supported-device-types),
which [Google supports](https://developers.home.google.com/matter/supported-devices).
An on command runs the script; the endpoint reports off again rather than
representing a persistent power state. An off command does not cancel playback.
The plug icon is a consequence of this trigger mapping, not a physical outlet.

## Use the reports

Say **"Hey Google, turn on Energy status report."** Substitute **Battery
report**, **Solar power report**, **Solar today report**, or **Energy alarms
report** for another report. Use `turn on` for these Matter endpoints; the
cloud-scene verb `activate` is a different route.

For **"Hey Google, energy status"**, create a Google Home routine with that
voice starter and an action turning on **Energy status report**. The repository
does not create routines in your account. See [routine setup](routines.md).

Every report plays on the output selected in the Cast service (or original HA
speech adapter), regardless of which microphone hears the request. Request one
report at a time; the standalone service rejects a concurrent request as busy.

## Verify the complete path

1. Check that the bridge is running, all original endpoints remain, and exactly
   the five intended reports were added. A saved Google fabric proves prior
   commissioning, not a current connection or discovery by Google.
2. Check Google Home's report controls. Turning on **Energy status report**
   should change the HA wrapper's `last_triggered` timestamp. For Matter, cloud
   scene exposure settings and "sync my devices" are not substitutes for
   checking bridge discovery and connectivity.
3. For standalone output, confirm the corresponding new request reaches the Cast service, its exact
   temporary media URL reaches `PLAYING` on the selected receiver, playback time
   advances, and the service records `report_played`. HTTP 202 or a script
   returning to idle proves only request acceptance. A stale/unavailable IGW
   report may still play successfully; also check the report's data status.
   For the original HA speech adapter, follow its [HA/TTS/Cast checks](testing.md#original-ha-speech-adapter)
   instead; that mode has no standalone service or `report_played` result.
4. Speak the direct command to the intended device and confirm the screen and
   sound physically. Repeat the five reports and any routines you configured.
   An SDK-issued command can test routing for its own Google account, but cannot
   prove microphone recognition or access for another household member. The
   HA Google Assistant SDK's empty text response is not success evidence, and
   it cannot invoke Google Home routines; see its [documented limitations](https://www.home-assistant.io/integrations/google_assistant_sdk/).

If no new HA trigger appears, investigate Google Home membership, endpoint names,
discovery and Matter connectivity. If HA runs but playback fails, diagnose the
[standalone Cast path](standalone-cast.md#verification-and-rollback) or the
[original HA speech path](testing.md#original-ha-speech-adapter). Do not restart or reset
the bridge simply because an SDK request completed without a report.

## Rollback

Remove only the five added include rules through the supported bridge interface,
or restore the previous filter. Keep unrelated endpoints, bridge identity and
fabrics intact. A dispatcher exclusion may remain as a safety measure unless it
conflicts with your original policy. No HA script deletion, Cast service removal,
Google account unlinking or bridge factory reset is needed to undo this exposure.
