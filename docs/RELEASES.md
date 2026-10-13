# Releases

Public versions use Python-compatible version numbers and matching Git tags:
`0.6.0a1` / `v0.6.0a1`. Alpha (`a`), beta (`b`) and release-candidate (`rc`)
versions are published as GitHub prereleases; ordinary versions are stable releases.

1. Update `pyproject.toml`, the README version/download and `CHANGELOG.md`.
2. Run Ruff, formatting, mypy and the complete test suite, including the smoke check.
3. Merge the preparation into `main`; create an annotated `v<version>` tag on that
   exact commit and push the tag. Never move a published release tag.
4. The tagged **Windows desktop** workflow audits dependencies, runs tests, builds
   and launches the executable, checks the bundle, and records provenance/checksums.
5. Its release job downloads that run's Windows artifact, verifies its source
   commit, version, file inventory and hashes, and packages the complete portable folder.
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
git notes --ref=paradigma-releases show 'v0.6.0a1^{}'
```

These notes are CI receipts, not signatures. The portable folder's
`security/build-info.json` and `SHA256SUMS.txt` identify and checksum its actual contents.
