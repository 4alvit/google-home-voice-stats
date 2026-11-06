# Dependency locks

The dependency files used by the Google voice adapter pin exact package versions and
SHA-256 distribution hashes. CI installs build tools from
`.github/requirements-build.txt` before installing source distributions or this
project with `--no-build-isolation`. This prevents pip from resolving a separate,
unlocked build environment. Application dependencies remain installed from their
full locks; `--no-deps` is used only for the subsequent local project install.

The first two comment lines in each generated lock record its `uv pip compile`
command. Run that command from the repository root with uv 0.13.4 to regenerate
the lock, review version and hash changes, then repeat the corresponding CI
checks before merging. Hashes establish the selected artifact identity; they do
not establish that a package is free of vulnerabilities. Keep dependency
security scanning and update review enabled.

The test, Cast runtime and optional Piper runtime each have a separate lock.
All Python runtime environments additionally install `requirements-tls.lock`,
which pins the certificate-key decoder and its dependencies. Intel macOS uses
the native public-key decoder documented in `tls-policy.md`.
Their top-level versions come from `pyproject.toml`. The image uses a pinned
Python Bookworm manifest; review a live registry manifest before changing
that digest. CI tests both `CAST_INSTALL_PIPER=false` and `true`, checks installed
dependency consistency and imports the runtime without contacting Cast devices.
The Python locks do not freeze Debian apt repositories; OS packages still
receive the base distribution's updates when rebuilding.

Renovate uses native `pip-compile` to update the recorded source and supported
compiled locks together. Binary-only targets include
`.github/requirements-wheels-only.in`, preserving their previous
`--only-binary :all:` policy without changing other compile flags. The platform-specific locks use the guarded regeneration commands below.

The cast, Piper and test project locks use `requirements-tls.lock` as a
constraint. This keeps shared cryptography dependencies consistent when CI
installs the test and TLS locks together. Native updates regenerate the TLS
lock before those dependent project outputs.

## Platform-specific regeneration

Renovate updates each exact `.in` source and regenerates its lock with a literal
allowlisted uv 0.13.4 command, with shell execution disabled. The `--no-build`
flag forbids source builds while preserving platform, index, hashes and no-deps
policies. The package-only source replaces stdin with the same reviewed
`kittenml` pin. The macOS Intel ONNX Runtime pin stays at 1.19.2 for macOS 12;
changing that compatibility boundary requires a separate reviewed change.

```sh
uv pip compile --generate-hashes --python-version 3.11 --python-platform x86_64-apple-darwin --no-build --output-file requirements-kitten-macos-intel.lock requirements-kitten-macos-intel.in
uv pip compile requirements-russian-silero.in --generate-hashes --emit-index-url --index-strategy unsafe-best-match --python-version 3.11 --python-platform x86_64-manylinux_2_28 --no-build --output-file requirements-russian-silero.lock
uv pip compile --no-deps --generate-hashes --python-version 3.11 --no-build --output-file requirements-kitten-package.lock requirements-kitten-package.in
```
