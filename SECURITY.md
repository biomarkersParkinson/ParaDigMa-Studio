# Security review and safe testing

This is a focused source, dependency and build review performed on 6 October 2026. It is not a security certification, a full audit of upstream libraries, or a guarantee that the Windows executable cannot cause harm.

## Scope and findings

Reviewed the desktop interface, file loaders and their upstream entry points, analysis orchestration, CSV/JSON export, diagnostic writes, PyInstaller configuration, bundled classifier loading, and GitHub Actions workflow. Ran a Bandit source scan and a pip-audit scan of the installed Python distributions. Source checks and packaged application checks run on Linux locally; the workflow runs Windows executable checks.

The application's source has no network-upload functionality, administrator request, registry modification, service installation, scheduled task, shell-command execution based on recording contents, or destructive filesystem traversal. This observation applies to the reviewed wrapper and inspected loader paths; it is not proof about every line of every dependency. Development scripts launch Python/PyInstaller or the explicitly selected executable through argument lists without a shell. Bandit flags those subprocess calls as low-severity review items; their inputs are build/developer choices, not sensor-file contents.

| Finding | Change or disposition |
| --- | --- |
| Pickle input executes Python code during deserialization | Backend rejects pickle by default. The GUI enables it only after explicit confirmation of trust. CSV/Parquet avoid this deserialization behavior. A confirmed pickle can still execute arbitrary code. |
| Formula-like text in CSV exports can be interpreted by spreadsheet software | Prefix potentially active text cells and headers with an apostrophe, including formulas with leading whitespace. Actual numeric values remain unchanged. JSON retains the original text. This mitigation depends on the spreadsheet application's import behavior. |
| Exports could overwrite the loaded recording or leave partial destination files after failure | Block export to the source file, including hardlink/symlink aliases resolved by the OS. Write to a unique temporary file and replace the output only after a successful write. Other existing destinations still require care: the GUI asks before overwriting them. |
| Predictable shared directory for diagnostic files | Default analysis uses a unique temporary directory that is cleaned after each run. Close newly created log handlers even if the pipeline raises an exception. The UI processing log is retained in local run metadata. Explicit developer `output_dir` overrides still persist logs to the caller's chosen path. |
| Dependency versions and Actions tags could change between builds | Pin primary app and packaging dependencies to reviewed versions. Pin Actions to exact commits, limit the workflow token to read-only repository contents, and disable persistence of checkout credentials. Transitive dependencies can still change; audit and record the actual installed versions on each build. |
| Known vulnerabilities reported for the old pip installer | Upgrade the development/build installer to pip 26.2 or newer. pip is build tooling; this finding does not mean the executable was observed exploiting these issues. |
| Arrow C++ advisory CVE-2026-25087 / PYSEC-2026-113 for pyarrow 22 | Reviewed exception described below; retained visibly in the audit report. |
| Unsigned binary and third-party package/model trust | Still present. Record the source commit, installed package versions, dependency audit and SHA-256 hashes in the artifact. These records help inspection but do not authenticate the publisher or prevent a compromised build. |
| Artifact upload could omit hidden native runtime directories | Explicitly include hidden files from the narrowly scoped `dist/ParaDigMaStudio/` bundle. This retains required folders such as `sklearn/.libs` without uploading the source checkout or its credentials. |

Version 0.2.0 adds local run history under the user's local data directory (`%LOCALAPPDATA%\ParaDigMaDesktop\runs` on Windows). History JSON includes source paths, settings, status, warnings, processing logs and export locations, so these details now persist after closing the app. Original sensor frames and full results are held in memory and excluded from history files. Reopening saved results reads explicitly exported JSON, never automatically deserializes original sensor files, and does not rerun analysis. Exports protect both the source of the displayed results and the currently loaded input, including TSDF companions and filesystem aliases. No scientific algorithm or network-upload behavior is introduced by the redesign.

## Dependency audit exception

