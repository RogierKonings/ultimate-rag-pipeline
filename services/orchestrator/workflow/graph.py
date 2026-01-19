"""LangGraph workflow definition for the RAG pipeline.

This module defines the StateGraph for the RAG workflow with conditional
edges for routing decisions and proper error handling.
"""

from typing import Literal

from langgraph.graph import END, StateGraph
from workflow.nodes import (
    cache_check_node,
    cache_store_node,
    decomposition_node,
    generation_node,
    input_validation_node,
    multi_retrieval_node,
    output_validation_node,
    prompt_building_node,
    retrieval_node,
    routing_node,
    verification_node,
)
from workflow.state import RAGState

# Multi-hop strategies that require decomposition (US-10.4.3)
MULTI_HOP_STRATEGIES = {"multi_hop", "comparison", "aggregation"}


def _route_after_routing(
    state: RAGState,
) -> Literal["retrieval", "decomposition", "prompt_building"]:
    """
    Route based on query strategy after routing node.

    Args:
        state: Current RAGState with strategy set

    Returns:
        Next node to execute: "retrieval", "decomposition", or "prompt_building"
    """
    strategy = state.get("strategy", "simple")

    if strategy == "no_retrieval":
        # Skip retrieval for no_retrieval strategy
        return "prompt_building"

    # Route multi-hop strategies to decomposition first (US-10.4.3)
    if strategy in MULTI_HOP_STRATEGIES:
        return "decomposition"

    # Complex queries also go to decomposition for potential sub-question generation
    if strategy == "complex":
        return "decomposition"

    # Default: simple retrieval
    return "retrieval"


def _route_after_input_validation(
    state: RAGState,
) -> Literal["cache_check", "output_validation"]:
    """
    Route after input validation node.

    If there's an error, skip to output validation (which will handle the error).

    Args:
        state: Current RAGState

    Returns:
        Next node to execute
    """
    error = state.get("error")

    if error:
        # Skip to output validation if there's an error
        return "output_validation"
    return "cache_check"


def _route_after_cache_check(
    state: RAGState,
) -> Literal["routing", "output_validation"]:
    """
    Route after cache check node.

    If cache hit, skip to output validation (response is ready).
    Otherwise continue to routing for normal processing.

    Args:
        state: Current RAGState

    Returns:
        Next node to execute
    """
    cache_hit = state.get("cache_hit", False)

    if cache_hit:
        # Skip to output validation if cache hit (response already populated)
        return "output_validation"
    return "routing"


def _route_after_generation(
    state: RAGState,
) -> Literal["output_validation"]:
    """
    Route after generation node.

    Args:
        state: Current RAGState

    Returns:
        Next node to execute
    """
    # Always proceed to output validation
    return "output_validation"


def build_rag_workflow() -> StateGraph:
    """
    Build and compile the RAG workflow graph.

    The workflow consists of the following stages:
    1. input_validation - Check input for safety issues
    2. cache_check - Check answer cache for instant response (US-10.5.3)
    3. routing - Determine handling strategy (simple/complex/no_retrieval/multi_hop/etc.)
    4. decomposition - Break complex queries into sub-questions (US-10.4.3)
    5. retrieval - Fetch relevant context (conditional on strategy)
       OR multi_retrieval - Parallel retrieval for sub-questions (US-10.4.4)
    6. prompt_building - Construct the LLM prompt
    7. generation - Generate response with LLM
    8. cache_store - Store response in cache for future hits (US-10.5.3)
    9. verification - Verify answer is grounded in context (CRAG-style)
    10. output_validation - Check output for safety

    Conditional edges:
    - After input_validation: Skip to output if error detected
    - After cache_check: Skip to output if cache hit (US-10.5.3)
    - After routing: Skip retrieval for no_retrieval strategy,
                     go to decomposition for multi-hop/complex (US-10.4.3)

    Returns:
        Compiled StateGraph ready for execution
    """
    # Create graph with RAGState schema
    graph = StateGraph(RAGState)

    # Add nodes
    graph.add_node("input_validation", input_validation_node)
    graph.add_node("cache_check", cache_check_node)
    graph.add_node("routing", routing_node)
    graph.add_node("decomposition", decomposition_node)  # US-10.4.3
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("multi_retrieval", multi_retrieval_node)  # US-10.4.4
    graph.add_node("prompt_building", prompt_building_node)
    graph.add_node("generation", generation_node)
    graph.add_node("cache_store", cache_store_node)
    graph.add_node("verification", verification_node)
    graph.add_node("output_validation", output_validation_node)

    # Set entry point
    graph.set_entry_point("input_validation")

    # Add conditional edge after input_validation
    graph.add_conditional_edges(
        "input_validation",
        _route_after_input_validation,
        {
            "cache_check": "cache_check",
            "output_validation": "output_validation",
        },
    )

    # Add conditional edge after cache_check (US-10.5.3)
    graph.add_conditional_edges(
        "cache_check",
        _route_after_cache_check,
        {
            "routing": "routing",
            "output_validation": "output_validation",
        },
    )

    # Add conditional edge after routing (for strategy-based routing)
    graph.add_conditional_edges(
        "routing",
        _route_after_routing,
        {
            "retrieval": "retrieval",
            "decomposition": "decomposition",  # US-10.4.3: multi-hop/complex
            "prompt_building": "prompt_building",
        },
    )

    # Decomposition -> Multi-Retrieval (US-10.4.3)
    graph.add_edge("decomposition", "multi_retrieval")

    # Retrieval -> Prompt Building
    graph.add_edge("retrieval", "prompt_building")

    # Multi-Retrieval -> Prompt Building (US-10.4.4)
    graph.add_edge("multi_retrieval", "prompt_building")

    # Prompt Building -> Generation
    graph.add_edge("prompt_building", "generation")

    # Generation -> Cache Store (store response for future cache hits)
    graph.add_edge("generation", "cache_store")

    # Cache Store -> Verification
    graph.add_edge("cache_store", "verification")

    # Verification -> Output Validation
    graph.add_edge("verification", "output_validation")

    # Output Validation -> END
    graph.add_edge("output_validation", END)

    # Compile and return the graph
    return graph.compile()


def get_graph_visualization() -> str:
    """
    Get a Mermaid diagram representation of the workflow.

    Returns:
        Mermaid diagram string
    """
    # Build and compile the workflow to get the graph
    compiled_graph = build_rag_workflow()

    # Get the drawable graph from the compiled workflow
    return compiled_graph.get_graph().draw_mermaid()
