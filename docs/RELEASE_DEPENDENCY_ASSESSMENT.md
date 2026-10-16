# GitHub CLI release-helper dependency assessment

Assessment date: 2026-10-16. This is a scoped vulnerability disposition, not a claim that GitHub CLI has no advisories.

## Exact software and supported use

Official GitHub CLI 2.102.0, upstream commit `fc4b137cdef0a6bd28fd461b7cf9c84a5812a8cd`, binary built with Go 1.27.1. SHA-256: `81904d0aaa9fb3d9e35e13e7b1fe917451df0430eaee63144c69426d5d2832f1`. Source: https://github.com/cli/cli/tree/fc4b137cdef0a6bd28fd461b7cf9c84a5812a8cd

This assessment covers the checked-in release helper invoking `gh api`, `gh repo view`, `gh workflow run`, and `gh run list`, with `GH_HOST=github.com`, normal GitHub TLS verification, and `GODEBUG=fips140=on`. It does not authorize arbitrary CLI commands, Codespaces listeners, extensions, custom API hosts, aliases that change command behavior, or disabling verification. Existing maintainer authentication remains required; no operator credentials were used in fixture tests.

## Findings and threshold decision

Binary govulncheck reports thirteen advisory identifiers. Twelve were first published on 2026-10-08, eight days before this assessment. Their primary CVE records assign at most 7.5 except GO-2026-6612 (9.1). Those eleven noncritical recent records have not reached the Passing 60-day threshold; they remain tracked, not fixed or dismissed. Upstream Go 1.27.2 / x/net 0.60.0 are the remediation versions and a patched dependency build is being qualified.

The sole critical record, [GO-2026-6612](https://pkg.go.dev/vuln/GO-2026-6612), concerns an HTTP/2 **server** refunding receive flow control after a client resets a stream. The supported commands construct outbound `http.Client` instances. They neither start an HTTP/2 server nor accept streams from a remote client. The advisory's x/net symbol set includes client and common frame functions, so a symbol match alone does not establish its server precondition. Source review of the actual commands and shared HTTP factory confirms this precondition is absent:

- [API client construction and request loop](https://github.com/cli/cli/blob/fc4b137cdef0a6bd28fd461b7cf9c84a5812a8cd/pkg/cmd/api/api.go#L395)
- [Shared outbound HTTP client](https://github.com/cli/cli/blob/fc4b137cdef0a6bd28fd461b7cf9c84a5812a8cd/api/http_client.go#L36)
- [Repository view client](https://github.com/cli/cli/blob/fc4b137cdef0a6bd28fd461b7cf9c84a5812a8cd/pkg/cmd/repo/view/view.go#L81)
- [Workflow dispatch](https://github.com/cli/cli/blob/fc4b137cdef0a6bd28fd461b7cf9c84a5812a8cd/pkg/cmd/workflow/run/run.go#L259)
- [Run list implementation](https://github.com/cli/cli/blob/fc4b137cdef0a6bd28fd461b7cf9c84a5812a8cd/pkg/cmd/run/list/list.go)

The only older record is [GO-2026-5932](https://pkg.go.dev/vuln/GO-2026-5932), dated 2026-07-07. It applies to the unmaintained `golang.org/x/crypto/openpgp` packages, not every package in x/crypto. `go list -deps ./cmd/gh` lists 1,136 packages and **no openpgp package**. Source-mode govulncheck likewise reports one module-only vulnerability but zero imported-package vulnerabilities. The binary scanner emitted wildcard package names; these are not proof that the OpenPGP implementation was linked or invoked.

Consequently, these specific release-helper paths have no identified applicable critical or 60-day-old medium-or-higher vulnerability as of this date. `vulnerabilities_critical_fixed` and `vulnerabilities_fixed_60_days` may use this scoped evidence together with the project's own clean dependency/security checks. This finding cannot be reused for arbitrary GitHub CLI use or indefinitely: reassess after dependency changes and before the recent advisories reach the deadline.

## Reproduction and retained evidence

- `gh-newscanner-binary-vuln.log`: unmodified binary scan (thirteen records).
- `gh-command-dependencies.txt`: complete upstream cmd/gh dependency package list, generated with the exact upstream go.mod.
- `gh-source-vuln.log`: source-mode scan using selected Go 1.27.2; five recent x/net records, zero imported-package vulnerabilities and one module-only record. This does **not** represent the stdlib of the installed Go 1.27.1 binary.
- `gh-release-profile-advisory-triage.json`: each advisory's date, primary metrics and explicit disposition.
- `go-advisories/*.json`, `cve-records/*.json`: retained primary Go/CVE source records.

No source, installed binary, production configuration or credentials were modified to obtain this assessment.
