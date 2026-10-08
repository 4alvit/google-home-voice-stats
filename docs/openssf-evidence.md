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

## Implementation evidence audited on 2026-10-08 UTC

80 tests passed, with one external-media-tool test skipped, and 84% statement coverage across 1,005 application statements. The major brief/cards/automation update added regression tests in commit 5b5ab5a. Coverage is statement coverage, not a claim of complete branch or hardware coverage. The unit commands are documented in CONTRIBUTING; the coverage measurement used coverage.py 7.10.7 for the voice projects and the hash-locked pytest-cov toolchain for the generated template.

The supported Python 3.12 runtime was checked with `ssl.create_default_context()`: Python 3.12.14 / OpenSSL 3.5.8 reported a TLS 1.2 minimum, security level 2, required certificate validation, hostname checks and at least 128-bit symmetric ciphers. Offered TLS 1.2 key exchanges were ephemeral ECDHE/DHE; TLS 1.3 was also enabled. The application uses the standard context without enabling obsolete protocol versions or lowering its security level. These are runtime configuration observations, not measurements of a production endpoint. Operators must retain an updated supported runtime and validate their own ingress and devices. See [Python's TLS documentation](https://docs.python.org/3.12/library/ssl.html#ssl.create_default_context).

Outbound HTTPS uses urllib's certificate-verified default TLS context; generated HA configuration retains `verify_ssl: true`. Playback bearer tokens use `secrets.token_urlsafe(24)`, and authentication comparisons use `hmac.compare_digest`. Operator-supplied API tokens are not a user password database. Local Cast media intentionally uses HTTP on a private LAN and must not be published through an Internet tunnel; the explicit private-IGW HTTP mode likewise requires a trusted isolated network. No forward-secrecy claim is made about those plaintext paths or device firmware.

No dedicated fuzzer or dynamic taint tool is currently claimed. The optional dynamic-analysis criterion is explicitly unmet, and complete branch coverage/maximum warning strictness are not claimed. Existing tests execute with assertions enabled. No confirmed medium/high exploitable issue discovered by these runtime tests remains unresolved; future findings follow SECURITY.md.
