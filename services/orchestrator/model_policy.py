"""Central model selection policy for orchestrator LLM stages.

This module centralizes how models are selected for generation-like stages.
It builds on top of :class:`model_router.ModelRouter` and applies consistent
rules for strategy -> complexity and strategy -> default intent mapping.
"""

from dataclasses import dataclass
from typing import Any

import structlog
from model_router import ModelRouter, ModelTier

logger = structlog.get_logger(__name__)

# Strategies that should be treated as complex for model tiering decisions.
COMPLEX_STRATEGIES = {
    "complex",
    "multi_hop",
    "comparison",
    "aggregation",
}

# Default intent inferred from workflow strategy when caller does not provide one.
STRATEGY_INTENT_DEFAULTS = {
    "no_retrieval": "CONVERSATIONAL",
    "simple": "FACTUAL",
    "complex": "ANALYTICAL",
    "multi_hop": "ANALYTICAL",
    "comparison": "ANALYTICAL",
    "aggregation": "ANALYTICAL",
}


@dataclass(frozen=True)
class ModelPolicyDecision:
    """Resolved model decision for a single stage invocation."""

    model: str
    max_tokens: int
    tier: str
    tenant_tier: str
    complexity: str
    intent: str


def strategy_to_complexity(strategy: str) -> str:
    """Map workflow strategy to model-tiering complexity.

    Args:
        strategy: Workflow strategy string.

    Returns:
        "complex" for complex/multi-hop style strategies, otherwise "simple".
    """
    strategy_lower = (strategy or "simple").lower()
    return "complex" if strategy_lower in COMPLEX_STRATEGIES else "simple"


def infer_intent_from_strategy(
    strategy: str,
    explicit_intent: str | None = None,
) -> str:
    """Infer intent used for model routing.

    Args:
        strategy: Workflow strategy string.
        explicit_intent: Optional caller-supplied intent override.

    Returns:
        Upper-cased intent string.
    """
    if explicit_intent and explicit_intent.strip():
        return explicit_intent.strip().upper()

    strategy_lower = (strategy or "simple").lower()
    inferred = STRATEGY_INTENT_DEFAULTS.get(strategy_lower, "FACTUAL")
    return inferred.upper()


def select_generation_model(
    *,
    config: Any,
    tenant_tier: str,
    strategy: str,
    intent: str | None = None,
    max_tokens_override: int | None = None,
    model_override: str | None = None,
    router: ModelRouter | None = None,
) -> ModelPolicyDecision:
    """Resolve model selection for generation-like stages.

    Args:
        config: Orchestrator config object.
        tenant_tier: Tenant tier (basic/standard/premium).
        strategy: Workflow strategy.
        intent: Optional intent override.
        max_tokens_override: Optional max token override from request options.
        router: Optional shared ModelRouter instance.

    Returns:
        ModelPolicyDecision with selected model metadata.
    """
    strategy_lower = (strategy or "simple").lower()
    effective_intent = infer_intent_from_strategy(strategy_lower, intent)
    complexity = strategy_to_complexity(strategy_lower)
    effective_tenant_tier = (tenant_tier or "standard").lower()

    if model_override and model_override.strip():
        return ModelPolicyDecision(
            model=model_override.strip(),
            max_tokens=max_tokens_override or config.max_tokens,
            tier="override",
            tenant_tier=effective_tenant_tier,
            complexity=complexity,
            intent=effective_intent,
        )

    # Feature-flagged fallback to default model path.
    if not getattr(config, "enable_model_tiering", True):
        return ModelPolicyDecision(
            model=config.default_model,
            max_tokens=max_tokens_override or config.max_tokens,
            tier="default",
            tenant_tier=effective_tenant_tier,
            complexity=complexity,
            intent=effective_intent,
        )

    active_router = router or ModelRouter()

    try:
        selection = active_router.select_model(
            tenant_tier=effective_tenant_tier,
            complexity=complexity,
            intent=effective_intent,
        )
        return ModelPolicyDecision(
            model=selection.model,
            max_tokens=max_tokens_override or selection.max_tokens,
            tier=selection.tier,
            tenant_tier=selection.tenant_tier,
            complexity=selection.complexity,
            intent=selection.intent,
        )
    except Exception as exc:
        logger.warning(
            "model_policy_router_failed_falling_back_to_default",
            error=str(exc),
            strategy=strategy_lower,
            tenant_tier=effective_tenant_tier,
            intent=effective_intent,
        )
        return ModelPolicyDecision(
            model=config.default_model,
            max_tokens=max_tokens_override or config.max_tokens,
            tier="default",
            tenant_tier=effective_tenant_tier,
            complexity=complexity,
            intent=effective_intent,
        )


def select_decomposition_model(
    *,
    config: Any,
    max_tokens_override: int | None = None,
    model_override: str | None = None,
    router: ModelRouter | None = None,
) -> ModelPolicyDecision:
    """Resolve model selection for query decomposition stage.

    Decomposition is intentionally cost-sensitive and defaults to the small tier.
    """
    if model_override and model_override.strip():
        return ModelPolicyDecision(
            model=model_override.strip(),
            max_tokens=max_tokens_override or config.max_tokens,
            tier="override",
            tenant_tier="n/a",
            complexity="complex",
            intent="ANALYTICAL",
        )

    active_router = router or ModelRouter()

    if getattr(config, "enable_model_tiering", True):
        try:
            small_config = active_router.get_model_config(ModelTier.SMALL)
            return ModelPolicyDecision(
                model=small_config.model_name,
                max_tokens=max_tokens_override or small_config.max_tokens,
                tier=ModelTier.SMALL.value,
                tenant_tier="n/a",
                complexity="complex",
                intent="ANALYTICAL",
            )
        except Exception as exc:
            logger.warning(
                "model_policy_decomposition_small_tier_lookup_failed",
                error=str(exc),
            )

    fallback_model = getattr(config, "fallback_model", None) or config.default_model
    return ModelPolicyDecision(
        model=fallback_model,
        max_tokens=max_tokens_override or config.max_tokens,
        tier="default",
        tenant_tier="n/a",
        complexity="complex",
        intent="ANALYTICAL",
    )


def select_verification_model(
    *,
    config: Any,
    tenant_tier: str,
    strategy: str,
    intent: str | None = None,
    max_tokens_override: int | None = None,
    model_override: str | None = None,
    router: ModelRouter | None = None,
) -> ModelPolicyDecision:
    """Resolve model selection for verification stage.

    Verification uses generation policy as baseline, but caps tier at MEDIUM to
    avoid unnecessary large-model cost/latency.
    """
    active_router = router or ModelRouter()
    base = select_generation_model(
        config=config,
        tenant_tier=tenant_tier,
        strategy=strategy,
        intent=intent,
        max_tokens_override=max_tokens_override,
        model_override=model_override,
        router=active_router,
    )

    if base.tier != ModelTier.LARGE.value:
        return base

    try:
        medium_config = active_router.get_model_config(ModelTier.MEDIUM)
        return ModelPolicyDecision(
            model=medium_config.model_name,
            max_tokens=max_tokens_override or medium_config.max_tokens,
            tier=ModelTier.MEDIUM.value,
            tenant_tier=base.tenant_tier,
            complexity=base.complexity,
            intent=base.intent,
        )
    except Exception as exc:
        logger.warning(
            "model_policy_verification_medium_tier_lookup_failed",
            error=str(exc),
        )
        return base
