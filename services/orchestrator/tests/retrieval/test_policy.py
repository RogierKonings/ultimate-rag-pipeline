"""Unit tests for retrieval policy helpers."""

from retrieval.policy import (
    coerce_positive_int,
    get_retrieval_option,
    should_enable_rerank,
)


def test_should_enable_rerank_defaults_to_false_for_simple_queries():
    """Simple/factual queries should keep reranking disabled by default."""
    assert should_enable_rerank(strategy="simple", intent="FACTUAL") is False


def test_should_enable_rerank_for_complex_strategy():
    """Complex strategies should enable reranking."""
    assert should_enable_rerank(strategy="comparison", intent="FACTUAL") is True


def test_should_enable_rerank_for_analytical_intent():
    """Analytical intent should enable reranking."""
    assert should_enable_rerank(strategy="simple", intent="ANALYTICAL") is True


def test_should_enable_rerank_respects_explicit_override():
    """Explicit rerank option should take precedence over policy defaults."""
    assert should_enable_rerank(strategy="comparison", rerank_override=False) is False
    assert should_enable_rerank(strategy="simple", rerank_override="true") is True


def test_get_retrieval_option_prefers_nested_retrieval_options():
    """Nested retrieval options should override top-level values."""
    options = {
        "top_k": 10,
        "retrieval_mode": "hybrid",
        "retrieval": {
            "top_k": 25,
            "mode": "semantic",
            "rerank": True,
        },
    }

    assert get_retrieval_option(options, key="top_k", default=5) == 25
    assert get_retrieval_option(options, key="mode", legacy_key="retrieval_mode") == "semantic"
    assert get_retrieval_option(options, key="rerank", default=False) is True


def test_coerce_positive_int_falls_back_on_invalid_values():
    """Invalid/non-positive integer values should resolve to defaults."""
    assert coerce_positive_int("12", 5) == 12
    assert coerce_positive_int(0, 5) == 5
    assert coerce_positive_int(-4, 5) == 5
    assert coerce_positive_int("oops", 5) == 5
