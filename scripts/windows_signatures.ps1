# Read signatures without launching any executable in the bundle.
param(
    [Parameter(Mandatory = $true)][string]$Inventory,
    [Parameter(Mandatory = $true)][string]$Report
)
$ErrorActionPreference = 'Stop'
$entries = Get-Content -LiteralPath $Inventory -Raw | ConvertFrom-Json
$results = foreach ($entry in $entries) {
    $signature = Get-AuthenticodeSignature -LiteralPath $entry.absolute_path
    [ordered]@{
        path = $entry.path
        status = $signature.Status.ToString()
        signature_type = $signature.SignatureType.ToString()
        subject = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
        thumbprint = if ($signature.SignerCertificate) { $signature.SignerCertificate.Thumbprint } else { $null }
        timestamp_subject = if ($signature.TimeStamperCertificate) { $signature.TimeStamperCertificate.Subject } else { $null }
    }
}
ConvertTo-Json -InputObject @($results) -Depth 6 | Set-Content -LiteralPath $Report -Encoding utf8
