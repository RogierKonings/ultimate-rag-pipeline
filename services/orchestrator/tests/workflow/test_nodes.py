"""Tests for individual workflow nodes."""

from uuid import uuid4

import pytest
from workflow.nodes import (
    generation_node,
    input_validation_node,
    output_validation_node,
    prompt_building_node,
    retrieval_node,
    routing_node,
)
from workflow.state import create_initial_state


class TestInputValidationNode:
    """Tests for input_validation_node."""

    @pytest.mark.asyncio
    async def test_validates_valid_query(self):
        """Test validation passes for valid query."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python programming?",
        )

        result = await input_validation_node(state)

        assert result.get("error") is None
        assert "input_validation" in result["timing"]
        assert result["timing"]["input_validation"] >= 0

    @pytest.mark.asyncio
    async def test_fails_empty_query(self):
        """Test validation fails for empty query."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="",
        )

        result = await input_validation_node(state)

        assert result.get("error") is not None
        assert "empty" in result["error"].lower() or "invalid" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_fails_whitespace_query(self):
        """Test validation fails for whitespace-only query."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="   ",
        )

        result = await input_validation_node(state)

        assert result.get("error") is not None

    @pytest.mark.asyncio
    async def test_fails_too_long_query(self):
        """Test validation fails for query exceeding max length."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="x" * 15000,  # Exceeds 10000 char limit
        )

        result = await input_validation_node(state)

        assert result.get("error") is not None
        assert "length" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_preserves_existing_state(self):
        """Test validation preserves existing state fields."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
            session_id=str(uuid4()),
            user_id=str(uuid4()),
        )

        result = await input_validation_node(state)

        assert result["request_id"] == state["request_id"]
        assert result["session_id"] == state["session_id"]
        assert result["user_id"] == state["user_id"]


class TestRoutingNode:
    """Tests for routing_node."""

    @pytest.mark.asyncio
    async def test_routes_simple_query(self):
        """Test simple query routes to 'simple' strategy."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="What is machine learning?",
        )

        result = await routing_node(state)

        assert result["strategy"] == "simple"
        assert "routing" in result["timing"]

    @pytest.mark.asyncio
    async def test_routes_greeting_to_no_retrieval(self):
        """Test greeting routes to 'no_retrieval' strategy."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Hello, how are you?",
        )

        result = await routing_node(state)

        assert result["strategy"] == "no_retrieval"

    @pytest.mark.asyncio
    async def test_routes_complex_query(self):
        """Test complex query routes to 'complex' strategy."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Compare and contrast Python and Java programming languages",
        )

        result = await routing_node(state)

        assert result["strategy"] == "complex"

    @pytest.mark.asyncio
    async def test_routing_records_timing(self):
        """Test routing records timing."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
        )

        result = await routing_node(state)

        assert "routing" in result["timing"]
        assert result["timing"]["routing"] >= 0

    @pytest.mark.asyncio
    async def test_routing_preserves_state(self):
        """Test routing preserves other state fields."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
            session_id=str(uuid4()),
        )
        state["timing"] = {"input_validation": 5.0}

        result = await routing_node(state)

        assert result["session_id"] == state["session_id"]
        assert result["timing"]["input_validation"] == 5.0


