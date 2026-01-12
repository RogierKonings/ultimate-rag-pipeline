"""Prompts module for the Orchestrator Service.

This module provides prompt building functionality including:
- Jinja2 templates for different prompt strategies (RAG, no-context, follow-up)
- PromptBuilder class for constructing LLM message lists
- Context formatting and truncation utilities
- Token counting for limit enforcement

Example usage:
    >>> from prompts import PromptBuilder, PromptConfig, PromptStrategy
    >>>
    >>> # Create a builder with default config
    >>> builder = PromptBuilder()
    >>>
    >>> # Build a RAG prompt
    >>> messages = builder.build(
    ...     query="What is Python?",
    ...     documents=[{"content": "Python is...", "title": "Intro"}],
    ...     strategy="rag"
    ... )
    >>>
    >>> # Or use the factory function
    >>> from prompts import create_prompt_builder
    >>> builder = create_prompt_builder(
    ...     strategy="rag",
    ...     max_context_tokens=2000
    ... )
"""

# Templates
# Builder
from .builder import (
    PromptBuilder,
    create_prompt_builder,
)

# Context utilities
from .context import (
    count_tokens,
    extract_document_metadata,
    format_citations,
    format_context,
    format_history_summary,
    get_tokenizer,
    truncate_context,
    truncate_documents,
)

# Models
from .models import (
    CitationConfig,
    Message,
    PromptBuildRequest,
    PromptBuildResponse,
    PromptConfig,
    PromptStrategy,
    TokenLimits,
)
from .templates import (
    CLARIFICATION_PROMPT,
    FOLLOW_UP_PROMPT,
    NO_CONTEXT_PROMPT,
    RAG_CITATIONS_PROMPT,
    RAG_SYSTEM_PROMPT,
    SUMMARY_PROMPT,
    TEMPLATES,
    get_template,
    list_templates,
)

__all__ = [
    # Templates
    "RAG_SYSTEM_PROMPT",
    "NO_CONTEXT_PROMPT",
    "FOLLOW_UP_PROMPT",
    "RAG_CITATIONS_PROMPT",
    "CLARIFICATION_PROMPT",
    "SUMMARY_PROMPT",
    "TEMPLATES",
    "get_template",
    "list_templates",
    # Models
    "PromptStrategy",
    "TokenLimits",
    "CitationConfig",
    "PromptConfig",
    "Message",
    "PromptBuildRequest",
    "PromptBuildResponse",
    # Builder
    "PromptBuilder",
    "create_prompt_builder",
    # Context utilities
    "format_context",
    "format_citations",
    "truncate_context",
    "truncate_documents",
    "format_history_summary",
    "count_tokens",
    "get_tokenizer",
    "extract_document_metadata",
]
