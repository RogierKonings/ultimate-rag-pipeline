"""Prompt Builder for the Orchestrator Service.

This module provides the PromptBuilder class which constructs
formatted message lists for LLM calls based on query, context,
conversation history, and strategy configuration.
"""

from typing import Any

from jinja2 import BaseLoader, Environment

from .context import (
    count_tokens,
    format_citations,
    format_context,
    truncate_context,
)
from .models import (
    PromptConfig,
    PromptStrategy,
    TokenLimits,
)
from .templates import get_template


class PromptBuilder:
    """Builds prompts for LLM calls with context and citation support.

    The PromptBuilder handles:
    - Template selection based on strategy
    - Context formatting and truncation
    - Conversation history integration
    - Citation instruction injection
    - Token counting and limit enforcement

    Example:
        >>> builder = PromptBuilder()
        >>> messages = builder.build(
        ...     query="What is Python?",
        ...     context="Python is a programming language...",
        ...     history=[],
        ...     strategy="rag"
        ... )
        >>> # Returns list of message dicts with role and content
    """

    def __init__(self, config: PromptConfig | None = None):
        """Initialize the PromptBuilder.

        Args:
            config: Optional PromptConfig instance. If not provided,
                    default configuration will be used.
        """
        self.config = config or PromptConfig()
        self._jinja_env = Environment(loader=BaseLoader())

    def build(
        self,
        query: str,
        context: str | None = None,
        history: list[dict[str, str]] | None = None,
        strategy: str | None = None,
        documents: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        """Build a prompt message list for the LLM.

        Args:
            query: The user's query string.
            context: Optional pre-formatted context string.
            history: Optional list of previous messages (role, content dicts).
            strategy: Optional strategy override (e.g., 'rag', 'no_context').
            documents: Optional list of retrieved documents (used if context not provided).

        Returns:
            List of message dictionaries with 'role' and 'content' keys.
        """
        history = history or []
        strategy = strategy or self.config.strategy

        # Determine the effective strategy
        effective_strategy = self._determine_strategy(strategy, context, documents)

        # Format context from documents if not provided directly
        if context is None and documents:
            context = format_context(documents)

        # Truncate context if needed
        context_truncated = False
        if context and self.config.truncate_context:
            context, context_truncated = truncate_context(
                context,
                self.config.token_limits.max_context_tokens,
                self.config.model_name,
            )

        # Build the messages list
        messages = []

        # Add system prompt
        if self.config.include_system_prompt:
            system_content = self._render_system_prompt(
                effective_strategy, context, documents,
            )
            if system_content:
                messages.append({"role": "system", "content": system_content})

        # Add conversation history
        if history:
            history_messages = self._format_history(history)
            messages.extend(history_messages)

        # Add current user query
        messages.append({"role": "user", "content": query})

        return messages

    def build_with_metadata(
        self,
        query: str,
        context: str | None = None,
        history: list[dict[str, str]] | None = None,
        strategy: str | None = None,
        documents: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build a prompt with additional metadata about the build process.

        Args:
            query: The user's query string.
            context: Optional pre-formatted context string.
            history: Optional list of previous messages.
            strategy: Optional strategy override.
            documents: Optional list of retrieved documents.

        Returns:
            Dictionary containing:
                - messages: List of message dicts
                - total_tokens: Estimated token count
                - context_truncated: Whether context was truncated
                - history_truncated: Whether history was truncated
                - strategy_used: The effective strategy used
        """
        history = history or []
        strategy = strategy or self.config.strategy

        # Build the messages
        messages = self.build(
            query=query,
            context=context,
            history=history,
            strategy=strategy,
            documents=documents,
        )

        # Calculate token count
        total_tokens = self._count_messages_tokens(messages)

        # Determine if truncation occurred
        context_truncated = False
        if context or documents:
            original_context = context if context else format_context(documents or [])
            original_tokens = count_tokens(original_context, self.config.model_name)
            context_truncated = original_tokens > self.config.token_limits.max_context_tokens

        history_truncated = len(history) > self.config.token_limits.max_history_tokens // 50

        return {
            "messages": messages,
            "total_tokens": total_tokens,
            "context_truncated": context_truncated,
            "history_truncated": history_truncated,
            "strategy_used": strategy,
        }

    def _determine_strategy(
        self,
        requested_strategy: str,
        context: str | None,
        documents: list[dict[str, Any]] | None,
    ) -> str:
        """Determine the effective strategy based on inputs.

        Args:
            requested_strategy: The requested strategy.
            context: The context string.
            documents: The documents list.

        Returns:
            The effective strategy to use.
        """
        # If no context or documents, fall back to no_context
        if not context and not documents:
            if requested_strategy in (
                PromptStrategy.RAG.value,
                PromptStrategy.RAG_CITATIONS.value,
            ):
                return PromptStrategy.NO_CONTEXT.value

        return requested_strategy

    def _render_system_prompt(
        self,
        strategy: str,
        context: str | None,
        documents: list[dict[str, Any]] | None,
    ) -> str:
        """Render the system prompt for the given strategy.

        Args:
            strategy: The prompt strategy.
            context: The formatted context string.
            documents: The source documents.

        Returns:
            The rendered system prompt.
        """
        template_str = get_template(strategy)
        template = self._jinja_env.from_string(template_str)

        # Prepare template variables
        template_vars = {}

        if context:
            template_vars["context"] = context

        if documents and self.config.citation_config.enabled:
            citations = format_citations(
                documents, self.config.citation_config.max_citations,
            )
            template_vars["citations"] = citations

        # Render the template
        return template.render(**template_vars).strip()

    def _format_history(
        self, history: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Format conversation history for inclusion in the prompt.

        Args:
            history: List of message dictionaries.

        Returns:
            List of formatted message dictionaries.
        """
        if not history:
            return []

        # Calculate token budget for history
        max_history_tokens = self.config.token_limits.max_history_tokens

        # If preserve_recent_history is True, include most recent messages first
        if self.config.preserve_recent_history:
            history = list(reversed(history))

        formatted_messages = []
        current_tokens = 0

        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            msg_tokens = count_tokens(content, self.config.model_name)

            if current_tokens + msg_tokens > max_history_tokens:
                break

            formatted_messages.append({"role": role, "content": content})
            current_tokens += msg_tokens

        # Reverse back to chronological order if we reversed
        if self.config.preserve_recent_history:
            formatted_messages = list(reversed(formatted_messages))

        return formatted_messages

    def _count_messages_tokens(self, messages: list[dict[str, str]]) -> int:
        """Count total tokens in a list of messages.

        Args:
            messages: List of message dictionaries.

        Returns:
            Total token count.
        """
        total = 0
        for msg in messages:
            # Add overhead for message structure (role, etc.)
            total += 4  # Approximate overhead per message
            total += count_tokens(msg.get("content", ""), self.config.model_name)
        return total

    def render_template(
        self,
        template_name: str,
        **kwargs: Any,
    ) -> str:
        """Render a specific template with provided variables.

        Args:
            template_name: The name of the template to render.
            **kwargs: Variables to pass to the template.

        Returns:
            The rendered template string.
        """
        template_str = get_template(template_name)
        template = self._jinja_env.from_string(template_str)
        return template.render(**kwargs).strip()

    def estimate_tokens(
        self,
        query: str,
        context: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, int]:
        """Estimate token counts for prompt components.

        Args:
            query: The user's query.
            context: Optional context string.
            history: Optional conversation history.

        Returns:
            Dictionary with token counts for each component.
        """
        history = history or []

        query_tokens = count_tokens(query, self.config.model_name)
        context_tokens = count_tokens(context or "", self.config.model_name)
        history_tokens = sum(
            count_tokens(msg.get("content", ""), self.config.model_name)
            for msg in history
        )

        # Estimate system prompt tokens
        system_prompt_tokens = 100  # Approximate base system prompt size

        return {
            "query_tokens": query_tokens,
            "context_tokens": context_tokens,
            "history_tokens": history_tokens,
            "system_prompt_tokens": system_prompt_tokens,
            "total_estimated": query_tokens + context_tokens + history_tokens + system_prompt_tokens,
        }


def create_prompt_builder(
    strategy: str = "rag",
    max_context_tokens: int = 2000,
    max_history_tokens: int = 1000,
    model_name: str = "gpt-4",
) -> PromptBuilder:
    """Factory function to create a configured PromptBuilder.

    Args:
        strategy: The default prompt strategy.
        max_context_tokens: Maximum tokens for context.
        max_history_tokens: Maximum tokens for history.
        model_name: Model name for token counting.

    Returns:
        A configured PromptBuilder instance.
    """
    config = PromptConfig(
        strategy=PromptStrategy(strategy),
        token_limits=TokenLimits(
            max_context_tokens=max_context_tokens,
            max_history_tokens=max_history_tokens,
        ),
        model_name=model_name,
    )
    return PromptBuilder(config)
