"""Dynamic retrieval parameter configuration based on tenant tier and query type.

This module provides tier-based configuration for retrieval parameters,
enabling cost optimization without sacrificing quality for higher-tier tenants.

Reference: US-10.5.1 - Dynamic Retrieval Parameters
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TenantTier(str, Enum):
    """Tenant subscription tiers.

    Tiers determine the base retrieval parameters available to tenants.
    Higher tiers get more candidates and reranking capabilities.
    """

    BASIC = "basic"
    STANDARD = "standard"
    PREMIUM = "premium"


class TierConfig(BaseModel):
    """Configuration for a specific tenant tier."""

    semantic_top_k: int = Field(..., description="Number of semantic search candidates")
    keyword_top_k: int = Field(..., description="Number of keyword search candidates")
    use_reranker: bool = Field(..., description="Whether to use cross-encoder reranking")
    rerank_top_k: int = Field(..., description="Number of candidates to rerank")
    max_context_tokens: int = Field(..., description="Maximum context tokens for LLM")


# Tier configurations as specified in US-10.5.1
TIER_CONFIGS: dict[str, TierConfig] = {
    "basic": TierConfig(
        semantic_top_k=20,
        keyword_top_k=20,
        use_reranker=False,
        rerank_top_k=0,
        max_context_tokens=2000,
    ),
    "standard": TierConfig(
        semantic_top_k=35,
        keyword_top_k=35,
        use_reranker=True,
        rerank_top_k=15,
        max_context_tokens=4000,
    ),
    "premium": TierConfig(
        semantic_top_k=50,
        keyword_top_k=50,
        use_reranker=True,
        rerank_top_k=30,
        max_context_tokens=8000,
    ),
}


class QueryTypeModifier(BaseModel):
    """Modifier applied based on query type."""

    top_k_multiplier: float = Field(
        default=1.0,
        ge=0.1,
        le=2.0,
        description="Multiplier for top_k values",
    )
    use_reranker: bool = Field(
        default=True,
        description="Whether to use reranker for this query type",
    )


# Query type modifiers as specified in US-10.5.1
QUERY_TYPE_MODIFIERS: dict[str, QueryTypeModifier] = {
    "SIMPLE": QueryTypeModifier(top_k_multiplier=0.5, use_reranker=False),
    "QUESTION": QueryTypeModifier(top_k_multiplier=1.0, use_reranker=True),
    "SEMANTIC": QueryTypeModifier(top_k_multiplier=1.2, use_reranker=True),
    "HYBRID": QueryTypeModifier(top_k_multiplier=1.0, use_reranker=True),
}


class DynamicRetrievalParams(BaseModel):
    """Effective retrieval parameters after applying tier and query type rules.

    These parameters are calculated dynamically based on the tenant's tier
    and the detected query type.
    """

    semantic_top_k: int = Field(..., description="Effective semantic search candidates")
    keyword_top_k: int = Field(..., description="Effective keyword search candidates")
    use_reranker: bool = Field(..., description="Whether to use reranker")
    rerank_top_k: int = Field(..., description="Candidates to send to reranker")
    max_context_tokens: int = Field(..., description="Max context tokens")

    # Provenance tracking
    tenant_tier: str = Field(..., description="Tenant tier used")
    query_type: str = Field(..., description="Query type detected")
    top_k_multiplier_applied: float = Field(..., description="Multiplier applied")

    def to_debug_dict(self) -> dict[str, Any]:
        """Convert to dictionary for debug info response."""
        return {
            "effective_semantic_top_k": self.semantic_top_k,
            "effective_keyword_top_k": self.keyword_top_k,
            "effective_use_reranker": self.use_reranker,
            "effective_rerank_top_k": self.rerank_top_k,
            "tenant_tier": self.tenant_tier,
            "query_type_detected": self.query_type,
        }


def get_effective_params(tenant_tier: str, query_type: str) -> DynamicRetrievalParams:
    """Calculate effective retrieval parameters.

    Combines the base tier configuration with query type modifiers to
    produce the final retrieval parameters.

    Args:
        tenant_tier: Tenant tier (basic, standard, premium).
        query_type: Detected query type (SIMPLE, QUESTION, SEMANTIC, HYBRID).

    Returns:
        DynamicRetrievalParams with calculated values.

    Example:
        >>> params = get_effective_params("premium", "SIMPLE")
        >>> params.semantic_top_k  # 50 * 0.5 = 25
        25
        >>> params.use_reranker  # False (SIMPLE disables reranker)
        False
    """
    # Get base config for tier (default to standard if unknown)
    base = TIER_CONFIGS.get(tenant_tier.lower(), TIER_CONFIGS["standard"])

    # Get modifier for query type (default to QUESTION if unknown)
    modifier = QUERY_TYPE_MODIFIERS.get(query_type.upper(), QUERY_TYPE_MODIFIERS["QUESTION"])

    # Calculate effective values
    effective_semantic = int(base.semantic_top_k * modifier.top_k_multiplier)
    effective_keyword = int(base.keyword_top_k * modifier.top_k_multiplier)

    # Reranker is enabled only if both tier and query type allow it
    effective_reranker = base.use_reranker and modifier.use_reranker

    return DynamicRetrievalParams(
        semantic_top_k=effective_semantic,
        keyword_top_k=effective_keyword,
        use_reranker=effective_reranker,
        rerank_top_k=base.rerank_top_k if effective_reranker else 0,
        max_context_tokens=base.max_context_tokens,
        tenant_tier=tenant_tier.lower(),
        query_type=query_type.upper(),
        top_k_multiplier_applied=modifier.top_k_multiplier,
    )


def get_tier_config(tier: str | TenantTier) -> TierConfig:
    """Get the configuration for a specific tier.

    Args:
        tier: Tier name or TenantTier enum.

    Returns:
        TierConfig for the specified tier.
    """
    tier_name = tier.value if isinstance(tier, TenantTier) else tier.lower()
    return TIER_CONFIGS.get(tier_name, TIER_CONFIGS["standard"])


def get_all_tiers() -> list[str]:
    """Get list of all available tier names."""
    return [t.value for t in TenantTier]