[CVE-2026-25087](https://www.cve.org/CVERecord?id=CVE-2026-25087) concerns Arrow C++ IPC-file reading with pre-buffering enabled through `RecordBatchFileReader::PreBufferMetadata`. The advisory explicitly states that this API is not exposed in Python bindings and those bindings are not vulnerable. The application uses Python Parquet loading, not that C++ IPC API. ParaDigMa 1.1.2 requires pyarrow below version 23, while the C++ fix is in 23.0.1.

The build audit accepts only this identified advisory on the `pyarrow` package. It preserves the original finding and adds the reason in `security/dependency-audit.json`; other vulnerabilities and skipped package audits fail the build. This is an applicability assessment, not a patched Arrow C++ version. Reassess it if the app starts using C++ IPC pre-buffering or if the advisory changes. At review time pip-audit reported this same advisory twice under the same identifier; both entries are retained.

## What the build checks

Before uploading the Windows artifact, CI runs dependency auditing, regression tests, verifies required scikit-learn DLLs, and launches the frozen executable away from the source checkout. The executable probe loads all four bundled classifiers, runs tremor extraction on synthetic samples, renders a Qt plot, and verifies exported results. Regression tests cover default rejection of a pickle with a harmless file-writing deserialization payload, spreadsheet-formula text, source-file aliases, failed export preservation and diagnostic cleanup.

After building, the artifact contains `security/build-info.json`, `security/dependency-audit.json` and `SHA256SUMS.txt`. To check an executable's hash in PowerShell, run:

```powershell
Get-FileHash .\ParaDigMaStudio.exe -Algorithm SHA256
```

Compare it with the `ParaDigMaStudio.exe` entry in `SHA256SUMS.txt`. A matching hash establishes agreement with that manifest, not independent trust: someone who can replace the artifact could replace its manifest too. Keep the entire extracted folder together and download it directly from the expected repository/run.

Local validation for this review: 25 tests passed; the dependency audit checked 86 installed packages with no blocking findings and the single distinct Arrow exception above; Bandit reported no medium/high-severity findings and nine low-severity subprocess review items. The rebuilt Linux executable loaded all four classifiers, produced 29 quantified tremor windows, rendered the plot and verified JSON export. All 2,385 files listed in the generated bundle manifest matched their SHA-256 hashes. These results are Linux validation, not a scan of a downloaded Windows artifact.

## Publisher verification and Smart App Control

The current Windows build has no publisher signature. Smart App Control can therefore refuse to run it because its publisher cannot be verified. A successful CI build, malware scan or matching hash does not provide a signing identity. Rebuilding the same unsigned application does not resolve that requirement.

Publisher signing requires a trusted code-signing certificate or a signing service with identity verification, neither of which is configured here. A self-signed certificate is insufficient to establish publisher trust on a recipient's standard Windows installation. All executable components and native dependencies need consideration; a signed launcher alone does not guarantee acceptance of the whole bundle.

For development, run the source with a verified Python installation using `python.exe desktop.py` from the repository directory. This avoids the generated desktop launcher, but Smart App Control may still block unsigned native dependencies. A disposable VM or Windows Sandbox can provide a separate environment for testing. Keep the host's Smart App Control and Defender protections enabled; this repository does not provide a bypass or a script to weaken those settings.

## First run on Windows

Run with a normal user account, without administrator elevation. Keep Microsoft Defender enabled. In Windows Security, use Virus & threat protection → Scan options → Custom scan to scan the extracted application folder. No Defender scan of the Windows artifact or test on the user's computer was performed by this cloud review.

For stronger isolation, use a disposable VM or Windows Sandbox. Sandbox availability depends on Windows edition and virtualization support; enabling it is a separate Windows configuration step. A VM is an alternative if Sandbox is unavailable.

Once Windows Sandbox is installed, save this as `ParaDigMa-test.wsb`, replacing `YOUR_USER` and the host folder with the actual extracted app location. Put **copies of non-sensitive test recordings** in that folder first.

```xml
<Configuration>
  <Networking>Disable</Networking>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <VGpu>Disable</VGpu>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>C:\Users\YOUR_USER\Downloads\ParaDigMaStudio-Windows</HostFolder>
      <SandboxFolder>C:\App</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>C:\App\ParaDigMaStudio.exe</Command>
  </LogonCommand>
</Configuration>
```

Double-click the `.wsb` file. Open a CSV recording from `C:\App`, run analysis, inspect results, and export to the **Sandbox's own Desktop**, not the read-only shared folder. Close Sandbox afterward; its local files are discarded. Do not map your whole home directory or enable network/clipboard sharing for this first test. [Microsoft's Sandbox configuration documentation](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file) describes these settings.

