#!/usr/bin/env bash
# Idempotent environment bootstrap for Onix System (Cloud Agent).
# Installs system packages, Python deps and provisions a local PostgreSQL DB.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DB_NAME="onix_system"
DB_USER="postgres"
DB_PASSWORD="postgres"

echo "== Onix System | Cloud Agent install =="

# 1) System packages (PostgreSQL server + Python build/runtime deps).
# Snapshots that already contain PostgreSQL skip apt entirely; a clean base
# image installs it here, retrying to tolerate transient mirror/proxy errors.
if ! command -v psql >/dev/null 2>&1; then
  apt_install() {
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --fix-missing \
      postgresql postgresql-contrib libpq-dev \
      python3-venv python3-pip build-essential
  }
  installed=0
  for attempt in 1 2 3; do
    sudo apt-get update -qq || true
    if apt_install; then installed=1; break; fi
    echo "apt install attempt ${attempt} failed; retrying..." >&2
    sleep $((attempt * 5))
  done
  if [ "$installed" -ne 1 ]; then
    echo "ERROR: failed to install system packages after retries." >&2
    exit 1
  fi
fi

# 2) Python virtualenv + dependencies.
if [ ! -d "$ROOT/.venv" ]; then
  python3 -m venv "$ROOT/.venv"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install --upgrade pip -q
python -m pip install -q -r "$ROOT/sga_financeiro/requirements.txt"

# 3) Ensure the PostgreSQL cluster is running so we can provision the DB.
PGVER="$(ls /etc/postgresql 2>/dev/null | sort -V | tail -1 || true)"
if [ -n "$PGVER" ]; then
  sudo pg_ctlcluster "$PGVER" main start 2>/dev/null || true
fi

# Wait for the server to accept connections.
for _ in $(seq 1 30); do
  if sudo -u postgres pg_isready -q; then break; fi
  sleep 1
done

# 4) Provision role password and application database (idempotent).
sudo -u postgres psql -c "ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';"
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  sudo -u postgres createdb "${DB_NAME}"
fi

# 5) Local connection config consumed by the app (gitignored).
if [ ! -f "$ROOT/config.local.json" ]; then
  cat > "$ROOT/config.local.json" <<EOF
{
  "db_host": "127.0.0.1",
  "db_port": 5432,
  "db_name": "${DB_NAME}",
  "db_user": "${DB_USER}",
  "db_password": "${DB_PASSWORD}"
}
EOF
fi

echo "== install complete =="
