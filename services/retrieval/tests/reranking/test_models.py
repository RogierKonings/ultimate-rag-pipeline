"""Tests for reranking models."""

import pytest
from uuid import uuid4

from reranking.models import (
    RerankerConfig,
    RerankRequest,
    RerankResponse,
    RerankResult,
)


class TestRerankRequest:
    """Tests for RerankRequest model."""

    def test_basic_creation(self):
        """Test basic request creation."""
        request = RerankRequest(
            query="test query",
            documents=["doc1", "doc2"],
            document_ids=[uuid4(), uuid4()],
        )
        assert request.query == "test query"
        assert len(request.documents) == 2
        assert request.top_k is None
        assert request.return_documents is False

    def test_with_options(self):
        """Test request with optional parameters."""
        request = RerankRequest(
            query="test",
            documents=["doc"],
            document_ids=[uuid4()],
            top_k=5,
            return_documents=True,
        )
        assert request.top_k == 5
        assert request.return_documents is True


class TestRerankResult:
    """Tests for RerankResult model."""

    def test_basic_creation(self):
        """Test basic result creation."""
        doc_id = uuid4()
        result = RerankResult(
            document_id=doc_id,
            index=0,
            relevance_score=0.95,
        )
        assert result.document_id == doc_id
        assert result.index == 0
        assert result.relevance_score == 0.95
        assert result.document is None

    def test_with_document(self):
        """Test result with document text."""
        result = RerankResult(
            document_id=uuid4(),
            index=1,
            relevance_score=0.8,
            document="Document content",
        )
        assert result.document == "Document content"


class TestRerankResponse:
    """Tests for RerankResponse model."""

    def test_basic_creation(self):
        """Test basic response creation."""
        response = RerankResponse(
            results=[],
            model="test-model",
            processing_time_ms=50.5,
        )
        assert response.model == "test-model"
        assert response.processing_time_ms == 50.5
        assert len(response.results) == 0

    def test_with_results(self):
        """Test response with results."""
        results = [
            RerankResult(
                document_id=uuid4(),
                index=0,
                relevance_score=0.95,
            ),
            RerankResult(
                document_id=uuid4(),
                index=1,
                relevance_score=0.75,
            ),
        ]
        response = RerankResponse(
            results=results,
            model="BAAI/bge-reranker-v2-m3",
            processing_time_ms=100.0,
        )
        assert len(response.results) == 2
        assert response.results[0].relevance_score == 0.95


class TestRerankerConfig:
    """Tests for RerankerConfig model."""

    def test_defaults(self):
        """Test default configuration values."""
        config = RerankerConfig()
        assert config.model == "BAAI/bge-reranker-v2-m3"
        assert config.llm_gateway_url == "http://localhost:8004"
        assert config.rerank_endpoint == "/v1/rerank"
        assert config.max_batch_size == 32
        assert config.max_documents == 100
        assert config.max_query_length == 512
        assert config.max_document_length == 512
        assert config.timeout_seconds == 30.0
        assert config.score_threshold == 0.0
        assert config.max_retries == 3

    def test_custom_values(self):
        """Test custom configuration values."""
        config = RerankerConfig(
            model="custom-model",
            llm_gateway_url="http://custom:8080",
            max_batch_size=16,
            score_threshold=0.5,
        )
        assert config.model == "custom-model"
        assert config.llm_gateway_url == "http://custom:8080"
        assert config.max_batch_size == 16
        assert config.score_threshold == 0.5
