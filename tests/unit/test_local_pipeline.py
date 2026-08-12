"""Local in-process indexing after register."""

from __future__ import annotations

from pathlib import Path

import pytest

from enterprise_rag.application.runtime import build_local_container
from enterprise_rag.application.ingestion.register_source import RegisterSourceRequest
from enterprise_rag.domain.ingestion.stages import IngestionRunStatus


@pytest.mark.asyncio
async def test_process_registered_pdf_completes(tmp_path: Path) -> None:
    sample = Path("examples/sample.pdf")
    if not sample.exists():
        pytest.skip("examples/sample.pdf missing")

    dest = tmp_path / "sample.pdf"
    dest.write_bytes(sample.read_bytes())
    container = build_local_container(auto_process_ingest=False)
    tenant = await container.resolve_tenant(tenant_key="pipeline-demo")
    result = await container.require_register_source().execute(
        tenant,
        RegisterSourceRequest(local_path=str(dest), title="Sample"),
    )
    await container.require_process_ingestion().execute(tenant, result.ingestion_run_id)
    run = await container.require_ingestion_repo().get_run(tenant, result.ingestion_run_id)
    assert run is not None
    assert run.status in {
        IngestionRunStatus.COMPLETED,
        IngestionRunStatus.COMPLETED_WITH_WARNINGS,
    }
    assert run.pages_processed >= 1
    assert run.elements_processed >= 1
