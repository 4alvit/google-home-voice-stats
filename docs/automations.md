# Optional notifications and scheduled briefings

These Home Assistant blueprints add configurable notifications and a daily report
to an existing installation. They do not change inverter settings, create voice
routines, select phone recipients, discover sensors or enable themselves.

## Render and install

```bash
python3 -m igw_google_voice.automations --output ./rendered-automations
```

The command copies three automation blueprints into a new staging directory and
refuses existing files or symlinks. Copy its `blueprints/automation/igw/` directory
into your HA configuration. In HA's automation blueprint interface, create only
the desired automations. Validate the resulting HA configuration before enabling
them. The repository's offline HA checks instantiate all three templates with
synthetic entity names; they never send a notification.

## Battery reserve and recovery

Select an authoritative percentage sensor for the battery you intend to monitor.
Select a separate freshness binary sensor that is `on` only when this value is
known, valid and current. An entity merely existing, an MQTT connection, or its
last state-change timestamp alone does not establish measurement freshness. These
templates do not create either sensor or add an IGW polling integration.

Create a dedicated Toggle helper (`input_boolean`) for this notification episode.
Do not give it a fixed YAML `initial` value; let HA restore its prior state.
Do not expose this internal helper through Matter or voice assistants.

Choose the low reserve and a strictly higher recovery threshold. The defaults
are illustrative 20 and 25 percent; they are not a recommendation for a specific
battery. Normal threshold triggers require the value to remain valid, fresh and
beyond the threshold together for the configured number of minutes. Losing any
qualification cancels that hold; freshness recovery starts a new full hold only
when the threshold condition is also met. One successful notification call sets the helper;
only recovery above the higher threshold clears it and sends recovery. Remaining
in either state cannot generate repeated notifications.

Unknown, unavailable, nonnumeric, out-of-range or non-fresh values do not generate
an alert or an all-clear. A broken freshness signal can still make any automation
unreliable; independently verify the selected sensor's failure behavior.

## Energy condition and recovery

Use the condition blueprint for a known binary condition: `on` means active and
`off` means cleared. It needs its own freshness sensor and its own restoring
episode helper. Configure explicit active/recovery wording for that condition.

For power loss, use a trusted grid-loss/availability signal mapped to those
states. **Zero grid import is not evidence of grid loss.** The optional IGW flow
report describes watts and direction; it does not itself establish grid presence.
Do not turn an unknown condition into `off`, or an unavailable connection into a
recovery message. This blueprint does not perform that conversion.

## Delivery, quiet hours and limits

Set the allowed daily notification window in HA's local timezone. Outside it,
the templates leave the notification latch unchanged and send nothing. At the
next window start they check the current qualified state, so a still-active
condition can be reported then. A condition that starts and ends wholly during
quiet hours may produce no notification. This is an intentionally quiet policy,
not a safety alarm or an event-history service.

Pending holds are lost on an HA restart or automation reload. Do not rely on a
previously active condition automatically restarting its timer: the next
qualified-condition transition or allowed-window start supplies another check.
The window-start check intentionally evaluates the current qualified state
without imposing another hold or replaying overnight events. These are not
guaranteed-delivery notifications.

By default messages become HA persistent notifications. To deliver to a phone,
set **Notification service** to the existing named service for the intended
Companion App recipient, for example `notify.mobile_app_your_phone`. Confirm that
service and recipient in HA first. Only `persistent_notification.create` and
`notify.<lowercase_name>` names containing letters, digits or underscores are
accepted. Choose a service that accepts `title` and `message` without additional
target arguments; a generic entity-based service such as `notify.send_message`
is not a substitute for a configured phone service.

The blueprint supplies the title and condition message and makes one ordinary
service call. It does not accept arbitrary action sequences, infer recipients or
customize notification payloads. A raised service error stops the sequence before
changing the latch. A returned call confirms acceptance by the selected HA
service, not delivery to a phone; integrations can also handle failures internally.
After a failed call, another qualified transition or window-start check is needed
for a retry. The templates disable stored traces,
but the chosen notification integration, phone and action history can retain
message content. Do not put credentials in messages. A single-run mode, state
persistence, a recovery threshold and the episode latch reduce alert storms;
there is no separate time-based cooldown or message queue.

Alexa's custom-skill notification API has predefined event schemas and user
opt-in requirements; these HA templates do not promise arbitrary proactive Alexa
speech. See [Amazon's notification model](https://developer.amazon.com/en-US/docs/alexa/smapi/proactive-events-api.html).

## Scheduled briefing

Select an existing public report wrapper, for example your installed status
script, plus local time and weekdays. Keep the private parameterized dispatcher
unselected. The blueprint invokes the same read-only report path as a voice
command. It adds no gateway credentials or separate speech provider.

The report plays on the script's configured output device and can replace current
media. Concurrent standalone reports remain subject to the service's busy check.
Scheduled playback is not enabled until you create and enable the automation.

## Verify and undo

Use temporary synthetic HA sensors and separate test helpers first. Verify one
low/active message, no duplicate while the episode remains active, one recovery,
unknown/stale suppression, and the allowed-hours behavior. Confirm the actual
phone recipient. For the briefing, run the chosen public wrapper and verify
screen and sound, then check one scheduled invocation.

Disable or remove only the optional automation to undo it. Keep existing report
scripts, Cast service and Matter pairing. Removing a helper while its automation
is enabled is not a substitute for disabling the automation.

References: [HA blueprint setup](https://www.home-assistant.io/docs/automation/using_blueprints/),
[trigger semantics](https://www.home-assistant.io/docs/automation/trigger/), and
[selectors](https://www.home-assistant.io/docs/blueprint/selectors/).
