"""Member title wins when it is non-empty."""

from graph_rag.application.ingestion.register_source import _title_from_source


def test_non_empty_title_is_stored() -> None:
    assert (
        _title_from_source(
            source_filename="report.pdf",
            request_title="Quarterly review",
            loaded_filename="report.pdf",
        )
        == "Quarterly review"
    )


def test_blank_title_falls_back_to_filename() -> None:
    assert (
        _title_from_source(
            source_filename="quarterly_review.pdf",
            request_title="  ",
            loaded_filename="quarterly_review.pdf",
        )
        == "quarterly review"
    )
