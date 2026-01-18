"""Tests for tier configuration and dynamic retrieval parameters.

Tests for US-10.5.1: Dynamic Retrieval Parameters
"""

import pytest

from tier_config import (
    QUERY_TYPE_MODIFIERS,
    TIER_CONFIGS,
    DynamicRetrievalParams,
    QueryTypeModifier,
    TenantTier,
    TierConfig,
    get_all_tiers,
    get_effective_params,
    get_tier_config,
)


class TestTenantTier:
    """Tests for TenantTier enum."""

    def test_tier_values(self):
        """Test all tier values exist."""
        assert TenantTier.BASIC.value == "basic"
        assert TenantTier.STANDARD.value == "standard"
        assert TenantTier.PREMIUM.value == "premium"

    def test_tier_is_string_enum(self):
        """Test tier can be used as string."""
        assert str(TenantTier.BASIC) == "TenantTier.BASIC"
        assert TenantTier.BASIC == "basic"


class TestTierConfigs:
    """Tests for TIER_CONFIGS dictionary."""

    def test_all_tiers_have_configs(self):
        """Test all tier values have corresponding configs."""
        for tier in TenantTier:
            assert tier.value in TIER_CONFIGS

    def test_basic_tier_config(self):
        """Test basic tier has correct values."""
        config = TIER_CONFIGS["basic"]
        assert config.semantic_top_k == 20
        assert config.keyword_top_k == 20
        assert config.use_reranker is False
        assert config.rerank_top_k == 0
        assert config.max_context_tokens == 2000

    def test_standard_tier_config(self):
        """Test standard tier has correct values."""
        config = TIER_CONFIGS["standard"]
        assert config.semantic_top_k == 35
        assert config.keyword_top_k == 35
        assert config.use_reranker is True
        assert config.rerank_top_k == 15
        assert config.max_context_tokens == 4000

    def test_premium_tier_config(self):
        """Test premium tier has correct values."""
        config = TIER_CONFIGS["premium"]
        assert config.semantic_top_k == 50
        assert config.keyword_top_k == 50
        assert config.use_reranker is True
        assert config.rerank_top_k == 30
        assert config.max_context_tokens == 8000

    def test_higher_tiers_have_more_candidates(self):
        """Test tier progression increases candidates."""
        basic = TIER_CONFIGS["basic"]
        standard = TIER_CONFIGS["standard"]
        premium = TIER_CONFIGS["premium"]

        assert basic.semantic_top_k < standard.semantic_top_k < premium.semantic_top_k
        assert basic.keyword_top_k < standard.keyword_top_k < premium.keyword_top_k


class TestQueryTypeModifiers:
    """Tests for QUERY_TYPE_MODIFIERS dictionary."""

    def test_all_query_types_have_modifiers(self):
        """Test all expected query types have modifiers."""
        expected_types = ["SIMPLE", "QUESTION", "SEMANTIC", "HYBRID"]
        for query_type in expected_types:
            assert query_type in QUERY_TYPE_MODIFIERS

    def test_simple_modifier_reduces_candidates(self):
        """Test SIMPLE query type reduces candidates."""
        modifier = QUERY_TYPE_MODIFIERS["SIMPLE"]
        assert modifier.top_k_multiplier == 0.5
        assert modifier.use_reranker is False

    def test_question_modifier_is_neutral(self):
        """Test QUESTION query type has neutral multiplier."""
        modifier = QUERY_TYPE_MODIFIERS["QUESTION"]
        assert modifier.top_k_multiplier == 1.0
        assert modifier.use_reranker is True

    def test_semantic_modifier_increases_candidates(self):
        """Test SEMANTIC query type increases candidates."""
        modifier = QUERY_TYPE_MODIFIERS["SEMANTIC"]
        assert modifier.top_k_multiplier == 1.2
        assert modifier.use_reranker is True

    def test_hybrid_modifier(self):
        """Test HYBRID query type modifier."""
        modifier = QUERY_TYPE_MODIFIERS["HYBRID"]
        assert modifier.top_k_multiplier == 1.0
        assert modifier.use_reranker is True


