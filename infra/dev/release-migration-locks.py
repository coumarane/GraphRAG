"""Terminate stale idle transactions that block upload-session DDL.

This is the only write. It calls pg_terminate_backend for backends that match
every condition below. It does not change roles, grants, or row level security.

- same database and same login role as this connection
- state is exactly idle in transaction
- the transaction started more than 60 seconds ago
- a granted lock on document_versions or one of its indexes
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg

LIST_SQL = """
SELECT a.pid,
       a.usename,
       a.state,
       now() - a.xact_start AS xact_age,
       a.wait_event_type,
       a.wait_event,
       c.relname,
       l.mode,
       left(a.query, 180) AS query
FROM pg_locks l
JOIN pg_stat_activity a ON a.pid = l.pid
LEFT JOIN pg_class c ON c.oid = l.relation
WHERE l.granted
  AND a.pid <> pg_backend_pid()
  AND a.datname = current_database()
  AND l.relation IN (
        SELECT cls.oid
        FROM pg_class cls
        WHERE cls.oid = 'public.document_versions'::regclass
           OR cls.oid IN (
                SELECT i.indexrelid
                FROM pg_index i
                WHERE i.indrelid = 'public.document_versions'::regclass
           )
  )
ORDER BY a.xact_start NULLS LAST, a.pid
"""

TERMINATE_SQL = """
SELECT pg_terminate_backend(s.pid) AS terminated,
       s.pid,
       s.state,
       s.xact_age
FROM (
    SELECT DISTINCT a.pid,
           a.state,
           now() - a.xact_start AS xact_age
    FROM pg_locks l
    JOIN pg_stat_activity a ON a.pid = l.pid
    WHERE l.granted
      AND a.pid <> pg_backend_pid()
      AND a.datname = current_database()
      AND a.usename = current_user
      AND a.state = 'idle in transaction'
      AND a.xact_start < now() - interval '60 seconds'
      AND l.relation IN (
            SELECT cls.oid
            FROM pg_class cls
            WHERE cls.oid = 'public.document_versions'::regclass
               OR cls.oid IN (
                    SELECT i.indexrelid
                    FROM pg_index i
                    WHERE i.indrelid = 'public.document_versions'::regclass
               )
      )
) s
ORDER BY s.pid
"""


def _print_rows(title: str, rows: list[asyncpg.Record]) -> None:
    print(title)
    if not rows:
        print("(none)")
        return
    for row in rows:
        print(" | ".join(str(value) for value in row))


async def main() -> None:
    conn = await asyncpg.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        ssl="prefer",
        timeout=20,
        server_settings={"statement_timeout": "15s"},
    )
    try:
        before = await conn.fetch(LIST_SQL)
        _print_rows("document_versions_locks_before", before)
        terminated = await conn.fetch(TERMINATE_SQL)
        _print_rows("terminated_idle_lock_holders", terminated)
        failed = [row for row in terminated if row["terminated"] is not True]
        if failed:
            print("pg_terminate_backend returned false", file=sys.stderr)
            raise SystemExit(1)
        after = await conn.fetch(LIST_SQL)
        _print_rows("document_versions_locks_after", after)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
