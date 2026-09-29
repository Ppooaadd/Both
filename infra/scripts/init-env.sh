#!/bin/sh
# Create infra/.env from the example with random secrets. Never overwrites.
set -eu
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  echo "infra/.env already exists; leaving it unchanged."
  exit 0
fi
rand() { head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "$1"; }
sed \
  -e "s|^STORAGE_SECRET_KEY=.*|STORAGE_SECRET_KEY=$(rand 32)|" \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand 32)|" \
  -e "s|^PF_JWT_SECRET=.*|PF_JWT_SECRET=$(rand 48)|" \
  .env.example > .env
chmod 600 .env
echo "Created infra/.env with random secrets."
