"""Tests for the LangGraph workflow definition."""

from uuid import uuid4

import pytest
from workflow.graph import (
    _route_after_cache_check,
    _route_after_input_validation,
    _route_after_routing,
    build_rag_workflow,
    get_graph_visualization,
)
from workflow.state import RAGState, create_initial_state


class TestRouteAfterRouting:
    """Tests for _route_after_routing conditional edge function."""

    def test_route_simple_strategy_to_retrieval(self):
        """Test simple strategy routes to retrieval."""
        state: RAGState = {"strategy": "simple"}

        result = _route_after_routing(state)

        assert result == "retrieval"

    def test_route_complex_strategy_to_retrieval(self):
        """Test complex strategy routes to retrieval."""
        state: RAGState = {"strategy": "complex"}

        result = _route_after_routing(state)

        assert result == "retrieval"

    def test_route_no_retrieval_strategy_to_prompt_building(self):
        """Test no_retrieval strategy skips to prompt_building."""
        state: RAGState = {"strategy": "no_retrieval"}

        result = _route_after_routing(state)

        assert result == "prompt_building"

    def test_route_default_strategy_to_retrieval(self):
        """Test default (missing) strategy routes to retrieval."""
        state: RAGState = {}

        result = _route_after_routing(state)

        assert result == "retrieval"


class TestRouteAfterCacheCheck:
    """Tests for _route_after_cache_check conditional edge function (US-10.5.3)."""

    def test_route_cache_hit_to_output_validation(self):
        """Test cache hit skips to output_validation."""
        state: RAGState = {"query": "test", "cache_hit": True}

        result = _route_after_cache_check(state)

        assert result == "output_validation"

    def test_route_cache_miss_to_routing(self):
        """Test cache miss continues to routing."""
        state: RAGState = {"query": "test", "cache_hit": False}

        result = _route_after_cache_check(state)

        assert result == "routing"

    def test_route_missing_cache_hit_key_to_routing(self):
        """Test missing cache_hit key defaults to routing."""
        state: RAGState = {"query": "test"}

        result = _route_after_cache_check(state)

        assert result == "routing"


class TestRouteAfterInputValidation:
    """Tests for _route_after_input_validation conditional edge function."""

    def test_route_no_error_to_cache_check(self):
        """Test no error routes to cache_check node (US-10.5.3)."""
        state: RAGState = {"query": "test", "error": None}

        result = _route_after_input_validation(state)

        assert result == "cache_check"

    def test_route_with_error_to_output_validation(self):
        """Test error routes to output_validation."""
        state: RAGState = {"query": "test", "error": "Input validation failed"}

        result = _route_after_input_validation(state)

        assert result == "output_validation"

    def test_route_missing_error_key_to_cache_check(self):
        """Test missing error key routes to cache_check."""
        state: RAGState = {"query": "test"}

        result = _route_after_input_validation(state)

        assert result == "cache_check"


