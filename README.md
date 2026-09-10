# Google Home ↔ Home Assistant voice stats

Portable patterns so **Google Home / Nest / Google Assistant** can drive home **changes** and speak **statistics**, with Home Assistant (or Matter) as the hub.

> Google is the microphone. HA owns devices and sensors. Keep Google Cloud projects, OAuth clients, and household entity ids out of this repo.

## Architecture

1. **Hub**: Home Assistant (preferred), or Matter/Thread devices Google already supports
2. **Link** (preferred order):
   - HA Cloud (Nabu Casa) Google Assistant integration
   - Google Home ↔ Matter commission
   - Avoid duplicate clouds when HA is source of truth
3. **Stats**: expose clear sensors; for richer answers use HA scripts + Nest/TTS, or Google Routines → authenticated webhook / script

## Quick start

1. Expose lights/switches/climate/scenes with speakable names; assign rooms in Google Home.
2. Sync devices after exposing new entities.
3. For questions Google cannot answer natively (“how much solar today”), use a Routine → HA script that speaks via Nest/TTS.
4. Default-deny locks, alarms, garage unless explicitly opted in.
5. Test one control + one stats path on a real speaker.

## Patterns in this repo

| Path | Purpose |
|------|---------|
| `patterns/helpers/speakable_sensors.yaml` | Template sensors for voice questions |
| `patterns/scripts/announce_stat.yaml` | Script skeleton (Nest / Google TTS) |
| `docs/utterance-catalog.md` | Example say → does table |
| `docs/routines.md` | Routine → script wiring notes |

## Safety

- Opt-in list for voice; confirm before enabling setpoint-changing scripts.
- Webhooks for Routines must authenticate; no open URLs.

## License

MIT
