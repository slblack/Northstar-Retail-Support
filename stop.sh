#!/usr/bin/env bash
# Stops and removes the Northstar Retail Support container (macOS / Linux).
# Saved settings and API keys stay in the "northstar-data" Docker volume.
#   bash stop.sh [--delete-saved-settings]
set -euo pipefail
NAME="northstar-retail-support"
command -v docker >/dev/null || { echo "Docker was not found." >&2; exit 1; }
if [ -n "$(docker ps -a --filter "name=^/${NAME}\$" --format '{{.ID}}' 2>/dev/null)" ]; then
  docker rm -f "$NAME" >/dev/null
  echo "Stopped and removed the $NAME container."
else
  echo "No $NAME container is running."
fi
if [ "${1:-}" = "--delete-saved-settings" ]; then
  docker volume rm northstar-data >/dev/null 2>&1 || true
  echo "Deleted the saved settings volume (northstar-data), including saved API keys."
else
  echo "Saved settings and API keys are kept for next time."
fi
