"""Pydantic models for prompt configuration.

This module defines the configuration models used by the PromptBuilder
for controlling template selection, token limits, and formatting options.
"""

from enum import Enum

from pydantic import BaseModel, Field


class PromptStrategy(str, Enum):
    """Enum for available prompt strategies."""

    RAG = "rag"
    RAG_CITATIONS = "rag_citations"
    NO_CONTEXT = "no_context"
    FOLLOW_UP = "follow_up"
    CLARIFICATION = "clarification"
    SUMMARY = "summary"


class TokenLimits(BaseModel):
    """Token limit configuration for prompts."""

    max_context_tokens: int = Field(
        default=2000,
        ge=100,
        le=100000,
        description="Maximum tokens allowed for context section",
    )
    max_history_tokens: int = Field(
        default=1000,
        ge=0,
        le=50000,
        description="Maximum tokens allowed for conversation history",
    )
    max_total_tokens: int = Field(
        default=4096,
        ge=100,
        le=128000,
        description="Maximum total tokens for the entire prompt",
    )
    reserved_output_tokens: int = Field(
        default=1024,
        ge=100,
        le=16000,
        description="Tokens reserved for model output",
    )

    @property
    def available_input_tokens(self) -> int:
        """Calculate available tokens for input (total minus reserved output)."""
        return self.max_total_tokens - self.reserved_output_tokens


class CitationConfig(BaseModel):
    """Configuration for citation formatting."""

    enabled: bool = Field(
        default=True,
        description="Whether to include citation instructions",
    )
    format: str = Field(
        default="[Source: {title}]",
        description="Format string for citations",
    )
    include_uri: bool = Field(
        default=True,
        description="Whether to include source URIs in citations",
    )
    max_citations: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of citations to include",
    )


class PromptConfig(BaseModel):
    """Configuration for prompt building.

    This model controls all aspects of prompt construction including
    template selection, token limits, and citation formatting.
    """

    strategy: PromptStrategy = Field(
        default=PromptStrategy.RAG,
        description="The prompt strategy to use",
    )
    token_limits: TokenLimits = Field(
        default_factory=TokenLimits,
        description="Token limit configuration",
    )
    citation_config: CitationConfig = Field(
        default_factory=CitationConfig,
        description="Citation formatting configuration",
    )
    model_name: str = Field(
        default="gpt-4",
        description="Model name for token counting (affects tokenizer selection)",
    )
    include_system_prompt: bool = Field(
        default=True,
        description="Whether to include a system prompt",
    )
    truncate_context: bool = Field(
        default=True,
        description="Whether to truncate context if it exceeds limits",
    )
    preserve_recent_history: bool = Field(
        default=True,
        description="When truncating history, preserve most recent messages",
    )

    class Config:
        """Pydantic configuration."""

        use_enum_values = True


class Message(BaseModel):
    """A single message in the conversation."""

    role: str = Field(
        ...,
        pattern="^(system|user|assistant)$",
        description="The role of the message sender",
    )
    content: str = Field(
        ...,
        min_length=1,
        description="The content of the message",
    )


class PromptBuildRequest(BaseModel):
    """Request model for building a prompt."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The user's query",
    )
    context: str | None = Field(
        default=None,
        description="Retrieved context to include in the prompt",
    )
    history: list[Message] = Field(
        default_factory=list,
        description="Conversation history",
    )
    config: PromptConfig = Field(
        default_factory=PromptConfig,
        description="Prompt configuration",
    )


class PromptBuildResponse(BaseModel):
    """Response model from prompt building."""

    messages: list[Message] = Field(
        ...,
        description="The formatted messages for the LLM",
    )
    total_tokens: int = Field(
        ...,
        ge=0,
        description="Total estimated token count",
    )
    context_truncated: bool = Field(
        default=False,
        description="Whether the context was truncated",
    )
    history_truncated: bool = Field(
        default=False,
        description="Whether the history was truncated",
    )
    strategy_used: str = Field(
        ...,
        description="The prompt strategy that was used",
    )
