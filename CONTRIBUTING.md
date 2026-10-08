# Contributing

Read-only IGW energy reports for Google Nest through generated Home Assistant adapters and an optional standalone Cast service.

## Questions, bugs and proposals

Use [GitHub Issues](https://github.com/4alvit/google-home-voice-stats/issues) for questions, bug reports and feature proposals. Search existing issues first. Describe the affected version/commit, expected and actual behavior, minimal reproduction and relevant environment. Remove tokens, private endpoints, household identifiers and personal data from examples. Security vulnerabilities use the confidential process in [SECURITY.md](SECURITY.md).

Anyone may propose a change through a pull request. Discuss compatibility or architectural changes in an issue before a large implementation. Maintainers aim to acknowledge actionable reports within 14 days; security reports follow the security policy. No paid support or response-time guarantee is implied.

## Development and validation

Clone the repository, create a branch from `main`, and use the Python version and dependencies declared by the project and CI. Run from the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install '.[test,cast]'
bash scripts/ci.sh unit
bash scripts/ci.sh syntax
```

The unittest suite covers report parsing, generated templates, automations, Cast requests and media handling. The syntax check requires actionlint 1.7.12. Run `bash scripts/ci.sh config` with Docker available to validate generated Home Assistant configurations. Physical speaker playback and voice recognition need the documented installation smoke test.

For a bug fix, add a regression test that fails before the fix and passes afterward. For new functionality, test normal behavior, invalid input and relevant authorization/error paths. Preserve existing checks; do not lower coverage gates or ignore findings merely to obtain a green build. Python code follows the configured formatter/linter where present and normal PEP 8 conventions otherwise. Keep shell, YAML and generated examples compatible with their declared tools.

## Review and compatibility

Keep pull requests focused and explain the problem, resulting behavior, compatibility impact and exact validation performed. Update the user-facing documentation when changing configuration, interfaces or operational behavior. Call out tests not run and their prerequisites. Maintainers review changes through GitHub pull requests and required CI; automated review is supplemental. Contributions are provided under the repository's [MIT license](LICENSE); a contributor must have the right to submit the work.

This repository uses validation-only CI. Its manual source releases identify validated commits; preserve the documented deployment and physical playback checks in release notes.

## Source and interfaces

- [`igw_google_voice`](igw_google_voice)
- [`blueprints`](blueprints)
- [`README.md`](README.md)
- [`architecture.md`](architecture.md)
- [`docs/igw-contract.md`](docs/igw-contract.md)
- [`docs/testing.md`](docs/testing.md)
- [`docs/standalone-cast.md`](docs/standalone-cast.md)

See the [OpenSSF evidence index](docs/openssf-evidence.md) for the current assessment scope and outstanding verification.

## FLOSS static analysis

Install hash-verified analysis dependencies with
`python3 -m pip install --require-hashes --only-binary=:all: -r .github/requirements-security.txt`,
then run `python3 scripts/security_check.py`. The required quality gate runs the
same Ruff and Bandit checks. Scanner failures, empty/incomplete reports and
findings fail the gate. Any narrowly scoped exception must have an explanatory
source comment and a reviewer must verify that it is not an exploitable finding.
