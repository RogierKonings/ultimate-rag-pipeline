"""Output validation node for the RAG workflow.

This node validates the generated response for safety issues,
quality, and compliance with guardrails.
"""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workflow.state import RAGState


async def output_validation_node(state: "RAGState") -> "RAGState":
    """
    Validate output for safety issues.

    This node:
    - Checks response for harmful content
    - Validates response quality
    - Applies output guardrails
    - May trigger retry if validation fails

    Args:
        state: Current RAGState with generated response

    Returns:
        Updated RAGState with validation results
    """
    start = time.time()

    timing = dict(state.get("timing", {}))
    error = state.get("error")
    fallbacks_used = list(state.get("fallbacks_used", []))
    response = state.get("response")

    # Check if we have a response to validate
    if not response:
        # If there's no response and no error yet, set one
        if not error:
            error = "No response generated"

    # Stub: Additional validation would be performed here
    # - Content safety checks
    # - Quality validation
    # - Citation verification

    timing["output_validation"] = (time.time() - start) * 1000

    return {
        **state,
        "timing": timing,
        "error": error,
        "fallbacks_used": fallbacks_used,
    }
