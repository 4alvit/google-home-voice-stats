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
routines, and another intended household member after Matter setup or cloud
account linking and room assignment. Confirm the report is audible on the
configured output speaker.
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

The merged runtime was subsequently installed as a private-LAN service targeting
one Lenovo Smart Display 10. Its identity matched the existing device registry.
The service passed its health check, and all pre-existing containers remained
unchanged. The display retrieved the generated media from the NAS and reported
`PLAYING` for that request's exact media URL. The service completed with
`report_played`, rather than its connection-error fallback. This verifies actual
receiver playback of an IGW report, beyond MP4 generation or request acceptance.
The live API rejected unauthenticated requests with HTTP 401 and a concurrent
report request with HTTP 409, without starting another playback.

The optional HA trigger was installed after standalone playback succeeded. Full
installed-configuration checks passed before and after the replacement. REST
commands and scripts were reloaded without restarting HA, and REST logging was
set to warning in the running process. All five report names, entity-registry
settings and unrelated configuration files were preserved. HA stores only a
separate local playback token for this trigger; the independent service handles
the authenticated IGW read, rendering and Cast playback.

Invoking the public `script.igw_google_status` then exercised the HA dispatcher
and local REST command. An independent observer saw the new request's exact
media URL reach `PLAYING` on the display, with advancing playback time. The
service again completed with `report_played` and no gateway fallback. The
observer issued no playback commands of its own.

Receiver protocol status does not establish physical screen appearance or human
audibility. Those checks and Google microphone invocation require confirmation
on the device. Detailed identifiers, credentials and household media are not
part of this public validation record.

## Google reports through Matter

The existing Home Assistant Matter Hub 2.0.56 bridge was updated through its
supported configuration API to include only the five public report scripts in
addition to its original device. All five appeared as `OnOffPlugInUnit`
endpoints with their expected English report names. The original endpoint
identity, bridge settings and commissioning fabrics were preserved. The private
dispatcher remained excluded, and the exact filter was verified in persistent
storage. No bridge restart or recommissioning was performed. Protected backups
and a filter-only rollback were retained outside the repository.

After removal of an unused Homeway cloud integration and a controlled HA
restart, HA reconnected to Matter Hub. The existing Google fabric had an active
session and subscription. The cloud `google_assistant` integration was unloaded;
Google Assistant SDK, Matter, Cast and the report scripts remained available.

One SDK command, `turn on Energy status report`, was followed by new command
activity on the Google Matter fabric and invocation of the requested HA wrapper.
An independent observer saw the exact new media URL reach `PLAYING` on the
configured display with advancing playback time. This first request completed
with `fallback_played`: it exercised the trigger and playback path, but failed
to deliver an IGW report. The service recorded a transport failure. A subsequent
read-only IGW request returned HTTP 200 with all five reports marked fresh;
no persistent authentication or configuration fault was found.

A single full retry again correlated Google Matter command activity with the
requested HA script. Its new media URL reached `PLAYING`, playback time advanced,
and the service completed with `report_played` and no fallback. The observer
submitted no commands or playback requests. Both the initial failure and the
successful retry were retained as private evidence; no configuration change was
needed between them.

This supports the Google-to-Matter-to-HA-to-Cast actuation path. Matter command
attribution is based on fabric/session timing and the requested HA script; the
available health receipt does not include an endpoint-specific command trace.
The SDK test does not prove physical microphone recognition, human audibility,
screen appearance, other household members' access, or live voice invocation of
all five reports. Those remain installation checks. One transient transport
failure also remains part of the observed reliability record.

The operator subsequently confirmed that the status report works on the physical
display. That user confirmation supplements the automated receiver observation;
it does not establish voice invocation of the other four reports or access by
other household members.

The main report was then renamed to **Energy** using only HA's entity-registry
display-name override. Its entity ID and all Matter endpoint identities,
commissioning fabrics, filters, mappings and unrelated names were preserved.
One SDK command, `turn on Energy`, invoked the intended status script. The
independent observer confirmed the new media URL reached `PLAYING`, playback
time advanced, and the service completed with `report_played` without a fallback.
No restart, new pairing or Google routine was needed for this shorter command.

The documentation and generated installation instructions passed independent
review. All 54 tests passed without skips in Linux CI, and both generated HA
package modes passed configuration checks with HA 2026.9.2. Generated runtime
YAML and application behavior were unchanged by the documentation update.
