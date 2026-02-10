"""Unit tests for the ModelRouter.

Tests cover:
- Selection matrix mappings
- Intent override logic
- Fallback model behavior
- Edge cases and defaults
"""

import pytest
from model_router import (
    MODEL_CONFIGS,
    SELECTION_MATRIX,
    ModelConfig,
    ModelRouter,
    ModelSelectionResult,
    ModelTier,
)


class TestModelTier:
    """Tests for ModelTier enum."""

    def test_tier_values(self):
        """Test tier enum values."""
        assert ModelTier.SMALL.value == "small"
        assert ModelTier.MEDIUM.value == "medium"
        assert ModelTier.LARGE.value == "large"

    def test_tier_string_comparison(self):
        """Test tier can be compared as string."""
        assert ModelTier.SMALL == "small"
        assert ModelTier.MEDIUM == "medium"
        assert ModelTier.LARGE == "large"


class TestModelConfigs:
    """Tests for default model configurations."""

    def test_all_tiers_have_config(self):
        """Test all tiers have configuration."""
        for _tier in ModelTier:
            assert _tier in MODEL_CONFIGS

    def test_config_structure(self):
        """Test config has required fields."""
        for _tier, config in MODEL_CONFIGS.items():
            assert isinstance(config, ModelConfig)
            assert config.model_name
            assert config.max_tokens > 0
            assert config.cost_per_1k_tokens > 0

    def test_tier_ordering(self):
        """Test larger tiers have more tokens and higher cost."""
        small = MODEL_CONFIGS[ModelTier.SMALL]
        medium = MODEL_CONFIGS[ModelTier.MEDIUM]
        large = MODEL_CONFIGS[ModelTier.LARGE]

        # Verify max_tokens increases with tier
        assert small.max_tokens < medium.max_tokens < large.max_tokens

        # Verify cost increases with tier
        assert small.cost_per_1k_tokens < medium.cost_per_1k_tokens < large.cost_per_1k_tokens


class TestSelectionMatrix:
    """Tests for the selection matrix."""

    def test_basic_tier_always_small(self):
        """Test basic tier always gets small model."""
        assert SELECTION_MATRIX[("basic", "simple")] == ModelTier.SMALL
        assert SELECTION_MATRIX[("basic", "complex")] == ModelTier.SMALL

    def test_standard_tier_upgrades_for_complex(self):
        """Test standard tier upgrades for complex queries."""
        assert SELECTION_MATRIX[("standard", "simple")] == ModelTier.SMALL
        assert SELECTION_MATRIX[("standard", "complex")] == ModelTier.MEDIUM

    def test_premium_tier_uses_larger_models(self):
        """Test premium tier uses larger models."""
        assert SELECTION_MATRIX[("premium", "simple")] == ModelTier.MEDIUM
        assert SELECTION_MATRIX[("premium", "complex")] == ModelTier.LARGE


