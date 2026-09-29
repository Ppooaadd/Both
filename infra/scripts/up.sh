#!/bin/sh
# Build and start the stack. Picks bridge networking, or the host-network overlay
# when containers cannot reach each other over the bridge.
#   sh infra/scripts/up.sh [gpu]
set -u
cd "$(dirname "$0")/../.."
sh infra/scripts/init-env.sh || exit 1

FILES="-f infra/docker-compose.yml"
[ "${1:-}" = "gpu" ] && FILES="$FILES -f infra/docker-compose.gpu.yml"
compose() { docker compose $FILES $HOST_FILE --env-file infra/.env "$@"; }

HOST_FILE=""
[ -f infra/.host-network ] && HOST_FILE="-f infra/docker-compose.host.yml"

[ -n "${PF_SKIP_BUILD:-}" ] || compose build || exit 1

if [ -z "$HOST_FILE" ]; then
  echo "Checking container networking..."
  if sh infra/scripts/netcheck.sh; then
    echo "  bridge network OK"
  else
    echo "  containers cannot reach each other over the bridge network;"
    echo "  switching to host networking (infra/.host-network)."
    touch infra/.host-network
    HOST_FILE="-f infra/docker-compose.host.yml"
    docker compose $FILES --env-file infra/.env down --remove-orphans >/dev/null 2>&1
  fi
fi

if ! timeout 420 docker compose $FILES $HOST_FILE --env-file infra/.env up -d; then
  echo
  echo "Startup did not finish in time or failed."
  sh infra/scripts/diagnose.sh
  exit 1
fi
# The Caddyfile is bind-mounted; compose does not notice edits to it.
docker compose $FILES $HOST_FILE --env-file infra/.env restart caddy >/dev/null 2>&1
echo
echo "  PianoForge is running: $(sed -n 's/^WEB_ORIGIN=//p' infra/.env)"
echo
