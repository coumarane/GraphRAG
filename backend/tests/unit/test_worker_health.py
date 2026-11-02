"""Worker health answers live always and ready only when checks pass."""

from __future__ import annotations

import urllib.error
import urllib.request

from graph_rag.infrastructure.workers.main import start_health_acceptor


def _status(port: int, path: str) -> int:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            response.read()
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_liveness_is_up_while_readiness_fails_closed() -> None:
    failed = start_health_acceptor(
        host="127.0.0.1",
        port=0,
        ready_check=lambda: False,
    )
    passed = start_health_acceptor(
        host="127.0.0.1",
        port=0,
        ready_check=lambda: True,
    )
    failed_port = int(failed.server_address[1])
    passed_port = int(passed.server_address[1])
    try:
        assert _status(failed_port, "/health/live") == 200
        assert _status(failed_port, "/health/ready") == 503
        assert _status(passed_port, "/health/ready") == 200
    finally:
        failed.shutdown()
        failed.server_close()
        passed.shutdown()
        passed.server_close()
