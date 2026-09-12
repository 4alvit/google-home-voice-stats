# Deployment validation — September 12, 2026

The Google adapter was installed in an existing Home Assistant 2026.9.1
deployment. Its REST command uses the private Kubernetes IGW service route with
a scoped read bearer token. No Cloudflare Access service-token headers are
configured in HA, and no battery, solar, or alarm calculations run in HA.

## Configuration and startup

- The generated package and blueprint passed an isolated configuration check
  in the actual HA runtime. A full check of the installed configuration also
  passed; the same baseline duplicate-configuration and deprecation warnings
  remained, with no new configuration validation failure.
- The existing imported Google Assistant entry was recovered by restoring its
  YAML project configuration. Historical entity exposure defaults were preserved;
  the five IGW report scripts were explicitly exposed and the shared dispatcher
  excluded. Existing Google device exposure was not replaced by a five-item
  allowlist.
- The approved HA core restart temporarily closed port 8123 for several minutes,
  without a Kubernetes container restart. Read-only inspection subsequently
  found the HA process running and port 8123 listening on IPv4 and IPv6; the HA
  API then accepted requests.
- All six adapter script entities loaded in the `off` state. The Google Assistant
  integration, Google Cast, and the English Google Translate TTS provider loaded.

HA initially reported `NOT_RUNNING` while the API and adapter were already
functional, then completed bootstrap and reported `RUNNING`. The installed HA
source confirms that this API field reads the live core lifecycle state.
Bootstrap/setup logging was temporarily raised to `info` for a bounded diagnostic
window, then both loggers were restored to their original `error` level. No
specific pending integration was identified. Other integrations logged Alexa
Media device registry compatibility, SmartThings time-entity, and Prometheus
callback errors during startup; they did not prevent the final `RUNNING` state.

## IGW request path

Calling the installed `rest_command.igw_energy_report` returned HTTP 200 from the
internal IGW route. All five report keys were present and had `fresh` status:
battery, solar power, solar today, alarms, and combined energy status. This
verified the actual HA-to-IGW transport and authentication path without sending
an inverter command.

## Google export and speech

The selected Nest was initially `off`. A real call to
`script.igw_google_battery` completed successfully, and its Cast state changed to
`playing` with Default Media Receiver, then to `idle`. The test did not override
volume or interrupt other playing content. This confirms that Cast accepted and
played the generated report; there was no human observation of audibility.

Google microphone phrases, household account routing, and a real Google-initiated
SYNC remain untested. A synthetic SYNC was deliberately not used because HA
would register its caller as a Google agent user. The loaded Google Assistant
entry and explicit script exposure alone do not establish end-to-end Google
voice recognition.

## Automated checks

The adapter's 21 tests passed, including all five report paths, error/freshness
handling, and private-HTTP URL restrictions. actionlint and whitespace checks
passed. A wheel installation rendered the packaged blueprint outside the source
checkout. CI also validated the package with an isolated HA 2026.9.2 container.

No credentials, household entity IDs, private host addresses, or configuration
backups are included in this record.
