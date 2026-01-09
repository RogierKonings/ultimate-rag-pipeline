"""Input validation node for the RAG workflow.

This node validates incoming queries for safety issues, including
prompt injection attempts and PII content.
"""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workflow.state import RAGState


async def input_validation_node(state: "RAGState") -> "RAGState":
    """
    Validate input for safety issues.

    This node:
    - Checks for prompt injection attempts
    - Validates query format and length
    - Flags potentially problematic content
    - Sets error state if validation fails

    Args:
        state: Current RAGState with query to validate

    Returns:
        Updated RAGState with validation results
    """
    start = time.time()

    # Initialize updated fields
    timing = dict(state.get("timing", {}))
    error = state.get("error")
    fallbacks_used = list(state.get("fallbacks_used", []))

    query = state.get("query", "")

    # Basic validation checks
    if not query or not query.strip():
        error = "Query is empty or invalid"
        timing["input_validation"] = (time.time() - start) * 1000
        return {
            **state,
            "timing": timing,
            "error": error,
        }

    # Query length validation
    max_query_length = 10000
    if len(query) > max_query_length:
        error = f"Query exceeds maximum length of {max_query_length} characters"
        timing["input_validation"] = (time.time() - start) * 1000
        return {
            **state,
            "timing": timing,
            "error": error,
        }

    # Stub: Additional validation would be performed here
    # - Prompt injection detection
    # - PII detection
    # - Content filtering

    timing["input_validation"] = (time.time() - start) * 1000

    return {
        **state,
        "timing": timing,
        "error": error,
        "fallbacks_used": fallbacks_used,
    }
