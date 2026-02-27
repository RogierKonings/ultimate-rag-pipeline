"""Tests for multi-hop routing and decomposition (US-10.4.3).

This module tests the extended routing strategies and query decomposition
for comparison, aggregation, and multi-hop queries.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from workflow.nodes.decomposition import (
    QueryDecomposer,
    decomposition_node,
)
from workflow.nodes.routing import (
    AGGREGATION_PATTERNS,
    COMPARISON_PATTERNS,
    SEQUENTIAL_PATTERNS,
    _classify_query,
    _detect_multi_hop_type,
    routing_node,
)
from workflow.state import create_initial_state

# =============================================================================
# Multi-Hop Detection Tests
# =============================================================================


class TestMultiHopDetection:
    """Tests for multi-hop pattern detection."""

    @pytest.mark.parametrize(
        "query,expected_type",
        [
            # Comparison patterns
            ("Compare Python and JavaScript", "comparison"),
            ("What is the difference between REST and GraphQL?", "comparison"),
            ("Python vs Java for web development", "comparison"),
            ("Which is better, React or Vue?", "comparison"),
            ("Pros and cons of microservices", "comparison"),
            ("How does SQL differ from NoSQL?", "comparison"),
            ("Contrast functional and object-oriented programming", "comparison"),
            # Aggregation patterns
            ("List all authentication methods in the API", "aggregation"),
            ("What are all the configuration options?", "aggregation"),
            ("Summarize the main features of Python", "aggregation"),
            ("Overview of the system architecture", "aggregation"),
            ("Everything about error handling in the codebase", "aggregation"),
            # Sequential patterns
            ("First configure the database, then start the server", "sequential"),
            ("Step by step guide to deploy the application", "sequential"),
            ("What happens when a request comes in and then gets processed?", "sequential"),
            # Multi-entity patterns (maps to comparison)
            ("Both Python and Java support multithreading", "comparison"),
            ("Relationship between microservices and Docker containers", "comparison"),
        ],
    )
    def test_detects_multi_hop_type(self, query: str, expected_type: str):
        """Test detection of various multi-hop query types."""
        result = _detect_multi_hop_type(query.lower())
        assert result == expected_type

    @pytest.mark.parametrize(
        "query",
        [
            "What is Python?",
            "How do I install pip?",
            "Explain machine learning",
            "Tell me about databases",
            "What is a function?",
        ],
    )
    def test_returns_none_for_simple_queries(self, query: str):
        """Test that simple queries return None for multi-hop type."""
        result = _detect_multi_hop_type(query.lower())
        assert result is None


# =============================================================================
# Routing Strategy Classification Tests
# =============================================================================


class TestRoutingClassification:
    """Tests for query classification into routing strategies."""

    @pytest.mark.parametrize(
        "query,expected_strategy,expected_type",
        [
            # Comparison queries
            ("Compare Python and Java", "comparison", "comparison"),
            ("What is the difference between SQL and NoSQL?", "comparison", "comparison"),
            # Aggregation queries
            ("List all the API endpoints", "aggregation", "aggregation"),
            ("Summarize the project structure", "aggregation", "aggregation"),
            # Multi-hop queries
            ("First setup the DB, then configure the API", "multi_hop", "sequential"),
            # Simple queries (no multi-hop)
            ("What is Python?", "simple", None),
            # No retrieval (greetings)
            ("Hello, how are you?", "no_retrieval", None),
        ],
    )
    def test_classify_query_strategies(
        self,
        query: str,
        expected_strategy: str,
        expected_type: str | None,
    ):
        """Test query classification returns correct strategy and type."""
        strategy, multi_hop_type = _classify_query(query)
        assert strategy == expected_strategy
        assert multi_hop_type == expected_type


# =============================================================================
# Routing Node Tests
# =============================================================================


class TestRoutingNode:
    """Tests for routing_node with multi-hop strategies."""

    @pytest.mark.asyncio
    async def test_routes_comparison_query(self):
        """Test comparison query routes to 'comparison' strategy."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Compare Python and JavaScript for backend development",
        )

        result = await routing_node(state)

        assert result["strategy"] == "comparison"
        assert result.get("multi_hop_type") == "comparison"
        assert result["intent"] == "ANALYTICAL"
        assert result["complexity_score"] == 0.9
        assert "routing" in result["timing"]

    @pytest.mark.asyncio
    async def test_routes_aggregation_query(self):
        """Test aggregation query routes to 'aggregation' strategy."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="List all the authentication methods supported",
        )

        result = await routing_node(state)

        assert result["strategy"] == "aggregation"
        assert result.get("multi_hop_type") == "aggregation"
        assert result["intent"] == "ANALYTICAL"
        assert result["complexity_score"] == 0.9

    @pytest.mark.asyncio
    async def test_routes_sequential_query(self):
        """Test sequential query routes to 'multi_hop' strategy."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="First configure the database, then deploy the service",
        )

        result = await routing_node(state)

        assert result["strategy"] == "multi_hop"
        assert result.get("multi_hop_type") == "sequential"
        assert result["intent"] == "ANALYTICAL"
        assert result["complexity_score"] == 0.9

    @pytest.mark.asyncio
    async def test_routes_simple_query(self):
        """Test simple query routes to 'simple' strategy without multi_hop_type."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="What is machine learning?",
        )

        result = await routing_node(state)

        assert result["strategy"] == "simple"
        assert result.get("multi_hop_type") is None

    @pytest.mark.asyncio
    async def test_routes_greeting_to_no_retrieval(self):
        """Test greeting routes to 'no_retrieval' strategy."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Hello, thanks for the help!",
        )

        result = await routing_node(state)

        assert result["strategy"] == "no_retrieval"
        assert result.get("multi_hop_type") is None


