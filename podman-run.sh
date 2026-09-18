#!/usr/bin/env bash
# Deprecated entrypoint: use ./podman-up.sh instead, which detects the host LAN
# proxy address and keeps the JWT signing key inside the data volume.
set -euo pipefail
exec "$(dirname "$0")/podman-up.sh" "$@"
