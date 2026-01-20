"""Generation node for the RAG workflow.

This node calls the LLM gateway to generate a response based on
the constructed prompt messages, using dynamic model selection
based on tenant tier and query complexity.

Reference: US-10.5.2 - LLM Model Tiering
"""

import logging
import time
from typing import TYPE_CHECKING

import httpx
from model_router import ModelRouter
from observability.llm_metrics import (
    record_llm_duration,
    record_llm_request,
    record_model_fallback,
)
from opentelemetry import trace

from config import get_config
from shared.observability.otel.span_names import SpanNames

if TYPE_CHECKING:
    from workflow.state import RAGState

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Module-level router instance
_model_router = ModelRouter()


def _get_complexity_from_strategy(strategy: str) -> str:
    """Map routing strategy to complexity level.

    Args:
        strategy: The routing strategy (simple, complex, no_retrieval).

    Returns:
        Complexity level (simple, complex).
    """
    return "complex" if strategy == "complex" else "simple"


async def generation_node(state: "RAGState") -> "RAGState":
    """
    Generate response using LLM with dynamic model selection.

    This node:
    - Selects model based on tenant tier and query complexity
    - Sends messages to LLM gateway
    - Captures the generated response
    - Records model used and token usage
    - Handles generation failures with fallback
    - Records metrics for model usage

    Args:
        state: Current RAGState with messages for LLM

    Returns:
        Updated RAGState with response, model_used, and usage
    """
    with tracer.start_as_current_span(SpanNames.ORCHESTRATOR_GENERATION) as span:
        start = time.time()

        timing = dict(state.get("timing", {}))
        fallbacks_used = list(state.get("fallbacks_used", []))
        error = state.get("error")
        messages = state.get("messages", [])

        # Set span attributes for query context
        query = state.get("query", "")
        tenant_id = state.get("tenant_id")
        span.set_attribute("orchestrator.query_length", len(query) if query else 0)
        if tenant_id:
            span.set_attribute("orchestrator.tenant_id", tenant_id)

        config = get_config()

        # Check for messages
        if not messages:
            error = "No messages available for generation"
            span.set_attribute("orchestrator.generation_error", "no_messages")
            timing["generation"] = (time.time() - start) * 1000
            return {
                **state,
                "timing": timing,
                "error": error,
            }

        response = None
        model_used = config.default_model
        usage = {}
        selected_tier = "default"

        # Get options from state for per-request overrides
        options = state.get("options", {})
        temperature = options.get("temperature", config.temperature)
        max_tokens_override = options.get("max_tokens")

        # Get tenant tier and complexity for model selection
        tenant_tier = options.get("tenant_tier", "standard")
        strategy = state.get("strategy", "simple")
        complexity = _get_complexity_from_strategy(strategy)

        # Get intent from routing (if available)
        intent = options.get("intent", "FACTUAL")

        # Dynamic model selection (US-10.5.2)
        if config.enable_model_tiering:
            try:
                selection = _model_router.select_model(
                    tenant_tier=tenant_tier,
                    complexity=complexity,
                    intent=intent,
                )
                model_to_use = selection.model
                max_tokens = max_tokens_override or selection.max_tokens
                selected_tier = selection.tier

                logger.info(
                    f"Model router selected: {model_to_use} (tier={selected_tier})",
                    extra={
                        "model": model_to_use,
                        "tier": selected_tier,
                        "tenant_tier": tenant_tier,
                        "complexity": complexity,
                        "intent": intent,
                    },
                )
            except Exception as e:
                logger.warning(f"Model router failed, using default: {e}")
                model_to_use = config.default_model
                max_tokens = max_tokens_override or config.max_tokens
        else:
            # Feature flag disabled - use default model
            model_to_use = config.default_model
            max_tokens = max_tokens_override or config.max_tokens

        # Set model attribute on span
        span.set_attribute("orchestrator.model", model_to_use)

        async def _call_llm(model: str, max_tok: int) -> dict | None:
            """Make LLM call with given model."""
            async with httpx.AsyncClient(timeout=config.stream_timeout) as client:
                payload = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tok,
                    "temperature": temperature,
                    "stream": False,
                }

                llm_response = await client.post(
                    f"{config.llm_gateway_url}/v1/chat/completions",
                    json=payload,
                )
                llm_response.raise_for_status()
                return llm_response.json()

        try:
            result = await _call_llm(model_to_use, max_tokens)

            # Extract response content
            choices = result.get("choices", [])
            if choices:
                response = choices[0].get("message", {}).get("content", "")
                model_used = result.get("model", model_to_use)

            # Extract usage info
            usage_data = result.get("usage", {})
            usage = {
                "prompt_tokens": usage_data.get("prompt_tokens", 0),
                "completion_tokens": usage_data.get("completion_tokens", 0),
                "total_tokens": usage_data.get("total_tokens", 0),
            }

            # Record metrics
            record_llm_request(model_used, selected_tier, tenant_tier)
            record_llm_duration(selected_tier, time.time() - start)

            logger.info(f"Generated response with {usage.get('total_tokens', 0)} tokens")

        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            # Try fallback model
            logger.warning(f"Primary model {model_to_use} failed: {e}, trying fallback")
            fallbacks_used.append("llm_primary_failed")
            span.set_attribute("orchestrator.generation_error", "primary_failed")

            try:
                fallback_model = await _model_router.get_fallback_model(model_to_use)
                fallback_max_tokens = config.max_tokens  # Use default for fallback

                result = await _call_llm(fallback_model, fallback_max_tokens)

                # Extract response content
                choices = result.get("choices", [])
                if choices:
                    response = choices[0].get("message", {}).get("content", "")
                    model_used = result.get("model", fallback_model)

                # Extract usage info
                usage_data = result.get("usage", {})
                usage = {
                    "prompt_tokens": usage_data.get("prompt_tokens", 0),
                    "completion_tokens": usage_data.get("completion_tokens", 0),
                    "total_tokens": usage_data.get("total_tokens", 0),
                }

                # Record fallback metrics
                record_model_fallback(model_to_use, fallback_model)
                record_llm_request(model_used, "small", tenant_tier)  # Fallback is always small
                record_llm_duration("small", time.time() - start)

                logger.info(f"Fallback succeeded with {usage.get('total_tokens', 0)} tokens")

            except Exception as fallback_error:
                logger.error(f"Fallback also failed: {fallback_error}")
                error = f"LLM request failed (primary and fallback): {e}"
                fallbacks_used.append("llm_fallback_failed")
                span.set_attribute("orchestrator.generation_error", "fallback_failed")

        except Exception as e:
            logger.exception(f"Unexpected error during generation: {e}")
            error = f"Generation failed: {e}"
            fallbacks_used.append("generation_exception")
            span.set_attribute("orchestrator.generation_error", "exception")

        # Set tokens used attribute on span
        total_tokens = usage.get("total_tokens", 0) if usage else 0
        span.set_attribute("orchestrator.tokens_used", total_tokens)

        timing["generation"] = (time.time() - start) * 1000

        return {
            **state,
            "response": response,
            "model_used": model_used,
            "usage": usage,
            "timing": timing,
            "error": error,
            "fallbacks_used": fallbacks_used,
        }

