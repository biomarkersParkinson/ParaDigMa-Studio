# Releases

This guide describes the maintainer workflow for preparing, publishing and
verifying Windows releases from the current source. Download and launch
instructions live in the [README](../README.md#download-and-launch).
The [1.0.0rc1 verification record](RELEASE_CANDIDATE.md) is a dated example of
source checks, Windows artifact verification and remaining manual acceptance.

- [Version and tag policy](#version-and-tag-policy)
- [Prepare the release](#prepare-the-release)
- [Tag and push the reviewed commit](#tag-and-push-the-reviewed-commit)
- [What the publishing workflow does](#what-the-publishing-workflow-does)
- [Verify publication](#verify-publication)
- [Retry or investigate a failure](#retry-or-investigate-a-failure)
- [Signed builds](#signed-builds)

## Version and tag policy

The release tag must be exactly `v` followed by `project.version` in
[`pyproject.toml`](../pyproject.toml). The release helper accepts the following
Python-compatible version forms:

| Kind | Version / tag example | GitHub publication |
| --- | --- | --- |
| Alpha | `1.0.0a1` / `v1.0.0a1` | Prerelease; not marked latest |
| Beta | `1.0.0b1` / `v1.0.0b1` | Prerelease; not marked latest |
| Release candidate | `1.0.0rc1` / `v1.0.0rc1` | Prerelease; not marked latest |
| Stable | `1.0.0` / `v1.0.0` | Stable release; marked latest |

Alpha, beta and candidate versions follow the same publishing process as stable
versions. The suffix controls prerelease status. Version/tag validation and
release-note extraction are implemented in
[`prepare_release.py`](../scripts/prepare_release.py).

Published tags and assets remain immutable. Corrections to a published release
get a new version and tag.

## Prepare the release

### Update metadata and documentation

1. Set the intended version in `pyproject.toml`. Run `uv lock` to refresh Studio's
   root project entry while retaining dependency pins; review the lock diff.
2. Add exactly one dated `## <version> — YYYY-MM-DD` section to
   [`CHANGELOG.md`](../CHANGELOG.md). Its text becomes the GitHub release notes.
   Keep later work under `Unreleased`.
3. Update the README's version, download links and release description. Point
   its user-guide links and the [documentation index](README.md) to the new Git
   tag, so they match the published ZIP. Keep the guide on `main` labelled as
   current source.
4. Review the user-guide text, screenshots, known limitations and acceptance
   evidence for the version being prepared. Preserve earlier dated records.
   Run the [Markdown and link checks](../CONTRIBUTING.md#documentation-checks).

### Validate the source and Windows build

Use a clean checkout with the
[reviewed dependency environment](DEPENDENCIES.md#install-and-verify).
Verify the installed graph before running the
[dependency audit](DEPENDENCIES.md#run-the-installed-environment-audit).

Complete the [development checks](DEVELOPMENT.md#run-development-checks): source
guards, Ruff/format, mypy and the full suite with branch coverage, including the
[scientific comparisons](SCIENTIFIC_TESTS.md). Build and verify the
[Windows executable](DEVELOPMENT.md#build-and-verify-a-windows-executable).
The separate Documentation workflow checks Markdown and links.

Record completed checks and any remaining limitations. Before promoting a
candidate to stable, complete representative manual acceptance on the exact
Windows ZIP, including a machine without a source Python environment. The
[candidate acceptance checklist](RELEASE_CANDIDATE.md#windows-verification-and-acceptance)
provides a starting point; adapt its version and feature checks to the release.

## Tag and push the reviewed commit

Merge the preparation into `main` and identify the exact reviewed commit. From
that checkout, use these command templates, replacing `<version>` and
`<reviewed-commit>` with the chosen version and full commit hash:

```text
uv run --locked --all-groups python scripts/prepare_release.py version --tag v<version>
git tag -a v<version> <reviewed-commit> -m "ParaDigMa Studio <version>"
git push origin refs/tags/v<version>
```

Run the version check first and stop if it fails. Create the annotated tag on the
reviewed commit, then push that tag. **Pushing the tag starts automatic
publication** after the required build and artifact checks pass.

The ordinary [Windows desktop workflow](../.github/workflows/windows.yml) has
different outcomes depending on its trigger:

| Trigger | Outcome |
| --- | --- |
| Branch push or pull request | Checks and a portable build artifact |
| Manual **Run workflow** | Checks and a portable build artifact |
| Push of a matching `v<version>` tag | Checks, artifact verification and GitHub release publication |

A successful branch build or manual dispatch does not publish a release.
Follow the run associated with the pushed tag.

## What the publishing workflow does

The tagged workflow has three jobs:

| Job | Responsibility |
| --- | --- |
| `build` | Validate tag/version, install and audit the locked environment, run source/tests, build and launch the EXE, measure performance, and record provenance/checksums |
| `release` | Download that run's Windows artifact, verify and package it, then upload and publish the matching release |
| `release-status` | Record build/publication results and the run URL in a Git note, including failures where available |

The release job performs these stages in order:

1. **Verify the bundle.** Check the Windows layout, source commit, Studio version,
   Python/uv identity, locked package versions and Git sources, matching audit,
   complete file inventory and hashes.
2. **Prepare assets.** Package the complete portable folder, including hidden
   runtime directories. Generate the ZIP checksum, release notes and an internal
   release plan outside the application folder.
3. **Check the draft.** Create or reuse a draft whose tag, source commit and
   prerelease status match the plan.
4. **Upload and verify.** Upload the two assets and compare their exact names,
   uploaded state, sizes and GitHub-reported SHA-256 digests with the plan.
5. **Publish and recheck.** Publish the draft, set prerelease/latest status, and
   verify the published metadata and assets again.

Release write permissions are limited to the publishing and status-receipt jobs.
The workflow can replace assets in a matching draft; it refuses to overwrite an
already published release. Prepublication failures stop publication. A failure
in the final recheck can occur after the release is public; inspect its actual
state as described below.

## Verify publication

### Release page and download

Confirm that the tagged workflow's `release` job succeeded and inspect the
[GitHub releases page](https://github.com/biomarkersParkinson/ParaDigMa-Studio/releases).
Check the tag, source commit, release notes and prerelease/stable status. The
public assets are:

| Asset | Contents |
| --- | --- |
| `ParaDigMaStudio-<version>-Windows-x64.zip` | Complete portable app under `ParaDigMaStudio/` |
| `ParaDigMaStudio-<version>-SHA256SUMS.txt` | SHA-256 of that ZIP |

Download both assets and compare the ZIP's SHA-256 with the checksum file.
After extraction, `security/build-info.json` identifies the source and build
environment; the folder's `SHA256SUMS.txt` inventories its files. Keep `_internal`,
notices and security evidence with the EXE. The
[dependency guide](DEPENDENCIES.md#evidence-included-in-the-portable-folder)
explains the shipped evidence, and [Security](../SECURITY.md#release-verification)
links the dated checks on the first published candidate.

The [CI artifacts](DEVELOPMENT.md#ci-artifacts) retain build, test, dependency and
performance reports separately. Use the public release ZIP for acceptance of the
published download.

### Git-only status receipts

When the GitHub API is unavailable, fetch the workflow's Git notes. For the
published `v1.0.0rc1` example:

```bash
git fetch origin refs/notes/paradigma-releases:refs/notes/paradigma-releases
git notes --ref=paradigma-releases show 'v1.0.0rc1^{}'
```

Substitute the tag being investigated. `^{}` selects the commit behind an
annotated tag. The note records the tag/commit, build and publication results,
release/workflow URLs, archive checksum and failed steps when available.
A rerun can replace the note on that source commit; inspect its tag and run URL.

These notes are CI receipts, not signatures. Their publication status records
the release job's conclusion; check the release page if a failure occurred after
publication or the receipt could not be written.

## Retry or investigate a failure

| Situation | Next step |
| --- | --- |
| Build, audit or tests failed | Inspect the failing step and retained reports. Retry transient failures with **Re-run failed jobs**; source fixes need a newly prepared version/tag. |
| Upload/publication stopped with a matching draft | Use **Re-run failed jobs** on the same tagged workflow. The retry verifies the draft before replacing its assets. |
| Existing draft has a different source or preview status | Inspect the draft and release plan. The workflow rejects the mismatch before uploading. |
| Release is public but the final verification failed | Inspect the published metadata/assets and the failed step. A retry will refuse to overwrite the public release; content corrections require a new version. |
| Only `release-status` failed, or its note is missing | Inspect the `release` job and public page directly; receipt failure alone does not establish publication failure. |
| Build passed but no release job ran | Check that the event was a tag push; branch builds and manual dispatches only produce artifacts. |

A retry uses the same tagged source. Keep published tags and downloads unchanged;
prepare a new candidate or stable version for fixes.

## Signed builds

The ordinary tag-driven release publishes an **unsigned Studio build**. Publisher
signing has a separate manual
[Windows signed desktop workflow](../.github/workflows/windows-signed.yml), run
from `main`. It builds, signs and verifies the app before producing the
`ParaDigMaStudio-Windows-Signed` artifact; it does not run the public-release
publishing job described above.

Account setup, publisher verification, workflow isolation and current validation
status are maintained in [Signing](../SIGNING.md). Follow that guide for
publisher-signed artifacts and their verification evidence.