class TestModelRouter:
    """Tests for ModelRouter class."""

    @pytest.fixture
    def router(self):
        """Create a router instance."""
        return ModelRouter()

    def test_select_model_returns_result(self, router):
        """Test select_model returns ModelSelectionResult."""
        result = router.select_model(
            tenant_tier="standard",
            complexity="simple",
            intent="FACTUAL",
        )
        assert isinstance(result, ModelSelectionResult)

    def test_select_model_basic_simple(self, router):
        """Test basic tier with simple query gets small model."""
        result = router.select_model(
            tenant_tier="basic",
            complexity="simple",
            intent="FACTUAL",
        )
        assert result.tier == "small"
        assert result.model == MODEL_CONFIGS[ModelTier.SMALL].model_name

    def test_select_model_premium_complex(self, router):
        """Test premium tier with complex query gets large model."""
        result = router.select_model(
            tenant_tier="premium",
            complexity="complex",
            intent="FACTUAL",
        )
        assert result.tier == "large"
        assert result.model == MODEL_CONFIGS[ModelTier.LARGE].model_name

    def test_select_model_case_insensitive(self, router):
        """Test tenant tier and complexity are case insensitive."""
        result1 = router.select_model(
            tenant_tier="PREMIUM",
            complexity="COMPLEX",
            intent="FACTUAL",
        )
        result2 = router.select_model(
            tenant_tier="premium",
            complexity="complex",
            intent="FACTUAL",
        )
        assert result1.tier == result2.tier
        assert result1.model == result2.model

    def test_select_model_unknown_tier_defaults_to_small(self, router):
        """Test unknown tier defaults to small model."""
        result = router.select_model(
            tenant_tier="unknown",
            complexity="simple",
            intent="FACTUAL",
        )
        assert result.tier == "small"

    def test_analytical_intent_upgrades_model(self, router):
        """Test ANALYTICAL intent upgrades model tier."""
        # Standard + simple normally gets small
        result_factual = router.select_model(
            tenant_tier="standard",
            complexity="simple",
            intent="FACTUAL",
        )
        assert result_factual.tier == "small"

        # But with ANALYTICAL, it upgrades to medium
        result_analytical = router.select_model(
            tenant_tier="standard",
            complexity="simple",
            intent="ANALYTICAL",
        )
        assert result_analytical.tier == "medium"

    def test_analytical_intent_does_not_upgrade_basic(self, router):
        """Test ANALYTICAL doesn't upgrade basic tier (cost control)."""
        result = router.select_model(
            tenant_tier="basic",
            complexity="simple",
            intent="ANALYTICAL",
        )
        assert result.tier == "small"

    def test_analytical_intent_caps_at_large(self, router):
        """Test ANALYTICAL upgrade caps at large tier."""
        # Premium + complex is already large
        result = router.select_model(
            tenant_tier="premium",
            complexity="complex",
            intent="ANALYTICAL",
        )
        assert result.tier == "large"

    def test_result_includes_metadata(self, router):
        """Test result includes selection metadata."""
        result = router.select_model(
            tenant_tier="standard",
            complexity="complex",
            intent="PROCEDURAL",
        )
        assert result.tenant_tier == "standard"
        assert result.complexity == "complex"
        assert result.intent == "PROCEDURAL"


class TestModelRouterFallback:
    """Tests for fallback model selection."""

    @pytest.fixture
    def router(self):
        """Create a router instance."""
        return ModelRouter()

    @pytest.mark.asyncio
    async def test_fallback_returns_small_model(self, router):
        """Test fallback always returns small model."""
        fallback = await router.get_fallback_model("llama-3.1-70b")
        assert fallback == MODEL_CONFIGS[ModelTier.SMALL].model_name

    @pytest.mark.asyncio
    async def test_fallback_from_any_model(self, router):
        """Test fallback works from any model."""
        models = ["llama-3.1-70b", "llama-3.1-8b", "qwen2.5-7b", "unknown-model"]
        for model in models:
            fallback = await router.get_fallback_model(model)
            assert fallback == MODEL_CONFIGS[ModelTier.SMALL].model_name


class TestModelRouterCustomConfig:
    """Tests for custom router configuration."""

    def test_custom_model_configs(self):
        """Test router with custom model configs."""
        custom_configs = {
            ModelTier.SMALL: ModelConfig(
                model_name="custom-small",
                max_tokens=1000,
                cost_per_1k_tokens=0.0001,
            ),
            ModelTier.MEDIUM: ModelConfig(
                model_name="custom-medium",
                max_tokens=2000,
                cost_per_1k_tokens=0.0002,
            ),
            ModelTier.LARGE: ModelConfig(
                model_name="custom-large",
                max_tokens=4000,
                cost_per_1k_tokens=0.0004,
            ),
        }

        router = ModelRouter(model_configs=custom_configs)
        result = router.select_model(
            tenant_tier="basic",
            complexity="simple",
            intent="FACTUAL",
        )
        assert result.model == "custom-small"

    def test_custom_selection_matrix(self):
        """Test router with custom selection matrix."""
        # All queries get large model
        custom_matrix = {
            ("basic", "simple"): ModelTier.LARGE,
            ("basic", "complex"): ModelTier.LARGE,
            ("standard", "simple"): ModelTier.LARGE,
            ("standard", "complex"): ModelTier.LARGE,
            ("premium", "simple"): ModelTier.LARGE,
            ("premium", "complex"): ModelTier.LARGE,
        }

        router = ModelRouter(selection_matrix=custom_matrix)
        result = router.select_model(
            tenant_tier="basic",
            complexity="simple",
            intent="FACTUAL",
        )
        assert result.tier == "large"
