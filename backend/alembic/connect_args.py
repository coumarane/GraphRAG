"""Optional session settings for one Alembic connection.

The DEV migration runs from a GitHub-hosted runner. PostgreSQL waits forever
for AccessExclusiveLock when lock_timeout is 0, and that wait sends no
packets. The path then resets the idle TCP connection. These settings apply
only when the workflow sets them. They do not change server configuration.
"""

from __future__ import annotations

import os
from collections.abc import Mapping


def migration_connect_args(
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Build asyncpg connect args from ALEMBIC_* environment variables."""
    env = os.environ if environ is None else environ
    server_settings: dict[str, str] = {}
    lock_timeout = env.get("ALEMBIC_LOCK_TIMEOUT", "").strip()
    if lock_timeout:
        server_settings["lock_timeout"] = lock_timeout
    keepalive_idle = env.get("ALEMBIC_TCP_KEEPALIVES_IDLE", "").strip()
    if keepalive_idle:
        server_settings["tcp_keepalives_idle"] = keepalive_idle
        server_settings["tcp_keepalives_interval"] = env.get(
            "ALEMBIC_TCP_KEEPALIVES_INTERVAL", "10"
        ).strip()
        server_settings["tcp_keepalives_count"] = env.get(
            "ALEMBIC_TCP_KEEPALIVES_COUNT", "5"
        ).strip()
    if not server_settings:
        return {}
    return {"server_settings": server_settings}
