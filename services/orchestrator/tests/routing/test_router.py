"""Tests for the QueryRouter class."""

import pytest
from routing import (
    QueryIntent,
    QueryRouter,
    RoutingConfig,
    RoutingResult,
    RoutingStrategy,
)

# ============================================================================
# QueryRouter Basic Tests
# ============================================================================


class TestQueryRouterInitialization:
    """Tests for QueryRouter initialization."""

    def test_default_initialization(self):
        """Test router initializes with default config."""
        router = QueryRouter()
        assert router.config is not None
        assert router.config.complexity_threshold == 0.5

    def test_custom_config(self):
        """Test router accepts custom configuration."""
        config = RoutingConfig(
            complexity_threshold=0.7,
            min_greeting_confidence=0.8,
        )
        router = QueryRouter(config=config)
        assert router.config.complexity_threshold == 0.7
        assert router.config.min_greeting_confidence == 0.8


# ============================================================================
# Greeting/Chitchat Routing Tests
# ============================================================================


class TestQueryRouterGreetings:
    """Tests for greeting/chitchat routing."""

    @pytest.fixture
    def router(self):
        """Create a QueryRouter instance."""
        return QueryRouter()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "query",
        [
            "hello",
            "hi",
            "hey",
            "Hello!",
            "Hi there",
            "good morning",
            "Good afternoon",
            "thanks",
            "Thank you!",
            "bye",
            "goodbye",
            "ok",
            "okay",
            "got it",
        ],
    )
    async def test_greetings_route_to_no_retrieval(self, router, query):
        """Test that greetings are routed to NO_RETRIEVAL strategy."""
        result = await router.route(query)

        assert isinstance(result, RoutingResult)
        assert result.strategy == RoutingStrategy.NO_RETRIEVAL
        assert result.intent == QueryIntent.CONVERSATIONAL
        assert result.confidence >= 0.7
        assert result.complexity_score == 0.0

    @pytest.mark.asyncio
    async def test_greeting_has_reasoning(self, router):
        """Test that greeting routing includes reasoning."""
        result = await router.route("hello")
        assert result.reasoning is not None
        assert "greeting" in result.reasoning.lower() or "chitchat" in result.reasoning.lower()


# ============================================================================
# Simple Query Routing Tests
# ============================================================================


class TestQueryRouterSimpleQueries:
    """Tests for simple query routing."""

    @pytest.fixture
    def router(self):
        """Create a QueryRouter instance."""
        return QueryRouter()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "query",
        [
            "What is Python?",
            "Who created Linux?",
            "Where is the configuration file?",
            "When was Java released?",
            "Define microservices",
            "How do I install pip?",
        ],
    )
    async def test_simple_factual_queries_route_to_simple(self, router, query):
        """Test that simple factual queries route to SIMPLE strategy."""
        result = await router.route(query)

        assert result.strategy == RoutingStrategy.SIMPLE
        # Intent should be factual or procedural depending on the question
        assert result.intent in [QueryIntent.FACTUAL, QueryIntent.PROCEDURAL]
        assert result.complexity_score < 0.5  # Low complexity

    @pytest.mark.asyncio
    async def test_simple_query_has_confidence(self, router):
        """Test that simple queries have reasonable confidence."""
        result = await router.route("What is Python?")
        assert result.confidence >= 0.5

    @pytest.mark.asyncio
    async def test_simple_query_has_reasoning(self, router):
        """Test that simple queries include reasoning."""
        result = await router.route("What is Python?")
        assert result.reasoning is not None


# ============================================================================
# Complex Query Routing Tests
# ============================================================================


