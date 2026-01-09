"""Context formatting utilities for the Prompt Builder.

This module provides functions for formatting retrieved documents into
context strings, creating citation references, and truncating content
to fit within token limits.
"""

from typing import Any, Optional
import tiktoken


# Default encoding for token counting
DEFAULT_ENCODING = "cl100k_base"


def get_tokenizer(model_name: str = "gpt-4") -> tiktoken.Encoding:
    """Get the tiktoken encoding for a given model.

    Args:
        model_name: The name of the model (e.g., 'gpt-4', 'gpt-3.5-turbo').

    Returns:
        The tiktoken Encoding object.
    """
    try:
        return tiktoken.encoding_for_model(model_name)
    except KeyError:
        # Fall back to cl100k_base for unknown models
        return tiktoken.get_encoding(DEFAULT_ENCODING)


def count_tokens(text: str, model_name: str = "gpt-4") -> int:
    """Count the number of tokens in a text string.

    Args:
        text: The text to count tokens for.
        model_name: The model name for selecting the tokenizer.

    Returns:
        The number of tokens in the text.
    """
    if not text:
        return 0
    encoding = get_tokenizer(model_name)
    return len(encoding.encode(text))


def format_context(documents: list[dict[str, Any]]) -> str:
    """Format a list of retrieved documents into a context string.

    Each document should have at minimum a 'content' field. Additional
    fields like 'title', 'source', 'metadata' are optional but improve
    context quality.

    Args:
        documents: List of document dictionaries with at least 'content' field.

    Returns:
        Formatted context string with numbered documents.
    """
    if not documents:
        return ""

    context_parts = []

    for i, doc in enumerate(documents, start=1):
        content = doc.get("content", "").strip()
        if not content:
            continue

        # Build document header
        title = doc.get("metadata", {}).get("title") or doc.get("title", f"Document {i}")
        source = doc.get("source", "")

        # Format document block
        doc_block = f"[{i}] {title}"
        if source:
            doc_block += f"\nSource: {source}"
        doc_block += f"\n{content}"

        context_parts.append(doc_block)

    return "\n\n---\n\n".join(context_parts)


def format_citations(documents: list[dict[str, Any]], max_citations: int = 10) -> str:
    """Create citation references from a list of documents.

    Args:
        documents: List of document dictionaries.
        max_citations: Maximum number of citations to include.

    Returns:
        Formatted citation string listing sources.
    """
    if not documents:
        return ""

    citations = []

    for i, doc in enumerate(documents[:max_citations], start=1):
        title = doc.get("metadata", {}).get("title") or doc.get("title", f"Document {i}")
        source = doc.get("source", "")

        citation = f"[{i}] {title}"
        if source:
            citation += f" - {source}"

        citations.append(citation)

    return "\n".join(citations)


def truncate_context(
    context: str,
    max_tokens: int,
    model_name: str = "gpt-4",
    preserve_end: bool = False,
) -> tuple[str, bool]:
    """Truncate context to fit within token limits.

    The truncation attempts to preserve complete sentences and paragraphs
    where possible.

    Args:
        context: The context string to truncate.
        max_tokens: Maximum number of tokens allowed.
        model_name: The model name for token counting.
        preserve_end: If True, preserve the end of the context instead of the beginning.

    Returns:
        Tuple of (truncated context string, was_truncated boolean).
    """
    if not context:
        return "", False

    current_tokens = count_tokens(context, model_name)

    if current_tokens <= max_tokens:
        return context, False

    encoding = get_tokenizer(model_name)
    tokens = encoding.encode(context)

    if preserve_end:
        # Keep tokens from the end
        truncated_tokens = tokens[-max_tokens:]
        truncated_text = encoding.decode(truncated_tokens)
        # Try to start at a word boundary
        first_space = truncated_text.find(" ")
        if first_space > 0 and first_space < len(truncated_text) // 4:
            truncated_text = "..." + truncated_text[first_space + 1:]
        else:
            truncated_text = "..." + truncated_text
    else:
        # Keep tokens from the beginning
        truncated_tokens = tokens[:max_tokens]
        truncated_text = encoding.decode(truncated_tokens)
        # Try to end at a sentence boundary
        last_period = truncated_text.rfind(". ")
        last_newline = truncated_text.rfind("\n")
        cut_point = max(last_period, last_newline)
        if cut_point > len(truncated_text) * 0.75:
            truncated_text = truncated_text[: cut_point + 1] + "..."
        else:
            truncated_text = truncated_text.rstrip() + "..."

    return truncated_text, True


def truncate_documents(
    documents: list[dict[str, Any]],
    max_tokens: int,
    model_name: str = "gpt-4",
) -> tuple[list[dict[str, Any]], bool]:
    """Truncate a list of documents to fit within token limits.

    Documents are included in order until the token limit is reached.
    The last included document may be truncated.

    Args:
        documents: List of document dictionaries.
        max_tokens: Maximum total tokens for all documents.
        model_name: The model name for token counting.

    Returns:
        Tuple of (truncated documents list, was_truncated boolean).
    """
    if not documents:
        return [], False

    result = []
    current_tokens = 0
    was_truncated = False

    for doc in documents:
        content = doc.get("content", "")
        doc_tokens = count_tokens(content, model_name)

        if current_tokens + doc_tokens <= max_tokens:
            result.append(doc)
            current_tokens += doc_tokens
        else:
            # Try to fit a truncated version
            remaining_tokens = max_tokens - current_tokens
            if remaining_tokens > 50:  # Only include if meaningful content remains
                truncated_content, _ = truncate_context(
                    content, remaining_tokens, model_name
                )
                truncated_doc = doc.copy()
                truncated_doc["content"] = truncated_content
                truncated_doc["truncated"] = True
                result.append(truncated_doc)
            was_truncated = True
            break

    if len(result) < len(documents):
        was_truncated = True

    return result, was_truncated


def format_history_summary(history: list[dict[str, str]], max_messages: int = 10) -> str:
    """Format conversation history into a summary string.

    Args:
        history: List of message dictionaries with 'role' and 'content' keys.
        max_messages: Maximum number of messages to include.

    Returns:
        Formatted conversation summary string.
    """
    if not history:
        return ""

    # Take the most recent messages
    recent_history = history[-max_messages:]

    summary_parts = []
    for msg in recent_history:
        role = msg.get("role", "unknown").capitalize()
        content = msg.get("content", "").strip()
        if content:
            # Truncate very long messages in the summary
            if len(content) > 500:
                content = content[:500] + "..."
            summary_parts.append(f"{role}: {content}")

    return "\n\n".join(summary_parts)


def extract_document_metadata(
    documents: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Extract metadata from documents for citation purposes.

    Args:
        documents: List of document dictionaries.

    Returns:
        List of metadata dictionaries with id, title, source, and score.
    """
    metadata_list = []

    for i, doc in enumerate(documents):
        metadata = {
            "index": i + 1,
            "id": doc.get("id", f"doc-{i + 1}"),
            "title": doc.get("metadata", {}).get("title") or doc.get("title", f"Document {i + 1}"),
            "source": doc.get("source", ""),
            "score": doc.get("score"),
        }
        metadata_list.append(metadata)

    return metadata_list
