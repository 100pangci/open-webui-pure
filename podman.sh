#!/usr/bin/env bash
#
# Open WebUI Pure — single Podman entry point.
#
# Usage:
#   ./podman.sh up        Start (builds the image first if it does not exist;
#                         recreates the container when the image changed)
#   ./podman.sh build     Build the image only
#   ./podman.sh update    Rebuild the image and switch the container to it
#   ./podman.sh restart   Restart the container
#   ./podman.sh stop      Stop the container (volume preserved)
#   ./podman.sh down      Stop and remove the container (volume preserved)
#   ./podman.sh logs      Follow the container logs
#   ./podman.sh health    GET /health
#   ./podman.sh shell     Open a shell inside the container
#
# Configuration (environment variables):
#   OPEN_WEBUI_PORT   host port (default 3000)
#   WEBUI_IMAGE       image to run (default "localhost/open-webui:pure"; set
#                     it to a prebuilt image, e.g.
#                     docker.io/ywpc05/open-webui-pure:latest, to skip builds)
#   OPENAI_API_BASE_URL / OPENAI_API_KEY (and *_URLS / *_KEYS for multiple endpoints)
#   WEBUI_SECRET_KEY  JWT signing key; generated into the data volume when unset
#   HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / NO_PROXY
#                     passed to the container as-is. If the proxy runs on the
#                     host, use an address the container can reach (for example
#                     http://host.containers.internal:PORT or the host LAN IP),
#                     never 127.0.0.1 (that is the container itself).
#
# Optional feature build args: WEBUI_ENABLE_POSTGRES, WEBUI_ENABLE_REDIS,
#   WEBUI_ENABLE_AZURE, WEBUI_ENABLE_LDAP, WEBUI_ENABLE_PDF,
#   WEBUI_ENABLE_CODE_FORMAT, WEBUI_ENABLE_PILLOW (all default to false).
#
# The data volume is never removed by this script. To delete the database and
# uploaded files you must remove the volume explicitly.

set -euo pipefail
cd "$(dirname "$0")"

COMPOSE=(podman compose -f docker-compose.yml)
CONTAINER="${WEBUI_CONTAINER_NAME:-open-webui}"
IMAGE="${WEBUI_IMAGE:-localhost/open-webui:${WEBUI_IMAGE_TAG:-pure}}"
export WEBUI_IMAGE="$IMAGE"

container_image_id() {
	podman inspect -f '{{.Image}}' "$CONTAINER" 2>/dev/null || true
}

image_id() {
	podman image inspect -f '{{.Id}}' "$IMAGE" 2>/dev/null || true
}

# `podman compose up` does not recreate a container when the image ID changed
# (the compose config hash is unchanged), and would silently keep running the
# old image. Recreate explicitly in that case.
up() {
	if ! podman image exists "$IMAGE"; then
		echo "Image $IMAGE not found — building it first."
		"${COMPOSE[@]}" build
	fi

	local current desired
	current="$(container_image_id)"
	desired="$(image_id)"

	if [ -n "$current" ] && [ "$current" != "$desired" ]; then
		echo "Image changed ($current -> $desired) — recreating $CONTAINER."
		"${COMPOSE[@]}" up -d --force-recreate
	else
		"${COMPOSE[@]}" up -d
	fi

	echo "Open WebUI: http://localhost:${OPEN_WEBUI_PORT:-3000}"
}

case "${1:-}" in
	up)      up ;;
	build)   "${COMPOSE[@]}" build ;;
	update)  "${COMPOSE[@]}" build; up ;;
	restart) "${COMPOSE[@]}" restart ;;
	stop)    "${COMPOSE[@]}" stop ;;
	down)    "${COMPOSE[@]}" down --remove-orphans; echo "Container removed. The open-webui volume was preserved." ;;
	logs)    "${COMPOSE[@]}" logs -f "$CONTAINER" ;;
	health)  curl --fail --silent "http://localhost:${OPEN_WEBUI_PORT:-3000}/health" && echo ;;
	shell)   podman exec -it "$CONTAINER" bash ;;
	*)
		sed -n '3,30p' "$0" | sed 's/^# \{0,1\}//'
		exit 1
		;;
esac