# =============================================================================
# Query Decomposer Tests
# =============================================================================


class TestQueryDecomposer:
    """Tests for QueryDecomposer class."""

    @pytest.mark.asyncio
    async def test_decompose_returns_sub_questions(self):
        """Test decomposer returns list of sub-questions."""
        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": '["What are the features of Python?", "What are the features of JavaScript?"]',
                    },
                },
            ],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=MagicMock(
                    json=lambda: mock_response,
                    raise_for_status=lambda: None,
                ),
            )

            decomposer = QueryDecomposer(
                llm_gateway_url="http://localhost:8004",
                model="test-model",
            )
            sub_questions = await decomposer.decompose(
                "Compare Python and JavaScript",
                multi_hop_type="comparison",
            )

        assert len(sub_questions) == 2
        assert "Python" in sub_questions[0]
        assert "JavaScript" in sub_questions[1]

    @pytest.mark.asyncio
    async def test_decompose_limits_sub_questions(self):
        """Test decomposer limits sub-questions to max."""
        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": '["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7"]',
                    },
                },
            ],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=MagicMock(
                    json=lambda: mock_response,
                    raise_for_status=lambda: None,
                ),
            )

            decomposer = QueryDecomposer(
                llm_gateway_url="http://localhost:8004",
                model="test-model",
                max_sub_questions=3,
            )
            sub_questions = await decomposer.decompose("Test query")

        assert len(sub_questions) == 3

    @pytest.mark.asyncio
    async def test_decompose_returns_original_on_error(self):
        """Test decomposer returns original query on HTTP error."""
        with patch("httpx.AsyncClient") as mock_client:
            # Use httpx.ConnectError which inherits from httpx.HTTPError
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.ConnectError("Connection error"),
            )

            decomposer = QueryDecomposer(
                llm_gateway_url="http://localhost:8004",
                model="test-model",
            )
            sub_questions = await decomposer.decompose("Original query")

        assert sub_questions == ["Original query"]

    def test_parse_sub_questions_json_array(self):
        """Test parsing JSON array response."""
        decomposer = QueryDecomposer(
            llm_gateway_url="http://localhost:8004",
            model="test-model",
        )

        content = '["Question 1?", "Question 2?", "Question 3?"]'
        result = decomposer._parse_sub_questions(content)

        assert len(result) == 3
        assert result[0] == "Question 1?"

    def test_parse_sub_questions_markdown_code_block(self):
        """Test parsing JSON in markdown code block."""
        decomposer = QueryDecomposer(
            llm_gateway_url="http://localhost:8004",
            model="test-model",
        )

        content = '```json\n["Q1", "Q2"]\n```'
        result = decomposer._parse_sub_questions(content)

        assert len(result) == 2


# =============================================================================
# Decomposition Node Tests
# =============================================================================