class TestGetEffectiveParams:
    """Tests for get_effective_params function."""

    def test_basic_tier_simple_query(self):
        """Test basic tier with simple query."""
        params = get_effective_params("basic", "SIMPLE")

        # 20 * 0.5 = 10
        assert params.semantic_top_k == 10
        assert params.keyword_top_k == 10
        # Basic doesn't use reranker, SIMPLE also disables it
        assert params.use_reranker is False
        assert params.rerank_top_k == 0
        assert params.tenant_tier == "basic"
        assert params.query_type == "SIMPLE"

    def test_premium_tier_semantic_query(self):
        """Test premium tier with semantic query."""
        params = get_effective_params("premium", "SEMANTIC")

        # 50 * 1.2 = 60
        assert params.semantic_top_k == 60
        assert params.keyword_top_k == 60
        assert params.use_reranker is True
        assert params.rerank_top_k == 30
        assert params.tenant_tier == "premium"
        assert params.query_type == "SEMANTIC"

    def test_standard_tier_question_query(self):
        """Test standard tier with question query."""
        params = get_effective_params("standard", "QUESTION")

        # 35 * 1.0 = 35
        assert params.semantic_top_k == 35
        assert params.keyword_top_k == 35
        assert params.use_reranker is True
        assert params.rerank_top_k == 15

    def test_reranker_disabled_when_tier_disables_it(self):
        """Test reranker is disabled for basic tier even with reranker-enabled query type."""
        params = get_effective_params("basic", "QUESTION")

        # QUESTION enables reranker, but basic tier doesn't
        assert params.use_reranker is False

    def test_reranker_disabled_when_query_type_disables_it(self):
        """Test reranker is disabled for SIMPLE query even with premium tier."""
        params = get_effective_params("premium", "SIMPLE")

        # Premium enables reranker, but SIMPLE disables it
        assert params.use_reranker is False

    def test_unknown_tier_defaults_to_standard(self):
        """Test unknown tier falls back to standard."""
        params = get_effective_params("unknown", "QUESTION")

        assert params.semantic_top_k == 35
        assert params.keyword_top_k == 35

    def test_unknown_query_type_defaults_to_question(self):
        """Test unknown query type falls back to QUESTION."""
        params = get_effective_params("standard", "UNKNOWN")

        assert params.top_k_multiplier_applied == 1.0
        assert params.query_type == "UNKNOWN"

    def test_case_insensitivity(self):
        """Test tier and query type are case-insensitive."""
        params1 = get_effective_params("PREMIUM", "simple")
        params2 = get_effective_params("premium", "SIMPLE")

        assert params1.semantic_top_k == params2.semantic_top_k
        assert params1.tenant_tier == params2.tenant_tier

    def test_to_debug_dict(self):
        """Test DynamicRetrievalParams.to_debug_dict method."""
        params = get_effective_params("premium", "QUESTION")
        debug_dict = params.to_debug_dict()

        assert debug_dict["effective_semantic_top_k"] == 50
        assert debug_dict["effective_keyword_top_k"] == 50
        assert debug_dict["effective_use_reranker"] is True
        assert debug_dict["effective_rerank_top_k"] == 30
        assert debug_dict["tenant_tier"] == "premium"
        assert debug_dict["query_type_detected"] == "QUESTION"


class TestGetTierConfig:
    """Tests for get_tier_config function."""

    def test_get_by_enum(self):
        """Test getting config by TenantTier enum."""
        config = get_tier_config(TenantTier.PREMIUM)
        assert config.semantic_top_k == 50

    def test_get_by_string(self):
        """Test getting config by string."""
        config = get_tier_config("premium")
        assert config.semantic_top_k == 50

    def test_unknown_tier_returns_standard(self):
        """Test unknown tier returns standard config."""
        config = get_tier_config("nonexistent")
        assert config.semantic_top_k == 35


class TestGetAllTiers:
    """Tests for get_all_tiers function."""

    def test_returns_all_tier_names(self):
        """Test all tier names are returned."""
        tiers = get_all_tiers()
        assert "basic" in tiers
        assert "standard" in tiers
        assert "premium" in tiers
        assert len(tiers) == 3


class TestDynamicRetrievalParams:
    """Tests for DynamicRetrievalParams model."""

    def test_model_creation(self):
        """Test creating DynamicRetrievalParams model."""
        params = DynamicRetrievalParams(
            semantic_top_k=50,
            keyword_top_k=50,
            use_reranker=True,
            rerank_top_k=30,
            max_context_tokens=8000,
            tenant_tier="premium",
            query_type="QUESTION",
            top_k_multiplier_applied=1.0,
        )

        assert params.semantic_top_k == 50
        assert params.use_reranker is True


class TestTierConfig:
    """Tests for TierConfig model."""

    def test_model_creation(self):
        """Test creating TierConfig model."""
        config = TierConfig(
            semantic_top_k=50,
            keyword_top_k=50,
            use_reranker=True,
            rerank_top_k=30,
            max_context_tokens=8000,
        )

        assert config.semantic_top_k == 50
        assert config.use_reranker is True


class TestQueryTypeModifier:
    """Tests for QueryTypeModifier model."""

    def test_default_values(self):
        """Test default values."""
        modifier = QueryTypeModifier()
        assert modifier.top_k_multiplier == 1.0
        assert modifier.use_reranker is True

    def test_multiplier_range_validation(self):
        """Test multiplier range validation."""
        # Valid range
        QueryTypeModifier(top_k_multiplier=0.1)
        QueryTypeModifier(top_k_multiplier=2.0)

        # Invalid range
        with pytest.raises(ValueError):
            QueryTypeModifier(top_k_multiplier=0.0)

        with pytest.raises(ValueError):
            QueryTypeModifier(top_k_multiplier=2.1)
