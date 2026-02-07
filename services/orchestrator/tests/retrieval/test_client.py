"""Tests for the RetrievalClient high-level wrapper."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from retrieval.client import RetrievalClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _mock_retrieval_response():
    """Return a realistic retrieval service JSON response."""
    return {
        "results": [
            {
                "content": "Python is a programming language.",
                "score": 0.95,
                "chunk_id": "c-1",
                "document_id": "d-1",
                "metadata": {"title": "Intro", "source_uri": "docs/intro.md"},
            },
            {
                "content": "Python supports OOP.",
                "score": 0.88,
                "chunk_id": "c-2",
                "document_id": "d-2",
                "metadata": {"title": "OOP", "source_uri": "docs/oop.md"},
            },
        ],
        "degradation_mode": "hybrid_full",
        "components_used": ["qdrant", "opensearch"],
        "components_skipped": [],
    }


@pytest.fixture
def _mock_degraded_response():
    """Return a degraded retrieval response (semantic_only)."""
    return {
        "results": [
            {
                "content": "Semantic-only result.",
                "score": 0.80,
                "chunk_id": "c-3",
                "document_id": "d-3",
                "metadata": {"source_uri": "docs/test.md"},
            },
        ],
        "degradation_mode": "semantic_only",
        "components_used": ["qdrant"],
        "components_skipped": ["opensearch"],
    }


@pytest.fixture
def mock_http_client(_mock_retrieval_response):
    """Create a mock httpx.AsyncClient with a successful search response."""
    client = AsyncMock(spec=httpx.AsyncClient)
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = _mock_retrieval_response
    response.raise_for_status = MagicMock()
    client.post = AsyncMock(return_value=response)
    client.get = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# Tests: search()
# ---------------------------------------------------------------------------


class TestRetrievalClientSearch:
    """Tests for RetrievalClient.search()."""

    async def test_search_returns_documents(self, mock_http_client, _mock_retrieval_response):
        """Test that search() returns normalised documents."""
        with patch("retrieval.client._get_http_client", return_value=mock_http_client):
            client = RetrievalClient(top_k=10)
            result = await client.search("What is Python?")

        assert isinstance(result, dict)
        assert len(result["documents"]) == 2
        assert result["documents"][0]["content"] == "Python is a programming language."
        assert result["documents"][0]["score"] == 0.95
        assert result["documents"][0]["chunk_id"] == "c-1"
        assert result["documents"][0]["source"] == "docs/intro.md"

    async def test_search_returns_degradation_info(self, mock_http_client):
        """Test that search() passes through degradation metadata."""
        with patch("retrieval.client._get_http_client", return_value=mock_http_client):
            client = RetrievalClient(top_k=10)
            result = await client.search("test")

        assert result["degradation_mode"] == "hybrid_full"
        assert result["components_used"] == ["qdrant", "opensearch"]
        assert result["components_skipped"] == []

    async def test_search_sends_correct_payload(self, mock_http_client):
        """Test that search() constructs the correct request payload."""
        with patch("retrieval.client._get_http_client", return_value=mock_http_client):
            client = RetrievalClient(top_k=25)
            await client.search("my query", tenant_id="t-1")

        call_kwargs = mock_http_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")

        assert payload["query"] == "my query"
        assert payload["top_k"] == 25
        assert payload["mode"] == "hybrid"
        assert payload["filters"] == {"tenant_id": "t-1"}
        assert headers["X-Tenant-Id"] == "t-1"

    async def test_search_without_tenant_id_omits_filter(self, mock_http_client):
        """Test that search() omits tenant filter when tenant_id is None."""
        with patch("retrieval.client._get_http_client", return_value=mock_http_client):
            client = RetrievalClient(top_k=10)
            await client.search("test query")

        call_kwargs = mock_http_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "filters" not in payload

    async def test_search_allows_top_k_override(self, mock_http_client):
        """Test that search() respects per-call top_k override."""
        with patch("retrieval.client._get_http_client", return_value=mock_http_client):
            client = RetrievalClient(top_k=10)
            await client.search("test", top_k=5)

        call_kwargs = mock_http_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["top_k"] == 5

    async def test_search_propagates_http_error(self, mock_http_client):
        """Test that search() propagates HTTP errors for callers to handle."""
        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 503
        error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Service unavailable",
            request=MagicMock(),
            response=error_response,
        )
        mock_http_client.post = AsyncMock(return_value=error_response)

        with patch("retrieval.client._get_http_client", return_value=mock_http_client):
            client = RetrievalClient(top_k=10)
            with pytest.raises(httpx.HTTPStatusError):
                await client.search("test")

    async def test_search_propagates_connection_error(self):
        """Test that search() propagates connection errors."""
        failing_client = AsyncMock(spec=httpx.AsyncClient)
        failing_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with patch("retrieval.client._get_http_client", return_value=failing_client):
            client = RetrievalClient(top_k=10)
            with pytest.raises(httpx.ConnectError):
                await client.search("test")

    async def test_search_with_degraded_response(self, _mock_degraded_response):
        """Test that search() correctly parses degraded retrieval response."""
        degraded_client = AsyncMock(spec=httpx.AsyncClient)
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.json.return_value = _mock_degraded_response
        response.raise_for_status = MagicMock()
        degraded_client.post = AsyncMock(return_value=response)

        with patch("retrieval.client._get_http_client", return_value=degraded_client):
            client = RetrievalClient(top_k=10)
            result = await client.search("test")

        assert result["degradation_mode"] == "semantic_only"
        assert result["components_used"] == ["qdrant"]
        assert result["components_skipped"] == ["opensearch"]
        assert len(result["documents"]) == 1

    async def test_search_handles_empty_results(self, mock_http_client):
        """Test that search() handles empty results gracefully."""
        empty_response = MagicMock(spec=httpx.Response)
        empty_response.status_code = 200
        empty_response.json.return_value = {
            "results": [],
            "degradation_mode": "hybrid_full",
            "components_used": ["qdrant", "opensearch"],
            "components_skipped": [],
        }
        empty_response.raise_for_status = MagicMock()
        mock_http_client.post = AsyncMock(return_value=empty_response)

        with patch("retrieval.client._get_http_client", return_value=mock_http_client):
            client = RetrievalClient(top_k=10)
            result = await client.search("obscure query")

        assert result["documents"] == []
        assert result["degradation_mode"] == "hybrid_full"


# ---------------------------------------------------------------------------
# Tests: health_check()
# ---------------------------------------------------------------------------


class TestRetrievalClientHealthCheck:
    """Tests for RetrievalClient.health_check()."""

    async def test_health_check_healthy(self):
        """Test health_check returns healthy status."""
        healthy_client = AsyncMock(spec=httpx.AsyncClient)
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.json.return_value = {"status": "healthy"}
        response.raise_for_status = MagicMock()
        healthy_client.get = AsyncMock(return_value=response)

        with patch("retrieval.client._get_http_client", return_value=healthy_client):
            client = RetrievalClient(top_k=10)
            result = await client.health_check()

        assert result["status"] == "healthy"

    async def test_health_check_returns_unhealthy_on_failure(self):
        """Test health_check returns unhealthy dict on connection failure."""
        failing_client = AsyncMock(spec=httpx.AsyncClient)
        failing_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with patch("retrieval.client._get_http_client", return_value=failing_client):
            client = RetrievalClient(top_k=10)
            result = await client.health_check()

        assert result["status"] == "unhealthy"
        assert "error" in result

    async def test_health_check_returns_unhealthy_on_http_error(self):
        """Test health_check returns unhealthy dict on HTTP error."""
        error_client = AsyncMock(spec=httpx.AsyncClient)
        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 503
        error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unavailable", request=MagicMock(), response=error_response
        )
        error_client.get = AsyncMock(return_value=error_response)

        with patch("retrieval.client._get_http_client", return_value=error_client):
            client = RetrievalClient(top_k=10)
            result = await client.health_check()

        assert result["status"] == "unhealthy"


# ---------------------------------------------------------------------------
# Tests: Streaming integration (verifying the contract with query.py)
# ---------------------------------------------------------------------------


class TestRetrievalClientStreamingContract:
    """Tests verifying the RetrievalClient satisfies the streaming path contract.

    The streaming endpoint in query.py calls:
        result = await retrieval_client.search(query)
    and expects either a dict with 'documents', 'degradation_mode', etc.
    or a plain list of documents.
    """

    async def test_search_result_is_dict_with_required_keys(self, mock_http_client):
        """Test that search() result has the keys the streaming path expects."""
        with patch("retrieval.client._get_http_client", return_value=mock_http_client):
            client = RetrievalClient(top_k=10)
            result = await client.search("test")

        assert isinstance(result, dict)
        assert "documents" in result
        assert "degradation_mode" in result
        assert "components_used" in result
        assert "components_skipped" in result

    async def test_documents_have_content_key(self, mock_http_client):
        """Test that each document has a 'content' key for context building."""
        with patch("retrieval.client._get_http_client", return_value=mock_http_client):
            client = RetrievalClient(top_k=10)
            result = await client.search("test")

        for doc in result["documents"]:
            assert "content" in doc
