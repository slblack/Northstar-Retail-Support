<#
.SYNOPSIS
  Exports the CA certificates your network uses to re-sign HTTPS traffic (for example Cisco Secure
  Access / Umbrella, Zscaler) to certs\network-root-ca.pem, so the container can trust them.

.DESCRIPTION
  Opens a TLS connection to the host (default api.openai.com) and reads the certificate chain that
  Windows builds for it using its own trust store. It writes every CA certificate in that chain
  (intermediates and root) - never the site's own certificate - as PEM. If Windows cannot supply
  the issuing CAs, it looks in the Windows certificate stores for the issuer by name. It changes no
  system settings and sends no data beyond a normal TLS handshake.

  Confirm with your IT/security team that the exported certificates are your organisation's
  expected inspection CAs before trusting them.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\export-network-root-ca.ps1
#>
param(
  [string]$HostName = "api.openai.com",
  [string]$OutFile = (Join-Path $PSScriptRoot "..\certs\network-root-ca.pem")
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Security
$X509 = [System.Security.Cryptography.X509Certificates.X509Certificate2]

function Test-IsCA($cert) {
  foreach ($ext in $cert.Extensions) {
    if ($ext -is [System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]) {
      return $ext.CertificateAuthority
    }
  }
  # No basic constraints: treat self-signed certificates as CAs, anything else as not.
  return ($cert.Subject -eq $cert.Issuer)
}

function Find-InStores($subject) {
  foreach ($loc in "CurrentUser", "LocalMachine") {
    foreach ($store in "Root", "CA", "AuthRoot") {
      $hit = Get-ChildItem -Path "Cert:\$loc\$store" -ErrorAction SilentlyContinue |
        Where-Object { $_.Subject -eq $subject } | Select-Object -First 1
      if ($hit) { return $hit }
    }
  }
  return $null
}

# 1. Connect and capture the chain Windows builds during the handshake. This includes intermediate
#    certificates the server (or inspection proxy) sends, which are not stored in Windows.
$script:handshakeChain = @()
$callback = [System.Net.Security.RemoteCertificateValidationCallback]{
  param($sender, $certificate, $chain, $sslPolicyErrors)
  if ($chain) { foreach ($el in $chain.ChainElements) { $script:handshakeChain += (New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($el.Certificate)) } }
  # Accept only so the chain can be read; nothing is sent over this connection.
  return $true
}
$client = New-Object System.Net.Sockets.TcpClient($HostName, 443)
try {
  $ssl = New-Object System.Net.Security.SslStream($client.GetStream(), $false, $callback)
  $ssl.AuthenticateAsClient($HostName)
  $leaf = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($ssl.RemoteCertificate)
} finally {
  $client.Dispose()
}

# 2. Collect CA certificates from the handshake chain, then from a fresh local chain build.
$cas = @()
function Add-CA($c) {
  if ($c.Thumbprint -ne $leaf.Thumbprint -and (Test-IsCA $c) -and -not ($script:cas | Where-Object { $_.Thumbprint -eq $c.Thumbprint })) { $script:cas += $c }
}
foreach ($c in $script:handshakeChain) { Add-CA $c }
$chain = New-Object System.Security.Cryptography.X509Certificates.X509Chain
$chain.ChainPolicy.RevocationMode = [System.Security.Cryptography.X509Certificates.X509RevocationMode]::NoCheck
[void]$chain.Build($leaf)
foreach ($el in $chain.ChainElements) { Add-CA $el.Certificate }

# 3. Fill any gaps by walking issuers through the Windows certificate stores.
$current = if ($script:cas.Count -gt 0) { $script:cas[-1] } else { $leaf }
for ($i = 0; $i -lt 5 -and $current.Subject -ne $current.Issuer; $i++) {
  $issuer = Find-InStores $current.Issuer
  if (-not $issuer) { break }
  Add-CA $issuer
  $current = $issuer
}

# 4. Last resort: any root in the Windows stores whose name matches the issuing organisation's
#    inspection product (for example "Cisco Secure Access" or "Cisco Umbrella").
if (-not ($script:cas | Where-Object { $_.Subject -eq $_.Issuer })) {
  $hint = if ($leaf.Issuer -match "CN=([^,]+?)\s+(Secondary\s+)?Sub\s*CA") { $Matches[1] } else { $null }
  if ($hint) {
    Write-Host "Searching Windows certificate stores for roots matching '$hint'..."
    foreach ($loc in "CurrentUser", "LocalMachine") {
      foreach ($store in "Root", "AuthRoot") {
        Get-ChildItem -Path "Cert:\$loc\$store" -ErrorAction SilentlyContinue |
          Where-Object { $_.Subject -eq $_.Issuer -and $_.Subject -like "*$hint*" } |
          ForEach-Object { Add-CA $_ }
      }
    }
  }
}

Write-Host "Site certificate presented for ${HostName}:" $leaf.Subject
Write-Host "  issued by:" $leaf.Issuer
if ($script:cas.Count -eq 0) {
  Write-Host ""
  Write-Host "Could not find the issuing CA certificates for this site in Windows." -ForegroundColor Yellow
  Write-Host "Ask IT for your network's inspection root CA (PEM) and save it in the certs folder." -ForegroundColor Yellow
  exit 1
}

$publicRoots = "DigiCert|GlobalSign|Google Trust|Let's Encrypt|ISRG|Sectigo|Baltimore|Amazon|Microsoft"
$pem = ""
Write-Host ""
Write-Host "CA certificates written (confirm these with IT):"
foreach ($c in $script:cas) {
  $b64 = [Convert]::ToBase64String($c.RawData, [Base64FormattingOptions]::InsertLineBreaks)
  $pem += "# Subject: $($c.Subject)`n# Issuer:  $($c.Issuer)`n-----BEGIN CERTIFICATE-----`n$b64`n-----END CERTIFICATE-----`n`n"
  $kind = if ($c.Subject -eq $c.Issuer) { "root" } else { "intermediate" }
  Write-Host " - [$kind]" $c.Subject
  Write-Host "   SHA-256:" ($c.GetCertHashString([System.Security.Cryptography.HashAlgorithmName]::SHA256)) " expires:" $c.NotAfter.ToString("yyyy-MM-dd")
}
if (($script:cas | Where-Object { $_.Subject -eq $_.Issuer }).Count -eq 0) {
  Write-Host "Note: no self-signed root was found; the intermediates alone are usually sufficient." -ForegroundColor Yellow
}
if ($leaf.Issuer -match $publicRoots) {
  Write-Host "Note: this site's issuer looks like a public CA, so this traffic may not be inspected." -ForegroundColor Yellow
}

$full = [System.IO.Path]::GetFullPath($OutFile)
New-Item -ItemType Directory -Force -Path (Split-Path $full) | Out-Null
[System.IO.File]::WriteAllText($full, $pem)
Write-Host ""
Write-Host "Written to $full"
