"""LLM Model Router for cost-aware model selection.

This module implements model tiering based on query complexity and tenant tier
to reduce inference costs while maintaining quality.

Reference: US-10.5.2 - LLM Model Tiering
"""

import logging
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    """Model tiers based on parameter count and capabilities."""

    SMALL = "small"  # 7-8B models (Qwen2.5-7B, Llama-3.1-8B)
    MEDIUM = "medium"  # 13-14B models
    LARGE = "large"  # 70B+ models


class ModelConfig(BaseModel):
    """Configuration for a specific model tier."""

    model_name: str = Field(..., description="Full model identifier")
    max_tokens: int = Field(..., description="Maximum tokens for this tier")
    cost_per_1k_tokens: float = Field(..., description="Relative cost per 1K tokens")


# Default model configurations per tier
# These can be overridden via environment variables
MODEL_CONFIGS: dict[ModelTier, ModelConfig] = {
    ModelTier.SMALL: ModelConfig(
        model_name="qwen2.5-7b",
        max_tokens=2048,
        cost_per_1k_tokens=0.001,
    ),
    ModelTier.MEDIUM: ModelConfig(
        model_name="llama-3.1-13b",
        max_tokens=4096,
        cost_per_1k_tokens=0.003,
    ),
    ModelTier.LARGE: ModelConfig(
        model_name="llama-3.1-70b",
        max_tokens=8192,
        cost_per_1k_tokens=0.01,
    ),
}

# Selection matrix: (tenant_tier, complexity) -> model_tier
# Basic tier always gets small models regardless of complexity
# Premium tier gets larger models for complex queries
SELECTION_MATRIX: dict[tuple[str, str], ModelTier] = {
    # Basic tier - always small for cost control
    ("basic", "simple"): ModelTier.SMALL,
    ("basic", "complex"): ModelTier.SMALL,
    # Standard tier - upgrades for complex queries
    ("standard", "simple"): ModelTier.SMALL,
    ("standard", "complex"): ModelTier.MEDIUM,
    # Premium tier - best models available
    ("premium", "simple"): ModelTier.MEDIUM,
    ("premium", "complex"): ModelTier.LARGE,
}


class ModelSelectionResult(BaseModel):
    """Result of model selection containing full model configuration."""

    model: str = Field(..., description="Model name to use")
    max_tokens: int = Field(..., description="Max tokens for this model")
    tier: str = Field(..., description="Selected model tier")
    tenant_tier: str = Field(..., description="Tenant tier used for selection")
    complexity: str = Field(..., description="Query complexity")
    intent: str = Field(..., description="Query intent")


class ModelRouter:
    """Routes requests to appropriate LLM model based on tenant and query characteristics.

    The router uses a selection matrix that maps (tenant_tier, complexity) combinations
    to model tiers. It also applies overrides for specific query intents.

    Example:
        ```python
        router = ModelRouter()
        result = router.select_model(
            tenant_tier="premium",
            complexity="complex",
            intent="ANALYTICAL",
        )
        print(f"Selected model: {result.model}")
        ```
    """

    def __init__(
        self,
        model_configs: dict[ModelTier, ModelConfig] | None = None,
        selection_matrix: dict[tuple[str, str], ModelTier] | None = None,
    ) -> None:
        """Initialize the model router.

        Args:
            model_configs: Optional custom model configurations per tier.
            selection_matrix: Optional custom selection matrix.
        """
        self._model_configs = model_configs or MODEL_CONFIGS
        self._selection_matrix = selection_matrix or SELECTION_MATRIX

    def select_model(
        self,
        tenant_tier: str,
        complexity: str,
        intent: str,
    ) -> ModelSelectionResult:
        """Select model based on tenant and query characteristics.

        Args:
            tenant_tier: Tenant subscription tier (basic, standard, premium).
            complexity: Query complexity (simple, complex).
            intent: Query intent (FACTUAL, ANALYTICAL, PROCEDURAL, etc.).

        Returns:
            ModelSelectionResult with selected model configuration.
        """
        tenant_tier_lower = tenant_tier.lower()
        complexity_lower = complexity.lower()

        # Look up base tier from selection matrix
        key = (tenant_tier_lower, complexity_lower)
        model_tier = self._selection_matrix.get(key, ModelTier.SMALL)

        # Apply intent-based overrides
        # ANALYTICAL queries benefit from larger models for reasoning
        if intent.upper() == "ANALYTICAL" and tenant_tier_lower != "basic":
            # Upgrade by one tier for analytical queries (non-basic tenants)
            if model_tier == ModelTier.SMALL:
                model_tier = ModelTier.MEDIUM
            elif model_tier == ModelTier.MEDIUM:
                model_tier = ModelTier.LARGE

        # Get model config
        config = self._model_configs[model_tier]

        logger.info(
            "Model selected",
            extra={
                "model": config.model_name,
                "tier": model_tier.value,
                "tenant_tier": tenant_tier_lower,
                "complexity": complexity_lower,
                "intent": intent,
            },
        )

        return ModelSelectionResult(
            model=config.model_name,
            max_tokens=config.max_tokens,
            tier=model_tier.value,
            tenant_tier=tenant_tier_lower,
            complexity=complexity_lower,
            intent=intent,
        )

    async def get_fallback_model(self, failed_model: str) -> str:
        """Get fallback model if primary fails.

        Always falls back to the smallest model for reliability and cost efficiency.

        Args:
            failed_model: The model that failed.

        Returns:
            The fallback model name (always the small tier model).
        """
        fallback = self._model_configs[ModelTier.SMALL].model_name
        logger.warning(
            f"Falling back from {failed_model} to {fallback}",
            extra={"failed_model": failed_model, "fallback_model": fallback},
        )
        return fallback

    def get_model_config(self, tier: ModelTier) -> ModelConfig:
        """Get the configuration for a specific tier.

        Args:
            tier: The model tier.

        Returns:
            ModelConfig for the specified tier.
        """
        return self._model_configs[tier]
