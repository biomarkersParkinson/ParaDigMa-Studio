# Contributing to ParaDigMa Studio

Contributions can be bug reports, fixes, tests, documentation or improvements
to Studio's workflows. This guide explains how to report a problem, prepare a
pull request and maintain the documentation for the current source on `main`.
Use [Development](docs/DEVELOPMENT.md) for environment setup and commands, or the
[documentation index](docs/README.md) to find a specific guide.

- [Report a problem](#report-a-problem)
- [Propose a change](#propose-a-change)
- [Choose the relevant checks](#choose-the-relevant-checks)
- [Maintaining documentation](#maintaining-documentation)
- [Documentation checks](#documentation-checks)

## Report a problem

Use the [bug-report form](https://github.com/biomarkersParkinson/ParaDigMa-Studio/issues/new?template=bug_report.yml)
for application bugs and unexpected scientific output. Include:

- **Environment:** Studio version from About and Windows version; include the
  commit if running from a source checkout.
- **Reproduction:** steps, sensor file format and relevant Analyze or graph
  settings. For processing issues, include units, time format, watch side and
  signal-column choices where relevant.
- **Expected and actual behavior:** describe the difference and any error message.
- **Supporting evidence:** a small synthetic example, relevant processing log or
  screenshot. Remove private recordings, subject information and identifying paths.

Report suspected vulnerabilities through the
[security policy](SECURITY.md#reporting-a-vulnerability), which provides the
private reporting route.

## Propose a change

For substantial UI, scientific or storage changes, discuss the problem and
proposed behavior in an issue before implementation. Keep the scope focused and
link an existing issue when relevant.

1. **Set up a checkout.** Follow the
   [development setup](docs/DEVELOPMENT.md#set-up-the-environment) and work on a
   branch in your checkout or fork.
2. **Make the change.** Use the [repository map](docs/REPOSITORY.md) to find the
   owning modules. Follow the [coding conventions](docs/DEVELOPMENT.md#quality-gates-and-implementation-conventions)
   and [architecture boundaries](docs/ARCHITECTURE.md).
3. **Validate the behavior and guidance.** Use the checks below and update the
   relevant documentation, field help and changelog when behavior changes.
4. **Open a pull request.** Use the [PR template](.github/PULL_REQUEST_TEMPLATE.md).
   Lead with the problem and resulting behavior, explain any effect on inputs,
   scientific outputs or saved data, and report the checks run and platform or
   workload limitations. Include reviewed screenshots when controls or workflows change.

## Choose the relevant checks

| Change | Relevant validation and guidance |
| --- | --- |
| Application code | Tests for the affected behavior, source guards, lint, types and the full suite with coverage; [development checks](docs/DEVELOPMENT.md#run-development-checks) and [test map](docs/TEST_SUITE.md#regression-coverage-map) |
| Preparation, processing or scientific outputs | Independent [scientific comparisons](docs/SCIENTIFIC_TESTS.md), in addition to the relevant application tests |
| UI or graph behavior | Interaction/layout tests and visual review; update affected [user guidance](docs/USER_GUIDE.md) and [screenshots](docs/DEVELOPMENT.md#refresh-user-guide-screenshots) |
| Performance | Relevant correctness/responsiveness regressions and comparable [benchmark measurements](docs/PERFORMANCE.md#investigate-and-compare-results) |
| Dependencies or packaging | [Dependency update checks](docs/DEPENDENCIES.md#update-deliberately) where applicable, plus the [built executable check](docs/DEVELOPMENT.md#build-and-verify-a-windows-executable) |
| Documentation | Markdown/local-link checks below, source verification for technical claims, and review of changed examples or images |

The Windows workflows run the full suite and its
[coverage gate](docs/TEST_SUITE.md#branch-coverage) before packaging. Linux
checks supplement native Windows validation. State which checks you ran and
which platform they exercised; use the [CI reports](docs/DEVELOPMENT.md#ci-artifacts)
to investigate failures.

## Maintaining documentation

### Keep detailed guidance in its owning document

Maintain each policy or contract in its owning guide and link to it elsewhere.
User instructions can explain behavior without repeating its implementation
specification.

| Information | Maintained in |
| --- | --- |
| Downloads and concise introduction | [README.md](README.md) |
| Current user workflow and explanations | [User guide](docs/USER_GUIDE.md) and the app's field help |
| Guide navigation | [Documentation index](docs/README.md) |
| Environment and dependency updates | [Dependencies](docs/DEPENDENCIES.md) |
| Setup, coding limits and typing policy | [Development](docs/DEVELOPMENT.md) |
| Module locations and composition rules | [Repository map](docs/REPOSITORY.md) |
| Component behavior and lifecycle | [Architecture](docs/ARCHITECTURE.md) |
| Service and persistence contracts | [Python API and saved-run formats](docs/PYTHON_API.md), checked against implementing code |
| Test coverage/helpers and scientific methodology | [Test suite](docs/TEST_SUITE.md) and [Scientific tests](docs/SCIENTIFIC_TESTS.md) |
| Runtime behavior and benchmark commands | [Performance](docs/PERFORMANCE.md) |
| Versioning, publication and publisher signing | [Releases](docs/RELEASES.md) and [Signing](SIGNING.md) |
| Vulnerability reporting and current trust boundaries | [Security policy](SECURITY.md) |
| Dated audit results, measurements and old screenshots | [Archive](docs/archive/README.md), with its index updated |

### Update guidance and visual assets together

When behavior changes, review the relevant guide, field help, changelog and
screenshots. Keep the user guide's Data, Analyze, Results and Runs chapters.
Refresh screenshots through the [capture workflow](docs/DEVELOPMENT.md#refresh-user-guide-screenshots),
inspect the full set and update captions and [capture notes](docs/images/user-guide/README.md)
when the demonstrated controls or selections change.

Architecture diagrams retain editable sources beside rendered images. Follow
[their regeneration instructions](docs/images/architecture/README.md), inspect
full-size and narrow views, and commit sources and images together.

### Distinguish current source from release records

Current-source guides describe `main`, including unreleased changes. Download
instructions link to the guide at the published release tag; update that link
when preparing a new release. The [release guide](docs/RELEASES.md#prepare-the-release)
maintains that process.

Preserve dated evidence with its original commit, results and scope. Add a new
dated record for new verification rather than replacing earlier measurements.

## Documentation checks

### Tools and configuration

The separate [Documentation workflow](.github/workflows/documentation.yml) runs
markdownlint-cli2 **0.18.1** with Node.js **22**, and lychee **0.21.0**. These tools
run outside Studio's Python environment and application bundle. Install Node.js
22 and follow lychee's
[installation instructions](https://github.com/lycheeverse/lychee/blob/lychee-v0.21.0/README.md#installation)
for that version.

### Run locally

From the repository root, in Bash or Git Bash:

```bash
npm exec --yes --package markdownlint-cli2@0.18.1 -- markdownlint-cli2
git ls-files --cached --others --exclude-standard '*.md' | lychee --config .lychee.toml --files-from -
```

The local link command includes new files before they are committed.

### Understand the results

| Check | Scope |
| --- | --- |
| Markdown style | [.markdownlint-cli2.yaml](.markdownlint-cli2.yaml) selects maintained guides, the PR template, image notes and archive index. Historical reports retain their original formatting. |
| Local links | [.lychee.toml](.lychee.toml) checks file, image and heading-fragment links in all repository Markdown, including archived reports. |
| External and release-tag links | Review changed URLs and version targets manually; the shared offline configuration does not query external websites. |

Fix local link and formatting failures before submitting Markdown changes.
Passing these checks verifies structure and targets; technical statements,
examples and images still need review against the relevant code or release.
