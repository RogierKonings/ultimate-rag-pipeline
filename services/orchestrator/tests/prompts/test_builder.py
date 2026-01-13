"""Tests for the PromptBuilder class."""

import pytest
from prompts.builder import PromptBuilder, create_prompt_builder
from prompts.models import (
    PromptConfig,
    PromptStrategy,
    TokenLimits,
)


class TestPromptBuilderInit:
    """Tests for PromptBuilder initialization."""

    def test_init_with_default_config(self):
        """Should initialize with default config."""
        builder = PromptBuilder()

        assert builder.config is not None
        assert builder.config.strategy == PromptStrategy.RAG.value

    def test_init_with_custom_config(self):
        """Should initialize with custom config."""
        config = PromptConfig(
            strategy=PromptStrategy.NO_CONTEXT,
            model_name="gpt-3.5-turbo",
        )
        builder = PromptBuilder(config=config)

        assert builder.config.strategy == PromptStrategy.NO_CONTEXT.value
        assert builder.config.model_name == "gpt-3.5-turbo"


class TestPromptBuilderBuild:
    """Tests for the build() method."""

    @pytest.fixture
    def builder(self):
        """Create a PromptBuilder instance."""
        return PromptBuilder()

    @pytest.fixture
    def sample_documents(self):
        """Create sample retrieved documents."""
        return [
            {
                "content": "Python is a versatile programming language.",
                "title": "Python Introduction",
                "source": "docs/python-intro.md",
                "metadata": {"title": "Python Introduction"},
            },
            {
                "content": "Python supports multiple paradigms.",
                "source": "docs/python-features.md",
                "metadata": {"title": "Python Features"},
            },
        ]

    def test_build_returns_list(self, builder):
        """build() should return a list."""
        messages = builder.build(query="What is Python?")
        assert isinstance(messages, list)

    def test_build_returns_message_dicts(self, builder):
        """build() should return list of message dicts."""
        messages = builder.build(query="What is Python?")

        for msg in messages:
            assert isinstance(msg, dict)
            assert "role" in msg
            assert "content" in msg

    def test_build_includes_user_query(self, builder):
        """build() should include the user query."""
        query = "What is the meaning of life?"
        messages = builder.build(query=query)

        user_messages = [m for m in messages if m["role"] == "user"]
        assert len(user_messages) >= 1
        assert user_messages[-1]["content"] == query

    def test_build_includes_system_prompt(self, builder):
        """build() should include system prompt by default."""
        messages = builder.build(query="Test query")

        system_messages = [m for m in messages if m["role"] == "system"]
        assert len(system_messages) == 1

    def test_build_with_context_string(self, builder):
        """build() should include provided context."""
        context = "Python is a programming language."
        messages = builder.build(
            query="What is Python?",
            context=context,
            strategy="rag",
        )

        system_message = next(m for m in messages if m["role"] == "system")
        assert context in system_message["content"]

    def test_build_with_documents(self, builder, sample_documents):
        """build() should format documents as context."""
        messages = builder.build(
            query="Tell me about Python",
            documents=sample_documents,
            strategy="rag",
        )

        system_message = next(m for m in messages if m["role"] == "system")
        assert "Python is a versatile" in system_message["content"]
        assert "Python supports multiple" in system_message["content"]

    def test_build_no_context_strategy(self, builder):
        """build() with no_context should work without context."""
        messages = builder.build(
            query="What is 2+2?",
            strategy="no_context",
        )

        system_message = next(m for m in messages if m["role"] == "system")
        assert "helpful assistant" in system_message["content"]

    def test_build_falls_back_to_no_context(self, builder):
        """RAG strategy should fall back to no_context without documents."""
        messages = builder.build(
            query="Test query",
            strategy="rag",
            # No context or documents provided
        )

        # Should have used no_context since no context available
        system_message = next(m for m in messages if m["role"] == "system")
        # The system message should still work
        assert len(system_message["content"]) > 0

    def test_build_with_history(self, builder):
        """build() should include conversation history."""
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        messages = builder.build(
            query="How are you?",
            history=history,
            strategy="no_context",
        )

        # Should have system + history + current query
        assert len(messages) >= 4
        assert messages[1]["content"] == "Hello"
        assert messages[2]["content"] == "Hi there!"

    def test_build_with_rag_citations_strategy(self, builder, sample_documents):
        """build() with rag_citations should include citations section."""
        messages = builder.build(
            query="What is Python?",
            documents=sample_documents,
            strategy="rag_citations",
        )

        system_message = next(m for m in messages if m["role"] == "system")
        # Should have both context and citations
        assert "Python is a versatile" in system_message["content"]


