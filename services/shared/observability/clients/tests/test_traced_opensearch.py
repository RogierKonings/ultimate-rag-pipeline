"""Tests for TracedOpenSearchClient."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add services/shared to path for imports
shared_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(shared_root))


class TestTracedOpenSearchClient:
    """Tests for TracedOpenSearchClient wrapper."""

    @pytest.fixture
    def mock_opensearch_client(self):
        """Create a mock OpenSearch client."""
        client = AsyncMock()
        client.search = AsyncMock(return_value={"hits": {"total": {"value": 5}, "hits": []}})
        client.index = AsyncMock(return_value={"result": "created"})
        client.bulk = AsyncMock(return_value={"errors": False, "items": []})
        client.delete = AsyncMock(return_value={"result": "deleted"})
        return client

    @pytest.fixture
    def traced_client(self, mock_opensearch_client):
        """Create a TracedOpenSearchClient with mock."""
        from observability.clients.traced_opensearch import TracedOpenSearchClient

        return TracedOpenSearchClient(
            client=mock_opensearch_client,
            index_name="test_index",
        )

    @pytest.mark.asyncio
    async def test_search_calls_underlying_client(self, traced_client, mock_opensearch_client):
        """Test search delegates to underlying client."""
        query = {"match_all": {}}

        await traced_client.search(body={"query": query})

        mock_opensearch_client.search.assert_called_once()
        call_kwargs = mock_opensearch_client.search.call_args.kwargs
        assert call_kwargs["index"] == "test_index"
        assert call_kwargs["body"] == {"query": query}

    @pytest.mark.asyncio
    async def test_search_uses_custom_index(self, traced_client, mock_opensearch_client):
        """Test search can override index name."""
        await traced_client.search(
            body={"query": {"match_all": {}}},
            index="other_index",
        )

        call_kwargs = mock_opensearch_client.search.call_args.kwargs
        assert call_kwargs["index"] == "other_index"

    @pytest.mark.asyncio
    async def test_index_calls_underlying_client(self, traced_client, mock_opensearch_client):
        """Test index delegates to underlying client."""
        document = {"title": "Test", "content": "Test content"}

        await traced_client.index(body=document, id="doc1")

        mock_opensearch_client.index.assert_called_once()
        call_kwargs = mock_opensearch_client.index.call_args.kwargs
        assert call_kwargs["index"] == "test_index"
        assert call_kwargs["body"] == document
        assert call_kwargs["id"] == "doc1"

    @pytest.mark.asyncio
    async def test_bulk_calls_underlying_client(self, traced_client, mock_opensearch_client):
        """Test bulk delegates to underlying client."""
        operations = [
            {"index": {"_index": "test_index", "_id": "1"}},
            {"title": "Doc 1"},
        ]

        await traced_client.bulk(body=operations)

        mock_opensearch_client.bulk.assert_called_once()
        call_kwargs = mock_opensearch_client.bulk.call_args.kwargs
        assert call_kwargs["body"] == operations

    @pytest.mark.asyncio
    async def test_delete_calls_underlying_client(self, traced_client, mock_opensearch_client):
        """Test delete delegates to underlying client."""
        await traced_client.delete(id="doc1")

        mock_opensearch_client.delete.assert_called_once()
        call_kwargs = mock_opensearch_client.delete.call_args.kwargs
        assert call_kwargs["index"] == "test_index"
        assert call_kwargs["id"] == "doc1"

    @pytest.mark.asyncio
    async def test_search_creates_span(self, traced_client):
        """Test search creates an OTEL span."""
        with patch("observability.clients.traced_opensearch.tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.__enter__ = MagicMock(return_value=mock_span)
            mock_span.__exit__ = MagicMock(return_value=False)
            mock_tracer.start_as_current_span.return_value = mock_span

            await traced_client.search(body={"query": {"match_all": {}}})

            mock_tracer.start_as_current_span.assert_called_once()
            call_args = mock_tracer.start_as_current_span.call_args
            assert call_args[0][0] == "opensearch.query.search"

    @pytest.mark.asyncio
    async def test_search_records_exception(self, traced_client, mock_opensearch_client):
        """Test search records exceptions in span."""
        mock_opensearch_client.search.side_effect = Exception("Connection failed")

        with pytest.raises(Exception, match="Connection failed"):
            await traced_client.search(body={"query": {"match_all": {}}})

    @pytest.mark.asyncio
    async def test_client_property_returns_underlying_client(
        self, traced_client, mock_opensearch_client
    ):
        """Test client property returns the underlying client."""
        assert traced_client.client is mock_opensearch_client

    @pytest.mark.asyncio
    async def test_index_creates_span(self, traced_client):
        """Test index creates an OTEL span."""
        with patch("observability.clients.traced_opensearch.tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.__enter__ = MagicMock(return_value=mock_span)
            mock_span.__exit__ = MagicMock(return_value=False)
            mock_tracer.start_as_current_span.return_value = mock_span

            await traced_client.index(body={"title": "Test"}, id="doc1")

            mock_tracer.start_as_current_span.assert_called_once()
            call_args = mock_tracer.start_as_current_span.call_args
            assert call_args[0][0] == "opensearch.mutation.index"

    @pytest.mark.asyncio
    async def test_bulk_creates_span(self, traced_client):
        """Test bulk creates an OTEL span."""
        with patch("observability.clients.traced_opensearch.tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.__enter__ = MagicMock(return_value=mock_span)
            mock_span.__exit__ = MagicMock(return_value=False)
            mock_tracer.start_as_current_span.return_value = mock_span

            await traced_client.bulk(body=[])

            mock_tracer.start_as_current_span.assert_called_once()
            call_args = mock_tracer.start_as_current_span.call_args
            assert call_args[0][0] == "opensearch.mutation.bulk"

    @pytest.mark.asyncio
    async def test_delete_creates_span(self, traced_client):
        """Test delete creates an OTEL span."""
        with patch("observability.clients.traced_opensearch.tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.__enter__ = MagicMock(return_value=mock_span)
            mock_span.__exit__ = MagicMock(return_value=False)
            mock_tracer.start_as_current_span.return_value = mock_span

            await traced_client.delete(id="doc1")

            mock_tracer.start_as_current_span.assert_called_once()
            call_args = mock_tracer.start_as_current_span.call_args
            assert call_args[0][0] == "opensearch.mutation.delete"

    @pytest.mark.asyncio
    async def test_search_records_response_size(self, traced_client, mock_opensearch_client):
        """Test search records response size from hits.total.value."""
        mock_opensearch_client.search.return_value = {"hits": {"total": {"value": 42}, "hits": []}}

        with patch("observability.clients.traced_opensearch.tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.__enter__ = MagicMock(return_value=mock_span)
            mock_span.__exit__ = MagicMock(return_value=False)
            mock_tracer.start_as_current_span.return_value = mock_span

            await traced_client.search(body={"query": {"match_all": {}}})

            # Check that set_attribute was called with result count
            set_attribute_calls = mock_span.set_attribute.call_args_list
            result_count_call = [
                call for call in set_attribute_calls if call[0][0] == "db.opensearch.result_count"
            ]
            assert len(result_count_call) == 1
            assert result_count_call[0][0][1] == 42