class TestDecompositionNode:
    """Tests for decomposition_node."""

    @pytest.mark.asyncio
    async def test_skips_decomposition_for_simple_strategy(self):
        """Test decomposition is skipped for simple strategy."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python?",
        )
        state["strategy"] = "simple"

        result = await decomposition_node(state)

        assert result["sub_questions"] == ["What is Python?"]
        assert "decomposition" in result["timing"]

    @pytest.mark.asyncio
    async def test_decomposes_comparison_query(self):
        """Test decomposition works for comparison queries."""
        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": '["What is Python?", "What is Java?"]',
                    },
                },
            ],
        }

        state = create_initial_state(
            request_id=str(uuid4()),
            query="Compare Python and Java",
        )
        state["strategy"] = "comparison"
        state["multi_hop_type"] = "comparison"

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=MagicMock(
                    json=lambda: mock_response,
                    raise_for_status=lambda: None,
                ),
            )

            result = await decomposition_node(state)

        assert len(result["sub_questions"]) == 2
        assert result["original_query"] == "Compare Python and Java"
        assert "decomposition" in result["timing"]

    @pytest.mark.asyncio
    @patch("workflow.nodes.decomposition.select_decomposition_model")
    async def test_decomposition_uses_model_policy(self, mock_select_model):
        """Decomposition should use centralized model policy selection."""
        mock_select_model.return_value = MagicMock(
            model="policy-small-model",
            tier="small",
        )

        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": '["What is Python?", "What is Java?"]',
                    },
                },
            ],
        }

        state = create_initial_state(
            request_id=str(uuid4()),
            query="Compare Python and Java",
        )
        state["strategy"] = "comparison"
        state["multi_hop_type"] = "comparison"

        with patch("httpx.AsyncClient") as mock_client:
            post_mock = AsyncMock(
                return_value=MagicMock(
                    json=lambda: mock_response,
                    raise_for_status=lambda: None,
                ),
            )
            mock_client.return_value.__aenter__.return_value.post = post_mock

            await decomposition_node(state)

        assert post_mock.call_args.kwargs["json"]["model"] == "policy-small-model"

    @pytest.mark.asyncio
    async def test_decomposes_aggregation_query(self):
        """Test decomposition works for aggregation queries."""
        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": '["List OAuth methods", "List API key methods"]',
                    },
                },
            ],
        }

        state = create_initial_state(
            request_id=str(uuid4()),
            query="List all authentication methods",
        )
        state["strategy"] = "aggregation"
        state["multi_hop_type"] = "aggregation"

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=MagicMock(
                    json=lambda: mock_response,
                    raise_for_status=lambda: None,
                ),
            )

            result = await decomposition_node(state)

        assert len(result["sub_questions"]) == 2
        assert result["original_query"] == "List all authentication methods"

    @pytest.mark.asyncio
    async def test_preserves_state_fields(self):
        """Test decomposition preserves existing state fields."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
            tenant_id="test-tenant",
        )
        state["strategy"] = "simple"
        state["timing"] = {"routing": 10.0}

        result = await decomposition_node(state)

        assert result["tenant_id"] == "test-tenant"
        assert result["timing"]["routing"] == 10.0
        assert "decomposition" in result["timing"]


# =============================================================================
# Pattern Coverage Tests
# =============================================================================


class TestPatternCoverage:
    """Tests to verify pattern coverage is comprehensive."""

    def test_comparison_patterns_are_valid_regex(self):
        """Test all comparison patterns compile as valid regex."""
        import re

        for pattern in COMPARISON_PATTERNS:
            # Should not raise
            re.compile(pattern)

    def test_aggregation_patterns_are_valid_regex(self):
        """Test all aggregation patterns compile as valid regex."""
        import re

        for pattern in AGGREGATION_PATTERNS:
            re.compile(pattern)

    def test_sequential_patterns_are_valid_regex(self):
        """Test all sequential patterns compile as valid regex."""
        import re

        for pattern in SEQUENTIAL_PATTERNS:
            re.compile(pattern)


# =============================================================================
# Edge-Case and Regex Safety Tests (TEST-003)
# =============================================================================


