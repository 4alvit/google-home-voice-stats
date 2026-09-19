# Report phrases

For Matter, say **"Hey Google, turn on Energy status report"**. Substitute any
of the five report names below. For cloud scenes, use **"Hey Google, activate
Energy status report"** instead. Test the direct command for your route before
adding shorter routine phrases.

After the optional [HA display-name override](matter.md#use-a-shorter-name), the
direct Matter command is **"Hey Google, turn on Energy"**. It invokes
`script.igw_google_status` without a routine. The bare phrase **"Hey Google,
energy"** still requires a routine.

Optional routines map these voice starters to the corresponding report. Their
action turns on the Matter device or activates the cloud scene:

- "Hey Google, battery status" → **Battery report** →
  `script.igw_google_battery` → IGW `reports.battery.text`.
- "Hey Google, solar power" → **Solar power report** →
  `script.igw_google_solar` → IGW `reports.solar.text`.
- "Hey Google, solar today" → **Solar today report** →
  `script.igw_google_solar_today` → IGW `reports.solar_today.text`.
- "Hey Google, energy status" → **Energy status report** →
  `script.igw_google_status` → IGW `reports.status.text`.

- "Hey Google, energy alarms" → **Energy alarms report** →
  `script.igw_announce_alarms` → IGW `reports.alarms.text`.

These phrases require either [Matter setup](matter.md) or cloud account linking
and scene exposure. The routine voice starters listed above additionally require
creating the routine; the renamed direct Matter command does not.
The repository does not create Google account settings or routines on your behalf.

All five paths read IGW. They never change charge settings, loads, relays,
thermostats, or inverter configuration.

## Optional flow report

After generating the HA package with `--include-flow`, configuring IGW flow
sources, and exposing `script.igw_google_flow` through the existing route:

- Matter: "Hey Google, turn on Energy flow report."
- Cloud scene: "Hey Google, activate Energy flow report."

The response explains configured consumption, grid import/export, and battery
charging/discharging. The default five scripts stay unchanged. A bare phrase
still requires your own Routine; this is not a conversational Google Action.
