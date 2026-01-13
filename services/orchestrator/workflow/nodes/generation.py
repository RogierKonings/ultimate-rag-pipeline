"""Generation node for the RAG workflow.

This node calls the LLM gateway to generate a response based on
the constructed prompt messages.
"""

import logging
import time
from typing import TYPE_CHECKING

import httpx

from config import get_config

if TYPE_CHECKING:
    from workflow.state import RAGState

logger = logging.getLogger(__name__)


async def generation_node(state: "RAGState") -> "RAGState":
    """
    Generate response using LLM.

    This node:
    - Sends messages to LLM gateway
    - Captures the generated response
    - Records model used and token usage
    - Handles generation failures

    Args:
        state: Current RAGState with messages for LLM

    Returns:
        Updated RAGState with response, model_used, and usage
    """
    start = time.time()

    timing = dict(state.get("timing", {}))
    fallbacks_used = list(state.get("fallbacks_used", []))
    error = state.get("error")
    messages = state.get("messages", [])

    config = get_config()

    # Check for messages
    if not messages:
        error = "No messages available for generation"
        timing["generation"] = (time.time() - start) * 1000
        return {
            **state,
            "timing": timing,
            "error": error,
        }

    response = None
    model_used = config.default_model
    usage = {}

    # Get options from state for per-request overrides
    options = state.get("options", {})
    temperature = options.get("temperature", config.temperature)
    max_tokens = options.get("max_tokens", config.max_tokens)

    try:
        async with httpx.AsyncClient(timeout=config.stream_timeout) as client:
            # Build OpenAI-compatible request
            payload = {
                "model": config.default_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            }

            llm_response = await client.post(
                f"{config.llm_gateway_url}/v1/chat/completions",
                json=payload,
            )
            llm_response.raise_for_status()

            result = llm_response.json()

            # Extract response content
            choices = result.get("choices", [])
            if choices:
                response = choices[0].get("message", {}).get("content", "")
                model_used = result.get("model", config.default_model)

            # Extract usage info
            usage_data = result.get("usage", {})
            usage = {
                "prompt_tokens": usage_data.get("prompt_tokens", 0),
                "completion_tokens": usage_data.get("completion_tokens", 0),
                "total_tokens": usage_data.get("total_tokens", 0),
            }

            logger.info(f"Generated response with {usage.get('total_tokens', 0)} tokens")

    except httpx.HTTPStatusError as e:
        logger.error(f"LLM gateway returned error: {e.response.status_code}")
        error = f"LLM request failed: {e.response.status_code}"
        fallbacks_used.append("llm_error")
    except httpx.RequestError as e:
        logger.error(f"Failed to connect to LLM gateway: {e}")
        error = f"LLM connection failed: {e}"
        fallbacks_used.append("llm_unavailable")
    except Exception as e:
        logger.exception(f"Unexpected error during generation: {e}")
        error = f"Generation failed: {e}"
        fallbacks_used.append("generation_exception")

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
