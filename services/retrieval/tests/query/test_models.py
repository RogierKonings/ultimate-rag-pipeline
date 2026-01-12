"""Tests for query preprocessing models."""


from query.models import (
    ProcessedQuery,
    QueryPreprocessorConfig,
    QueryType,
)


class TestQueryType:
    """Tests for QueryType enum."""

    def test_query_type_values(self):
        """Test that query types have expected values."""
        assert QueryType.SIMPLE.value == "simple"
        assert QueryType.QUESTION.value == "question"
        assert QueryType.SEMANTIC.value == "semantic"
        assert QueryType.HYBRID.value == "hybrid"

    def test_query_type_is_string_enum(self):
        """Test query type can be compared to string."""
        assert QueryType.SIMPLE == "simple"
        assert QueryType.QUESTION == "question"


class TestProcessedQuery:
    """Tests for ProcessedQuery model."""

    def test_processed_query_creation(self):
        """Test basic processed query creation."""
        embedding = [0.1] * 1024

        query = ProcessedQuery(
            original_query="What is machine learning?",
            normalized_query="what is machine learning",
            embedding=embedding,
        )

        assert query.original_query == "What is machine learning?"
        assert query.normalized_query == "what is machine learning"
        assert len(query.embedding) == 1024
        assert query.query_id is not None

    def test_processed_query_defaults(self):
        """Test default values."""
        query = ProcessedQuery(
            original_query="test",
            normalized_query="test",
            embedding=[0.1] * 1024,
        )

        assert query.expanded_queries == []
        assert query.hyde_document is None
        assert query.query_type == QueryType.SIMPLE
        assert query.tokens == 0
        assert query.processing_time_ms == 0.0
        assert query.metadata == {}

    def test_processed_query_with_expansions(self):
        """Test with expanded queries."""
        query = ProcessedQuery(
            original_query="fix the error",
            normalized_query="fix the error",
            embedding=[0.1] * 1024,
            expanded_queries=["fix the bug", "resolve the issue", "solve the problem"],
        )

        assert len(query.expanded_queries) == 3
        assert "fix the bug" in query.expanded_queries

    def test_processed_query_with_hyde(self):
        """Test with HyDE document."""
        hyde_doc = "Machine learning is a subset of artificial intelligence..."

        query = ProcessedQuery(
            original_query="what is machine learning",
            normalized_query="what is machine learning",
            embedding=[0.1] * 1024,
            hyde_document=hyde_doc,
            query_type=QueryType.QUESTION,
        )

        assert query.hyde_document == hyde_doc
        assert query.query_type == QueryType.QUESTION

    def test_processed_query_metadata(self):
        """Test metadata field."""
        query = ProcessedQuery(
            original_query="test",
            normalized_query="test",
            embedding=[0.1] * 1024,
            metadata={"cached": True, "cache_key": "abc123"},
        )

        assert query.metadata["cached"] is True
        assert query.metadata["cache_key"] == "abc123"

    def test_processed_query_json_serialization(self):
        """Test JSON serialization/deserialization."""
        query = ProcessedQuery(
            original_query="test query",
            normalized_query="test query",
            embedding=[0.1, 0.2, 0.3],
            query_type=QueryType.HYBRID,
            tokens=10,
            processing_time_ms=50.5,
        )

        json_str = query.model_dump_json()
        restored = ProcessedQuery.model_validate_json(json_str)

        assert restored.original_query == query.original_query
        assert restored.embedding == query.embedding
        assert restored.query_type == query.query_type
        assert restored.tokens == query.tokens


class TestQueryPreprocessorConfig:
    """Tests for QueryPreprocessorConfig model."""

    def test_default_config(self):
        """Test default configuration values."""
        config = QueryPreprocessorConfig()

        # Normalization defaults
        assert config.lowercase is True
        assert config.strip_whitespace is True
        assert config.remove_special_chars is False

        # Expansion defaults
        assert config.enable_expansion is True
        assert config.max_expansions == 3
        assert config.expansion_model == "synonym"

        # HyDE defaults
        assert config.enable_hyde is False
        assert config.hyde_max_tokens == 256

        # Embedding defaults
        assert config.embedding_model == "BAAI/bge-large-en-v1.5"
        assert config.embedding_prefix == "query: "
        assert config.embedding_dimension == 1024

        # Cache defaults
        assert config.cache_enabled is True
        assert config.cache_ttl == 3600

    def test_custom_config(self):
        """Test custom configuration."""
        config = QueryPreprocessorConfig(
            lowercase=False,
            enable_hyde=True,
            hyde_model="custom-model",
            max_expansions=5,
            cache_enabled=False,
        )

        assert config.lowercase is False
        assert config.enable_hyde is True
        assert config.hyde_model == "custom-model"
        assert config.max_expansions == 5
        assert config.cache_enabled is False

    def test_llm_gateway_config(self):
        """Test LLM Gateway configuration."""
        config = QueryPreprocessorConfig(
            llm_gateway_url="http://custom-llm:8000",
            embedding_endpoint="/embeddings",
            completion_endpoint="/generate",
            request_timeout=60.0,
        )

        assert config.llm_gateway_url == "http://custom-llm:8000"
        assert config.embedding_endpoint == "/embeddings"
        assert config.completion_endpoint == "/generate"
        assert config.request_timeout == 60.0

    def test_retry_config(self):
        """Test retry configuration."""
        config = QueryPreprocessorConfig(
            max_retries=5,
            retry_min_wait=2.0,
            retry_max_wait=20.0,
        )

        assert config.max_retries == 5
        assert config.retry_min_wait == 2.0
        assert config.retry_max_wait == 20.0
