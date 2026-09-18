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

## Standalone Cast adapter

The standalone runtime has been built on a Linux NAS and exercised separately
from the existing HA speech installation. Its authenticated IGW read returned
fresh reports. Offline eSpeak NG and ffmpeg generated an H.264/AAC 1280x720
snapshot within the configured 30-second envelope age limit. The disposable
runtime used one CPU, a 384 MiB memory limit and a 128 MiB temporary filesystem.
The generated household media was removed with that temporary container.

This runtime required CPU affinity because its kernel did not support CPU CFS
quotas. A disabled PIDs limit was also verified for its missing PIDs controller;
the portable Compose settings and setup guide describe those options. Generic
Compose configuration validation passed without starting a playback service.

The expanded 54-test suite covers gateway validation, an actual slow response,
authentication, concurrent request rejection, expiring byte-range media delivery,
offline speech/video generation, private diagnostics and both HA package modes.
Both HA packages passed isolated configuration checks with HA 2026.9.2.

No reachable display was available for physical playback acceptance. Only the
container images and source package were staged: a target-specific service was
not started, and existing HA voice routing was retained. Cast screen appearance,
audibility and Google microphone invocation remain unverified. A valid MP4,
passing tests and a successful IGW fetch do not establish those device checks.
