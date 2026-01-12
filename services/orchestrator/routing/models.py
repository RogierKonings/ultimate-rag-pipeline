"""Pydantic models for query routing."""

from enum import Enum

from pydantic import BaseModel, Field


class QueryIntent(str, Enum):
    """Classification of query intent."""

    FACTUAL = "factual"  # Seeking specific information
    ANALYTICAL = "analytical"  # Requires reasoning/comparison
    PROCEDURAL = "procedural"  # How-to/step-by-step
    CONVERSATIONAL = "conversational"  # Chitchat/greetings
    CLARIFICATION = "clarification"  # Asking to explain more


class RoutingStrategy(str, Enum):
    """Strategy for handling the query."""

    SIMPLE = "simple"  # Single retrieval pass
    COMPLEX = "complex"  # Multi-step retrieval
    NO_RETRIEVAL = "no_retrieval"  # Direct LLM response


class RoutingResult(BaseModel):
    """Result of query routing decision."""

    strategy: RoutingStrategy = Field(
        ...,
        description="The routing strategy to use for this query",
    )
    intent: QueryIntent = Field(..., description="The classified intent of the query")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0 - 1.0)",
    )
    complexity_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Query complexity score (0.0 - 1.0)",
    )
    reasoning: str | None = Field(
        default=None,
        description="Optional explanation for routing decision",
    )


class RoutingConfig(BaseModel):
    """Configuration for the QueryRouter."""

    # Complexity thresholds
    complexity_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Complexity score above which query is considered complex",
    )

    # Confidence thresholds
    min_greeting_confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for greeting classification",
    )

    # Feature weights for complexity scoring
    clause_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Weight for clause count in complexity",
    )
    length_weight: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Weight for query length in complexity",
    )
    modifier_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Weight for temporal/comparison modifiers",
    )
    history_weight: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Weight for conversation history complexity",
    )

    # Query length normalization
    max_query_length: int = Field(
        default=500,
        gt=0,
        description="Query length for maximum length complexity score",
    )