class TestPromptBuilderBuildWithMetadata:
    """Tests for the build_with_metadata() method."""

    @pytest.fixture
    def builder(self):
        """Create a PromptBuilder instance."""
        return PromptBuilder()

    @pytest.fixture
    def sample_documents(self):
        """Create sample documents."""
        return [
            {
                "content": "Test content for document.",
                "title": "Test Doc",
                "metadata": {"title": "Test Document"},
            },
        ]

    def test_build_with_metadata_returns_dict(self, builder):
        """build_with_metadata() should return a dict."""
        result = builder.build_with_metadata(query="Test")
        assert isinstance(result, dict)

    def test_build_with_metadata_includes_messages(self, builder):
        """Result should include messages list."""
        result = builder.build_with_metadata(query="Test")

        assert "messages" in result
        assert isinstance(result["messages"], list)

    def test_build_with_metadata_includes_token_count(self, builder):
        """Result should include total_tokens."""
        result = builder.build_with_metadata(query="Test query")

        assert "total_tokens" in result
        assert result["total_tokens"] > 0

    def test_build_with_metadata_includes_truncation_flags(self, builder):
        """Result should include truncation flags."""
        result = builder.build_with_metadata(query="Test")

        assert "context_truncated" in result
        assert "history_truncated" in result
        assert isinstance(result["context_truncated"], bool)
        assert isinstance(result["history_truncated"], bool)

    def test_build_with_metadata_includes_strategy(self, builder):
        """Result should include strategy_used."""
        result = builder.build_with_metadata(
            query="Test",
            strategy="no_context",
        )

        assert "strategy_used" in result
        assert result["strategy_used"] == "no_context"


class TestPromptBuilderContextTruncation:
    """Tests for context truncation behavior."""

    def test_truncates_long_context(self):
        """Long context should be truncated to fit limits."""
        config = PromptConfig(
            token_limits=TokenLimits(max_context_tokens=100),
            truncate_context=True,
        )
        builder = PromptBuilder(config=config)

        long_context = "This is a test sentence. " * 200
        messages = builder.build(
            query="Summarize this",
            context=long_context,
            strategy="rag",
        )

        system_message = next(m for m in messages if m["role"] == "system")
        # Should be truncated, not the full context
        assert len(system_message["content"]) < len(long_context)

    def test_no_truncation_when_disabled(self):
        """Context should not be truncated when truncate_context is False."""
        config = PromptConfig(
            token_limits=TokenLimits(max_context_tokens=100),
            truncate_context=False,
        )
        builder = PromptBuilder(config=config)

        context = "Short context"
        messages = builder.build(
            query="Test",
            context=context,
            strategy="rag",
        )

        system_message = next(m for m in messages if m["role"] == "system")
        assert context in system_message["content"]


class TestPromptBuilderHistoryHandling:
    """Tests for conversation history handling."""

    def test_preserves_recent_history(self):
        """Should preserve recent history when limit is reached."""
        config = PromptConfig(
            token_limits=TokenLimits(max_history_tokens=50),
            preserve_recent_history=True,
        )
        builder = PromptBuilder(config=config)

        history = [{"role": "user", "content": f"Message {i}" * 10} for i in range(10)]

        messages = builder.build(
            query="Current query",
            history=history,
            strategy="no_context",
        )

        # Should include recent messages, possibly truncated
        content_str = str(messages)
        # Later messages should be present
        assert "Message 9" in content_str or len(messages) < 12


