# Installation smoke tests

Run offline tests and HA's configuration check before activating this package.
Offline tests are not evidence of actual audio or Google account linking.

See the [anonymized validation record](deployment-validation.md) for completed
checks and their limits. Run this checklist for your own installation.

1. Verify the selected Nest entity and TTS provider with a short `tts.speak`
   action. Set `target.entity_id` to the `tts.*` entity and
   `data.media_player_entity_id` to the Cast `media_player.*` entity.
2. After installing the package and restarting HA, call each of the five wrapper
   scripts in the HA Actions tool. Check that battery, solar power, solar today,
   status, and alarms speak the corresponding centrally generated report.
3. Issue two different report requests quickly. They should execute through the
   shared queue, fetching when each run begins, and speak in order. Playback
   waiting is bounded; check the selected Nest's state reporting if they overlap.
4. Test each exposed scene directly through Google, then each configured Routine.
   Repeat with another household member to verify room assignment and access.
5. Use a separate staging IGW endpoint/HA configuration for failures: return 401,
   403, 503, an HTML login page, a malformed envelope, or an old `generated_at`.
   The adapter should speak its fallback sentence. A request timeout also falls
   back. Do not invalidate production tokens or disconnect home systems for this
   test.
6. In staging, return recent envelopes with `stale`, `unavailable`, and
   `unconfigured` report text. Verify that IGW's warning is spoken and no numeric
   zero is fabricated by HA.

Keep a private deployment record with software versions and which checks passed.
Keep timestamps, hostnames, namespaces, paths, physical device/entity IDs,
telemetry, and credentials out of public records. Do not publish full request
headers. Keep REST command logging at WARNING or higher: its DEBUG logging
contains authentication headers. The scripts disable stored traces; temporarily
enabling traces exposes report data, and is not required for the tests above.

For Container/Core configuration validation, run inside the actual HA runtime:

```bash
python -m homeassistant --script check_config --config /config
```

The `tests/make_ha_fixture.py` helper writes a disposable offline configuration
with fake credentials. Its `check_config` run validates HA syntax, blueprint
expansion, and REST configuration without executing any report script.
