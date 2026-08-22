"""Query/ingestion contract alignment tests."""

from __future__ import annotations

from graph_rag.domain.citations import Citation
from graph_rag.domain.documents import IngestionResult, IngestionStatus
from graph_rag.domain.ids import new_id
from graph_rag.domain.modality import Modality
from graph_rag.domain.retrieval import QueryResponse, RetrievalMode
from tests.unit.contract_support import assert_matches_contract


def test_ingestion_result_matches_contract() -> None:
    result = IngestionResult(
        status=IngestionStatus.COMPLETED,
        tenant_id="demo",
        document_id=new_id(),
        version_id=new_id(),
        ingestion_run_id=new_id(),
        parser_requested="auto",
        parser_used="docling",
        pages=3,
        elements={"text": 10, "tables": 1},
        chunks={"parents": 2, "children": 8},
        graph={"entities": 5, "relationships": 7},
        vectors=8,
        duration_seconds=1.25,
        warnings=[],
    )
    assert_matches_contract("ingestion-result", result.model_dump(mode="json"))


def test_query_response_matches_contract() -> None:
    citation = Citation(
        citation_id="C1",
        tenant_id=new_id(),
        document_id=new_id(),
        document_version_id=new_id(),
        document_name="Report",
        page_start=1,
        page_end=1,
        section_path=["Overview"],
        element_id=new_id(),
        chunk_id=new_id(),
        modality=Modality.CHART,
        source_object_key="tenants/t/docs/d/v/assets/chart.png",
        evidence="Particle size decreases with temperature.",
    )
    response = QueryResponse(
        answer="The chart shows particle size decreasing with temperature. [C1]",
        retrieval_mode=RetrievalMode.MIX,
        citations=[citation],
        retrieval_trace_id=new_id(),
        warnings=[],
        graph_paths=[],
    )
    # Contract citation does not require tenant_id; extra properties are allowed.
    payload = response.model_dump(mode="json")
    assert_matches_contract("query-response", payload)
