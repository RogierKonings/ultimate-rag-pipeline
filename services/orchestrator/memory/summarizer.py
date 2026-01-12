"""History summarization for conversation memory."""

from typing import Any, Protocol

from .models import MemoryConfig, Message, MessageRole


class ModelGateway(Protocol):
    """Protocol for model gateway."""

    async def chat_completion(self, request: Any) -> Any:
        """Send a chat completion request."""
        ...


class HistorySummarizer:
    """
    Summarizes conversation history to save tokens.

    Uses an LLM to create concise summaries of older
    conversation turns that can be included as context.
    """

    SUMMARIZE_PROMPT = """Summarize the following conversation history into a concise paragraph.
Focus on key topics discussed, decisions made, and any important context for future messages.

{existing_summary}

Recent messages:
{messages}

Provide a brief summary (max 2-3 paragraphs):"""

    def __init__(
        self,
        config: MemoryConfig,
        gateway: ModelGateway | None = None,
    ):
        """Initialize the history summarizer.

        Args:
            config: Memory configuration.
            gateway: Optional model gateway for LLM-based summarization.
        """
        self.config = config
        self.gateway = gateway

    async def summarize(
        self,
        messages: list[Message],
        existing_summary: str | None = None,
    ) -> str:
        """
        Summarize a list of messages.

        Args:
            messages: Messages to summarize.
            existing_summary: Previous summary to incorporate.

        Returns:
            Summary text.
        """
        if not self.gateway:
            # Fallback: simple truncation
            return self._simple_summary(messages)

        # Format messages for prompt
        formatted = self._format_messages(messages)

        existing = ""
        if existing_summary:
            existing = f"Previous summary:\n{existing_summary}\n\n"

        prompt = self.SUMMARIZE_PROMPT.format(
            existing_summary=existing,
            messages=formatted,
        )

        try:
            # Import here to avoid circular dependencies
            # Gateway models would need to be imported
            from dataclasses import dataclass

            @dataclass
            class ChatMessage:
                role: str
                content: str

            @dataclass
            class ChatCompletionRequest:
                model: str
                messages: list[ChatMessage]
                max_tokens: int
                temperature: float

            request = ChatCompletionRequest(
                model=self.config.summary_model,
                messages=[ChatMessage(role="user", content=prompt)],
                max_tokens=self.config.summary_max_tokens,
                temperature=0.3,  # Lower temperature for consistent summaries
            )

            response = await self.gateway.chat_completion(request)
            return response.choices[0].message.content

        except Exception:
            return self._simple_summary(messages)

    def _format_messages(self, messages: list[Message]) -> str:
        """Format messages for summary prompt.

        Args:
            messages: Messages to format.

        Returns:
            Formatted string of messages.
        """
        lines = []
        for msg in messages:
            role = msg.role.value.capitalize()
            content = msg.content[:500]  # Truncate long messages
            if len(msg.content) > 500:
                content += "..."
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def _simple_summary(self, messages: list[Message]) -> str:
        """Create simple summary without LLM.

        Args:
            messages: Messages to summarize.

        Returns:
            Simple summary string.
        """
        if not messages:
            return ""

        # Extract key topics from user messages
        user_messages = [m for m in messages if m.role == MessageRole.USER]

        if not user_messages:
            return "Previous conversation context."

        topics = []
        for msg in user_messages[-5:]:  # Last 5 user messages
            # Take first sentence or first 100 chars
            content = msg.content.split(".")[0][:100]
            topics.append(content)

        return f"Topics discussed: {'; '.join(topics)}"
