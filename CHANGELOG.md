# Changelog

## [0.3.4] - 2026-10-18

### Changed

- Add configurable local Silero Russian speech, bounded voice and prosody settings, and persistent settings controls. Keep the container on a Python version supported by its pinned ONNX runtime.

- Add persistent Silero voice/prosody settings over authenticated HTTPS and a
  Wyoming service-default alias. Expose all five pinned v5_6_ru speakers while
  preserving per-utterance streaming snapshots and bounded synthesis.

### Upgrade

Preserve installation-specific configuration and retain the previous immutable release for rollback. Required CI and source-bound RC qualification remain enabled. Publishing this release does not deploy it to an installation or establish hardware acceptance.

### Security

The settings API retains authenticated HTTPS, certificate verification, bounded input and private persisted settings. Keep the settings bearer token outside source and public logs.

## [0.3.3] - 2026-10-17

### Changed

- Apply verified certificate-chain key checks to the speech HTTPS path.
- Document OpenSSF assessment evidence and the illustrated RC fuzzing process and results.

### Upgrade

Preserve installation-specific credentials and configuration. Ensure speech HTTPS peers satisfy the documented TLS trust and key requirements, and retain the previous package for rollback. Physical speaker and cloud-integration acceptance remains deployment-specific.

### Security

Speech HTTPS connections now enforce the documented verified-chain key policy before using the transport. Required CI and source-bound RC fuzzing remain enabled.

## [0.3.2] - 2026-10-14

### Changed

- Validate each public release candidate with bounded, network-isolated fuzz campaigns against its exact source revision.
- Require positive engine execution counts, instrumented production code and validated seed corpora; retain source-bound reports and diagnostic evidence.
- Run deterministic seed and configuration checks in ordinary CI without starting mutation campaigns on betas.

### Upgrade

Use the existing installation procedure, preserve local configuration and keep the previous accepted package for rollback. This maintenance release updates release validation and does not change the application configuration format. Deployment and applicable device or integration acceptance remain separate from publication.

### Security

RC publication rejects absent or invalid source-bound fuzz reports. The fuzz runner bounds corpus paths, file types and size. No application vulnerability or new target-device acceptance is claimed by these tooling changes.

## [0.3.1]

### Added

- Installable source release archives containing the Python application, integration templates, dependency locks and operator documentation.
- Frozen beta, nightly and RC version plans, package metadata verification and exact-asset build receipts.

### Upgrade

Install the source archive in a fresh environment using the documented locked dependencies. Compare and merge configuration templates; preserve installation-specific credentials and existing service configuration outside the checkout. This release does not deploy services, create cloud resources or configure physical speakers. Keep the previously accepted package and configuration for rollback.

### Security

The release process preserves the existing required validation workflows and publishes only tracked inputs. Local secrets, environment files, deployment state and generated media are excluded by the repository's existing tracking policy. Release receipts verify artifact identity; physical voice behavior and installation-specific access must still be accepted separately.
