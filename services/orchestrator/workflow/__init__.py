"""RAG Workflow module for the Orchestrator Service.

This module provides a LangGraph-based workflow for Retrieval-Augmented Generation.

Public API:
    - RAGState: TypedDict state schema for the workflow
    - create_initial_state: Helper to create initial state
    - build_rag_workflow: Factory function to build the compiled workflow graph
    - get_graph_visualization: Get Mermaid diagram of the workflow

Node functions (for testing/extension):
    - input_validation_node
    - routing_node
    - retrieval_node
    - prompt_building_node
    - generation_node
    - output_validation_node
"""

from workflow.graph import (
    build_rag_workflow,
    get_graph_visualization,
)
from workflow.nodes import (
    generation_node,
    input_validation_node,
    output_validation_node,
    prompt_building_node,
    retrieval_node,
    routing_node,
)
from workflow.state import (
    RAGState,
    add_timing,
    create_initial_state,
    total_time_ms,
)

__all__ = [
    # State
    "RAGState",
    "create_initial_state",
    "add_timing",
    "total_time_ms",
    # Graph
    "build_rag_workflow",
    "get_graph_visualization",
    # Nodes
    "input_validation_node",
    "routing_node",
    "retrieval_node",
    "prompt_building_node",
    "generation_node",
    "output_validation_node",
]
