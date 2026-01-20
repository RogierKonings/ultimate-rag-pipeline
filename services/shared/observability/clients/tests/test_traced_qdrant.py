"""Tests for TracedQdrantClient."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add services/shared to path for imports
shared_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(shared_root))


class TestTracedQdrantClient:
    """Tests for TracedQdrantClient wrapper."""

    @pytest.fixture
    def mock_qdrant_client(self):
        """Create a mock Qdrant client."""
        client = AsyncMock()
        client.query_points = AsyncMock(return_value=MagicMock(points=[]))
        client.upsert = AsyncMock(return_value=MagicMock())
        return client

    @pytest.fixture
    def traced_client(self, mock_qdrant_client):
        """Create a TracedQdrantClient with mock."""
        from observability.clients.traced_qdrant import TracedQdrantClient

        return TracedQdrantClient(
            client=mock_qdrant_client,
            collection_name="test_collection",
        )

    @pytest.mark.asyncio
    async def test_query_points_calls_underlying_client(self, traced_client, mock_qdrant_client):
        """Test query_points delegates to underlying client."""
        query_vector = [0.1, 0.2, 0.3]

        await traced_client.query_points(query=query_vector, limit=10)

        mock_qdrant_client.query_points.assert_called_once()
        call_kwargs = mock_qdrant_client.query_points.call_args.kwargs
        assert call_kwargs["collection_name"] == "test_collection"
        assert call_kwargs["query"] == query_vector
        assert call_kwargs["limit"] == 10

    @pytest.mark.asyncio
    async def test_query_points_uses_custom_collection(self, traced_client, mock_qdrant_client):
        """Test query_points can override collection name."""
        await traced_client.query_points(
            query=[0.1, 0.2],
            collection_name="other_collection",
            limit=5,
        )

        call_kwargs = mock_qdrant_client.query_points.call_args.kwargs
        assert call_kwargs["collection_name"] == "other_collection"

    @pytest.mark.asyncio
    async def test_upsert_calls_underlying_client(self, traced_client, mock_qdrant_client):
        """Test upsert delegates to underlying client."""
        points = [{"id": 1, "vector": [0.1, 0.2]}]

        await traced_client.upsert(points=points)

        mock_qdrant_client.upsert.assert_called_once()
        call_kwargs = mock_qdrant_client.upsert.call_args.kwargs
        assert call_kwargs["collection_name"] == "test_collection"
        assert call_kwargs["points"] == points

    @pytest.mark.asyncio
    async def test_query_points_creates_span(self, traced_client):
        """Test query_points creates an OTEL span."""
        with patch("observability.clients.traced_qdrant.tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_span.__enter__ = MagicMock(return_value=mock_span)
            mock_span.__exit__ = MagicMock(return_value=False)
            mock_tracer.start_as_current_span.return_value = mock_span

            await traced_client.query_points(query=[0.1], limit=10)

            mock_tracer.start_as_current_span.assert_called_once()
            call_args = mock_tracer.start_as_current_span.call_args
            assert call_args[0][0] == "qdrant.query.search"

    @pytest.mark.asyncio
    async def test_query_points_records_exception(self, traced_client, mock_qdrant_client):
        """Test query_points records exceptions in span."""
        mock_qdrant_client.query_points.side_effect = Exception("Connection failed")

        with pytest.raises(Exception, match="Connection failed"):
            await traced_client.query_points(query=[0.1], limit=10)

    @pytest.mark.asyncio
    async def test_client_property_returns_underlying_client(
        self, traced_client, mock_qdrant_client
    ):
        """Test client property returns the underlying client."""
        assert traced_client.client is mock_qdrant_client
