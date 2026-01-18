"""LangGraph workflow definition for the RAG pipeline.

This module defines the StateGraph for the RAG workflow with conditional
edges for routing decisions and proper error handling.
"""

from typing import Literal

from langgraph.graph import END, StateGraph
from workflow.nodes import (
    generation_node,
    input_validation_node,
    output_validation_node,
    prompt_building_node,
    retrieval_node,
    routing_node,
    verification_node,
)
from workflow.state import RAGState


def _route_after_routing(state: RAGState) -> Literal["retrieval", "prompt_building"]:
    """
    Route based on query strategy after routing node.

    Args:
        state: Current RAGState with strategy set

    Returns:
        Next node to execute: "retrieval" or "prompt_building"
    """
    strategy = state.get("strategy", "simple")

    if strategy == "no_retrieval":
        # Skip retrieval for no_retrieval strategy
        return "prompt_building"
    # For simple and complex strategies, perform retrieval
    return "retrieval"


def _route_after_input_validation(
    state: RAGState,
) -> Literal["routing", "output_validation"]:
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
    2. routing - Determine handling strategy (simple/complex/no_retrieval)
    3. retrieval - Fetch relevant context (conditional on strategy)
    4. prompt_building - Construct the LLM prompt
    5. generation - Generate response with LLM
    6. verification - Verify answer is grounded in context (CRAG-style)
    7. output_validation - Check output for safety

    Conditional edges:
    - After routing: Skip retrieval for no_retrieval strategy
    - After input_validation: Skip to output if error detected

    Returns:
        Compiled StateGraph ready for execution
    """
    # Create graph with RAGState schema
    graph = StateGraph(RAGState)

    # Add nodes
    graph.add_node("input_validation", input_validation_node)
    graph.add_node("routing", routing_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("prompt_building", prompt_building_node)
    graph.add_node("generation", generation_node)
    graph.add_node("verification", verification_node)
    graph.add_node("output_validation", output_validation_node)

    # Set entry point
    graph.set_entry_point("input_validation")

    # Add conditional edge after input_validation
    graph.add_conditional_edges(
        "input_validation",
        _route_after_input_validation,
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
            "prompt_building": "prompt_building",
        },
    )

    # Retrieval -> Prompt Building
    graph.add_edge("retrieval", "prompt_building")

    # Prompt Building -> Generation
    graph.add_edge("prompt_building", "generation")

    # Generation -> Verification
    graph.add_edge("generation", "verification")

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
