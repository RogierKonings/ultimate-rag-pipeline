"""Prompt building node for the RAG workflow.

This node constructs the prompt for LLM generation based on the
query, context, and conversation history.
"""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workflow.state import RAGState


# System prompt template
SYSTEM_PROMPT = """You are a helpful AI assistant that ONLY answers questions based on the provided document context. You must follow these rules strictly:

1. ONLY use information from the provided documents to answer questions
2. ALWAYS cite the document name/source when using information (e.g., "According to [Document 1: filename.pdf]...")
3. If the documents don't contain relevant information, say: "I don't have information about this in the provided documents."
4. NEVER make up or infer information not explicitly stated in the documents
5. Be concise and direct in your responses
6. If you're uncertain about something, express that uncertainty"""

RAG_PROMPT_TEMPLATE = """I have retrieved the following documents that may be relevant to your question:

{context}

---

User Question: {query}

Please answer ONLY based on the information in the documents above. Always cite which document your answer comes from."""

NO_CONTEXT_PROMPT_TEMPLATE = """User Question: {query}

I don't have any documents to reference for this question. I cannot provide an answer without relevant document context."""


def _build_messages(
    query: str,
    context: str,
    strategy: str,
    history: list[dict] | None = None,
) -> list[dict]:
    """
    Build the message list for LLM generation.

    Args:
        query: User's query
        context: Retrieved context (may be empty)
        strategy: Routing strategy
        history: Optional conversation history

    Returns:
        List of message dictionaries for LLM
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

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

    # Note: History handling would come from session/memory in production
    history: list[dict] = []

    # Build messages for LLM
    messages = _build_messages(query, context, strategy, history)

    timing["prompt_building"] = (time.time() - start) * 1000

    return {
        **state,
        "messages": messages,
        "timing": timing,
    }
