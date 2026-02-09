"""Unit tests for centralized model policy."""

from unittest.mock import MagicMock

from model_policy import (
    infer_intent_from_strategy,
    select_decomposition_model,
    select_generation_model,
    select_verification_model,
    strategy_to_complexity,
)


class DummyConfig:
    """Minimal config object for model policy tests."""

    default_model = "default-model"
    max_tokens = 1024
    enable_model_tiering = True


def test_strategy_to_complexity_marks_multi_hop_as_complex():
    """Multi-hop strategies should be treated as complex."""
    assert strategy_to_complexity("multi_hop") == "complex"
    assert strategy_to_complexity("comparison") == "complex"
    assert strategy_to_complexity("aggregation") == "complex"


def test_infer_intent_uses_strategy_default_and_override():
    """Intent inference should support both defaults and explicit overrides."""
    assert infer_intent_from_strategy("no_retrieval") == "CONVERSATIONAL"
    assert infer_intent_from_strategy("comparison") == "ANALYTICAL"
    assert infer_intent_from_strategy("simple", explicit_intent="procedural") == "PROCEDURAL"


def test_select_generation_model_falls_back_to_default_when_tiering_disabled():
    """Tiering disabled should always return default model path."""
    config = DummyConfig()
    config.enable_model_tiering = False

    result = select_generation_model(
        config=config,
        tenant_tier="standard",
        strategy="comparison",
        intent=None,
        max_tokens_override=256,
    )

    assert result.model == "default-model"
    assert result.max_tokens == 256
    assert result.tier == "default"
    assert result.complexity == "complex"


def test_select_generation_model_routes_comparison_as_complex():
    """Comparison strategy should pass complex to router selection."""
    config = DummyConfig()
    mock_router = MagicMock()
    mock_router.select_model.return_value = MagicMock(
        model="large-model",
        max_tokens=4096,
        tier="large",
        tenant_tier="standard",
        complexity="complex",
        intent="ANALYTICAL",
    )

    result = select_generation_model(
        config=config,
        tenant_tier="standard",
        strategy="comparison",
        intent=None,
        router=mock_router,
    )

    assert result.model == "large-model"
    assert result.complexity == "complex"
    assert result.intent == "ANALYTICAL"
    assert mock_router.select_model.call_args.kwargs["complexity"] == "complex"


def test_select_decomposition_model_prefers_small_tier():
    """Decomposition policy should use the small tier model when available."""
    config = DummyConfig()
    mock_router = MagicMock()
    mock_router.get_model_config.return_value = MagicMock(
        model_name="small-model",
        max_tokens=2048,
    )

    result = select_decomposition_model(
        config=config,
        router=mock_router,
    )

    assert result.model == "small-model"
    assert result.tier == "small"
    mock_router.get_model_config.assert_called_once()


def test_select_verification_model_caps_large_to_medium():
    """Verification policy should cap large-tier generation selection to medium."""
    config = DummyConfig()
    mock_router = MagicMock()
    mock_router.select_model.return_value = MagicMock(
        model="large-model",
        max_tokens=8192,
        tier="large",
        tenant_tier="premium",
        complexity="complex",
        intent="ANALYTICAL",
    )
    mock_router.get_model_config.return_value = MagicMock(
        model_name="medium-model",
        max_tokens=4096,
    )

    result = select_verification_model(
        config=config,
        tenant_tier="premium",
        strategy="comparison",
        router=mock_router,
    )

    assert result.model == "medium-model"
    assert result.tier == "medium"


def test_generation_model_override_is_respected():
    """Explicit model override should bypass tiering output model."""
    config = DummyConfig()

    result = select_generation_model(
        config=config,
        tenant_tier="standard",
        strategy="simple",
        model_override="custom-model",
        max_tokens_override=777,
    )

    assert result.model == "custom-model"
    assert result.tier == "override"
    assert result.max_tokens == 777
