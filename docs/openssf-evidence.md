# OpenSSF Best Practices evidence

This is an evidence index for the OpenSSF Best Practices Passing self-assessment. It is not an assertion that a badge has been awarded or that every criterion is satisfied. The public badge service is the authority for an awarded status.

## Project and participation

Read-only IGW energy reports for Google Nest through generated Home Assistant adapters and an optional standalone Cast service.

The project is developed publicly in [Git](https://github.com/4alvit/google-home-voice-stats) under the [MIT license](../LICENSE). Its source, issue tracker and pull requests are available without a paid account. [Contribution instructions](../CONTRIBUTING.md) describe reporting, changes, coding conventions, tests and review. The [security policy](../SECURITY.md) provides a confidential vulnerability-reporting path, support scope, response targets and deployment boundaries.

## User and interface documentation

- [`README.md`](../README.md)
- [`architecture.md`](../architecture.md)
- [`docs/igw-contract.md`](../docs/igw-contract.md)
- [`docs/testing.md`](../docs/testing.md)
- [`docs/standalone-cast.md`](../docs/standalone-cast.md)

## Source, testing and analysis

- [`igw_google_voice`](../igw_google_voice)
- [`blueprints`](../blueprints)

- [Test suite](../tests) and [CI workflows](../.github/workflows)
- [Local CI entry point](../scripts/ci.sh)
- [CodeQL analysis](../.github/workflows/codeql.yml)
- [Dependency update configuration](../.github/dependabot.yml)

The unittest suite covers report parsing, generated templates, automations, Cast requests and media handling. The syntax check requires actionlint 1.7.12. Run `bash scripts/ci.sh config` with Docker available to validate generated Home Assistant configurations. Physical speaker playback and voice recognition need the documented installation smoke test.

CI results are evidence for the tested revision and environment, not proof of safe production or hardware operation. Check the current default-branch runs and unresolved security findings before answering the analysis criteria. Fuzzing, coverage completeness and independent penetration testing must be supported by actual runs; ordinary unit tests must not be presented as those activities.

## Changes and releases

This repository uses validation-only CI. Its manual source releases identify validated commits; preserve the documented deployment and physical playback checks in release notes. The [release policy](../.release-policy.json) records automation behavior. A new release must identify its source revision and explain notable changes; security fixes must identify relevant advisories when known.

## Criteria still requiring verification

Before submitting or updating the questionnaire, verify the actual project-specific record: responses to bug and enhancement reports, vulnerability reports in every supported channel, release-note history, unresolved scanner findings, dependency status and required review settings. The primary maintainer must personally confirm knowledge of secure design and common implementation vulnerabilities. A confirmation about another repository does not establish these answers here.

Assess transport encryption, credential storage and privilege limits against the implementation and deployment documented in [SECURITY.md](../SECURITY.md). Do not mark a requirement satisfied solely because a policy says it should be. Record justified non-applicability only where the actual architecture supports it. No paid certification, blanket compliance guarantee or third-party audit is claimed.
