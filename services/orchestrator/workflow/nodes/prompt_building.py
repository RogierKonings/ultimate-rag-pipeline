"""Prompt building node for the RAG workflow.

This node constructs the prompt for LLM generation based on the
query, context, and conversation history.
"""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workflow.state import RAGState


# System prompt template
SYSTEM_PROMPT = """You are a helpful AI assistant. Use the provided context to answer the user's question accurately. If the context doesn't contain relevant information, acknowledge this and provide what help you can.

Guidelines:
- Be concise and direct in your responses
- Cite sources when using information from the context
- If you're uncertain, express that uncertainty
- Do not make up information not present in the context"""

RAG_PROMPT_TEMPLATE = """Context:
{context}

User Question: {query}

Please provide a helpful response based on the context above."""

NO_CONTEXT_PROMPT_TEMPLATE = """User Question: {query}

Please provide a helpful response."""

# Degradation disclaimers (US-10.2.2)
DEGRADATION_DISCLAIMERS = {
    "semantic_only": (
        "\n\nNote: The search results below were obtained using semantic similarity only. "
        "Keyword matching was unavailable, so some exact term matches may be missing."
    ),
    "keyword_only": (
        "\n\nNote: The search results below were obtained using keyword matching only. "
        "Semantic search was unavailable, so conceptually similar content may be missing."
    ),
    "hybrid_no_rerank": (
        "\n\nNote: Search results were not reranked for relevance. "
        "Results may not be in optimal order."
    ),
    "minimal": (
        "\n\nIMPORTANT: Search capabilities are significantly degraded. "
        "The context provided may be incomplete or less relevant than usual. "
        "Please indicate if the available information is insufficient to answer."
    ),
}


def _build_messages(
    query: str,
    context: str,
    strategy: str,
    history: list[dict] | None = None,
    retrieval_quality: dict | None = None,
) -> list[dict]:
    """
    Build the message list for LLM generation.

    Args:
        query: User's query
        context: Retrieved context (may be empty)
        strategy: Routing strategy
        history: Optional conversation history
        retrieval_quality: Optional retrieval quality info for degradation disclaimers

    Returns:
        List of message dictionaries for LLM
    """
    # Build system prompt with optional degradation disclaimer
    system_content = SYSTEM_PROMPT

    if retrieval_quality:
        degradation_level = retrieval_quality.get("degradation_level", "normal")
        mode = retrieval_quality.get("mode", "hybrid_full")

        if degradation_level != "normal" and mode in DEGRADATION_DISCLAIMERS:
            system_content += DEGRADATION_DISCLAIMERS[mode]

    messages = [{"role": "system", "content": system_content}]

    # Add conversation history if available
    if history:
        for msg in history:
            messages.append(msg)

    # Build user message based on strategy and context
    if strategy == "no_retrieval" or not context:
        user_content = NO_CONTEXT_PROMPT_TEMPLATE.format(query=query)
    else:
        user_content = RAG_PROMPT_TEMPLATE.format(context=context, query=query)

    messages.append({"role": "user", "content": user_content})

    return messages


async def prompt_building_node(state: "RAGState") -> "RAGState":
    """
    Build the prompt for LLM generation.

    This node:
    - Constructs system and user messages
    - Incorporates retrieved context
    - Includes conversation history if present
    - Applies appropriate prompt template based on strategy

    Args:
        state: Current RAGState with query, context, and strategy

    Returns:
        Updated RAGState with messages for LLM
    """
    start = time.time()

    query = state.get("query", "")
    context = state.get("context", "")
    strategy = state.get("strategy", "simple")
    timing = dict(state.get("timing", {}))
    retrieval_quality = state.get("retrieval_quality")

    # Note: History handling would come from session/memory in production
    history: list[dict] = []

    # Build messages for LLM (with degradation-aware prompt adjustments)
    messages = _build_messages(query, context, strategy, history, retrieval_quality)

    timing["prompt_building"] = (time.time() - start) * 1000

    return {
        **state,
        "messages": messages,
        "timing": timing,
    }