class TestRoutingEdgeCases:
    """Edge-case tests for routing classification."""

    def test_empty_string_returns_simple(self):
        """Empty query should return simple strategy, not crash."""
        strategy, multi_hop_type = _classify_query("")
        assert strategy == "simple"
        assert multi_hop_type is None

    def test_whitespace_only_returns_simple(self):
        """Whitespace-only query should return simple strategy."""
        strategy, _ = _classify_query("   ")
        assert strategy == "simple"

    def test_uppercase_query_still_matches(self):
        """All-uppercase query should still be classified correctly."""
        strategy, multi_hop_type = _classify_query("COMPARE PYTHON AND JAVA")
        assert strategy == "comparison"
        assert multi_hop_type == "comparison"

    def test_mixed_case_query(self):
        """Mixed case should not affect classification."""
        strategy, _ = _classify_query("List All The API Endpoints")
        assert strategy == "aggregation"


class TestNoRetrievalPriorityFix:
    """Tests verifying that no_retrieval doesn't swallow retrieval queries (CQ-005)."""

    @pytest.mark.parametrize(
        "query,expected_strategy",
        [
            # Greeting + comparison: comparison should win
            ("Hi, what is the difference between X and Y?", "comparison"),
            # Greeting + aggregation: aggregation should win
            ("Hey, can you list all configuration options?", "aggregation"),
            # Greeting + sequential: multi_hop should win
            ("Hello, first configure the DB, then deploy", "multi_hop"),
            # Thanks + comparison: comparison should win
            ("Thanks, can you compare A and B?", "comparison"),
            # Pure greeting should still be no_retrieval
            ("Hello!", "no_retrieval"),
            ("Thanks!", "no_retrieval"),
            ("Hi, how are you?", "no_retrieval"),
        ],
    )
    def test_retrieval_patterns_take_priority(self, query: str, expected_strategy: str):
        """Retrieval-needed patterns must take priority over no_retrieval."""
        strategy, _ = _classify_query(query)
        assert strategy == expected_strategy

    def test_greeting_only_still_no_retrieval(self):
        """A pure greeting with no retrieval indicators stays no_retrieval."""
        strategy, _ = _classify_query("Hello there!")
        assert strategy == "no_retrieval"

    def test_bye_with_question(self):
        """'Bye, but what about X vs Y?' should route to comparison."""
        strategy, _ = _classify_query("Bye, but what is the difference between REST and gRPC?")
        assert strategy == "comparison"


class TestMultiplePatternConflicts:
    """Tests for queries matching multiple pattern groups simultaneously."""

    def test_comparison_and_aggregation_overlap(self):
        """Query with both comparison and aggregation keywords classifies as comparison."""
        # Comparison patterns are checked before aggregation in _detect_multi_hop_type
        strategy, multi_hop_type = _classify_query(
            "Compare and list all differences between Python and Java"
        )
        assert strategy == "comparison"
        assert multi_hop_type == "comparison"

    def test_aggregation_and_complex_overlap(self):
        """Aggregation patterns take priority over complex indicators."""
        strategy, multi_hop_type = _classify_query(
            "Summarize the relationship between all modules"
        )
        assert strategy == "aggregation"
        assert multi_hop_type == "aggregation"


class TestRegexSafety:
    """Tests for regex performance and safety."""

    def test_long_query_does_not_hang(self):
        """Verify classification of a long query completes quickly."""
        import time

        # 2000-char query with no pattern matches
        long_query = "What is the meaning of " + "word " * 400

        start = time.monotonic()
        strategy, _ = _classify_query(long_query)
        elapsed = time.monotonic() - start

        assert strategy == "simple"
        assert elapsed < 1.0, f"Classification took {elapsed:.2f}s for a long query"

    def test_multi_entity_pattern_on_long_input(self):
        """The multi-entity regex should not cause catastrophic backtracking."""
        import time

        # Worst case for greedy patterns: many commas and "and" keywords
        adversarial = ", ".join(f"item{i}" for i in range(100)) + " and final"
        query = f"Tell me about {adversarial}"

        start = time.monotonic()
        _classify_query(query)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0, f"Multi-entity pattern took {elapsed:.2f}s"

    def test_both_and_pattern_on_long_input(self):
        """The 'both ... and ...' regex should complete quickly on long input."""
        import time

        # "both X and Y" with lots of words between
        filler = " ".join(f"w{i}" for i in range(200))
        query = f"both {filler} and something"

        start = time.monotonic()
        _classify_query(query)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0, f"'Both...and' pattern took {elapsed:.2f}s"