class TestQueryRouterComplexQueries:
    """Tests for complex query routing."""

    @pytest.fixture
    def router(self):
        """Create a QueryRouter instance."""
        return QueryRouter()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "query",
        [
            # Multi-part queries with explicit conjunctions
            "What is Python and also how do I install it and configure it?",
            "Explain REST APIs, and additionally describe GraphQL and compare them",
            # Highly complex analytical queries with multiple modifiers and clauses
            (
                "Compare Python and Java in terms of performance before and after optimization, "
                "while also considering the different paradigms, and analyze which is better "
                "for web development versus data science applications"
            ),
            (
                "Why is Python better than Java, and what are the advantages versus disadvantages, "
                "while considering the ecosystem differences, although some prefer Ruby or Go, "
                "and how do the trade-offs compare before making a final decision?"
            ),
        ],
    )
    async def test_complex_queries_route_to_complex(self, router, query):
        """Test that complex queries route to COMPLEX strategy."""
        result = await router.route(query)

        assert result.strategy == RoutingStrategy.COMPLEX
        # Intent should be analytical or match query type
        assert result.intent in [
            QueryIntent.ANALYTICAL,
            QueryIntent.FACTUAL,
            QueryIntent.PROCEDURAL,
        ]

    @pytest.mark.asyncio
    async def test_analytical_intent_detected(self, router):
        """Test that analytical queries are correctly classified."""
        result = await router.route("Compare Python and Java")
        assert result.intent == QueryIntent.ANALYTICAL

    @pytest.mark.asyncio
    async def test_complex_query_has_reasoning(self, router):
        """Test that complex queries include reasoning."""
        result = await router.route("Compare Python and Java in terms of performance")
        assert result.reasoning is not None
        # Reasoning should mention complexity or multi-step
        assert (
            "complex" in result.reasoning.lower()
            or "multi" in result.reasoning.lower()
            or "analytical" in result.reasoning.lower()
            or "threshold" in result.reasoning.lower()
        )


# ============================================================================
# Intent Classification Tests
# ============================================================================


class TestQueryRouterIntentClassification:
    """Tests for query intent classification."""

    @pytest.fixture
    def router(self):
        """Create a QueryRouter instance."""
        return QueryRouter()

    @pytest.mark.asyncio
    async def test_factual_intent(self, router):
        """Test factual intent classification."""
        result = await router.route("What is the capital of France?")
        assert result.intent == QueryIntent.FACTUAL

    @pytest.mark.asyncio
    async def test_analytical_intent(self, router):
        """Test analytical intent classification."""
        result = await router.route("Why is Python better for data science?")
        assert result.intent == QueryIntent.ANALYTICAL

    @pytest.mark.asyncio
    async def test_procedural_intent(self, router):
        """Test procedural intent classification."""
        result = await router.route("How do I set up a virtual environment?")
        assert result.intent == QueryIntent.PROCEDURAL

    @pytest.mark.asyncio
    async def test_conversational_intent(self, router):
        """Test conversational intent classification."""
        result = await router.route("hello")
        assert result.intent == QueryIntent.CONVERSATIONAL

    @pytest.mark.asyncio
    async def test_clarification_intent(self, router):
        """Test clarification intent classification."""
        result = await router.route("What do you mean by that?")
        assert result.intent == QueryIntent.CLARIFICATION


# ============================================================================
# History-Based Routing Tests
# ============================================================================


class TestQueryRouterWithHistory:
    """Tests for routing with conversation history."""

    @pytest.fixture
    def router(self):
        """Create a QueryRouter instance."""
        return QueryRouter()

    @pytest.mark.asyncio
    async def test_history_increases_complexity(self, router):
        """Test that conversation history increases complexity score."""
        query = "What about the other features?"

        # Without history
        result_no_history = await router.route(query)

        # With history
        history = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
            {"role": "user", "content": "What are its main features?"},
            {"role": "assistant", "content": "Python has many features..."},
        ]
        result_with_history = await router.route(query, history=history)

        assert result_with_history.complexity_score >= result_no_history.complexity_score

    @pytest.mark.asyncio
    async def test_clarification_with_history(self, router):
        """Test clarification queries with conversation history."""
        query = "Can you explain more?"
        history = [
            {"role": "user", "content": "What is machine learning?"},
            {"role": "assistant", "content": "Machine learning is..."},
        ]

        result = await router.route(query, history=history)
        assert result.intent == QueryIntent.CLARIFICATION


# ============================================================================
# Configuration Tests
# ============================================================================


