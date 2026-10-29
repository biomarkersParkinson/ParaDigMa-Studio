# Releases

Public versions use Python-compatible version numbers and matching Git tags:
`1.0.0rc1` / `v1.0.0rc1`. Alpha (`a`), beta (`b`) and release-candidate (`rc`)
versions are published as GitHub prereleases; ordinary versions are stable releases.

The first 1.0 candidate is `1.0.0rc1`. Its
[verification record](RELEASE_CANDIDATE.md) separates completed source checks from
Windows artifact checks and manual acceptance. Preparing the version does not
publish a download: pushing its tag starts the publishing workflow below.

1. Update `pyproject.toml`, the README version/download and `CHANGELOG.md`.
   Run `uv lock` to refresh the root project version while retaining dependency pins.
   Point the README and documentation index to the user guide at the new release
   tag. Label the guide on `main` as current source, review its text/captures and
   run the [documentation checks](../CONTRIBUTING.md#documentation-checks).
2. Install the [reviewed dependency lock](DEPENDENCIES.md) in a clean
   environment; verify it with `uv sync --locked --all-groups --check` and
   run the dependency audit. Run the [development checks](DEVELOPMENT.md):
   module-size, Ruff/format, mypy and the full suite with branch coverage and its
   configured floor. The tagged workflow also verifies the packaged executable.
3. Merge the preparation into `main`; create an annotated `v<version>` tag on that
   exact commit and push the tag. Never move a published release tag.
4. The tagged **Windows desktop** workflow audits dependencies, runs tests, builds
   and launches the executable, checks the bundle, and records provenance/checksums.
5. Its release job downloads that run's Windows artifact, verifies its source
   commit, version, locked dependency versions, matching audit, file inventory
   and hashes, and packages the complete portable folder.
   It uploads the ZIP and ZIP checksum to a draft, verifies the uploaded asset
   digests, then publishes. A failed build or verification leaves the release unpublished.

Release write permissions are limited to publishing and the status-receipt jobs.
Published assets are never overwritten by the workflow. Failed draft publication
can be retried using **Re-run failed jobs**; inspect the draft if its source differs.
Signing remains a separate workflow; an ordinary release is explicitly unsigned.

The workflow records its publication result and run URL in Git notes under
`refs/notes/paradigma-releases`. This lets a cloud workspace verify completion
through Git when GitHub API access is unavailable:

```bash
git fetch origin refs/notes/paradigma-releases:refs/notes/paradigma-releases
git notes --ref=paradigma-releases show 'v1.0.0rc1^{}'
```

These notes are CI receipts, not signatures. The portable folder's
`security/build-info.json` and `SHA256SUMS.txt` identify and checksum its actual contents.
