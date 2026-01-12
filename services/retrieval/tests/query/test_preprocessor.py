"""Tests for query preprocessor."""

from unittest.mock import patch

import pytest
from query.models import QueryPreprocessorConfig, QueryType
from query.preprocessor import QueryPreprocessor


@pytest.fixture
def config():
    """Create test configuration."""
    return QueryPreprocessorConfig(
        enable_expansion=True,
        enable_hyde=False,
        cache_enabled=False,
    )


@pytest.fixture
def preprocessor(config):
    """Create preprocessor with test config."""
    return QueryPreprocessor(config)


class TestQueryPreprocessorNormalization:
    """Tests for query normalization."""

    def test_normalize_lowercase(self, preprocessor):
        """Test lowercase normalization."""
        result = preprocessor._normalize("Hello WORLD")
        assert result == "hello world"

    def test_normalize_whitespace(self, preprocessor):
        """Test whitespace normalization."""
        result = preprocessor._normalize("  hello   world  ")
        assert result == "hello world"

    def test_normalize_both(self, preprocessor):
        """Test combined normalization."""
        result = preprocessor._normalize("  Hello   WORLD  ")
        assert result == "hello world"

    def test_normalize_no_lowercase(self):
        """Test with lowercase disabled."""
        config = QueryPreprocessorConfig(lowercase=False)
        preprocessor = QueryPreprocessor(config)

        result = preprocessor._normalize("Hello WORLD")
        assert result == "Hello WORLD"

    def test_normalize_remove_special_chars(self):
        """Test special character removal."""
        config = QueryPreprocessorConfig(remove_special_chars=True)
        preprocessor = QueryPreprocessor(config)

        result = preprocessor._normalize("hello @world #test!")
        assert result == "hello world test!"  # Keeps ! as it's allowed

    def test_normalize_preserves_punctuation(self, preprocessor):
        """Test that basic punctuation is preserved."""
        result = preprocessor._normalize("What is this? I don't know.")
        assert "?" in result
        assert "." in result


class TestQueryPreprocessorClassification:
    """Tests for query classification."""

    @pytest.fixture
    def preprocessor(self):
        """Create preprocessor for classification tests."""
        return QueryPreprocessor()

    def test_classify_question_what(self, preprocessor):
        """Test question detection with 'what'."""
        assert preprocessor._classify_query("what is machine learning") == QueryType.QUESTION

    def test_classify_question_how(self, preprocessor):
        """Test question detection with 'how'."""
        assert preprocessor._classify_query("how does it work") == QueryType.QUESTION

    def test_classify_question_why(self, preprocessor):
        """Test question detection with 'why'."""
        assert preprocessor._classify_query("why is the sky blue") == QueryType.QUESTION

    def test_classify_question_mark(self, preprocessor):
        """Test question detection with '?'."""
        assert preprocessor._classify_query("the sky is blue?") == QueryType.QUESTION

    def test_classify_question_is(self, preprocessor):
        """Test question detection with 'is'."""
        assert preprocessor._classify_query("is python a good language") == QueryType.QUESTION

    def test_classify_simple_short(self, preprocessor):
        """Test simple query detection for short queries."""
        assert preprocessor._classify_query("python tutorial") == QueryType.SIMPLE
        assert preprocessor._classify_query("machine learning") == QueryType.SIMPLE
        assert preprocessor._classify_query("api") == QueryType.SIMPLE

    def test_classify_semantic_explain(self, preprocessor):
        """Test semantic detection with 'explain'."""
        assert (
            preprocessor._classify_query("explain the concept of recursion") == QueryType.SEMANTIC
        )

    def test_classify_semantic_compare(self, preprocessor):
        """Test semantic detection with 'compare'."""
        assert preprocessor._classify_query("compare python and javascript") == QueryType.SEMANTIC

    def test_classify_semantic_difference(self, preprocessor):
        """Test semantic detection with 'difference'."""
        assert (
            preprocessor._classify_query("difference between lists and tuples")
            == QueryType.SEMANTIC
        )

    def test_classify_hybrid(self, preprocessor):
        """Test hybrid classification for medium-length queries."""
        # More than 3 words but not a question or semantic
        assert (
            preprocessor._classify_query("python web framework tutorial guide") == QueryType.HYBRID
        )