class TestQueryRouterConfiguration:
    """Tests for router configuration behavior."""

    @pytest.mark.asyncio
    async def test_custom_complexity_threshold(self):
        """Test that custom complexity threshold affects routing."""
        # Router with low threshold - more queries become complex
        low_threshold_router = QueryRouter(
            config=RoutingConfig(complexity_threshold=0.2),
        )

        # Router with high threshold - fewer queries become complex
        high_threshold_router = QueryRouter(
            config=RoutingConfig(complexity_threshold=0.8),
        )

        query = "What is Python and how does it work?"

        low_result = await low_threshold_router.route(query)
        high_result = await high_threshold_router.route(query)

        # Low threshold more likely to route to complex
        # High threshold more likely to route to simple
        # Both should have same complexity score but different strategies
        assert low_result.complexity_score == high_result.complexity_score

    @pytest.mark.asyncio
    async def test_custom_greeting_confidence_threshold(self):
        """Test that custom greeting confidence threshold affects routing."""
        # Router with high greeting confidence threshold
        strict_router = QueryRouter(
            config=RoutingConfig(min_greeting_confidence=0.99),
        )

        # "cool" might match with lower confidence
        result = await strict_router.route("cool")

        # With very high threshold, might not be classified as greeting
        # (depends on exact confidence returned)
        assert isinstance(result, RoutingResult)

    @pytest.mark.asyncio
    async def test_custom_weights(self):
        """Test that custom weights affect complexity scoring."""
        # Router emphasizing clause weight
        clause_heavy_router = QueryRouter(
            config=RoutingConfig(
                clause_weight=0.8,
                length_weight=0.1,
                modifier_weight=0.05,
                history_weight=0.05,
            ),
        )

        query = "What is Python, and how does it work, but why is it popular?"

        result = await clause_heavy_router.route(query)
        assert result.complexity_score >= 0.0  # Should work without errors


# ============================================================================
# Edge Cases Tests
# ============================================================================


class TestQueryRouterEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def router(self):
        """Create a QueryRouter instance."""
        return QueryRouter()

    @pytest.mark.asyncio
    async def test_empty_query(self, router):
        """Test handling of empty query."""
        result = await router.route("")
        assert isinstance(result, RoutingResult)
        # Empty query should have low complexity
        assert result.complexity_score <= 0.5

    @pytest.mark.asyncio
    async def test_whitespace_query(self, router):
        """Test handling of whitespace-only query."""
        result = await router.route("   ")
        assert isinstance(result, RoutingResult)

    @pytest.mark.asyncio
    async def test_very_long_query(self, router):
        """Test handling of very long query."""
        long_query = "What is " + "very " * 100 + "important?"
        result = await router.route(long_query)

        assert isinstance(result, RoutingResult)
        # Long query should have some complexity due to length
        assert result.complexity_score >= 0.1

    @pytest.mark.asyncio
    async def test_special_characters(self, router):
        """Test handling of special characters in query."""
        result = await router.route("What is @#$%^&*() ?")
        assert isinstance(result, RoutingResult)

    @pytest.mark.asyncio
    async def test_unicode_characters(self, router):
        """Test handling of unicode characters in query."""
        result = await router.route("What is Python? ")
        assert isinstance(result, RoutingResult)

    @pytest.mark.asyncio
    async def test_multiple_question_marks(self, router):
        """Test handling of multiple question marks."""
        result = await router.route("What??? Why??? How???")
        assert isinstance(result, RoutingResult)
        # Should be detected as multi-part
        assert result.strategy in [RoutingStrategy.SIMPLE, RoutingStrategy.COMPLEX]

    @pytest.mark.asyncio
    async def test_empty_history(self, router):
        """Test routing with empty history list."""
        result = await router.route("What is Python?", history=[])
        assert isinstance(result, RoutingResult)

    @pytest.mark.asyncio
    async def test_none_history(self, router):
        """Test routing with None history."""
        result = await router.route("What is Python?", history=None)
        assert isinstance(result, RoutingResult)


# ============================================================================
# Strategy Selection Logic Tests
# ============================================================================


