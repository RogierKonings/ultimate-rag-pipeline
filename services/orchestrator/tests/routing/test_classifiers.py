"""Tests for routing classifiers and scorers."""

import pytest
from routing.classifiers import ComplexityScorer, KeywordClassifier

# ============================================================================
# KeywordClassifier Tests
# ============================================================================


class TestKeywordClassifierGreetings:
    """Tests for greeting detection in KeywordClassifier."""

    @pytest.fixture
    def classifier(self):
        """Create a KeywordClassifier instance."""
        return KeywordClassifier()

    @pytest.mark.parametrize(
        "query,expected_is_greeting",
        [
            # Basic greetings
            ("hello", True),
            ("hi", True),
            ("hey", True),
            ("Hello!", True),
            ("Hi there", True),
            ("Howdy", True),
            ("Greetings", True),
            ("yo", True),
            ("hiya", True),
            # Time-based greetings
            ("good morning", True),
            ("Good afternoon", True),
            ("good evening", True),
            ("Good day", True),
            # Informal greetings
            ("what's up", True),
            ("whats up", True),
            ("sup", True),
            ("wassup", True),
            # Gratitude/closing
            ("thanks", True),
            ("thank you", True),
            ("Thanks!", True),
            ("bye", True),
            ("goodbye", True),
            ("see you", True),
            ("take care", True),
            # Simple acknowledgments
            ("ok", True),
            ("okay", True),
            ("got it", True),
            ("understood", True),
            ("perfect", True),
            ("great", True),
            # Short responses
            ("yes", True),
            ("no", True),
            ("yep", True),
            ("nope", True),
            ("sure", True),
            ("cool", True),
            ("nice", True),
        ],
    )
    def test_detects_greetings(self, classifier, query, expected_is_greeting):
        """Test that various greeting patterns are detected."""
        is_greeting, confidence = classifier.is_greeting(query)
        assert is_greeting == expected_is_greeting
        if is_greeting:
            assert confidence >= 0.7  # Should have reasonable confidence

    @pytest.mark.parametrize(
        "query",
        [
            "What is Python?",
            "How do I install numpy?",
            "Explain machine learning",
            "Why is the sky blue?",
            "Compare Python and Java",
            "Tell me about neural networks",
            "What are the best practices for testing?",
        ],
    )
    def test_non_greetings_not_detected(self, classifier, query):
        """Test that actual questions are not classified as greetings."""
        is_greeting, confidence = classifier.is_greeting(query)
        assert is_greeting is False
        assert confidence == 0.0

    def test_greeting_confidence_levels(self, classifier):
        """Test that different greeting types have appropriate confidence."""
        # Exact pattern match should have highest confidence
        is_greeting, confidence = classifier.is_greeting("hello")
        assert confidence >= 0.9

        # Gratitude patterns should have high but slightly lower confidence
        is_greeting, confidence = classifier.is_greeting("thanks")
        assert 0.85 <= confidence <= 0.95

        # Short word fallback should have lower confidence
        is_greeting, confidence = classifier.is_greeting("cool")
        assert 0.7 <= confidence <= 0.85


class TestKeywordClassifierQuestionTypes:
    """Tests for question type classification in KeywordClassifier."""

    @pytest.fixture
    def classifier(self):
        """Create a KeywordClassifier instance."""
        return KeywordClassifier()

    @pytest.mark.parametrize(
        "query,expected_type",
        [
            # Factual questions
            ("What is Python?", "factual"),
            ("What are microservices?", "factual"),
            ("Who is the author of this library?", "factual"),
            ("Where is the configuration file?", "factual"),
            ("When was Python released?", "factual"),
            ("Define dependency injection", "factual"),
            ("List the main features", "factual"),
            # Analytical questions
            ("Why is Python popular?", "analytical"),
            ("Compare Python and Java", "analytical"),
            ("What are the pros and cons versus the other option?", "analytical"),
            ("Which is better for web development?", "analytical"),
            ("Analyze the performance differences", "analytical"),
            ("What are the advantages versus disadvantages of using Docker?", "analytical"),
            ("Analyze the trade-offs of this approach", "analytical"),
            # Procedural questions
            ("How to install Python?", "procedural"),
            ("How do I create a virtual environment?", "procedural"),
            ("How can I configure the database?", "procedural"),
            ("Steps to deploy the application", "procedural"),
            ("Tutorial for setting up tests", "procedural"),
            ("How should I implement authentication?", "procedural"),
            ("Fix the connection error", "procedural"),
            ("Build a REST API", "procedural"),
            # Clarification questions
            ("What do you mean by that?", "clarification"),
            ("Can you explain more?", "clarification"),
            ("I don't understand", "clarification"),
            ("Could you expand on this?", "clarification"),
            ("Tell me more about it", "clarification"),
            ("What about the edge cases?", "clarification"),
        ],
    )
    def test_question_type_classification(self, classifier, query, expected_type):
        """Test that questions are classified correctly by type."""
        question_type, confidence = classifier.classify_question_type(query)
        assert question_type == expected_type
        assert confidence >= 0.5  # Should have reasonable confidence

    def test_unknown_question_type(self, classifier):
        """Test that ambiguous queries return unknown with low confidence."""
        question_type, confidence = classifier.classify_question_type(
            "interesting stuff here",
        )
        assert question_type == "unknown"
        assert confidence <= 0.4

    def test_higher_confidence_with_multiple_markers(self, classifier):
        """Test that multiple pattern matches increase confidence."""
        # Single marker
        _, single_conf = classifier.classify_question_type("What is Python?")

        # Multiple markers
        _, multi_conf = classifier.classify_question_type(
            "What is Python and define its main features?",
        )

        # Both should be factual, but multi should have higher confidence
        # (due to multiple pattern matches)
        assert multi_conf >= single_conf


