#! /usr/bin/env sh

# Lanza los tests del backend contra la base de pruebas desechable de compose.test.yml
set -e
set -x

cd "$(dirname "$0")/.."
docker compose -f compose.test.yml up -d --wait
# Elimina la base de pruebas al terminar, también si los tests fallan
trap 'docker compose -f compose.test.yml down -v' EXIT
(cd backend && uv run bash scripts/test.sh "$@")
