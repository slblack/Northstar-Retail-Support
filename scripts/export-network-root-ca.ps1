<#
.SYNOPSIS
  Exports the root CA certificate that your network presents for api.openai.com (or another host)
  to certs\network-root-ca.pem, for use when HTTPS traffic is inspected by a corporate proxy.

.DESCRIPTION
  Opens a TLS connection using Windows' own trust store, builds the certificate chain and writes
  the chain's root certificate as PEM. It does not change any system settings and sends no data
  beyond a normal TLS handshake. Confirm with your IT/security team that the exported certificate
  is your organisation's expected inspection CA before trusting it.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\export-network-root-ca.ps1
#>
param(
  [string]$HostName = "api.openai.com",
  [string]$OutFile = (Join-Path $PSScriptRoot "..\certs\network-root-ca.pem")
)

$ErrorActionPreference = "Stop"
$client = New-Object System.Net.Sockets.TcpClient($HostName, 443)
try {
  # Accept the presented certificate only so its chain can be read; nothing is sent over this connection.
  $ssl = New-Object System.Net.Security.SslStream($client.GetStream(), $false, { $true })
  $ssl.AuthenticateAsClient($HostName)
  $leaf = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($ssl.RemoteCertificate)
  $chain = New-Object System.Security.Cryptography.X509Certificates.X509Chain
  [void]$chain.Build($leaf)
  $root = $chain.ChainElements[$chain.ChainElements.Count - 1].Certificate
  $b64 = [Convert]::ToBase64String($root.RawData, [Base64FormattingOptions]::InsertLineBreaks)
  $pem = "-----BEGIN CERTIFICATE-----`n$b64`n-----END CERTIFICATE-----`n"
  New-Item -ItemType Directory -Force -Path (Split-Path $OutFile) | Out-Null
  $full = [System.IO.Path]::GetFullPath($OutFile)
  [System.IO.File]::WriteAllText($full, $pem)
  Write-Host "Root CA for $HostName :" $root.Subject
  Write-Host "Issuer:" $root.Issuer
  Write-Host "SHA-256 thumbprint:" ($root.GetCertHashString([System.Security.Cryptography.HashAlgorithmName]::SHA256))
  Write-Host "Written to $full"
} finally {
  $client.Dispose()
}
