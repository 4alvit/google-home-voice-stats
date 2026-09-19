# Google energy reports architecture

This project provides read-only report presentation and playback. The standalone
Cast service can run without Home Assistant. Google voice triggering uses an
existing Matter or cloud integration; Cast alone does not implement voice intents.

## Components and data ownership

```mermaid
flowchart LR
    Cerbo["Cerbo GX / Venus OS"] -->|"MQTT telemetry"| IGW["IGW on server or NAS"]
    IGW -->|"Authenticated read-only /v1/energy"| Cast["Standalone Cast service"]
    Cast --> Render["Numeric cards and local speech"]
    Render --> Media["Temporary H.264 / AAC snapshot"]
    Media -->|"Private LAN retrieval"| Display["Configured Cast display"]
    Voice["Google voice command"] --> Bridge["Google hub and Matter bridge"]
    Bridge --> HA["HA public report script"]
    HA -->|"Local playback token and POST"| Cast
```

IGW owns source selection, energy calculations, report wording and freshness.
The NAS renders media; Cerbo runs no speech model or renderer. HA is a small
trigger layer in this route and stores only the local playback token. The Cast
service holds the IGW read credentials and optional Cloudflare Access credentials.

The original HA speech adapter is an alternative: HA reads IGW and passes the
report to an existing TTS provider and speaker. Do not install both generated
packages with duplicate entity IDs. See the [setup guide](README.md).

## Google trigger paths

```mermaid
flowchart TD
    Command["Google voice command"] --> Route{"Configured integration"}
    Route -->|"Turn on report name"| Matter["Google Matter hub"]
    Matter --> Hub["Home Assistant Matter Hub"]
    Route -->|"Activate scene name"| Cloud["Optional cloud account link"]
    Hub --> Wrapper["Public report wrapper"]
    Cloud --> Wrapper
    Schedule["Optional daily briefing automation"] --> Wrapper
    Wrapper --> Private["Private parameterized dispatcher"]
    Private --> API["Authenticated local Cast POST"]
```

The five existing wrappers and names remain the default. `--include-flow` adds
one explicit power-flow wrapper; commissioning and exposure remain separate
operator steps. Keep the dispatcher private and preserve existing Matter
endpoint identities. The optional `Energy` display-name override preserves the
status script's entity ID. Bare voice starters require personal Google routines.

Each service instance targets one configured receiver. The originating microphone
does not automatically select another output room. The MP4 is a snapshot, so it
does not provide Alexa-style report buttons or an interactive web dashboard.

## Playback, authentication and resource bounds

```mermaid
sequenceDiagram
    participant H as HA or local authorized client
    participant S as Cast service
    participant G as IGW
    participant R as Local renderer
    participant D as Cast receiver
    H->>S: POST /v1/reports/report with playback token
    S->>S: Authorize and acquire single-report slot
    S-->>H: 202 accepted, or 409 busy
    S->>G: Scoped authenticated GET under a total deadline
    G-->>S: Metrics and central report text
    S->>R: Validate and select brief speech and full display details
    R-->>S: Bounded temporary MP4
    S->>D: Load capability-bearing media URL
    D->>S: Fetch media with byte ranges
    S->>S: Observe exact-media playback and record safe result
    S->>S: Expire media and release report slot
```

HTTP acceptance is not playback proof. Verification follows the new media URL
through receiver `PLAYING`, advancing playback time and the service's result.
Physical screen appearance, audibility and microphone recognition are separate.

The local API is restricted to a trusted LAN. Media capability URLs are temporary
and must remain private because receivers cannot attach the API token. Requests
are not queued into overlapping playback. Process, file, time and memory bounds
remain important on a NAS. At most one classified transient IGW read retry fits
inside the existing overall deadline; authorization and invalid data are not retried.

## Numeric cards and local speech

```mermaid
flowchart LR
    Data["Validated energy envelope"] --> Numbers["Validated optional numbers, units and receipt ages"]
    Numbers --> Cards["Large values and explicit status labels"]
    Data --> Full["Full central text and warning pages"]
    Data --> Brief["Optional status.brief_text with legacy fallback"]
    Brief --> Voice{"Configured local TTS"}
    Voice --> Espeak["eSpeak NG"]
    Voice --> Piper["Optional Piper with local reviewed model"]
    Piper -->|"Bounded failure fallback"| Espeak
    Espeak --> Compose["Compose speech and cards into MP4"]
    Piper --> Compose
    Cards --> Compose
    Full --> Compose
```

The source receipt age is distinct from envelope generation time and physical
sampling time. Unavailable, stale and unconfigured readings retain their meaning.
The renderer never extracts numbers from prose or replaces missing data with zero.
Brief speech does not remove full on-screen warning explanations.

Piper is optional, uses local model files, and does not download a model for a
voice request. Check its software and selected voice-model licenses. Benchmark
the actual NAS before changing its default engine. See the
[Piper installation instructions](docs/standalone-cast.md).

## Optional notifications

```mermaid
flowchart LR
    Sensors["Explicit HA energy and freshness entities"] --> Guard["Known and current data"]
    Guard --> Policy["Threshold or condition; persistence and allowed hours"]
    Policy --> Episode["Check dedicated restoring episode helper"]
    Episode --> Notify["Operator-selected notification service"]
    Notify -->|"Service call accepted"| Latch["Update episode helper"]
    Clock["Local time and weekdays"] --> Briefing["Existing public report script"]
```

Notification blueprints use explicitly selected HA sensors and freshness signals;
they do not add IGW polling or credentials to the Cast trigger. This is a separate
optional automation path. Grid-loss alerts require a real condition sensor, not
an inference from zero grid power. Reserve recovery uses a separate threshold.
The default notification stays in HA; phone recipients are selected by the operator.
The blueprints are templates and are never enabled by rendering files. See
[automation setup and limitations](docs/automations.md).

## Upgrade and verification

Upgrade IGW first when enabling additive brief or flow reports. Existing gateways
and five-report configurations remain usable. Install a reviewed local Piper
model only if opting in. Preserve the existing display identity and HA/Matter
configuration when updating the service.

Validate unit tests, real offline media generation, package installation and HA
configuration for both adapters with and without flow. Exercise one actual
receiver before relying on microphone acceptance. For automation templates,
test synthetic helpers and the selected notification service before using live
thresholds. No test fixture needs real credentials or household values.

Rollback uses the previous service image and HA package. Disable only the newly
created optional automations. Retain the bridge pairing, established public
entity IDs, secrets and unrelated services.
