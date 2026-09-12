# Anonymized deployment validation

This record preserves the verified scope without installation identifiers,
addresses, private paths, telemetry, or timestamps. It does not replace the
[smoke tests for a new installation](testing.md).

## Completed checks

- The generated package and blueprint passed an isolated HA configuration check.
  A full installed-configuration check also passed, with pre-existing warnings
  and no new validation failure from the adapter.
- HA completed startup, and the adapter scripts, Google integration, Cast, and
  TTS provider loaded. An intermediate startup state did not represent a final
  startup failure.
- The installed REST command successfully fetched an authenticated IGW response
  containing all five report keys. This verified the HA-to-IGW read path.
- A real battery-report script action completed, and the selected Cast device
  accepted and played the generated audio. This is observed Cast playback;
  human audibility was not observed.
- All 21 automated adapter tests passed. Workflow lint, whitespace checks, wheel
  installation, and rendering outside the checkout passed. CI also validated an
  isolated HA configuration.

## Not established by those checks

Physical Google microphone commands, household account routing, and a real
Google-initiated device sync remain unverified. A loaded integration and exposed
scripts alone do not prove the complete Google-to-HA voice path. Playback of one
report also does not establish audible output for every report.

For a new installation, test all five direct phrases in the README, any custom
routines, and another intended household member after account linking and room
assignment. Confirm the report is audible on the configured output speaker.
Keep detailed operational evidence privately; publish only anonymized outcomes.
