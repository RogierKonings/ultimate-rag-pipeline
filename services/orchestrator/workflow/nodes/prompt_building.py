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
- ALWAYS cite sources using bracket notation like [1], [2], etc. matching the document numbers in the context
- Place citations inline immediately after the relevant claim, e.g. "The total was €500 [3]."
- If you're uncertain, express that uncertainty
- Do not make up information not present in the context"""

RAG_PROMPT_TEMPLATE = """Context:
{context}

User Question: {query}

Please provide a helpful response based on the context above. Cite each source you use with [N] notation matching the document numbers."""

NO_CONTEXT_PROMPT_TEMPLATE = """User Question: {query}

Please provide a helpful response."""

# Multi-hop system prompt (US-10.4.4)
MULTI_HOP_SYSTEM_PROMPT = """You are a helpful AI assistant answering a complex question that has been broken down into sub-questions.

Guidelines:
- Address all aspects of the original question
- Synthesize information from multiple sub-question contexts
- ALWAYS cite sources using bracket notation like [1], [2], etc. matching the document numbers in the context
- Place citations inline immediately after the relevant claim
- If some sub-questions couldn't be fully answered, acknowledge this
- Be concise and direct in your responses
- Do not make up information not present in the context"""

MULTI_HOP_PROMPT_TEMPLATE = """Original Question: {query}

Sub-questions analyzed:
{sub_questions}

{context}

Instructions:
1. Address all aspects of the original question
2. Synthesize information from the context sections above
3. If information for any sub-question is incomplete, acknowledge this

Please provide a comprehensive answer to the original question."""

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
    sub_questions: list[str] | None = None,
) -> list[dict]:
    """
    Build the message list for LLM generation.

    Args:
        query: User's query
        context: Retrieved context (may be empty)
        strategy: Routing strategy
        history: Optional conversation history
        retrieval_quality: Optional retrieval quality info for degradation disclaimers
        sub_questions: Optional list of decomposed sub-questions (US-10.4.4)

    Returns:
        List of message dictionaries for LLM
    """
    # Check if this is a multi-hop query (US-10.4.4)
    is_multi_hop = sub_questions and len(sub_questions) > 1

    # Build system prompt
    system_content = MULTI_HOP_SYSTEM_PROMPT if is_multi_hop else SYSTEM_PROMPT

    # Add degradation disclaimers if applicable
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

    # Build user message based on strategy, context, and multi-hop status
    if strategy == "no_retrieval" or not context:
        user_content = NO_CONTEXT_PROMPT_TEMPLATE.format(query=query)
    elif is_multi_hop:
        # Multi-hop prompt with sub-question listing
        sub_questions_text = "\n".join(f"{i}. {sq}" for i, sq in enumerate(sub_questions, 1))
        user_content = MULTI_HOP_PROMPT_TEMPLATE.format(
            query=query,
            sub_questions=sub_questions_text,
            context=context,
        )
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
    - Handles multi-hop prompts when sub-questions are present (US-10.4.4)

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
    sub_questions = state.get("sub_questions", [])

    # Note: History handling would come from session/memory in production
    history: list[dict] = []

    # Build messages for LLM (with degradation-aware and multi-hop prompt adjustments)
    messages = _build_messages(query, context, strategy, history, retrieval_quality, sub_questions)

    timing["prompt_building"] = (time.time() - start) * 1000

    return {
        **state,
        "messages": messages,
        "timing": timing,
    }
