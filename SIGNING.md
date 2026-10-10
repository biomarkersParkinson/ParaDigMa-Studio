# Create a publisher-signed Windows application

The repository includes a manual **Windows signed desktop** workflow using
[Microsoft Artifact Signing](https://github.com/Azure/artifact-signing-action),
formerly Trusted Signing. The integration is prepared; no signing account,
verified publisher identity or signed release has been created by Codex.
Normal push/PR builds continue to produce unsigned artifacts.

## Set up the publisher account

1. Check Microsoft's current [Artifact Signing eligibility and setup guidance](https://learn.microsoft.com/azure/artifact-signing/faq)
   for your country and publisher type before purchasing a plan. The service
   requires an Azure subscription and an eligible individual or organization;
   review the service charges and available plans before activation.
   If you are ineligible, use a trusted code-signing certificate provider instead;
   that would require a different signing-service integration.
2. In the Azure portal, create an Artifact Signing account in a supported region.
   Complete publisher identity validation and create a **Public Trust**
   certificate profile using the validated identity. A Private Trust profile or
   self-signed certificate will not establish public publisher trust.
3. Create a Microsoft Entra application/service principal for this workflow.
   Assign **Artifact Signing Certificate Profile Signer** at the certificate
   profile's scope, without granting the workflow subscription-wide Contributor
   or Owner privileges. See the [official OIDC instructions](https://github.com/Azure/artifact-signing-action/blob/c7ab2a863ab5f9a846ddb8265964877ef296ee82/docs/OIDC.md).
4. Add a federated credential to that application with:

   | Field | Value |
   | --- | --- |
   | Issuer | `https://token.actions.githubusercontent.com` |
   | Subject | `repo:lucevers1991/ParaDigMa-Studio:environment:windows-signing` |
   | Audience | `api://AzureADTokenExchange` |

   If signing was configured before the repository rename, update the existing
   federated credential's subject to the value above.

5. In **this GitHub repository → Settings → Environments**, create the environment
   `windows-signing` and restrict its deployment branches to `main`. This is a
   GitHub Actions environment, separate from the Codex cloud environment.
   The branch restriction matters because the federated credential trusts the
   environment, not a branch claim. Add these environment **variables**:

   | Variable | Value |
   | --- | --- |
   | `AZURE_CLIENT_ID` | Application/client ID of the Entra application |
   | `AZURE_TENANT_ID` | Directory/tenant ID |
   | `AZURE_SUBSCRIPTION_ID` | Azure subscription ID |
   | `SIGNING_ENDPOINT` | Account's regional HTTPS endpoint, e.g. `https://weu.codesigning.azure.net/` |
   | `SIGNING_ACCOUNT_NAME` | Artifact Signing account name |
   | `SIGNING_CERTIFICATE_PROFILE` | Validated Public Trust certificate profile name |
   | `SIGNING_PUBLISHER_SUBJECT` | Exact certificate subject DN shown for that profile, not the app display name |

These identifiers are not passwords or private keys. The workflow authenticates
with GitHub OIDC and does not require uploading a PFX, exporting a private key or
storing a client secret. Account purchase and publisher identity verification
must be completed by the account owner; saving variables alone does not do it.

## Run the signed build

In GitHub **Actions → Windows signed desktop → Run workflow**, select `main`.
It is a manual workflow and does not sign pull-request builds. Non-main dispatches
skip the build. Three jobs perform the work:

1. Build, audit, test and record package/source provenance without signing access.
2. Inventory all native files, including `.exe`, `.dll`, `.pyd`, hidden library
   directories and PE files with other extensions. Preserve existing valid
   embedded vendor signatures, and sign unsigned or catalog-only components
   with SHA-256 and Microsoft's RFC3161 timestamp. Invalid/untrusted existing
   signatures stop the run. Verify the publisher and timestamp of newly signed
   files, every native certificate chain, unchanged vendor files, and unchanged
   classifier/resource assets. Refresh checksums after signing.
3. Recheck signatures and launch the signed application in a separate job without
   signing credentials or OIDC permission. Only after that succeeds, upload
   **ParaDigMaStudio-Windows-Signed** with the complete portable application.

The `unsigned-signing-input` and `signed-verification-input` artifacts are
intermediate inputs with one-day retention. Download the final
`ParaDigMaStudio-Windows-Signed` artifact from a completely successful run.
It includes `security/windows-signatures.json`, source/package provenance and
`SHA256SUMS.txt`. Extract the entire folder and keep `_internal` beside the EXE.

Code signing identifies the verified publisher and detects signed-file changes.
It does not certify the scientific results or prove absence of malware. Smart App
Control, SmartScreen reputation, organizational policies and the recipient's
Windows trust configuration can still affect execution; passing a build-runner
signature check does not guarantee acceptance on every Windows installation.

## Validation status

Linux checks cover file inventory, signing policy, configuration validation,
publisher/timestamp rules, and preservation of vendor/model files. The Windows
test suite additionally exercises the real Authenticode API with an unsigned
compiled assembly. Actual Azure signing, timestamping, certificate-chain checks
and launching a signed Windows application require the configured, verified
account and Windows workflow; these have not been performed in the Linux cloud.