class TestQueryPreprocessorProcess:
    """Tests for the main process method."""

    @pytest.fixture
    def mock_embedding(self):
        """Mock embedding vector."""
        return [0.1] * 1024

    @pytest.mark.asyncio
    async def test_process_returns_processed_query(self, config, mock_embedding):
        """Test that process returns a ProcessedQuery."""
        preprocessor = QueryPreprocessor(config)

        with patch.object(preprocessor, "_generate_embedding") as mock:
            mock.return_value = (mock_embedding, 10)

            result = await preprocessor.process("Test query")

            assert result.original_query == "Test query"
            assert result.normalized_query == "test query"
            assert len(result.embedding) == 1024
            assert result.tokens == 10

    @pytest.mark.asyncio
    async def test_process_with_expansion(self, config, mock_embedding):
        """Test process with query expansion enabled."""
        preprocessor = QueryPreprocessor(config)

        with patch.object(preprocessor, "_generate_embedding") as mock_embed:
            mock_embed.return_value = (mock_embedding, 10)

            # Mock the expander
            with patch.object(preprocessor, "_expand_query") as mock_expand:
                mock_expand.return_value = ["fix the bug", "resolve the issue"]

                result = await preprocessor.process("fix the error")

                assert len(result.expanded_queries) == 2
                assert "fix the bug" in result.expanded_queries

    @pytest.mark.asyncio
    async def test_process_without_expansion(self, mock_embedding):
        """Test process with expansion disabled."""
        config = QueryPreprocessorConfig(enable_expansion=False)
        preprocessor = QueryPreprocessor(config)

        with patch.object(preprocessor, "_generate_embedding") as mock:
            mock.return_value = (mock_embedding, 10)

            result = await preprocessor.process("test query")

            assert result.expanded_queries == []

    @pytest.mark.asyncio
    async def test_process_with_hyde(self, mock_embedding):
        """Test process with HyDE enabled for questions."""
        config = QueryPreprocessorConfig(
            enable_hyde=True,
            enable_expansion=False,
            cache_enabled=False,
        )
        preprocessor = QueryPreprocessor(config)

        hyde_doc = "Machine learning is a branch of AI..."

        with patch.object(preprocessor, "_generate_embedding") as mock_embed:
            mock_embed.return_value = (mock_embedding, 10)

            with patch.object(preprocessor, "_generate_hyde") as mock_hyde:
                mock_hyde.return_value = hyde_doc

                result = await preprocessor.process("what is machine learning")

                assert result.hyde_document == hyde_doc
                assert result.query_type == QueryType.QUESTION
                # Embedding should be called with hyde_doc, not query
                mock_embed.assert_called_once_with(hyde_doc)

    @pytest.mark.asyncio
    async def test_process_hyde_only_for_questions(self, mock_embedding):
        """Test that HyDE is only used for questions."""
        config = QueryPreprocessorConfig(
            enable_hyde=True,
            enable_expansion=False,
            cache_enabled=False,
        )
        preprocessor = QueryPreprocessor(config)

        with patch.object(preprocessor, "_generate_embedding") as mock_embed:
            mock_embed.return_value = (mock_embedding, 10)

            # Simple query should not trigger HyDE
            with patch.object(preprocessor, "_generate_hyde") as mock_hyde:
                result = await preprocessor.process("python tutorial")

                mock_hyde.assert_not_called()
                assert result.hyde_document is None

    @pytest.mark.asyncio
    async def test_process_tracks_time(self, config, mock_embedding):
        """Test that processing time is tracked."""
        preprocessor = QueryPreprocessor(config)

        with patch.object(preprocessor, "_generate_embedding") as mock:
            mock.return_value = (mock_embedding, 10)

            result = await preprocessor.process("test query")

            assert result.processing_time_ms > 0

    @pytest.mark.asyncio
    async def test_process_classifies_query(self, config, mock_embedding):
        """Test that queries are classified."""
        preprocessor = QueryPreprocessor(config)

        with patch.object(preprocessor, "_generate_embedding") as mock:
            mock.return_value = (mock_embedding, 10)

            result = await preprocessor.process("what is python")

            assert result.query_type == QueryType.QUESTION


class TestQueryPreprocessorCaching:
    """Tests for query caching."""

    @pytest.fixture
    def mock_embedding(self):
        """Mock embedding vector."""
        return [0.1] * 1024

    @pytest.mark.asyncio
    async def test_cache_key_generation(self):
        """Test that cache keys are deterministic."""
        config = QueryPreprocessorConfig()
        preprocessor = QueryPreprocessor(config)

        key1 = preprocessor._get_cache_key("test query")
        key2 = preprocessor._get_cache_key("test query")

        assert key1 == key2

    @pytest.mark.asyncio
    async def test_cache_key_different_queries(self):
        """Test that different queries get different keys."""
        config = QueryPreprocessorConfig()
        preprocessor = QueryPreprocessor(config)

        key1 = preprocessor._get_cache_key("query one")
        key2 = preprocessor._get_cache_key("query two")

        assert key1 != key2

    @pytest.mark.asyncio
    async def test_cache_key_includes_config(self):
        """Test that config affects cache key."""
        config1 = QueryPreprocessorConfig(enable_hyde=False)
        config2 = QueryPreprocessorConfig(enable_hyde=True)

        preprocessor1 = QueryPreprocessor(config1)
        preprocessor2 = QueryPreprocessor(config2)

        key1 = preprocessor1._get_cache_key("test query")
        key2 = preprocessor2._get_cache_key("test query")

        assert key1 != key2


class TestQueryPreprocessorCleanup:
    """Tests for resource cleanup."""

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        config = QueryPreprocessorConfig()

        async with QueryPreprocessor(config) as preprocessor:
            assert preprocessor is not None

    @pytest.mark.asyncio
    async def test_close_cleans_up(self):
        """Test that close cleans up resources."""
        config = QueryPreprocessorConfig()
        preprocessor = QueryPreprocessor(config)

        # Force creation of HTTP client
        _ = preprocessor.http_client

        await preprocessor.close()

        assert preprocessor._http_client is None
