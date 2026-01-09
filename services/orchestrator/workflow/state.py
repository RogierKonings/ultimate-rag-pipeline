"""RAG Workflow State definitions using TypedDict for LangGraph compatibility.

This module defines the state schema for the RAG workflow. LangGraph requires
TypedDict-based state definitions rather than Pydantic models for proper
state management and graph compilation.
"""

from typing import TypedDict, Optional, List


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
    session_id: Optional[str]  # Conversation session ID
    user_id: Optional[str]  # User identifier for ACL
    tenant_id: Optional[str]  # Tenant identifier for ACL

    # =========================================================================
    # Routing Fields
    # =========================================================================
    strategy: str  # "simple", "complex", "no_retrieval"

    # =========================================================================
    # Retrieval Fields
    # =========================================================================
    documents: List[dict]  # Retrieved documents with scores and metadata
    context: str  # Formatted context string for prompt

    # =========================================================================
    # Generation Fields
    # =========================================================================
    messages: List[dict]  # Conversation messages for LLM
    response: Optional[str]  # Generated response from LLM

    # =========================================================================
    # Metadata Fields
    # =========================================================================
    model_used: Optional[str]  # Model identifier used for generation
    usage: Optional[dict]  # Token usage statistics
    timing: dict  # Timing metrics per stage

    # =========================================================================
    # Error Handling Fields
    # =========================================================================
    error: Optional[str]  # Error message if workflow failed
    fallbacks_used: List[str]  # List of fallback strategies applied


def create_initial_state(
    request_id: str,
    query: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> RAGState:
    """
    Create an initial RAGState with default values.

    Args:
        request_id: Unique identifier for this request
        query: User's query text
        session_id: Optional conversation session ID
        user_id: Optional user identifier for ACL
        tenant_id: Optional tenant identifier for ACL

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
        # Routing
        strategy="simple",  # Default strategy
        # Retrieval
        documents=[],
        context="",
        # Generation
        messages=[],
        response=None,
        # Metadata
        model_used=None,
        usage=None,
        timing={},
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
