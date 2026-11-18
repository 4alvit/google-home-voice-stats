# Documentation

The Google Cast voice adapter that reads IGW energy reports, with the speech
options it can use and the release records that qualify each archive.

## Use the adapter

- [Report phrases](utterance-catalog.md) — what to say, including the Matter phrasing.
- [Google Home phrases and Home Assistant scripts](routines.md) — the five public scripts and how they are triggered.
- [Optional notifications and scheduled briefings](automations.md) — the blueprints that add notifications and a daily report.
- [Google voice reports through Matter](matter.md) — exposing the report scripts through the Matter Hub.

## Speech

- [Optional local Piper speech](local-speech.md) — Piper as an alternative to the default eSpeak NG renderer.
- [Russian speech](russian-speech.md) — a separate Piper service and an optional KittenTTS pilot.
- [Local Russian speech with Baya](silero-baya.md) — selecting the Baya speaker in Silero `v5_6_ru`.
- [KittenTTS Nano with a second server](kitten-speech.md) — requesting English speech from two private servers.
- [Standalone Cast display and speech](standalone-cast.md) — the dashboard snapshot on one configured Cast device.
- [TLS keys and supported speech configuration](tls-policy.md) — certificate verification across owned HTTPS clients.

## Contract and validation

- [IGW contract used by this adapter](igw-contract.md) — the authenticated `GET /v1/energy` request and its expectations.
- [Installation smoke tests](testing.md) — the offline tests and configuration check to run before activating.
- [Anonymized deployment validation](deployment-validation.md) — a verified scope recorded without installation identifiers.
- [Quality evidence and limitations](quality.md) — what the adapter, speech service and generated configuration are checked against.

## Release operation

- [CI and release operations](release-workflow.md) — `.release-policy.json` as source of truth.
- [CI and release policy](CI_WORKFLOW.md) — the validation-only policy and its events.
- [Source release packaging and acceptance](release-packaging.md) — the installable Python archive and Home Assistant artefacts.
- [Version plans and manifest synchronization](VERSIONING.md) — the versioning opt-in.
- [Dependency locks](DEPENDENCY_LOCKS.md) — the exact versions the adapter pins.
- [GitHub CLI release-helper dependency assessment](RELEASE_DEPENDENCY_ASSESSMENT.md) — a scoped 2026-10-16 disposition, not a clean-bill claim.
- [Release helper TLS profile](RELEASE_TLS_PROFILE.md) — the qualified `gh` transport profile.
- [Release-candidate fuzz testing](fuzzing.md) — the illustrated RC fuzzing process.
- [Fuzzing release candidates](rc-fuzzing.md) — the reusable bounded fuzz workflow.
- [Release read recovery and rerun validation](release-read-safety.md) — the two fixes carried from the shared toolkit.
- [Early final-build runner check](runner-preflight.md) — why the check runs before the final build.
- [OpenSSF evidence index](openssf-evidence.md) — source evidence and remaining limitations behind the self-assessment.
