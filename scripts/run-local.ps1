# Runs the app without Docker on Windows: creates .venv, installs pinned packages, starts the server.
# Usage (from the project folder):  powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m northstar
