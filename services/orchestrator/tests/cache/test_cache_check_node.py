"""Tests for the cache_check and cache_store workflow nodes.

Tests US-10.5.3: Answer-Level Caching workflow integration
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cache.answer_cache import AnswerCache, AnswerCacheConfig, CachedAnswer
from workflow.nodes.cache_check import (
    _compute_config_hash_from_options,
    cache_check_node,
    cache_store_node,
)


@pytest.fixture
def mock_answer_cache():
    """Create a mock AnswerCache."""
    cache = MagicMock(spec=AnswerCache)
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=True)
    cache._compute_config_hash = MagicMock(return_value="test_config_hash")
    return cache


@pytest.fixture
def sample_cached_answer():
    """Create a sample cached answer."""
    return CachedAnswer(
        response="Python is a programming language.",
        citations=[
            {
                "content": "Python is versatile...",
                "score": 0.95,
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "metadata": {"title": "Python Intro"},
                "source": "docs/python.md",
            }
        ],
        model_used="llama-3.1-8b",
        retrieval_mode="hybrid",
        strategy="simple",
        document_ids=["doc-1"],
    )


@pytest.fixture
def base_state():
    """Create a base RAGState for testing."""
    return {
        "request_id": "req-123",
        "query": "What is Python?",
        "session_id": "session-456",
        "user_id": "user-789",
        "tenant_id": "tenant-abc",
        "options": {},
        "strategy": "simple",
        "documents": [],
        "context": "",
        "messages": [],
        "response": None,
        "model_used": None,
        "usage": None,
        "timing": {},
        "verification_result": None,
        "cache_hit": False,
        "error": None,
        "fallbacks_used": [],
    }


class TestComputeConfigHashFromOptions:
    """Tests for config hash computation from options."""

    def test_default_options(self, mock_answer_cache):
        """Test config hash with default options."""
        options = {}
        _compute_config_hash_from_options(options, mock_answer_cache)
        mock_answer_cache._compute_config_hash.assert_called_once()

    def test_custom_options(self, mock_answer_cache):
        """Test config hash with custom options."""
        options = {
            "retrieval_mode": "semantic",
            "top_k": 20,
            "rerank": False,
            "semantic_weight": 0.8,
            "keyword_weight": 0.2,
        }
        _compute_config_hash_from_options(options, mock_answer_cache)
        mock_answer_cache._compute_config_hash.assert_called_once_with(
            retrieval_mode="semantic",
            top_k=20,
            rerank=False,
            semantic_weight=0.8,
            keyword_weight=0.2,
            extra_config=None,
        )

    def test_extra_config_with_temperature(self, mock_answer_cache):
        """Test extra config is included when temperature set."""
        options = {"temperature": 0.5, "max_tokens": 512}
        _compute_config_hash_from_options(options, mock_answer_cache)

        call_args = mock_answer_cache._compute_config_hash.call_args
        assert call_args[1]["extra_config"] == {"temperature": 0.5, "max_tokens": 512}


class TestCacheCheckNode:
    """Tests for cache_check_node."""

    @pytest.mark.asyncio
    async def test_cache_disabled(self, base_state):
        """Test cache check when caching is disabled."""
        base_state["options"] = {"enable_answer_cache": False}

        result = await cache_check_node(base_state)

        assert result["cache_hit"] is False
        assert "cache_check" in result["timing"]

    @pytest.mark.asyncio
    async def test_cache_not_configured(self, base_state):
        """Test cache check when cache not in options."""
        base_state["options"] = {"enable_answer_cache": True}  # No answer_cache

        result = await cache_check_node(base_state)

        assert result["cache_hit"] is False

    @pytest.mark.asyncio
    async def test_missing_tenant_id(self, base_state, mock_answer_cache):
        """Test cache check with missing tenant_id."""
        base_state["tenant_id"] = None
        base_state["options"] = {
            "enable_answer_cache": True,
            "answer_cache": mock_answer_cache,
        }

        result = await cache_check_node(base_state)

        assert result["cache_hit"] is False

    @pytest.mark.asyncio
    async def test_missing_query(self, base_state, mock_answer_cache):
        """Test cache check with missing query."""
        base_state["query"] = ""
        base_state["options"] = {
            "enable_answer_cache": True,
            "answer_cache": mock_answer_cache,
        }

        result = await cache_check_node(base_state)

        assert result["cache_hit"] is False

    @pytest.mark.asyncio
    async def test_cache_miss(self, base_state, mock_answer_cache):
        """Test cache miss."""
        mock_answer_cache.get.return_value = None
        base_state["options"] = {
            "enable_answer_cache": True,
            "answer_cache": mock_answer_cache,
        }

        result = await cache_check_node(base_state)

        assert result["cache_hit"] is False
        assert "_config_hash" in result["options"]
        mock_answer_cache.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_hit(self, base_state, mock_answer_cache, sample_cached_answer):
        """Test cache hit."""
        mock_answer_cache.get.return_value = sample_cached_answer
        base_state["options"] = {
            "enable_answer_cache": True,
            "answer_cache": mock_answer_cache,
        }

        result = await cache_check_node(base_state)

        assert result["cache_hit"] is True
        assert result["response"] == "Python is a programming language."
        assert result["model_used"] == "llama-3.1-8b"
        assert result["strategy"] == "simple"
        assert len(result["documents"]) == 1
        assert result["retrieval_quality"]["mode"] == "hybrid"
        assert result["context_quality"] == "full"

    @pytest.mark.asyncio
    async def test_cache_hit_documents_format(
        self, base_state, mock_answer_cache, sample_cached_answer
    ):
        """Test cache hit converts citations to documents format."""
        mock_answer_cache.get.return_value = sample_cached_answer
        base_state["options"] = {
            "enable_answer_cache": True,
            "answer_cache": mock_answer_cache,
        }

        result = await cache_check_node(base_state)

        doc = result["documents"][0]
        assert doc["content"] == "Python is versatile..."
        assert doc["score"] == 0.95
        assert doc["chunk_id"] == "chunk-1"
        assert doc["document_id"] == "doc-1"

    @pytest.mark.asyncio
    async def test_timing_recorded(self, base_state, mock_answer_cache):
        """Test timing is recorded."""
        mock_answer_cache.get.return_value = None
        base_state["options"] = {
            "enable_answer_cache": True,
            "answer_cache": mock_answer_cache,
        }

        result = await cache_check_node(base_state)

        assert "cache_check" in result["timing"]
        assert result["timing"]["cache_check"] >= 0


class TestCacheStoreNode:
    """Tests for cache_store_node."""

    @pytest.mark.asyncio
    async def test_skip_when_disabled(self, base_state, mock_answer_cache):
        """Test cache store is skipped when disabled."""
        base_state["options"] = {"enable_answer_cache": False}
        base_state["response"] = "Test response"
        base_state["cache_hit"] = False

        result = await cache_store_node(base_state)

        assert "cache_store" in result["timing"]
        mock_answer_cache.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_when_cache_hit(self, base_state, mock_answer_cache):
        """Test cache store is skipped on cache hit."""
        base_state["options"] = {
            "enable_answer_cache": True,
            "answer_cache": mock_answer_cache,
        }
        base_state["response"] = "Test response"
        base_state["cache_hit"] = True

        result = await cache_store_node(base_state)

        mock_answer_cache.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_when_no_response(self, base_state, mock_answer_cache):
        """Test cache store is skipped when no response."""
        base_state["options"] = {
            "enable_answer_cache": True,
            "answer_cache": mock_answer_cache,
        }
        base_state["response"] = None
        base_state["cache_hit"] = False

        result = await cache_store_node(base_state)

        mock_answer_cache.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_success(self, base_state, mock_answer_cache):
        """Test successful cache store."""
        base_state["options"] = {
            "enable_answer_cache": True,
            "answer_cache": mock_answer_cache,
            "_config_hash": "test_hash",
        }
        base_state["response"] = "Python is a programming language."
        base_state["cache_hit"] = False
        base_state["model_used"] = "llama-3.1-8b"
        base_state["documents"] = [
            {
                "content": "Python content",
                "score": 0.9,
                "chunk_id": "c1",
                "document_id": "d1",
                "metadata": {},
                "source": "test.md",
            }
        ]
        base_state["retrieval_quality"] = {"mode": "hybrid"}
        base_state["strategy"] = "simple"

        result = await cache_store_node(base_state)

        mock_answer_cache.set.assert_called_once()
        call_args = mock_answer_cache.set.call_args
        assert call_args[1]["tenant_id"] == "tenant-abc"
        assert call_args[1]["query"] == "What is Python?"
        assert call_args[1]["config_hash"] == "test_hash"

    @pytest.mark.asyncio
    async def test_store_extracts_document_ids(self, base_state, mock_answer_cache):
        """Test cache store extracts document IDs for invalidation."""
        base_state["options"] = {
            "enable_answer_cache": True,
            "answer_cache": mock_answer_cache,
            "_config_hash": "test_hash",
        }
        base_state["response"] = "Test response"
        base_state["cache_hit"] = False
        base_state["model_used"] = "test-model"
        base_state["documents"] = [
            {"document_id": "doc-1", "content": "a"},
            {"document_id": "doc-2", "content": "b"},
            {"document_id": None, "content": "c"},  # Should be skipped
        ]

        await cache_store_node(base_state)

        call_args = mock_answer_cache.set.call_args
        answer = call_args[1]["answer"]
        assert answer.document_ids == ["doc-1", "doc-2"]

    @pytest.mark.asyncio
    async def test_timing_recorded(self, base_state, mock_answer_cache):
        """Test timing is recorded."""
        base_state["options"] = {
            "enable_answer_cache": True,
            "answer_cache": mock_answer_cache,
            "_config_hash": "test_hash",
        }
        base_state["response"] = "Test"
        base_state["cache_hit"] = False
        base_state["model_used"] = "test-model"
        base_state["documents"] = []

        result = await cache_store_node(base_state)

        assert "cache_store" in result["timing"]


class TestCacheWorkflowIntegration:
    """Integration tests for cache workflow."""

    @pytest.mark.asyncio
    async def test_full_cache_cycle(self, base_state, mock_answer_cache):
        """Test full cache miss -> store -> hit cycle."""
        # First request: cache miss
        mock_answer_cache.get.return_value = None
        base_state["options"] = {
            "enable_answer_cache": True,
            "answer_cache": mock_answer_cache,
        }

        result1 = await cache_check_node(base_state)
        assert result1["cache_hit"] is False

        # Simulate generation
        result1["response"] = "Generated response"
        result1["model_used"] = "llama-3.1-8b"
        result1["documents"] = [{"document_id": "d1", "content": "c"}]
        result1["retrieval_quality"] = {"mode": "hybrid"}
        result1["strategy"] = "simple"

        # Store in cache
        await cache_store_node(result1)
        mock_answer_cache.set.assert_called_once()

        # Second request: cache hit
        stored_answer = CachedAnswer(
            response="Generated response",
            citations=[{"document_id": "d1", "content": "c"}],
            model_used="llama-3.1-8b",
            retrieval_mode="hybrid",
            strategy="simple",
            document_ids=["d1"],
        )
        mock_answer_cache.get.return_value = stored_answer

        result2 = await cache_check_node(base_state)
        assert result2["cache_hit"] is True
        assert result2["response"] == "Generated response"
