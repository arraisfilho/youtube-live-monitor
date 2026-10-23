#!/usr/bin/env bash
# Builds and starts the container stack (Linux or macOS with Docker) and creates the account on first run.
set -Eeuo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
BIND="${YLM_BIND:-127.0.0.1:8082}"

command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker not found." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: Docker Compose plugin not found." >&2; exit 1; }

# Secret that encrypts the YouTube API key in the database. It stays out of Git and of the image.
if [[ ! -s secrets/app_key ]]; then
  install -d -m 0700 secrets
  ( umask 0022; od -An -tx1 -N32 /dev/urandom | tr -d ' \n' > secrets/app_key )
  echo "Application secret created in secrets/app_key. Keep a copy: without it, the saved API key cannot be read."
fi

YLM_BIND="$BIND" docker compose up -d --build

echo "Waiting for the app to become healthy..."
for _ in $(seq 1 60); do
  status="$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q app)" 2>/dev/null || true)"
  [[ "$status" == healthy ]] && break
  sleep 2
done
[[ "$status" == healthy ]] || { echo "ERROR: the app did not become healthy; see: docker compose logs app" >&2; exit 1; }

docker compose exec -T app python -m backend.serve init
echo
echo "Ready: http://$BIND"
echo "Add your YouTube API key in Settings. For external access, put this address behind a reverse proxy with HTTPS."
