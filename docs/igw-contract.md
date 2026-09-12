# IGW contract used by this adapter

The request is an authenticated HTTPS `GET /v1/energy`, with `Accept:
application/json`, no payload, a ten-second timeout, and TLS verification enabled.
The bearer credential must be scoped to reading reports. Optional Cloudflare
Access service-token headers authorize the same read path through Access.

The JSON response envelope contains:

```json
{
  "schema_version": 1,
  "generated_at": 1789257600,
  "mqtt_connected": true,
  "metrics": {
    "battery_soc": {},
    "solar_power": {},
    "solar_today": {}
  },
  "reports": {
    "battery": {"text": "The battery is at 74 percent.", "status": "fresh"},
    "solar": {"text": "Solar power is 1200 watts.", "status": "fresh"},
    "solar_today": {"text": "Solar energy today is 6.2 kilowatt hours.", "status": "fresh"},
    "status": {"text": "The battery is at 74 percent. Solar power is 1200 watts. No active energy alarms.", "status": "fresh"},
    "alarms": {"text": "No active energy alarms.", "status": "fresh"}
  }
}
```

This illustrates only fields consumed by the adapter. IGW may also return a
top-level `alarms` object; the adapter speaks `reports.alarms.text` rather than
interpreting individual alarm fields. Metric objects may contain
values, units, source metadata, and timestamps; this adapter does not interpret
them. The gateway is responsible for identifying unavailable sources and
producing accurate reports. `generated_at` is the Unix timestamp in seconds of
this API response, not the original measurement timestamp. Serve `application/json`
and disable response caching at IGW and any reverse proxy.

`schema_version` must be the integer 1, `mqtt_connected` a boolean, and
`generated_at` a number within the configured envelope age window. The adapter
requires the three metric keys and validates the selected report. Report text
must be nonempty and at most 1200 characters. Recognized report statuses are
`fresh`, `stale`, `unavailable`, and `unconfigured`; the gateway text for each is
spoken unchanged. A `fresh` report with `mqtt_connected: false` is contradictory
and rejected. Other disconnected reports preserve central warning text: IGW must
incorporate connection conditions into report status and wording.

The adapter deliberately has no MQTT credentials, inverter-write credential,
energy calculation, statistics sensor, or zero-default conversion. Transport
errors and invalid envelopes get a local connection-error sentence because no
validated gateway sentence is available.
