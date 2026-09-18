# Report phrases

For Matter, say **"Hey Google, turn on Energy status report"**. Substitute any
of the five report names below. For cloud scenes, use **"Hey Google, activate
Energy status report"** instead. Test the direct command for your route before
adding shorter routine phrases.

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
and scene exposure. Short forms additionally require creating the routine.
The repository does not create Google account settings or routines on your behalf.

All five paths read IGW. They never change charge settings, loads, relays,
thermostats, or inverter configuration.
