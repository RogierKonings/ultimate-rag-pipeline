"""Retrieval node for the RAG workflow.

This node fetches relevant documents from the retrieval service
based on the query and routing strategy.
"""

import time
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from workflow.state import RAGState


def _format_context(documents: List[dict]) -> str:
    """
    Format retrieved documents into a context string.

    Args:
        documents: List of retrieved documents

    Returns:
        Formatted context string for prompt building
    """
    if not documents:
        return ""

    context_parts = []
    for i, doc in enumerate(documents, 1):
        content = doc.get("content", "")
        source = doc.get("source", "unknown")
        context_parts.append(f"[Source {i}: {source}]\n{content}")

    return "\n\n".join(context_parts)


async def retrieval_node(state: "RAGState") -> "RAGState":
    """
    Retrieve relevant context for the query.

    This node:
    - Calls the retrieval service
    - Processes and ranks results
    - Formats context for prompt building
    - Handles retrieval failures gracefully

    Args:
        state: Current RAGState with query and strategy

    Returns:
        Updated RAGState with documents and context
    """
    start = time.time()

    timing = dict(state.get("timing", {}))
    fallbacks_used = list(state.get("fallbacks_used", []))

    # Stub: In production, this would call the retrieval service
    # For now, we return empty results (will be mocked in tests)
    documents: List[dict] = []

    # Format context from retrieved documents
    context = _format_context(documents)

    timing["retrieval"] = (time.time() - start) * 1000

    return {
        **state,
        "documents": documents,
        "context": context,
        "timing": timing,
        "fallbacks_used": fallbacks_used,
    }
