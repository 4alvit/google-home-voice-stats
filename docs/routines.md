# Google Home phrases and Home Assistant scripts

The adapter exposes five public HA scripts. Either a Matter on command or a
cloud scene activation starts a wrapper without parameters. The wrapper passes
a fixed report key to the private dispatcher. There is no public webhook and no
need to put an IGW token into a Google routine.

## Matter route

1. Complete the [Matter setup](matter.md) and confirm the five report devices
   appear in the intended Google Home. Keep the dispatcher unexposed.
2. Try **"Hey Google, turn on Battery report"** before creating a routine.
   Confirm both the HA script invocation and playback on the selected display.
3. Create a Google Home automation/routine with the voice starter **"battery
   status"**. Choose a device action that turns on **Battery report**. If only a
   custom Assistant action is available, use the verified direct command
   **"turn on Battery report"**. Available actions vary by app and account.
4. Repeat for **"solar power"**, **"solar today"**, **"energy status"**, and
   **"energy alarms"**, choosing the matching device in the
   [report catalog](utterance-catalog.md). Check intended household members can
   use the reports.

Matter does not require cloud scene exposure or an HA-to-Google account link.
Use one route per report to avoid duplicate names.

## Cloud scene route

1. Complete one of the [account-linking routes in the README](../README.md#link-google-and-expose-the-report-scenes).
   This adapter has no standalone Google skill or store listing.
2. Use your chosen provider's exposure controls to expose these five entities
   (the HA **Expose** tab for Cloud, Homeway's Assistant Device Control, or
   explicit YAML for manual integration):
   `script.igw_google_battery`, `script.igw_google_solar`,
   `script.igw_google_solar_today`, `script.igw_google_status`, and
   `script.igw_announce_alarms`. Keep the
   dispatcher private. For manual integration, merge explicit `entity_config`
   entries with `expose: true` into the existing `google_assistant` configuration;
   preserve the existing exposure policy and account-linking configuration.
   The [merge example below](#manual-yaml-exposure) adds only adapter entries.
3. Assign the report scripts to an HA area and the matching Google room. HA's
   documentation notes that scripts/scenes without rooms can be inaccessible to
   other household members. Scene entities may not appear as ordinary controls
   on Google's main dashboard.
4. Say "Hey Google, sync my devices." First try "Hey Google, activate Battery
   report" to verify that the exposed scene works before adding a custom phrase.
5. In Google Home, create an automation/routine with a voice starter such as
   "battery status". Select the corresponding report scene under home/device
   actions when offered. If your app offers a custom Assistant action, use the
   direct command you verified in your installation, such as "activate Battery
   report", there. Google UI labels and available
   actions vary by account and app version; direct scene activation is the
   baseline test. Do not add a URL/webhook action or credentials.
6. Repeat for "solar power", "solar today", "energy status", and "energy alarms", choosing the
   matching scene from [utterance-catalog.md](utterance-catalog.md).

Both routes cause a fresh API request. The response plays on the display
configured in the standalone Cast service, or the Nest selected in the original
HA speech blueprint, regardless of which microphone hears the request. IGW's
unavailable or stale warning is preserved in the report.

These triggers request reports. Generic "what is the
battery sensor" queries are not the supported path: Google does not expose all
HA sensor classes as queryable sensors. See
[HA's supported domains](https://www.home-assistant.io/integrations/google_assistant/#available-domains).

## Manual YAML exposure

For HA's manual Google integration, merge the entries below **inside the existing
`google_assistant.entity_config` mapping**. They are not a replacement for the
whole integration. Preserve existing entries, project/service-account settings,
and exposure defaults. These IDs belong to the adapter, not to physical devices.

```yaml
script.igw_google_battery:
  expose: true
  name: Battery report
script.igw_google_solar:
  expose: true
  name: Solar power report
script.igw_google_solar_today:
  expose: true
  name: Solar today report
script.igw_google_status:
  expose: true
  name: Energy status report
script.igw_announce_alarms:
  expose: true
  name: Energy alarms report
script.igw_google_energy_dispatch:
  expose: false
```

Check HA configuration, restart to load YAML changes, and sync Google devices.
Cloud and Homeway users should use their provider's exposure controls instead
of adding a second manual integration. See
[HA's entity configuration reference](https://www.home-assistant.io/integrations/google_assistant/#yaml-configuration).
