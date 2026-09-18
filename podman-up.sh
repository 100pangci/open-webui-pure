#!/usr/bin/env bash
# Start (or recreate) the Open WebUI container with a working proxy configuration.
#
# Why this script exists:
#   - Inside the container, 127.0.0.1 is the container itself, not the host.
#   - On this machine host.containers.internal (pasta 169.254.1.2) is unreachable,
#     so the only working address for the host's v2rayN proxy is the host LAN IP.
#   - The LAN IP changes between office/home networks, so detect it at start time.
set -euo pipefail
cd "$(dirname "$0")"

HOST_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit }}')"
[ -n "${HOST_IP:-}" ] || HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

if [ -n "${HOST_IP:-}" ] && timeout 2 bash -c 'exec 3<>/dev/tcp/127.0.0.1/10808' 2>/dev/null; then
	export WEBUI_CONTAINER_HTTP_PROXY="http://${HOST_IP}:10808"
	echo "Container proxy: ${WEBUI_CONTAINER_HTTP_PROXY} (v2rayN detected on host)"
else
	export WEBUI_CONTAINER_HTTP_PROXY=""
	echo "Container proxy: disabled (v2rayN not listening on host:10808)"
fi

podman compose -f podman-compose.yaml up -d
echo "Open WebUI: http://localhost:${OPEN_WEBUI_PORT:-3000}"