class TestKeywordClassifierMultiPart:
    """Tests for multi-part query detection in KeywordClassifier."""

    @pytest.fixture
    def classifier(self):
        """Create a KeywordClassifier instance."""
        return KeywordClassifier()

    @pytest.mark.parametrize(
        "query,expected_multi_part",
        [
            # Multi-part queries
            ("What is Python and also how do I install it?", True),
            ("Explain REST APIs, and additionally describe GraphQL", True),
            ("Furthermore, what about performance?", True),
            ("Moreover, explain the architecture", True),
            ("First, tell me about X? Second, what about Y?", True),
            # Multiple question marks
            ("What is X? What is Y?", True),
            # Single-part queries
            ("What is Python?", False),
            ("How do I install numpy?", False),
            ("Explain machine learning in detail", False),
        ],
    )
    def test_multi_part_detection(self, classifier, query, expected_multi_part):
        """Test that multi-part queries are detected correctly."""
        is_multi_part, part_count = classifier.is_multi_part(query)
        assert is_multi_part == expected_multi_part
        if is_multi_part:
            assert part_count >= 2

    def test_part_count_estimation(self, classifier):
        """Test that part count is reasonably estimated."""
        # Multiple question marks
        _, part_count = classifier.is_multi_part("What is X? What is Y? What is Z?")
        assert part_count >= 3

        # Multiple conjunctions
        _, part_count = classifier.is_multi_part(
            "First, explain A. Second, describe B. Finally, analyze C.",
        )
        assert part_count >= 2


# ============================================================================
# ComplexityScorer Tests
# ============================================================================


