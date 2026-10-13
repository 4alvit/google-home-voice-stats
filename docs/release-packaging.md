# Source release packaging and acceptance

This repository publishes a real installable Python source archive for `igw-google-voice` together with its Home Assistant blueprints, Cast/Piper Compose and Docker recipes, speech dependency locks and installation documentation. The artifact is `google-home-voice-stats-<package-version>.tar.gz`. It contains tracked source inputs and never includes the checkout's Git metadata, untracked credentials, generated speech media or operator deployment state. The Python package is installed from that exact archive during the build, outside the source tree, before it can be staged for publication.

This replaces the previous validation-only operating policy with explicit beta, nightly and RC source releases. The deliverable is source software and integration templates. No prebuilt container, cloud service, Alexa/Google app-store listing, device firmware or configured installation is part of the artifact. Existing CI container builds remain required validation, and are not relabeled as release images. There is no new container or PyPI publication destination.

## Version ownership and channels

The numeric source base lives in `pyproject.toml` (`project.version`). The public `igw_google_voice.__version__` constant is also declared and synchronized. The exact selectors and archive metadata expectations are in [the release policy](../.release-policy.json). Third-party requirement pins and hashes remain unchanged.

The explicit promotion profile is `promote-bytes`: for base `0.3.0`, beta 7 is tagged `v0.3.0-beta.7`, the source archive uses `0.3.0-beta.7`, and installed Python metadata is `0.3.0b7`. Nightly Python versions use the frozen run/attempt projection described in [version plans](VERSIONING.md). RC 7 is tagged `v0.3.0-rc.7` but already installs as `0.3.0`, so a later approved stable promotion copies the exact accepted RC bytes. The manifest retains the full RC tag and source origin. A source version alone is insufficient to identify the accepted artifact; retain its tag, manifest and checksum.

## Frozen build and receipts

From a clean current default-branch checkout, `python3 scripts/release.py prepare-version --dry-run` reports the next base. `prepare-version --pr` prepares the owned fields for review. Use `--bump minor`, `--bump major` or `--version X.Y.Z` only for explicit version intent. Review the matching `CHANGELOG.md` section, including upgrade and security notes.

The release allocator stores one source- and policy-bound `.release-plan.json` before builds. The build downloads that exact plan and runs `version_plan.py sync`; its temporary overlay changes package metadata without committing candidate versions to the source branch. The source adapter validates the requested base/channel, snapshots tracked files, verifies all required integration paths, and writes a deterministic archive plus `SHA256SUMS`.

`verify_source_install.py` installs the archive in a fresh environment with the existing hash-locked build tools. It checks the installed distribution version, imports the package and runs CLI help without contacting a gateway or speaker. It also checks all packaged Home Assistant blueprint files and the public version constant. Finally `stage_release_assets.py` inspects the archive's actual project version and writes a receipt covering the final archive and checksum bytes. The release publisher requires the complete receipt and matching declared artifact metadata.

## Local reproduction

Restore the accepted manifest's `version_plan` into a disposable checkout of its exact source SHA. Never invent a release sequence or reset the allocation ledger. Then run with that plan's base and channel:

```sh
python3 scripts/version_plan.py sync --plan .release-plan.json
bash scripts/package-release.sh 0.3.0 beta
python3 scripts/verify_source_install.py release-dist
python3 scripts/stage_release_assets.py --target package --pattern 'release-dist/*'
```

The repository archive name differs from the Python distribution name. For direct uv installation, provide an explicit `igw-google-voice @ file:///absolute/path/to/archive.tar.gz` requirement so the filename is not mistaken for a distribution name; the verification script does this automatically.

These commands build and verify files locally; they do not publish or deploy. Without a frozen plan, the adapter may build a development archive from consistent base metadata, but staging publishable artifacts fails. The ignored `.release-plan.json`, `.release-inputs.json`, `release-dist/` and `release-assets/` are build outputs. Preserve the released manifest and receipt for reproduction, not local temporary directories.

Run `python3 -m unittest discover -s .github/release-tests` for the offline release contracts, and use `scripts/ci.sh` for the existing project validation. Full checks require the documented Docker/toolchain dependencies. From the toolkit checkout, `python3 scripts/install_release.py /path/to/repository --check` detects vendored drift. Update and rerender the toolkit instead of editing its generated scripts.

## Acceptance, upgrade and recovery

The required adapter workflow still runs offline response/rendering tests, Home Assistant configuration validation, Cast/Piper container checks and offline Kitten inference. The archived blueprints are installed by the Python package and checked from an isolated installation. Full Google microphone routing, physical display/audibility and other household members remain installation acceptance; historical results in [deployment validation](deployment-validation.md) apply only to their recorded scope.

The maintainer must test the exact RC archive against the intended installation and record its tag, source SHA, hashes, results and limitations before approving stable. Preserve existing installation credentials and merge generated configuration/templates deliberately. A passing source installation test neither configures integrations nor proves live authorization, network routing or physical speech. Stable publication remains an explicit accepted-RC operation; tag pushes never deploy.

Any source, dependency, template, workflow or policy change requires a new candidate. Do not edit an archive, manifest, plan or receipt after acceptance. If a build fails, correct the source and request a fresh candidate; leave reserved allocation gaps intact. Roll back operationally to previously accepted immutable software plus compatible configuration. See [the release runbook](release-workflow.md) for enablement, evidence retention and manual publication controls.
