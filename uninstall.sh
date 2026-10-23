#!/usr/bin/env bash
# Stops and removes the containers. Without --purge, volumes (database and history) and the secret are kept.
set -Eeuo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ "${1:-}" == --purge ]]; then
  docker compose down --volumes --rmi local
  rm -rf secrets
  echo "Removed, including database, history, local image and secret (--purge)."
else
  docker compose down
  echo "Containers removed. Database, history and secret were kept; use --purge to remove everything."
fi
