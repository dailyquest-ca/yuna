#!/usr/bin/env bash
# Start a throwaway Postgres for the integration suite, then:
#
#   export DATABASE_URL="host=/var/tmp port=55432 user=postgres dbname=postgres" DB_SSLMODE=disable
#   python -m pytest tests/integration -q
#
# The point is a local round-trip. Before this existed, every change to a job cost a push, a
# dispatch and a wait — which is why three of duties.py's bugs took a session each to find.
set -euo pipefail
PGBIN=${PGBIN:-$(ls -d /usr/lib/postgresql/*/bin | tail -1)}
PGDATA=${PGDATA:-/var/tmp/yuna-pgdata}
PORT=${PORT:-55432}

if [ ! -d "$PGDATA/base" ]; then
  rm -rf "$PGDATA"; mkdir -p "$PGDATA"
  chown postgres:postgres "$PGDATA"; chmod 700 "$PGDATA"
  su postgres -c "$PGBIN/initdb -D $PGDATA -A trust -U postgres" >/dev/null
fi
su postgres -c "$PGBIN/pg_ctl -D $PGDATA -o '-p $PORT -k /var/tmp' -l /var/tmp/pg.log start" || true
sleep 2
echo "ready: DATABASE_URL=\"host=/var/tmp port=$PORT user=postgres dbname=postgres\" DB_SSLMODE=disable"
