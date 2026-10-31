#!/bin/bash
# Read-only diagnostics for the DEV PostgreSQL host. Prints no passwords.
set -u
echo "=== host ==="
hostname
date -u
echo "=== listeners ==="
ss -lntp 2>/dev/null | awk 'NR==1 || /:5432|:6432|:5433|haproxy|postgres|bouncer/'
echo "=== processes ==="
ps -eo comm,args | awk 'BEGIN{IGNORECASE=1} /postgres|pgbouncer|haproxy|pgbackrest/ && !/awk/'
echo "=== units ==="
systemctl is-active postgresql postgresql@18-main haproxy pgbouncer 2>/dev/null || true
echo "=== timeouts ==="
sudo -u postgres psql -d postgres -v ON_ERROR_STOP=1 -c \
  "SELECT name, setting, unit FROM pg_settings WHERE name IN (
     'server_version','statement_timeout','lock_timeout',
     'idle_in_transaction_session_timeout','idle_session_timeout',
     'tcp_keepalives_idle','tcp_keepalives_interval','tcp_keepalives_count',
     'log_connections','log_disconnections','log_line_prefix','data_directory'
   ) ORDER BY name;"
echo "=== schema ==="
sudo -u postgres psql -d chatwithdocs_db -v ON_ERROR_STOP=1 -c \
  "SELECT version_num FROM alembic_version;"
sudo -u postgres psql -d chatwithdocs_db -v ON_ERROR_STOP=1 -c \
  "SELECT column_name FROM information_schema.columns
   WHERE table_schema='public' AND table_name='document_versions'
     AND column_name IN ('etag','object_version_id')
   ORDER BY 1;"
sudo -u postgres psql -d chatwithdocs_db -v ON_ERROR_STOP=1 -c \
  "SELECT to_regclass('public.upload_sessions') AS upload_sessions;"
sudo -u postgres psql -d chatwithdocs_db -v ON_ERROR_STOP=1 -c \
  "SELECT c.relname, pg_get_userbyid(c.relowner) AS owner,
          c.relrowsecurity, c.relforcerowsecurity, pg_size_pretty(pg_relation_size(c.oid)) AS size
   FROM pg_class c
   JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname='public' AND c.relname='document_versions';"
echo "=== sessions ==="
sudo -u postgres psql -d chatwithdocs_db -v ON_ERROR_STOP=1 -c \
  "SELECT pid, usename, state, wait_event_type, wait_event,
          now()-xact_start AS xact_age, left(query, 160) AS query
   FROM pg_stat_activity
   WHERE datname = current_database() AND pid <> pg_backend_pid()
   ORDER BY xact_start NULLS LAST;"
echo "=== locks ==="
sudo -u postgres psql -d chatwithdocs_db -v ON_ERROR_STOP=1 -c \
  "SELECT l.mode, l.granted, a.usename, a.state, left(a.query, 160) AS query
   FROM pg_locks l
   LEFT JOIN pg_stat_activity a ON a.pid = l.pid
   WHERE l.relation = 'public.document_versions'::regclass
   ORDER BY l.granted, l.mode;"
echo "=== resources ==="
uptime
free -h
echo "=== recent postgres log ==="
logdir=$(sudo -u postgres psql -d postgres -At -c "SHOW data_directory;")
confdir=$(sudo -u postgres psql -d postgres -At -c "SHOW config_file;")
echo "config_file=${confdir}"
# Log lines from the two failed migration windows, in the server's local time and UTC.
journalctl -u 'postgresql*' --since '2026-10-28 07:50:00 UTC' --until '2026-10-28 08:40:00 UTC' --no-pager 2>/dev/null | tail -n 200 || true
find /var/log/postgresql -type f -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -5
latest=$(find /var/log/postgresql -type f -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR==1 {print $2}')
if [ -n "${latest:-}" ]; then
  echo "latest_log=${latest}"
  awk 'index($0,"2026-10-28 08:") || index($0,"2026-10-28 09:") || index($0,"2026-10-28 10:")' "$latest" \
    | awk 'BEGIN{IGNORECASE=1} /fatal|panic|error|reset|terminat|cancel|lock|timeout|etag|document_versions/' \
    | tail -n 80
fi
echo "=== diagnose done ==="
