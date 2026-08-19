#!/usr/bin/env bash
# Per-boot startup for Onix System (Cloud Agent): bring up PostgreSQL.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_NAME="onix_system"

PGVER="$(ls /etc/postgresql 2>/dev/null | sort -V | tail -1 || true)"
if [ -n "$PGVER" ]; then
  # Idempotent: no-op if the cluster is already running.
  sudo pg_ctlcluster "$PGVER" main start 2>/dev/null || true
fi

# Wait until PostgreSQL is ready to serve connections.
for _ in $(seq 1 30); do
  if sudo -u postgres pg_isready -q; then break; fi
  sleep 1
done

# Ensure the application database exists (safe if snapshot lacks it).
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  sudo -u postgres createdb "${DB_NAME}"
fi

echo "PostgreSQL ready; Onix System database '${DB_NAME}' available."
