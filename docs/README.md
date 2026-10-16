# Documentation

| Guide | Purpose |
| --- | --- |
| [User guide](USER_GUIDE.md) | Analysis settings, result interpretation, sensor context, saving, exports and troubleshooting |
| [Development](DEVELOPMENT.md) | Source installation, checks and Windows packaging |
| [Releases](RELEASES.md) | Versioning, checked Windows downloads and publishing |
| [Repository map](REPOSITORY.md) | Folder responsibilities, module boundaries and maintenance conventions |
| [Test suite](TEST_SUITE.md) | Regression coverage map and shared test helpers |
| [Scientific tests](SCIENTIFIC_TESTS.md) | Independent official ParaDigMa comparisons, fixtures, tolerances and limitations |
| [Performance](PERFORMANCE.md) | Runtime behavior, benchmark commands and report locations |

Start with the repository [README](../README.md) to download and run the Windows
app and follow the four-page workflow. Guides describe the current source;
[release notes](../CHANGELOG.md) distinguish published previews from unreleased
changes. [Security](../SECURITY.md), [signing](../SIGNING.md) and the
[Apache 2.0 licence](../LICENSE) are maintained at the repository root.
The [recorded security review evidence](security-review.json) identifies its
reviewed commit, checked versions, source findings and validation outcomes;
it distinguishes source checks from packaged-artifact and Windows checks.
The [performance review evidence](performance-review.json) records baseline/current
measurements, workloads, unchanged output checks and platform limitations.
These reviews are dated snapshots of their stated commits, not fresh checks of
every later revision. Current CI results describe the commit they tested.

The [archive](archive/README.md) preserves earlier audits, measurements and
screenshots. Historical test counts and screenshots describe their original
versions, rather than the current app.
