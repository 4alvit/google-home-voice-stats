# Dependency locks

The dependency files used by the Google voice adapter pin exact package versions and
SHA-256 distribution hashes. CI installs build tools from
`.github/requirements-build.txt` before installing source distributions or this
project with `--no-build-isolation`. This prevents pip from resolving a separate,
unlocked build environment. Application dependencies remain installed from their
full locks; `--no-deps` is used only for the subsequent local project install.

The first two comment lines in each generated lock record its `uv pip compile`
command. Run that command from the repository root with uv 0.12.18 to regenerate
the lock, review version and hash changes, then repeat the corresponding CI
checks before merging. Hashes establish the selected artifact identity; they do
not establish that a package is free of vulnerabilities. Keep dependency
security scanning and update review enabled.

The test, Cast runtime and optional Piper runtime each have a separate lock.
Their top-level versions come from `pyproject.toml`. The image uses a pinned
Python 3.12 Bookworm manifest; review a live registry manifest before changing
that digest. CI tests both `CAST_INSTALL_PIPER=false` and `true`, checks installed
dependency consistency and imports the runtime without contacting Cast devices.
The Python locks do not freeze Debian apt repositories; OS packages still
receive the base distribution's updates when rebuilding.