class TestComplexityScorer:
    """Tests for the ComplexityScorer class."""

    @pytest.fixture
    def scorer(self):
        """Create a ComplexityScorer instance."""
        return ComplexityScorer(max_query_length=500)

    def test_simple_query_low_complexity(self, scorer):
        """Test that simple queries have low complexity scores."""
        score = scorer.score("What is Python?")
        assert score < 0.3

    def test_complex_query_high_complexity(self, scorer):
        """Test that complex queries have high complexity scores."""
        complex_query = (
            "Compare Python and Java in terms of performance, and also analyze "
            "the trade-offs between using one versus the other for web development, "
            "considering both the advantages and disadvantages of each approach, "
            "while taking into account the different programming paradigms they support."
        )
        score = scorer.score(complex_query)
        assert score >= 0.5

    def test_complexity_increases_with_clauses(self, scorer):
        """Test that more clauses increase complexity."""
        simple = "What is Python?"
        with_one_clause = "What is Python, and why is it popular?"
        with_many_clauses = (
            "What is Python, why is it popular, and how does it compare to Java, "
            "although some prefer Ruby, while others use Go?"
        )

        score_simple = scorer.score(simple)
        score_one_clause = scorer.score(with_one_clause)
        score_many_clauses = scorer.score(with_many_clauses)

        assert score_simple < score_one_clause < score_many_clauses

    def test_complexity_increases_with_length(self, scorer):
        """Test that longer queries have higher complexity."""
        short = "What is X?"
        medium = "What is X and how does it work in different contexts?"
        long = (
            "What is X and how does it work in different contexts? "
            "I need to understand the various aspects of X including its "
            "implementation details, best practices, and common pitfalls "
            "that developers encounter when using X in production systems."
        )

        score_short = scorer.score(short)
        score_medium = scorer.score(medium)
        score_long = scorer.score(long)

        assert score_short < score_medium < score_long

    def test_complexity_increases_with_modifiers(self, scorer):
        """Test that temporal/comparison modifiers increase complexity."""
        without_modifiers = "What is Python?"
        with_modifiers = "What was Python like before version 3, and how is it better now?"

        score_without = scorer.score(without_modifiers)
        score_with = scorer.score(with_modifiers)

        assert score_without < score_with

    def test_history_affects_complexity(self, scorer):
        """Test that conversation history affects complexity score."""
        query = "What about the other features?"
        no_history = scorer.score(query)
        short_history = scorer.score(query, history=[{"role": "user", "content": "test"}])
        long_history = scorer.score(
            query,
            history=[
                {"role": "user", "content": "test1"},
                {"role": "assistant", "content": "response1"},
                {"role": "user", "content": "test2"},
                {"role": "assistant", "content": "response2"},
                {"role": "user", "content": "test3"},
                {"role": "assistant", "content": "response3"},
            ],
        )

        assert no_history < short_history < long_history

    def test_custom_weights(self, scorer):
        """Test that custom weights affect scoring."""
        query = (
            "Compare Python and Java before making a decision, "
            "and also consider the different use cases."
        )

        # Default weights
        default_score = scorer.score(query)

        # Heavy modifier weight
        modifier_heavy_score = scorer.score(
            query,
            weights={"clause": 0.1, "length": 0.1, "modifier": 0.7, "history": 0.1},
        )

        # Heavy length weight
        length_heavy_score = scorer.score(
            query,
            weights={"clause": 0.1, "length": 0.7, "modifier": 0.1, "history": 0.1},
        )

        # Scores should differ based on weights
        # The query has modifiers, so modifier-heavy should be higher
        assert default_score != modifier_heavy_score or default_score != length_heavy_score

    def test_score_bounded_zero_to_one(self, scorer):
        """Test that scores are always bounded between 0 and 1."""
        # Very simple query
        simple_score = scorer.score("Hi")
        assert 0.0 <= simple_score <= 1.0

        # Very complex query
        complex_query = " ".join(
            [
                "Compare and analyze the performance characteristics, "
                "advantages and disadvantages, and trade-offs",
            ]
            * 10,
        )
        complex_score = scorer.score(complex_query)
        assert 0.0 <= complex_score <= 1.0

    def test_empty_query(self, scorer):
        """Test handling of empty query."""
        score = scorer.score("")
        assert score == 0.0 or score >= 0.0  # Should handle gracefully

    def test_whitespace_only_query(self, scorer):
        """Test handling of whitespace-only query."""
        score = scorer.score("   ")
        assert 0.0 <= score <= 1.0  # Should handle gracefully


class TestComplexityScorerComponents:
    """Tests for individual complexity scoring components."""

    @pytest.fixture
    def scorer(self):
        """Create a ComplexityScorer instance."""
        return ComplexityScorer(max_query_length=500)

    def test_clause_scoring_tiers(self, scorer):
        """Test that clause scoring follows expected tiers."""
        # 1 clause = 0.0
        single_clause = scorer._score_clauses("What is Python")
        assert single_clause == 0.0

        # 2 clauses = 0.3
        two_clause = scorer._score_clauses("What is Python, and why?")
        assert two_clause >= 0.2

        # Many clauses should approach 1.0
        many_clause = scorer._score_clauses(
            "A and B, but C, because D, while E, although F, if G",
        )
        assert many_clause >= 0.5

    def test_length_scoring_normalization(self, scorer):
        """Test that length scoring normalizes correctly."""
        # Short query
        short_score = scorer._score_length("Hi")
        assert short_score < 0.1

        # Query at max length
        max_length_query = "x" * 500
        max_score = scorer._score_length(max_length_query)
        assert max_score == 1.0

        # Query beyond max length
        beyond_max_query = "x" * 1000
        beyond_score = scorer._score_length(beyond_max_query)
        assert beyond_score == 1.0  # Should cap at 1.0

    def test_modifier_scoring_tiers(self, scorer):
        """Test that modifier scoring follows expected tiers."""
        # No modifiers
        no_mods = scorer._score_modifiers("What is Python")
        assert no_mods == 0.0

        # One modifier
        one_mod = scorer._score_modifiers("Compare Python to Java")
        assert one_mod >= 0.2

        # Multiple modifiers
        many_mods = scorer._score_modifiers(
            "Compare Python before and after version 3, considering what is better",
        )
        assert many_mods >= 0.5

    def test_history_scoring_tiers(self, scorer):
        """Test that history scoring follows expected tiers."""
        # No history
        assert scorer._score_history(None) == 0.0
        assert scorer._score_history([]) == 0.0

        # Short history (1-2 messages)
        short_history = [{"role": "user", "content": "Hi"}]
        assert scorer._score_history(short_history) <= 0.3

        # Medium history (3-4 messages)
        medium_history = [{"role": "user", "content": f"msg{i}"} for i in range(4)]
        assert scorer._score_history(medium_history) >= 0.3

        # Long history (7+ messages)
        long_history = [{"role": "user", "content": f"msg{i}"} for i in range(8)]
        assert scorer._score_history(long_history) >= 0.6
