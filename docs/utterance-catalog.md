# Report phrases

- "Hey Google, battery status" → Routine activates **Battery report** →
  `script.igw_google_battery` → IGW `reports.battery.text`.
- "Hey Google, solar power" → Routine activates **Solar power report** →
  `script.igw_google_solar` → IGW `reports.solar.text`.
- "Hey Google, solar today" → Routine activates **Solar today report** →
  `script.igw_google_solar_today` → IGW `reports.solar_today.text`.
- "Hey Google, energy status" → Routine activates **Energy status report** →
  `script.igw_google_status` → IGW `reports.status.text`.

- "Hey Google, energy alarms" → Routine activates **Energy alarms report** →
  `script.igw_announce_alarms` → IGW `reports.alarms.text`.

For a direct test without a Routine, say "Hey Google, activate Battery report"
or substitute another scene name. These phrases only work after linking,
exposure, room assignment, device sync, and (for the short forms) creating the
Routine. The repository cannot create Google account settings on your behalf.

All five paths read IGW. They never change charge settings, loads, relays,
thermostats, or inverter configuration.
