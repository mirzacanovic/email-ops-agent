#!/usr/bin/env bash
# Wipe all container state and rebuild fresh, so a demo always starts
# from the same clean slate (empty CRM, empty audit log).
set -euo pipefail

cd "$(dirname "$0")/.."

scripts/release_demo_emails.sh reset

docker compose down -v
docker compose up --build -d

echo "Waiting for app-db to accept connections..."
until docker compose exec -T app-db pg_isready -U "${APP_DB_USER:-appuser}" >/dev/null 2>&1; do
  sleep 1
done

echo "Stack is up. EspoCRM: http://localhost:${ESPOCRM_PORT:-8080}  App: http://localhost:${APP_PORT:-8000}"
echo "Run scripts/seed_espocrm.py once you've generated an EspoCRM API key."
