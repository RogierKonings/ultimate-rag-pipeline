"""Query Router for determining routing strategy."""


from .classifiers import ComplexityScorer, KeywordClassifier
from .models import QueryIntent, RoutingConfig, RoutingResult, RoutingStrategy


class QueryRouter:
    """
    Routes queries to appropriate handling strategies based on intent and complexity.

    The router analyzes incoming queries to determine:
    1. Intent classification (factual, analytical, procedural, conversational, clarification)
    2. Complexity scoring (0-1 scale)
    3. Routing strategy (simple, complex, no_retrieval)

    Strategy Selection Logic:
    - Greetings/chitchat -> no_retrieval (direct LLM response)
    - Simple factual queries (low complexity) -> simple (single retrieval pass)
    - Multi-part or analytical queries (high complexity) -> complex (multi-step retrieval)
    """

    def __init__(self, config: RoutingConfig | None = None):
        """
        Initialize the QueryRouter.

        Args:
            config: Optional routing configuration. Uses defaults if not provided.
        """
        self.config = config or RoutingConfig()
        self._keyword_classifier = KeywordClassifier()
        self._complexity_scorer = ComplexityScorer(
            max_query_length=self.config.max_query_length,
        )

    async def route(
        self,
        query: str,
        history: list[dict] | None = None,
    ) -> RoutingResult:
        """
        Route a query to the appropriate strategy.

        Args:
            query: The user's query string
            history: Optional conversation history

        Returns:
            RoutingResult with strategy, intent, confidence, and complexity score
        """
        # Step 1: Check for greetings/chitchat (fast path)
        is_greeting, greeting_confidence = self._keyword_classifier.is_greeting(query)

        if is_greeting and greeting_confidence >= self.config.min_greeting_confidence:
            return RoutingResult(
                strategy=RoutingStrategy.NO_RETRIEVAL,
                intent=QueryIntent.CONVERSATIONAL,
                confidence=greeting_confidence,
                complexity_score=0.0,
                reasoning="Query identified as greeting/chitchat - no retrieval needed",
            )

        # Step 2: Classify intent
        intent, intent_confidence = self._classify_intent(query)

        # Step 3: Score complexity
        complexity_score = self._score_complexity(query, history)

        # Step 4: Determine strategy
        strategy, strategy_reasoning = self._determine_strategy(
            intent, intent_confidence, complexity_score, query,
        )

        return RoutingResult(
            strategy=strategy,
            intent=intent,
            confidence=intent_confidence,
            complexity_score=complexity_score,
            reasoning=strategy_reasoning,
        )

    def _classify_intent(self, query: str) -> tuple[QueryIntent, float]:
        """
        Determine query intent and confidence.

        Args:
            query: The query string

        Returns:
            Tuple of (QueryIntent, confidence)
        """
        question_type, confidence = self._keyword_classifier.classify_question_type(
            query,
        )

        intent_mapping = {
            "factual": QueryIntent.FACTUAL,
            "analytical": QueryIntent.ANALYTICAL,
            "procedural": QueryIntent.PROCEDURAL,
            "clarification": QueryIntent.CLARIFICATION,
            "unknown": QueryIntent.FACTUAL,  # Default to factual for unknown
        }

        intent = intent_mapping.get(question_type, QueryIntent.FACTUAL)
        return (intent, confidence)

    def _score_complexity(
        self, query: str, history: list[dict] | None = None,
    ) -> float:
        """
        Score query complexity on a 0-1 scale.

        Args:
            query: The query string
            history: Optional conversation history

        Returns:
            Complexity score between 0.0 and 1.0
        """
        weights = {
            "clause": self.config.clause_weight,
            "length": self.config.length_weight,
            "modifier": self.config.modifier_weight,
            "history": self.config.history_weight,
        }

        return self._complexity_scorer.score(query, history, weights)

    def _determine_strategy(
        self,
        intent: QueryIntent,
        confidence: float,
        complexity_score: float,
        query: str,
    ) -> tuple[RoutingStrategy, str]:
        """
        Determine the routing strategy based on intent and complexity.

        Args:
            intent: The classified intent
            confidence: Intent classification confidence
            complexity_score: Query complexity score
            query: The original query string

        Returns:
            Tuple of (RoutingStrategy, reasoning)
        """
        # Check for multi-part queries
        is_multi_part, part_count = self._keyword_classifier.is_multi_part(query)

        # Conversational/chitchat queries don't need retrieval
        if intent == QueryIntent.CONVERSATIONAL:
            return (
                RoutingStrategy.NO_RETRIEVAL,
                "Conversational query - direct LLM response",
            )

        # Clarification queries often need context from history
        if intent == QueryIntent.CLARIFICATION:
            # Clarification with low complexity is simple
            if complexity_score < self.config.complexity_threshold:
                return (
                    RoutingStrategy.SIMPLE,
                    "Clarification query with manageable complexity",
                )
            return (
                RoutingStrategy.COMPLEX,
                "Clarification query requiring multi-step context gathering",
            )

        # Analytical queries typically need complex handling
        if intent == QueryIntent.ANALYTICAL:
            if is_multi_part or complexity_score >= self.config.complexity_threshold:
                return (
                    RoutingStrategy.COMPLEX,
                    f"Analytical query with complexity {complexity_score:.2f} "
                    f"(threshold: {self.config.complexity_threshold})",
                )
            return (
                RoutingStrategy.SIMPLE,
                f"Simple analytical query with complexity {complexity_score:.2f}",
            )

        # Multi-part queries need complex handling
        if is_multi_part and part_count > 1:
            return (
                RoutingStrategy.COMPLEX,
                f"Multi-part query with {part_count} estimated parts",
            )

        # High complexity queries need complex handling
        if complexity_score >= self.config.complexity_threshold:
            return (
                RoutingStrategy.COMPLEX,
                f"Query complexity {complexity_score:.2f} exceeds threshold "
                f"({self.config.complexity_threshold})",
            )

        # Default to simple for straightforward queries
        return (
            RoutingStrategy.SIMPLE,
            f"Standard {intent.value} query with complexity {complexity_score:.2f}",
        )