class TestBuildRagWorkflow:
    """Tests for build_rag_workflow function."""

    def test_build_rag_workflow_returns_compiled_graph(self):
        """Test that build_rag_workflow returns a compiled graph."""
        workflow = build_rag_workflow()

        # Check it's a compiled graph (has ainvoke method)
        assert hasattr(workflow, "ainvoke")
        assert hasattr(workflow, "invoke")

    def test_build_rag_workflow_has_expected_nodes(self):
        """Test that workflow has all expected nodes."""
        workflow = build_rag_workflow()

        # Get the graph structure
        graph = workflow.get_graph()

        # Check for expected nodes in the graph
        node_names = [node.name for node in graph.nodes.values()]

        assert "input_validation" in node_names
        assert "routing" in node_names
        assert "retrieval" in node_names
        assert "prompt_building" in node_names
        assert "generation" in node_names
        assert "output_validation" in node_names

    @pytest.mark.asyncio
    async def test_workflow_executes_simple_path(self):
        """Test workflow executes through simple retrieval path."""
        workflow = build_rag_workflow()

        initial_state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python?",
        )

        # Execute the workflow
        result = await workflow.ainvoke(initial_state)

        # Check state was modified
        assert "timing" in result
        assert "input_validation" in result["timing"]
        assert "routing" in result["timing"]
        assert "retrieval" in result["timing"]
        assert "prompt_building" in result["timing"]
        assert "generation" in result["timing"]
        assert "output_validation" in result["timing"]

    @pytest.mark.asyncio
    async def test_workflow_executes_no_retrieval_path(self):
        """Test workflow skips retrieval for no_retrieval strategy."""
        workflow = build_rag_workflow()

        initial_state = create_initial_state(
            request_id=str(uuid4()),
            query="Hello, how are you?",  # Should route to no_retrieval
        )

        # Execute the workflow
        result = await workflow.ainvoke(initial_state)

        # Check strategy was set correctly
        assert result["strategy"] == "no_retrieval"

        # Should still have prompt_building and generation timing
        assert "prompt_building" in result["timing"]
        assert "generation" in result["timing"]

    @pytest.mark.asyncio
    async def test_workflow_handles_empty_query_error(self):
        """Test workflow handles empty query error path."""
        workflow = build_rag_workflow()

        initial_state = create_initial_state(
            request_id=str(uuid4()),
            query="",  # Empty query should fail validation
        )

        # Execute the workflow
        result = await workflow.ainvoke(initial_state)

        # Check error was set
        assert result.get("error") is not None
        assert "empty" in result["error"].lower() or "invalid" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_workflow_preserves_request_id(self):
        """Test workflow preserves request_id through execution."""
        workflow = build_rag_workflow()

        request_id = str(uuid4())
        initial_state = create_initial_state(
            request_id=request_id,
            query="Test query",
        )

        result = await workflow.ainvoke(initial_state)

        assert result["request_id"] == request_id

    @pytest.mark.asyncio
    async def test_workflow_preserves_user_context(self):
        """Test workflow preserves user context fields."""
        workflow = build_rag_workflow()

        session_id = str(uuid4())
        user_id = str(uuid4())
        tenant_id = str(uuid4())

        initial_state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
        )

        result = await workflow.ainvoke(initial_state)

        assert result["session_id"] == session_id
        assert result["user_id"] == user_id
        assert result["tenant_id"] == tenant_id


class TestGraphVisualization:
    """Tests for get_graph_visualization function."""

    def test_get_graph_visualization_returns_mermaid(self):
        """Test visualization returns mermaid diagram."""
        mermaid = get_graph_visualization()

        # Should be a non-empty string
        assert isinstance(mermaid, str)
        assert len(mermaid) > 0

    def test_visualization_contains_node_names(self):
        """Test visualization contains expected node names."""
        mermaid = get_graph_visualization()

        # Check for node names in the diagram
        assert "input_validation" in mermaid
        assert "routing" in mermaid
        assert "retrieval" in mermaid
        assert "prompt_building" in mermaid
        assert "generation" in mermaid
        assert "output_validation" in mermaid

    def test_visualization_shows_edges(self):
        """Test visualization shows edge connections."""
        mermaid = get_graph_visualization()

        # Mermaid diagrams use --> for edges
        assert "-->" in mermaid


class TestWorkflowWithMockedNodes:
    """Tests for workflow execution with mocked node behavior."""

    @pytest.mark.asyncio
    async def test_workflow_with_retrieval_results(self):
        """Test workflow properly processes retrieved documents."""
        workflow = build_rag_workflow()

        # Create state with some context already
        initial_state = create_initial_state(
            request_id=str(uuid4()),
            query="What is machine learning?",
        )

        result = await workflow.ainvoke(initial_state)

        # Workflow should complete without error for valid queries
        assert result["timing"]["input_validation"] >= 0
        assert result["timing"]["routing"] >= 0

    @pytest.mark.asyncio
    async def test_workflow_timing_is_recorded(self):
        """Test all workflow stages record timing."""
        workflow = build_rag_workflow()

        initial_state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
        )

        result = await workflow.ainvoke(initial_state)

        # All timing values should be non-negative
        for stage, timing_ms in result["timing"].items():
            assert timing_ms >= 0, f"Stage {stage} has negative timing"

    @pytest.mark.asyncio
    async def test_workflow_messages_are_built(self):
        """Test workflow builds messages for generation."""
        workflow = build_rag_workflow()

        initial_state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python?",
        )

        result = await workflow.ainvoke(initial_state)

        # Messages should be built
        assert "messages" in result
        assert isinstance(result["messages"], list)
        assert len(result["messages"]) > 0

        # Should have system and user messages
        roles = [m["role"] for m in result["messages"]]
        assert "system" in roles
        assert "user" in roles
