"""Tests for Qdrant collection manager."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from qdrant_client.models import Distance

from services.ingestion.migrations.collection_manager import CollectionManager


@pytest.mark.asyncio
class TestCollectionManager:
    """Tests for CollectionManager."""

    async def test_create_migration_collection_success(self, mock_qdrant_client):
        """Test successful collection creation."""
        manager = CollectionManager(client=mock_qdrant_client)

        result = await manager.create_migration_collection(
            collection_name="test_collection",
            dimensions=1024,
        )

        assert result is True
        mock_qdrant_client.create_collection.assert_called_once()

    async def test_create_migration_collection_already_exists(self, mock_qdrant_client):
        """Test collection creation when already exists."""
        # Setup mock to return existing collection
        collections_response = MagicMock()
        collections_response.collections = [MagicMock(name="test_collection")]
        mock_qdrant_client.get_collections.return_value = collections_response

        manager = CollectionManager(client=mock_qdrant_client)

        result = await manager.create_migration_collection(
            collection_name="test_collection",
            dimensions=1024,
        )

        assert result is True
        mock_qdrant_client.create_collection.assert_not_called()

    async def test_create_migration_collection_failure(self, mock_qdrant_client):
        """Test collection creation failure."""
        mock_qdrant_client.create_collection.side_effect = Exception("Creation failed")

        manager = CollectionManager(client=mock_qdrant_client)

        result = await manager.create_migration_collection(
            collection_name="test_collection",
            dimensions=1024,
        )

        assert result is False

    async def test_get_alias_target_exists(self, mock_qdrant_client):
        """Test getting alias target when alias exists."""
        # Setup mock alias
        alias = MagicMock()
        alias.alias_name = "rag_chunks"
        alias.collection_name = "rag_chunks_v1"
        aliases_response = MagicMock()
        aliases_response.aliases = [alias]
        mock_qdrant_client.get_aliases.return_value = aliases_response

        manager = CollectionManager(client=mock_qdrant_client)

        result = await manager.get_alias_target("rag_chunks")

        assert result == "rag_chunks_v1"

    async def test_get_alias_target_not_found(self, mock_qdrant_client):
        """Test getting alias target when alias doesn't exist."""
        manager = CollectionManager(client=mock_qdrant_client)

        result = await manager.get_alias_target("nonexistent")

        assert result is None

    async def test_switch_alias_success(self, mock_qdrant_client):
        """Test successful alias switch."""
        manager = CollectionManager(client=mock_qdrant_client)

        result = await manager.switch_alias(
            alias_name="rag_chunks",
            new_collection="rag_chunks_v2",
            old_collection="rag_chunks_v1",
        )

        assert result is True
        mock_qdrant_client.update_collection_aliases.assert_called_once()

    async def test_switch_alias_with_existing(self, mock_qdrant_client):
        """Test alias switch when existing alias present."""
        # Setup existing alias
        alias = MagicMock()
        alias.alias_name = "rag_chunks"
        alias.collection_name = "rag_chunks_v1"
        aliases_response = MagicMock()
        aliases_response.aliases = [alias]
        mock_qdrant_client.get_aliases.return_value = aliases_response

        manager = CollectionManager(client=mock_qdrant_client)

        result = await manager.switch_alias(
            alias_name="rag_chunks",
            new_collection="rag_chunks_v2",
        )

        assert result is True
        # Should delete old and create new
        call_args = mock_qdrant_client.update_collection_aliases.call_args
        operations = call_args.kwargs["change_aliases_operations"]
        assert len(operations) == 2  # delete + create

    async def test_switch_alias_failure(self, mock_qdrant_client):
        """Test alias switch failure."""
        mock_qdrant_client.update_collection_aliases.side_effect = Exception("Failed")

        manager = CollectionManager(client=mock_qdrant_client)

        result = await manager.switch_alias(
            alias_name="rag_chunks",
            new_collection="rag_chunks_v2",
        )

        assert result is False

    async def test_delete_collection_success(self, mock_qdrant_client):
        """Test successful collection deletion."""
        manager = CollectionManager(client=mock_qdrant_client)

        result = await manager.delete_collection("old_collection")

        assert result is True
        mock_qdrant_client.delete_collection.assert_called_once_with("old_collection")

    async def test_delete_collection_with_aliases(self, mock_qdrant_client):
        """Test collection deletion blocked by active aliases."""
        # Setup alias pointing to collection
        alias = MagicMock()
        alias.alias_name = "rag_chunks"
        alias.collection_name = "old_collection"
        aliases_response = MagicMock()
        aliases_response.aliases = [alias]
        mock_qdrant_client.get_aliases.return_value = aliases_response

        manager = CollectionManager(client=mock_qdrant_client)

        result = await manager.delete_collection("old_collection")

        assert result is False
        mock_qdrant_client.delete_collection.assert_not_called()

    async def test_get_collection_info(self, mock_qdrant_client):
        """Test getting collection info."""
        manager = CollectionManager(client=mock_qdrant_client)

        info = await manager.get_collection_info("test_collection")

        assert info is not None
        assert info["name"] == "test_collection"
        assert info["vectors_count"] == 1000
        assert info["config"]["vector_size"] == 1024

    async def test_get_collection_vector_count(self, mock_qdrant_client):
        """Test getting vector count."""
        manager = CollectionManager(client=mock_qdrant_client)

        count = await manager.get_collection_vector_count("test_collection")

        assert count == 1000

    async def test_list_collection_aliases(self, mock_qdrant_client):
        """Test listing aliases for a collection."""
        # Setup multiple aliases
        alias1 = MagicMock()
        alias1.alias_name = "alias1"
        alias1.collection_name = "target_collection"
        alias2 = MagicMock()
        alias2.alias_name = "alias2"
        alias2.collection_name = "other_collection"
        aliases_response = MagicMock()
        aliases_response.aliases = [alias1, alias2]
        mock_qdrant_client.get_aliases.return_value = aliases_response

        manager = CollectionManager(client=mock_qdrant_client)

        aliases = await manager.list_collection_aliases("target_collection")

        assert aliases == ["alias1"]

    async def test_create_alias_success(self, mock_qdrant_client):
        """Test creating a new alias."""
        manager = CollectionManager(client=mock_qdrant_client)

        result = await manager.create_alias("new_alias", "collection")

        assert result is True
        mock_qdrant_client.update_collection_aliases.assert_called_once()

    async def test_delete_alias_success(self, mock_qdrant_client):
        """Test deleting an alias."""
        manager = CollectionManager(client=mock_qdrant_client)

        result = await manager.delete_alias("old_alias")

        assert result is True
        mock_qdrant_client.update_collection_aliases.assert_called_once()