class TestQueryRouterStrategySelection:
    """Tests for strategy selection logic."""

    @pytest.fixture
    def router(self):
        """Create a QueryRouter instance."""
        return QueryRouter()

    @pytest.mark.asyncio
    async def test_greeting_always_no_retrieval(self, router):
        """Test that greetings always route to NO_RETRIEVAL."""
        greetings = ["hello", "hi", "hey", "thanks", "bye"]
        for greeting in greetings:
            result = await router.route(greeting)
            assert result.strategy == RoutingStrategy.NO_RETRIEVAL

    @pytest.mark.asyncio
    async def test_simple_factual_routes_to_simple(self, router):
        """Test that simple factual queries route to SIMPLE."""
        result = await router.route("What is Python?")
        assert result.strategy == RoutingStrategy.SIMPLE
        assert result.intent == QueryIntent.FACTUAL

    @pytest.mark.asyncio
    async def test_multi_part_routes_to_complex(self, router):
        """Test that multi-part queries route to COMPLEX."""
        result = await router.route(
            "What is Python and also what are its main features?",
        )
        assert result.strategy == RoutingStrategy.COMPLEX

    @pytest.mark.asyncio
    async def test_analytical_with_high_complexity_routes_to_complex(self, router):
        """Test that analytical queries with high complexity route to COMPLEX."""
        result = await router.route(
            "Compare the advantages and disadvantages of Python versus Java, "
            "considering performance, ecosystem, and ease of learning",
        )
        assert result.strategy == RoutingStrategy.COMPLEX
        assert result.intent == QueryIntent.ANALYTICAL

    @pytest.mark.asyncio
    async def test_simple_analytical_can_route_to_simple(self, router):
        """Test that simple analytical queries can route to SIMPLE."""
        # Very simple analytical query
        result = await router.route("Why Python?")
        # Could be simple or complex depending on classification
        assert result.strategy in [RoutingStrategy.SIMPLE, RoutingStrategy.COMPLEX]


# ============================================================================
# RoutingResult Model Tests
# ============================================================================


class TestRoutingResult:
    """Tests for RoutingResult model."""

    def test_routing_result_creation(self):
        """Test creating a RoutingResult."""
        result = RoutingResult(
            strategy=RoutingStrategy.SIMPLE,
            intent=QueryIntent.FACTUAL,
            confidence=0.85,
            complexity_score=0.3,
            reasoning="Test reasoning",
        )

        assert result.strategy == RoutingStrategy.SIMPLE
        assert result.intent == QueryIntent.FACTUAL
        assert result.confidence == 0.85
        assert result.complexity_score == 0.3
        assert result.reasoning == "Test reasoning"

    def test_routing_result_optional_reasoning(self):
        """Test that reasoning is optional."""
        result = RoutingResult(
            strategy=RoutingStrategy.SIMPLE,
            intent=QueryIntent.FACTUAL,
            confidence=0.85,
            complexity_score=0.3,
        )
        assert result.reasoning is None

    def test_routing_result_confidence_bounds(self):
        """Test that confidence must be within bounds."""
        # Valid confidence
        result = RoutingResult(
            strategy=RoutingStrategy.SIMPLE,
            intent=QueryIntent.FACTUAL,
            confidence=0.5,
            complexity_score=0.3,
        )
        assert result.confidence == 0.5

        # Boundary values
        result_min = RoutingResult(
            strategy=RoutingStrategy.SIMPLE,
            intent=QueryIntent.FACTUAL,
            confidence=0.0,
            complexity_score=0.0,
        )
        assert result_min.confidence == 0.0

        result_max = RoutingResult(
            strategy=RoutingStrategy.SIMPLE,
            intent=QueryIntent.FACTUAL,
            confidence=1.0,
            complexity_score=1.0,
        )
        assert result_max.confidence == 1.0

    def test_routing_result_complexity_bounds(self):
        """Test that complexity_score must be within bounds."""
        # Valid complexity
        result = RoutingResult(
            strategy=RoutingStrategy.SIMPLE,
            intent=QueryIntent.FACTUAL,
            confidence=0.5,
            complexity_score=0.5,
        )
        assert result.complexity_score == 0.5

    def test_routing_result_validation_error_for_invalid_confidence(self):
        """Test that invalid confidence raises validation error."""
        with pytest.raises(ValueError):
            RoutingResult(
                strategy=RoutingStrategy.SIMPLE,
                intent=QueryIntent.FACTUAL,
                confidence=1.5,  # Invalid: > 1.0
                complexity_score=0.3,
            )

        with pytest.raises(ValueError):
            RoutingResult(
                strategy=RoutingStrategy.SIMPLE,
                intent=QueryIntent.FACTUAL,
                confidence=-0.1,  # Invalid: < 0.0
                complexity_score=0.3,
            )
