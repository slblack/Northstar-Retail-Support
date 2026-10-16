#!/usr/bin/env sh
# Runs the app without Docker on macOS/Linux: creates .venv, installs pinned packages, starts the server.
set -eu
cd "$(dirname "$0")/.."
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
exec .venv/bin/python -m northstar