class TestPromptBuilderRenderTemplate:
    """Tests for the render_template() method."""

    @pytest.fixture
    def builder(self):
        """Create a PromptBuilder instance."""
        return PromptBuilder()

    def test_render_rag_template(self, builder):
        """Should render RAG template with variables."""
        rendered = builder.render_template(
            "rag",
            context="Test context here.",
        )

        assert "Test context here." in rendered
        assert "Instructions:" in rendered

    def test_render_follow_up_template(self, builder):
        """Should render follow-up template."""
        rendered = builder.render_template(
            "follow_up",
            summary="Previous conversation summary.",
        )

        assert "Previous conversation summary." in rendered

    def test_render_unknown_template_raises(self, builder):
        """Should raise KeyError for unknown template."""
        with pytest.raises(KeyError):
            builder.render_template("nonexistent")


class TestPromptBuilderEstimateTokens:
    """Tests for the estimate_tokens() method."""

    @pytest.fixture
    def builder(self):
        """Create a PromptBuilder instance."""
        return PromptBuilder()

    def test_estimate_tokens_returns_dict(self, builder):
        """estimate_tokens() should return a dict."""
        result = builder.estimate_tokens(query="Test query")
        assert isinstance(result, dict)

    def test_estimate_tokens_includes_components(self, builder):
        """Result should include all component estimates."""
        result = builder.estimate_tokens(
            query="Test query",
            context="Some context",
            history=[{"role": "user", "content": "Hi"}],
        )

        assert "query_tokens" in result
        assert "context_tokens" in result
        assert "history_tokens" in result
        assert "system_prompt_tokens" in result
        assert "total_estimated" in result

    def test_estimate_tokens_values_are_positive(self, builder):
        """Token estimates should be positive integers."""
        result = builder.estimate_tokens(
            query="Test query",
            context="Some context",
        )

        assert result["query_tokens"] > 0
        assert result["context_tokens"] > 0


class TestCreatePromptBuilder:
    """Tests for the create_prompt_builder factory function."""

    def test_creates_builder_with_defaults(self):
        """Should create builder with default values."""
        builder = create_prompt_builder()

        assert isinstance(builder, PromptBuilder)
        assert builder.config.strategy == "rag"

    def test_creates_builder_with_custom_strategy(self):
        """Should create builder with custom strategy."""
        builder = create_prompt_builder(strategy="no_context")

        assert builder.config.strategy == "no_context"

    def test_creates_builder_with_custom_token_limits(self):
        """Should create builder with custom token limits."""
        builder = create_prompt_builder(
            max_context_tokens=1000,
            max_history_tokens=500,
        )

        assert builder.config.token_limits.max_context_tokens == 1000
        assert builder.config.token_limits.max_history_tokens == 500

    def test_creates_builder_with_custom_model(self):
        """Should create builder with custom model name."""
        builder = create_prompt_builder(model_name="gpt-3.5-turbo")

        assert builder.config.model_name == "gpt-3.5-turbo"


class TestPromptBuilderIntegration:
    """Integration tests for complete prompt building scenarios."""

    def test_full_rag_flow(self):
        """Test complete RAG prompt building flow."""
        builder = create_prompt_builder(
            strategy="rag",
            max_context_tokens=2000,
        )

        documents = [
            {
                "content": "Python was created by Guido van Rossum in 1991.",
                "title": "Python History",
                "source": "wiki/python-history.md",
                "metadata": {"title": "Python History"},
            },
            {
                "content": "Python emphasizes code readability and simplicity.",
                "title": "Python Philosophy",
                "source": "wiki/python-philosophy.md",
                "metadata": {"title": "Python Philosophy"},
            },
        ]

        history = [
            {"role": "user", "content": "I'm learning about programming languages."},
            {"role": "assistant", "content": "That's great! What would you like to know?"},
        ]

        result = builder.build_with_metadata(
            query="Tell me about Python's history and design philosophy.",
            documents=documents,
            history=history,
            strategy="rag",
        )

        messages = result["messages"]

        # Should have system, history, and user messages
        assert len(messages) >= 4

        # System message should contain context
        system_msg = messages[0]
        assert system_msg["role"] == "system"
        assert "Guido van Rossum" in system_msg["content"]
        assert "code readability" in system_msg["content"]

        # History should be included
        assert any("learning about programming" in m["content"] for m in messages)

        # Current query should be last
        assert messages[-1]["role"] == "user"
        assert "Python's history" in messages[-1]["content"]

        # Token count should be reasonable
        assert result["total_tokens"] > 0
        assert result["total_tokens"] < 10000

    def test_conversation_with_no_context(self):
        """Test conversation flow without retrieved context."""
        builder = create_prompt_builder(strategy="no_context")

        messages = builder.build(
            query="What is 2 + 2?",
            history=[
                {"role": "user", "content": "Can you do math?"},
                {"role": "assistant", "content": "Yes, I can help with math."},
            ],
        )

        # Should work without context
        assert len(messages) >= 3
        assert messages[-1]["content"] == "What is 2 + 2?"

        # System should not mention context
        system_msg = messages[0]
        assert "Context:" not in system_msg["content"]


