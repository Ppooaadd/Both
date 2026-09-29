#!/bin/sh
# Exit 0 if two containers on a fresh bridge network can talk to each other.
# Uses the already-built api image, so no download is needed.
IMG="${1:-pianoforge/api:local}"
NET=pf-netcheck
SRV=pf-netcheck-srv
cleanup() { docker rm -f "$SRV" >/dev/null 2>&1; docker network rm "$NET" >/dev/null 2>&1; }
cleanup
docker network create "$NET" >/dev/null 2>&1 || exit 1
trap cleanup EXIT
docker run -d --name "$SRV" --network "$NET" --entrypoint python "$IMG" \
  -m http.server 8080 >/dev/null 2>&1 || exit 1
sleep 2
docker run --rm --network "$NET" --entrypoint python "$IMG" -c \
  "import urllib.request; urllib.request.urlopen('http://$SRV:8080', timeout=8)" >/dev/null 2>&1
