#!/usr/bin/env bash
set -euo pipefail

podman compose -f podman-compose.yaml down --remove-orphans
echo "Open WebUI containers stopped. The open-webui volume was preserved."
