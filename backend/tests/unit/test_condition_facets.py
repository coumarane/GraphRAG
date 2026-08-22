"""Condition facet extraction and query-feature alignment."""

from __future__ import annotations

from graph_rag.domain.retrieval.condition_facets import (
    detect_query_features,
    extract_condition_facets,
    score_facet_alignment,
)


def test_extract_axis_range_from_glued_ph_ticks() -> None:
    text = "pH 3.0SYプラ 4.0 5.0 6.0 7.0 8.0 9.0 10.0\nLittle/No tinting"
    facets = extract_condition_facets(text)
    assert "ph" in facets.parameters
    assert "tinting" in facets.phenomena
    assert facets.ranges
    assert facets.ranges[0].min == 3.0
    assert facets.ranges[0].max == 10.0


def test_mic_table_tagged_as_conflict_topic() -> None:
    text = "MIC at pH 5, pH 7, pH 9 — no growth"
    facets = extract_condition_facets(text)
    assert "mic" in facets.topics
    assert "ph" in facets.parameters


def test_query_features_condition_range_not_slide_title() -> None:
    features = detect_query_features(
        "Over which pH range was the tinting test performed?"
    )
    assert features.asks_condition_range
    assert "ph" in features.condition_parameters
    assert "tinting" in features.phenomena
    assert features.prefer_chart
    assert "mic" in features.conflict_topics


def test_query_features_temperature_range_generic() -> None:
    features = detect_query_features(
        "Over which temperature range was the stability test performed?"
    )
    assert features.asks_condition_range
    assert "temperature" in features.condition_parameters
    assert features.prefer_chart


def test_alignment_prefers_axis_over_mic() -> None:
    features = detect_query_features(
        "Over which pH range was the tinting test performed?"
    )
    axis = extract_condition_facets(
        "Effect of pH values\npH 3.0 4.0 5.0 6.0 7.0 8.0 9.0 10.0\nLittle/No tinting"
    )
    mic = extract_condition_facets("MIC minimum inhibitory pH 5 pH 7 pH 9 no growth")
    axis_score = score_facet_alignment(features=features, facets=axis)
    mic_score = score_facet_alignment(features=features, facets=mic)
    assert axis_score.boost > mic_score.boost
