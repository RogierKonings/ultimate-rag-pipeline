"""Tests for re-embedding tasks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ..reembed import _reembed_collection_async, reembed_collection


class TestReembedCollection:
    """Tests for reembed_collection task."""

    @pytest.mark.asyncio
    async def test_reembed_empty_collection(self):
        """Test re-embedding an empty collection."""
        mock_task = MagicMock()
        mock_task.update_state = MagicMock()

        with patch("tasks.reembed.get_async_session") as mock_session:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_ctx.execute = AsyncMock(return_value=mock_result)

            mock_session.return_value = mock_ctx

            result = await _reembed_collection_async(
                task=mock_task,
                collection_name="test-collection",
                new_model="new-model",
                batch_size=100,
                tenant_id=None,
            )

        assert result["collection"] == "test-collection"
        assert result["chunks_reembedded"] == 0

    @pytest.mark.asyncio
    async def test_reembed_with_chunks(self):
        """Test re-embedding a collection with chunks."""
        mock_task = MagicMock()
        mock_task.update_state = MagicMock()

        # Create mock chunks
        mock_chunks = [MagicMock(chunk_id=i, content=f"content {i}") for i in range(5)]

        with patch("tasks.reembed.get_async_session") as mock_session:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = mock_chunks
            mock_ctx.execute = AsyncMock(return_value=mock_result)

            mock_session.return_value = mock_ctx

            with patch("tasks.reembed.EmbeddingService") as mock_embed:
                mock_service = AsyncMock()
                mock_service.embed_texts = AsyncMock(
                    return_value=MagicMock(
                        results=[MagicMock(embedding=[0.1] * 1024) for _ in mock_chunks],
                    ),
                )
                mock_service.__aenter__ = AsyncMock(return_value=mock_service)
                mock_service.__aexit__ = AsyncMock(return_value=None)
                mock_embed.return_value = mock_service

                with patch(
                    "tasks.reembed._update_embeddings_in_qdrant",
                ) as mock_update:
                    mock_update.return_value = None

                    result = await _reembed_collection_async(
                        task=mock_task,
                        collection_name="test-collection",
                        new_model="new-model",
                        batch_size=100,
                        tenant_id=None,
                    )

        assert result["collection"] == "test-collection"
        assert result["new_model"] == "new-model"
        assert result["chunks_reembedded"] == 5

    def test_reembed_task_is_registered(self, celery_app):
        """Test that reembed_collection task is properly registered."""
        assert reembed_collection.name == "tasks.reembed.reembed_collection"