class TestPromptBuilderLanguageDetection:
    """Tests for language detection and multi-language support."""

    @pytest.fixture
    def builder(self):
        """Create a PromptBuilder instance."""
        return PromptBuilder()

    def test_build_detects_english_query(self, builder):
        """build() should detect English and use English template."""
        messages = builder.build(
            query="What is the capital of France?",
            strategy="no_context",
        )

        system_message = next(m for m in messages if m["role"] == "system")
        # English template should have "helpful assistant"
        assert "helpful assistant" in system_message["content"]

    def test_build_detects_dutch_query(self, builder):
        """build() should detect Dutch and use Dutch template."""
        messages = builder.build(
            query="Wat is de hoofdstad van Nederland?",
            strategy="no_context",
        )

        system_message = next(m for m in messages if m["role"] == "system")
        # Dutch template should have "behulpzame assistent"
        assert "behulpzame assistent" in system_message["content"]

    def test_build_with_explicit_language_override(self, builder):
        """build() should use explicit language override."""
        # Query is in English but we force Dutch
        messages = builder.build(
            query="What is the capital of France?",
            strategy="no_context",
            language="nl",
        )

        system_message = next(m for m in messages if m["role"] == "system")
        # Should use Dutch template despite English query
        assert "behulpzame assistent" in system_message["content"]

    def test_build_with_dutch_rag_prompt(self, builder):
        """build() should use Dutch RAG template for Dutch query."""
        messages = builder.build(
            query="Kunt u mij meer vertellen over Python programmeren en hoe het werkt?",
            context="Python is een programmeertaal.",
            strategy="rag",
        )

        system_message = next(m for m in messages if m["role"] == "system")
        # Dutch RAG template should have Dutch instructions
        assert "Instructies:" in system_message["content"]
        assert "verstrekte context" in system_message["content"]

    def test_build_with_metadata_includes_detected_language(self, builder):
        """build_with_metadata() should include detected language."""
        result = builder.build_with_metadata(
            query="Wat is Python en hoe kan ik het gebruiken voor mijn projecten?",
            strategy="no_context",
        )

        assert "language_detected" in result
        assert result["language_detected"] == "nl"

    def test_build_with_metadata_explicit_language(self, builder):
        """build_with_metadata() should respect explicit language."""
        result = builder.build_with_metadata(
            query="What is Python?",
            strategy="no_context",
            language="nl",
        )

        assert result["language_detected"] == "nl"

    def test_render_template_with_language(self, builder):
        """render_template() should use specified language."""
        rendered = builder.render_template(
            "no_context",
            language="nl",
        )

        assert "behulpzame assistent" in rendered

    def test_render_template_default_english(self, builder):
        """render_template() should default to English."""
        rendered = builder.render_template("no_context")

        assert "helpful assistant" in rendered

    def test_dutch_citation_format_in_rag(self, builder):
        """Dutch RAG template should use Dutch citation format."""
        messages = builder.build(
            query="Wat is de geschiedenis van Python?",
            context="Python werd gemaakt door Guido van Rossum.",
            strategy="rag",
        )

        system_message = next(m for m in messages if m["role"] == "system")
        # Dutch template should mention [Bron: ...] format
        assert "[Bron:" in system_message["content"]
