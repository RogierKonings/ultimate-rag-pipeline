"""Generation node for the RAG workflow.

This node calls the LLM gateway to generate a response based on
the constructed prompt messages.
"""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workflow.state import RAGState


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

    # Check for messages
    if not messages:
        error = "No messages available for generation"
        timing["generation"] = (time.time() - start) * 1000
        return {
            **state,
            "timing": timing,
            "error": error,
        }

    # Stub: In production, this would call the LLM gateway
    # For now, we return a placeholder (will be mocked in tests)
    response = None
    model_used = None
    usage = None

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
