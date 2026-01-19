"""RAG Workflow State definitions using TypedDict for LangGraph compatibility.

This module defines the state schema for the RAG workflow. LangGraph requires
TypedDict-based state definitions rather than Pydantic models for proper
state management and graph compilation.
"""

from typing import TypedDict


class RAGState(TypedDict, total=False):
    """
    State object for the RAG workflow.

    This state is passed between nodes and accumulates information as
    the workflow progresses. Using TypedDict for LangGraph compatibility.

    Fields are divided into logical groups:
    - Input: Initial request data
    - Routing: Strategy decision from routing node
    - Retrieval: Documents and context from retrieval
    - Generation: LLM messages and response
    - Metadata: Model info, usage stats, timing
    - Error handling: Error state and fallback tracking
    """

    # =========================================================================
    # Input Fields
    # =========================================================================
    request_id: str  # Unique identifier for this request
    query: str  # User's original query
    session_id: str | None  # Conversation session ID
    user_id: str | None  # User identifier for ACL
    tenant_id: str | None  # Tenant identifier for ACL
    options: dict  # Request options (temperature, max_tokens, etc.)

    # =========================================================================
    # Routing Fields
    # =========================================================================
    strategy: str  # "simple", "complex", "no_retrieval"

    # =========================================================================
    # Retrieval Fields
    # =========================================================================
    documents: list[dict]  # Retrieved documents with scores and metadata
    context: str  # Formatted context string for prompt

    # =========================================================================
    # Multi-Retrieval Fields (US-10.4.4)
    # =========================================================================
    sub_questions: list[str]  # Decomposed sub-questions from query
    sub_question_mapping: dict  # Maps chunk_id -> list of sub-questions that retrieved it
    retrieval_stats: dict  # {sub_questions, total_retrieved, after_dedup, latency_ms}

    # =========================================================================
    # Retrieval Quality Fields (US-10.2.2)
    # =========================================================================
    retrieval_quality: dict  # {degradation_level, mode, components_used, components_skipped}
    context_quality: str  # "full", "partial", "minimal"

    # =========================================================================
    # Generation Fields
    # =========================================================================
    messages: list[dict]  # Conversation messages for LLM
    response: str | None  # Generated response from LLM

    # =========================================================================
    # Metadata Fields
    # =========================================================================
    model_used: str | None  # Model identifier used for generation
    usage: dict | None  # Token usage statistics
    timing: dict  # Timing metrics per stage

    # =========================================================================
    # Verification Fields (CRAG-style answer verification)
    # =========================================================================
    verification_result: dict | None  # VerificationResult as dict

    # =========================================================================
    # Answer Cache Fields (US-10.5.3)
    # =========================================================================
    cache_hit: bool  # Whether response was served from cache

    # =========================================================================
    # Error Handling Fields
    # =========================================================================
    error: str | None  # Error message if workflow failed
    fallbacks_used: list[str]  # List of fallback strategies applied


def create_initial_state(
    request_id: str,
    query: str,
    session_id: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    options: dict | None = None,
) -> RAGState:
    """
    Create an initial RAGState with default values.

    Args:
        request_id: Unique identifier for this request
        query: User's query text
        session_id: Optional conversation session ID
        user_id: Optional user identifier for ACL
        tenant_id: Optional tenant identifier for ACL
        options: Optional request options (temperature, max_tokens, etc.)

    Returns:
        RAGState with initialized values
    """
    return RAGState(
        # Input
        request_id=request_id,
        query=query,
        session_id=session_id,
        user_id=user_id,
        tenant_id=tenant_id,
        options=options or {},
        # Routing
        strategy="simple",  # Default strategy
        # Retrieval
        documents=[],
        context="",
        # Multi-retrieval (US-10.4.4)
        sub_questions=[],
        sub_question_mapping={},
        retrieval_stats={},
        # Generation
        messages=[],
        response=None,
        # Metadata
        model_used=None,
        usage=None,
        timing={},
        # Verification
        verification_result=None,
        # Answer cache
        cache_hit=False,
        # Error handling
        error=None,
        fallbacks_used=[],
    )


def add_timing(state: RAGState, stage: str, duration_ms: float) -> RAGState:
    """
    Add timing information to the state.

    Args:
        state: Current RAGState
        stage: Name of the workflow stage
        duration_ms: Duration in milliseconds

    Returns:
        Updated RAGState with timing added
    """
    timing = dict(state.get("timing", {}))
    timing[stage] = duration_ms
    return RAGState(**{**state, "timing": timing})


def total_time_ms(state: RAGState) -> float:
    """
    Calculate total workflow time from timing metrics.

    Args:
        state: Current RAGState with timing information

    Returns:
        Total time in milliseconds
    """
    timing = state.get("timing", {})
    return sum(timing.values())
