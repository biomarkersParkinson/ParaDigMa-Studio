# Contributing to ParaDigMa Studio

Start with the [documentation index](docs/README.md). The
[development guide](docs/DEVELOPMENT.md) describes the reviewed environment,
source setup, packaging and quality checks.

## Report a problem

Use the [bug-report form](https://github.com/biomarkersParkinson/ParaDigMa-Studio/issues/new?template=bug_report.yml)
for application bugs and unexpected scientific output. Include the Studio and
Windows versions, relevant settings, reproduction steps and expected behavior.
Small synthetic examples are useful; remove personal recordings, subject
information and identifying paths from logs and screenshots.

Report suspected vulnerabilities through the
[security policy](SECURITY.md#reporting-a-vulnerability).

## Propose a change

For substantial UI, scientific or storage changes, discuss the problem and
proposed behavior in an issue before implementation. Keep pull requests focused
and explain the resulting behavior and relevant validation. Follow the
[coding conventions](docs/DEVELOPMENT.md#quality-gates-and-implementation-conventions)
and [architecture boundaries](docs/ARCHITECTURE.md).

Run checks appropriate to the change and report their results. Changes to
preparation, processing or outputs need the independent scientific comparisons;
packaging changes need the packaged executable checks. The
[test guide](docs/TEST_SUITE.md) maps responsibilities to tests. CI runs the full
Windows suite and its coverage gate. The
[pull-request checklist](.github/PULL_REQUEST_TEMPLATE.md) includes documentation
and compatibility considerations.

## Maintaining documentation

Keep each detailed policy or contract in its owning guide and link to it from
other guides. User-facing instructions can state the relevant behavior without
repeating the implementation specification.

| Information | Maintained in |
| --- | --- |
| Download/version and concise introduction | `README.md`; version policy in `docs/RELEASES.md` |
| Current user workflow and explanations | `docs/USER_GUIDE.md` and the app's field help |
| Guide navigation | `docs/README.md` |
| Environment and dependency updates | `docs/DEPENDENCIES.md` |
| Setup, coding limits and typing policy | `docs/DEVELOPMENT.md` |
| Module locations and composition rules | `docs/REPOSITORY.md` |
| Component behavior and lifecycle | `docs/ARCHITECTURE.md` |
| Service and persistence contracts | `docs/PYTHON_API.md`, checked against the implementing code |
| Test coverage/helpers and scientific methodology | `docs/TEST_SUITE.md` and `docs/SCIENTIFIC_TESTS.md` |
| Runtime behavior and benchmark commands | `docs/PERFORMANCE.md` |
| Vulnerability reporting and current trust boundaries | `SECURITY.md` |
| Dated audit results, measurements and old screenshots | `docs/archive/`, with its index updated |

When behavior changes, review the relevant guide, field help, changelog and
screenshots. Refresh the [user-guide captures](docs/images/user-guide/README.md)
through the existing capture script and inspect the results. Keep the Data,
Analyze, Results and Runs chapter structure.

The current-source guide covers `main`. Download instructions link to the guide
at the published release tag; update that link when preparing a new release.
Preserve dated evidence with its original results and scope. New verification
gets a new dated record rather than replacing earlier measurements.

## Documentation checks

The separate **Documentation** workflow uses standard tools: markdownlint-cli2
**0.18.1** on Node.js 22 and lychee **0.21.0**. They run outside Studio's Python
environment and application bundle. Install lychee through its
[official instructions](https://github.com/lycheeverse/lychee/blob/lychee-v0.21.0/README.md#installation).

From the repository root, in Bash or Git Bash:

```bash
npm exec --yes --package markdownlint-cli2@0.18.1 -- markdownlint-cli2
git ls-files --cached --others --exclude-standard '*.md' | lychee --config .lychee.toml --files-from -
```

Markdown lint checks the maintained guides, contribution template and archive
index. Historical reports keep their original formatting. Lychee checks local
file, image and heading-fragment links in all repository Markdown, including the
archive; the local command also includes new files before they are committed.
The shared configuration runs offline, so external websites do not determine the
CI result. Review changed external URLs and release-tag links when publishing.