## CWA reader revision

Version 0.1.3 uses the official Open Movement repository at commit `087ac7b5a80b866c400d8021b7a2716d247fc034` to fix NumPy 2 timestamp arithmetic in its older PyPI release. Both distributions identify themselves as 0.0.1. Build manifests now also record VCS commit IDs, so the source revision remains distinguishable from the PyPI release. The dependency audit still checks known advisories for the package/version; it does not audit that repository's complete source history. Installation needs Git and network access to the official repository; running the packaged application does not.

The executable smoke test additionally loads the unmodified public ParaDigMa CWA example, runs gait analysis and renders its result plot. The recording's origin, hash and Apache 2.0 license accompany it in the bundle.

## Remaining risks and limits

The optional manual signing workflow is described in [SIGNING.md](SIGNING.md). It requires a verified Public Trust publisher account and a GitHub `windows-signing` environment restricted to `main`. Only the signing job receives OIDC permission; application execution occurs in a separate job. Existing valid vendor signatures and classifier/resource hashes are checked, invalid signatures stop signing, and final checksums are generated after signatures are added. Ordinary push/PR artifacts remain unsigned. Actual signing and recipient Smart App Control acceptance remain unverified until the external account is configured and the Windows workflow succeeds.

Version 0.1.5 adds explicit exclusion of missing/non-finite required samples, enabled by default in the GUI and logged with counts. The source file is unchanged. Analysis runs valid sections independently across excluded stretches and enabled time gaps; original missing samples are not replaced with generated sensor values. The exclusion count and analyzed sample count are retained in output metadata. Missing time differences remain an error because their elapsed duration cannot be inferred.

Version 0.1.4 adds an Empatica IMU adapter that reads Avro with the same Apache Avro library used by ParaDigMa, follows its device-loading tutorial and makes gyroscope data optional. Import does not execute pickle or recording-supplied code. The adapter validates channel lengths, finite samples, conversion parameters and matching IMU timelines, and rejects multi-record files instead of silently dropping records. The public example and license are bundled for the executable check. This change does not add support for treating processed BVP as raw green PPG.

- The application runs with the launching user's permissions; it is not itself a security sandbox. Administrator execution would increase the possible impact of a defect.
- Confirmed pickle input and bundled toolbox classifier pickles remain executable deserialization. Trust the input's source and the application/dependency distribution; a warning does not make an untrusted pickle safe.
- Native Qt, NumPy, SciPy, Arrow and other parsers were not exhaustively audited or fuzz-tested. Malformed or extremely large recordings can cause crashes, high memory use or long processing. Analysis has no hard resource limits or enforced timeout.
- No manual Windows Sandbox test, Microsoft Defender scan, code-signature validation, network-isolation test or complete audit of every dependency was performed in this Linux cloud environment. Windows CI checks run on a build runner, which differs from an ordinary user's machine.
- Dependency advisory databases cannot detect all malicious packages or unknown vulnerabilities. A compromised PyPI package, GitHub account or build runner remains a supply-chain risk. Full dependency locking with artifact hashes and publisher code signing are not implemented.
- Exports can include recording paths, metadata and original text. Handle patient recordings and exported results according to their confidentiality requirements. Do not submit private recordings to public malware-analysis services.

Use the latest successful build containing these changes for testing. A security review cannot retroactively change an executable already downloaded.

## Version 0.5.0 run controls and exports

Analysis runs in an owned child process. Stop terminates that process, rather than
Qt's thread or unrelated programs. The parent owns a unique temporary directory and
removes it after success, failure or cancellation. Internal pickle files transfer
only the already-loaded frames and results between those processes; these are
private generated files, not automatically opened user recordings.

Delete Run requires explicit confirmation and deletes the history entry and exact
associated export paths. It does not traverse directories. Source recordings, TSDF
companion binaries, filesystem aliases of those inputs, and exports shared with
other history entries are protected. Running jobs cannot be deleted.

Selective JSON/CSV/ZIP exports use the existing atomic-write and source-protection
rules. CSV contents retain formula neutralization; ZIP member names are generated
from fixed table keys with safe characters, never used as extraction paths.
