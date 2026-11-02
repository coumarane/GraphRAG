"""Liveness answers while the ingestion loop is blocked by synchronous work."""

from __future__ import annotations

import asyncio
import os
import threading
import time
import urllib.error
import urllib.request

from graph_rag.infrastructure.workers.main import (
    _ready_from_container,
    start_health_acceptor,
)


def _get(port: int, path: str, timeout: float = 5) -> tuple[int, float]:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}",
            timeout=timeout,
        ) as response:
            response.read()
            return response.status, time.monotonic() - started
    except urllib.error.HTTPError as exc:
        return exc.code, time.monotonic() - started


def test_liveness_answers_while_synchronous_work_blocks_the_loop() -> None:
    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        assert loop.is_running()
        server = start_health_acceptor(
            host="127.0.0.1",
            port=0,
            ready_check=lambda: False,
        )
        port = int(server.server_address[1])
        results: list[tuple[int, float]] = []
        started = threading.Event()

        def hit() -> None:
            assert started.wait(timeout=2)
            for _ in range(3):
                results.append(_get(port, "/health/live"))

        worker = threading.Thread(target=hit)
        worker.start()
        started.set()
        time.sleep(6)  # noqa: ASYNC251 - the loop must stay blocked for the probe
        worker.join(timeout=6)
        server.shutdown()
        server.server_close()
        assert len(results) == 3
        assert [status for status, _elapsed in results] == [200, 200, 200]
        assert all(elapsed < 5 for _status, elapsed in results)
        assert os.getpid() > 0

    asyncio.run(scenario())


def test_exited_health_server_does_not_answer() -> None:
    server = start_health_acceptor(host="127.0.0.1", port=0, ready_check=lambda: True)
    port = int(server.server_address[1])
    status, elapsed = _get(port, "/health/live")
    assert status == 200
    assert elapsed < 5
    server.shutdown()
    server.server_close()
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health/live", timeout=1)
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return
    raise AssertionError("exited health server still answered")


def test_readiness_stays_on_dependency_checks() -> None:
    async def scenario() -> None:
        loop = asyncio.get_running_loop()

        class _Container:
            def __init__(self) -> None:
                self.ready_checks = [lambda: False]

        server = start_health_acceptor(
            host="127.0.0.1",
            port=0,
            ready_check=lambda: _ready_from_container(loop, _Container()),
        )
        port = int(server.server_address[1])
        status, _elapsed = _get(port, "/health/ready")
        live, _elapsed = _get(port, "/health/live")
        server.shutdown()
        server.server_close()
        assert status == 503
        assert live == 200

    asyncio.run(scenario())


def test_probe_timeout_stays_five_seconds() -> None:
    text = (
        __import__("pathlib").Path(__file__).resolve().parents[3]
        / "infra/k8s/worker/deployment.yaml"
    ).read_text()
    assert "timeoutSeconds: 5" in text
    assert "longer timeout is not the fix" in text
