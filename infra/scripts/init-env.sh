#!/bin/sh
# Create infra/.env from the example with random secrets (never overwrites secrets).
# In GitHub Codespaces, also point WEB_ORIGIN at the forwarded HTTPS address of APP_PORT.
set -eu
cd "$(dirname "$0")/.."

rand() { head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "$1"; }

if [ ! -f .env ]; then
  sed \
    -e "s|^STORAGE_SECRET_KEY=.*|STORAGE_SECRET_KEY=$(rand 32)|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand 32)|" \
    -e "s|^PF_JWT_SECRET=.*|PF_JWT_SECRET=$(rand 48)|" \
    .env.example > .env
  chmod 600 .env
  echo "Created infra/.env with random secrets."
fi

if [ -n "${CODESPACE_NAME:-}" ] && [ -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
  port=$(sed -n 's/^APP_PORT=//p' .env)
  origin="https://${CODESPACE_NAME}-${port:-3000}.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
  if ! grep -qx "WEB_ORIGIN=${origin}" .env; then
    sed -i "s|^WEB_ORIGIN=.*|WEB_ORIGIN=${origin}|" .env
    echo "Codespaces detected: WEB_ORIGIN=${origin}"
  fi
fi
