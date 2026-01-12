"""Tests for RAGState TypedDict and helper functions."""

from uuid import uuid4

from workflow.state import (
    RAGState,
    add_timing,
    create_initial_state,
    total_time_ms,
)


class TestRAGState:
    """Tests for RAGState TypedDict."""

    def test_rag_state_has_all_required_fields(self):
        """Test RAGState has all expected fields."""
        # Create a state with all fields
        state: RAGState = {
            "request_id": str(uuid4()),
            "query": "What is Python?",
            "session_id": str(uuid4()),
            "user_id": str(uuid4()),
            "tenant_id": str(uuid4()),
            "strategy": "simple",
            "documents": [],
            "context": "",
            "messages": [],
            "response": None,
            "model_used": None,
            "usage": None,
            "timing": {},
            "error": None,
            "fallbacks_used": [],
        }

        # Verify all fields are present
        assert "request_id" in state
        assert "query" in state
        assert "session_id" in state
        assert "user_id" in state
        assert "tenant_id" in state
        assert "strategy" in state
        assert "documents" in state
        assert "context" in state
        assert "messages" in state
        assert "response" in state
        assert "model_used" in state
        assert "usage" in state
        assert "timing" in state
        assert "error" in state
        assert "fallbacks_used" in state

    def test_rag_state_input_fields(self):
        """Test RAGState input field values."""
        request_id = str(uuid4())
        query = "Test query"
        session_id = str(uuid4())
        user_id = str(uuid4())
        tenant_id = str(uuid4())

        state: RAGState = {
            "request_id": request_id,
            "query": query,
            "session_id": session_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
        }

        assert state["request_id"] == request_id
        assert state["query"] == query
        assert state["session_id"] == session_id
        assert state["user_id"] == user_id
        assert state["tenant_id"] == tenant_id

    def test_rag_state_routing_fields(self):
        """Test RAGState routing field values."""
        state: RAGState = {
            "strategy": "complex",
        }

        assert state["strategy"] == "complex"

    def test_rag_state_retrieval_fields(self):
        """Test RAGState retrieval field values."""
        documents = [
            {"id": "doc1", "content": "test", "score": 0.9},
            {"id": "doc2", "content": "test2", "score": 0.8},
        ]
        context = "Test context"

        state: RAGState = {
            "documents": documents,
            "context": context,
        }

        assert state["documents"] == documents
        assert len(state["documents"]) == 2
        assert state["context"] == context

    def test_rag_state_generation_fields(self):
        """Test RAGState generation field values."""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
        ]
        response = "Hello! How can I help?"
        model_used = "llama-3.1-8b"
        usage = {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18}

        state: RAGState = {
            "messages": messages,
            "response": response,
            "model_used": model_used,
            "usage": usage,
        }

        assert state["messages"] == messages
        assert state["response"] == response
        assert state["model_used"] == model_used
        assert state["usage"] == usage

    def test_rag_state_error_handling_fields(self):
        """Test RAGState error handling field values."""
        error = "Test error message"
        fallbacks = ["fallback1", "fallback2"]

        state: RAGState = {
            "error": error,
            "fallbacks_used": fallbacks,
        }

        assert state["error"] == error
        assert state["fallbacks_used"] == fallbacks

    def test_rag_state_timing_fields(self):
        """Test RAGState timing field values."""
        timing = {
            "input_validation": 5.0,
            "routing": 2.0,
            "retrieval": 50.0,
            "generation": 100.0,
        }

        state: RAGState = {
            "timing": timing,
        }

        assert state["timing"] == timing
        assert state["timing"]["retrieval"] == 50.0

    def test_rag_state_allows_optional_fields(self):
        """Test RAGState allows optional fields to be omitted."""
        # TypedDict with total=False allows all fields to be optional
        state: RAGState = {
            "query": "Test query",
        }

        assert state["query"] == "Test query"
        assert state.get("response") is None
        assert state.get("error") is None

    def test_rag_state_strategy_values(self):
        """Test RAGState supports all strategy values."""
        strategies = ["simple", "complex", "no_retrieval"]

        for strategy in strategies:
            state: RAGState = {"strategy": strategy}
            assert state["strategy"] == strategy


class TestCreateInitialState:
    """Tests for create_initial_state helper function."""

    def test_create_initial_state_with_required_fields(self):
        """Test creating initial state with required fields."""
        request_id = str(uuid4())
        query = "What is Python?"

        state = create_initial_state(request_id=request_id, query=query)

        assert state["request_id"] == request_id
        assert state["query"] == query
        assert state["session_id"] is None
        assert state["user_id"] is None
        assert state["tenant_id"] is None

    def test_create_initial_state_with_all_fields(self):
        """Test creating initial state with all fields."""
        request_id = str(uuid4())
        query = "What is Python?"
        session_id = str(uuid4())
        user_id = str(uuid4())
        tenant_id = str(uuid4())

        state = create_initial_state(
            request_id=request_id,
            query=query,
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
        )

        assert state["request_id"] == request_id
        assert state["query"] == query
        assert state["session_id"] == session_id
        assert state["user_id"] == user_id
        assert state["tenant_id"] == tenant_id

    def test_create_initial_state_default_values(self):
        """Test default values in initial state."""
        state = create_initial_state(request_id="test-id", query="test query")

        # Check defaults
        assert state["strategy"] == "simple"
        assert state["documents"] == []
        assert state["context"] == ""
        assert state["messages"] == []
        assert state["response"] is None
        assert state["model_used"] is None
        assert state["usage"] is None
        assert state["timing"] == {}
        assert state["error"] is None
        assert state["fallbacks_used"] == []


class TestTimingHelpers:
    """Tests for timing helper functions."""

    def test_add_timing_to_empty_state(self):
        """Test adding timing to state with empty timing dict."""
        state: RAGState = {
            "query": "test",
            "timing": {},
        }

        updated = add_timing(state, "retrieval", 50.5)

        assert updated["timing"]["retrieval"] == 50.5
        # Original state should not be modified
        assert state["timing"] == {}

    def test_add_timing_preserves_existing(self):
        """Test adding timing preserves existing timing entries."""
        state: RAGState = {
            "query": "test",
            "timing": {"input_validation": 5.0},
        }

        updated = add_timing(state, "routing", 2.5)

        assert updated["timing"]["input_validation"] == 5.0
        assert updated["timing"]["routing"] == 2.5

    def test_add_timing_overwrites_existing_stage(self):
        """Test adding timing overwrites existing stage timing."""
        state: RAGState = {
            "query": "test",
            "timing": {"retrieval": 50.0},
        }

        updated = add_timing(state, "retrieval", 75.0)

        assert updated["timing"]["retrieval"] == 75.0

    def test_total_time_ms_empty_timing(self):
        """Test total_time_ms with empty timing dict."""
        state: RAGState = {
            "query": "test",
            "timing": {},
        }

        total = total_time_ms(state)

        assert total == 0.0

    def test_total_time_ms_with_multiple_stages(self):
        """Test total_time_ms sums all stage timings."""
        state: RAGState = {
            "query": "test",
            "timing": {
                "input_validation": 5.0,
                "routing": 2.0,
                "retrieval": 50.0,
                "prompt_building": 3.0,
                "generation": 100.0,
                "output_validation": 5.0,
            },
        }

        total = total_time_ms(state)

        assert total == 165.0

    def test_total_time_ms_missing_timing_key(self):
        """Test total_time_ms handles missing timing key."""
        state: RAGState = {
            "query": "test",
        }

        total = total_time_ms(state)

        assert total == 0.0
