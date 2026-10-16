# Extra trusted CA certificates (optional)

Only needed if your network inspects HTTPS traffic (for example a corporate proxy that re-signs
certificates), which causes errors such as `CERTIFICATE_VERIFY_FAILED` when the app calls OpenAI
or Cisco AI Defense.

Put your organisation's root CA certificate here as a PEM file (`*.pem` or `*.crt` beginning with
`-----BEGIN CERTIFICATE-----`). Files in this folder are git-ignored. Mount the folder read-only
into the container at `/certs` (see the main README). The app *adds* these certificates to the
standard trust store; it never disables certificate verification.

On Windows you can export the root CA your network presents with `scripts/export-network-root-ca.ps1`.
Check with your IT/security team that it is the correct, expected certificate before trusting it.