class TestRetrievalNode:
    """Tests for retrieval_node."""

    @pytest.mark.asyncio
    async def test_retrieval_returns_empty_documents_stub(self):
        """Test retrieval returns empty documents (stub implementation)."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python?",
        )

        result = await retrieval_node(state)

        # Stub returns empty documents
        assert result["documents"] == []
        assert result["context"] == ""
        assert "retrieval" in result["timing"]

    @pytest.mark.asyncio
    async def test_retrieval_records_timing(self):
        """Test retrieval records timing."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
        )

        result = await retrieval_node(state)

        assert "retrieval" in result["timing"]
        assert result["timing"]["retrieval"] >= 0

    @pytest.mark.asyncio
    async def test_retrieval_preserves_state(self):
        """Test retrieval preserves other state fields."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
        )
        state["strategy"] = "simple"
        state["timing"] = {"routing": 2.0}

        result = await retrieval_node(state)

        assert result["strategy"] == "simple"
        assert result["timing"]["routing"] == 2.0


class TestPromptBuildingNode:
    """Tests for prompt_building_node."""

    @pytest.mark.asyncio
    async def test_builds_messages_for_simple_strategy(self):
        """Test prompt building creates messages for simple strategy."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python?",
        )
        state["strategy"] = "simple"
        state["context"] = "Python is a programming language."

        result = await prompt_building_node(state)

        assert "messages" in result
        assert len(result["messages"]) > 0

        # Should have system and user messages
        roles = [m["role"] for m in result["messages"]]
        assert "system" in roles
        assert "user" in roles

    @pytest.mark.asyncio
    async def test_builds_messages_for_no_retrieval(self):
        """Test prompt building creates messages for no_retrieval strategy."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Hello!",
        )
        state["strategy"] = "no_retrieval"
        state["context"] = ""

        result = await prompt_building_node(state)

        assert "messages" in result
        # User message should not include context section
        user_message = next(m for m in result["messages"] if m["role"] == "user")
        assert "Context:" not in user_message["content"]

    @pytest.mark.asyncio
    async def test_includes_context_in_messages(self):
        """Test context is included in user message."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python?",
        )
        state["strategy"] = "simple"
        state["context"] = "Python is a versatile programming language."

        result = await prompt_building_node(state)

        user_message = next(m for m in result["messages"] if m["role"] == "user")
        assert "Python is a versatile" in user_message["content"]

    @pytest.mark.asyncio
    async def test_prompt_building_records_timing(self):
        """Test prompt building records timing."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
        )
        state["strategy"] = "simple"

        result = await prompt_building_node(state)

        assert "prompt_building" in result["timing"]
        assert result["timing"]["prompt_building"] >= 0


class TestGenerationNode:
    """Tests for generation_node."""

    @pytest.mark.asyncio
    async def test_generation_returns_none_stub(self):
        """Test generation returns None response (stub implementation)."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python?",
        )
        state["messages"] = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What is Python?"},
        ]

        result = await generation_node(state)

        # Stub returns None
        assert result["response"] is None
        assert result["model_used"] is None
        assert result["usage"] is None
        assert "generation" in result["timing"]

    @pytest.mark.asyncio
    async def test_generation_fails_without_messages(self):
        """Test generation fails when no messages present."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test",
        )
        state["messages"] = []

        result = await generation_node(state)

        assert result.get("error") is not None
        assert "messages" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_generation_records_timing(self):
        """Test generation records timing."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
        )
        state["messages"] = [{"role": "user", "content": "test"}]

        result = await generation_node(state)

        assert "generation" in result["timing"]
        assert result["timing"]["generation"] >= 0


class TestOutputValidationNode:
    """Tests for output_validation_node."""

    @pytest.mark.asyncio
    async def test_validates_response(self):
        """Test output validation with a response."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python?",
        )
        state["response"] = "Python is a programming language."

        result = await output_validation_node(state)

        # Should not have error for valid response
        assert result.get("error") is None
        assert "output_validation" in result["timing"]

    @pytest.mark.asyncio
    async def test_fails_when_no_response(self):
        """Test output validation fails when no response."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test",
        )
        state["response"] = None

        result = await output_validation_node(state)

        assert result.get("error") is not None
        assert "response" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_preserves_existing_error(self):
        """Test output validation preserves existing error."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test",
        )
        state["error"] = "Previous error"
        state["response"] = None

        result = await output_validation_node(state)

        # Should preserve previous error
        assert result["error"] == "Previous error"

    @pytest.mark.asyncio
    async def test_output_validation_records_timing(self):
        """Test output validation records timing."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test",
        )
        state["response"] = "Test response"

        result = await output_validation_node(state)

        assert "output_validation" in result["timing"]
        assert result["timing"]["output_validation"] >= 0


class TestNodeChaining:
    """Tests for node chaining behavior."""

    @pytest.mark.asyncio
    async def test_nodes_can_be_chained(self):
        """Test nodes can be chained together manually."""
        initial_state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python?",
        )

        # Chain nodes manually
        state = await input_validation_node(initial_state)
        state = await routing_node(state)
        state = await retrieval_node(state)
        state = await prompt_building_node(state)
        state = await generation_node(state)
        state = await output_validation_node(state)

        # All timings should be recorded
        assert "input_validation" in state["timing"]
        assert "routing" in state["timing"]
        assert "retrieval" in state["timing"]
        assert "prompt_building" in state["timing"]
        assert "generation" in state["timing"]
        assert "output_validation" in state["timing"]

    @pytest.mark.asyncio
    async def test_state_accumulates_through_chain(self):
        """Test state accumulates information through chain."""
        initial_state = create_initial_state(
            request_id=str(uuid4()),
            query="Hello there!",  # Should route to no_retrieval
        )

        state = await input_validation_node(initial_state)
        state = await routing_node(state)

        # After routing, strategy should be set
        assert state["strategy"] == "no_retrieval"

        state = await prompt_building_node(state)

        # After prompt building, messages should be set
        assert len(state["messages"]) > 0
