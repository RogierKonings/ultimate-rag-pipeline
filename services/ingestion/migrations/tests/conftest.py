"""Pytest fixtures for migration tests."""

from datetime import datetime
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from qdrant_client import AsyncQdrantClient

from services.ingestion.migrations.collection_manager import CollectionManager
from services.ingestion.migrations.embedding_migrator import EmbeddingMigrator
from services.ingestion.migrations.models import (
    EmbeddingMigration,
    MigrationRequest,
    MigrationStatus,
)
from services.ingestion.migrations.progress_tracker import (
    MigrationProgressStore,
    MigrationProgressStoreConfig,
)


@pytest.fixture
def migration_id():
    """Generate a test migration ID."""
    return uuid4()


@pytest.fixture
def sample_migration(migration_id) -> EmbeddingMigration:
    """Create a sample migration for testing."""
    return EmbeddingMigration(
        migration_id=migration_id,
        source_model="BAAI/bge-large-en-v1.5",
        target_model="BAAI/bge-m3",
        source_dimensions=1024,
        target_dimensions=1024,
        source_collection="rag_chunks_v1",
        target_collection="rag_chunks_v2",
        alias_name="rag_chunks",
        status=MigrationStatus.PENDING,
        total_documents=1000,
        processed_documents=0,
        failed_documents=0,
    )


@pytest.fixture
def sample_migration_request() -> MigrationRequest:
    """Create a sample migration request for testing."""
    return MigrationRequest(
        target_model="BAAI/bge-m3",
        target_dimensions=1024,
        batch_size=100,
        max_concurrent_batches=4,
        validate_before_switch=True,
        auto_switch=False,
        preserve_source=True,
    )


@pytest.fixture
def mock_qdrant_client() -> AsyncMock:
    """Create a mock Qdrant client.

    Note: We don't use spec=AsyncQdrantClient because the spec enforcement
    in newer Python versions is stricter about async methods and can cause
    AttributeErrors when accessing methods that exist on the real client.
    """
    client = AsyncMock()

    # Mock get_collections
    collections_response = MagicMock()
    collections_response.collections = []
    client.get_collections.return_value = collections_response

    # Mock get_aliases
    aliases_response = MagicMock()
    aliases_response.aliases = []
    client.get_aliases.return_value = aliases_response

    # Mock create_collection
    client.create_collection.return_value = True

    # Mock create_payload_index
    client.create_payload_index.return_value = True

    # Mock update_collection_aliases
    client.update_collection_aliases.return_value = True

    # Mock delete_collection
    client.delete_collection.return_value = True

    # Mock get_collection
    collection_info = MagicMock()
    collection_info.vectors_count = 1000
    collection_info.points_count = 1000
    collection_info.status = MagicMock(value="green")
    collection_info.config = MagicMock()
    collection_info.config.params = MagicMock()
    collection_info.config.params.vectors = MagicMock()
    collection_info.config.params.vectors.size = 1024
    collection_info.config.params.vectors.distance = MagicMock(value="Cosine")
    client.get_collection.return_value = collection_info

    # Mock scroll
    client.scroll.return_value = ([], None)

    # Mock search
    client.search.return_value = []

    # Mock retrieve
    client.retrieve.return_value = []

    # Mock upsert
    client.upsert.return_value = True

    # Mock close
    client.close.return_value = None

    return client


@pytest.fixture
def mock_progress_store() -> AsyncMock:
    """Create a mock progress store."""
    store = AsyncMock(spec=MigrationProgressStore)

    store.connect.return_value = None
    store.disconnect.return_value = None
    store.save_migration.return_value = True
    store.get_migration.return_value = None
    store.delete_migration.return_value = True
    store.get_active_migrations.return_value = []
    store.update_progress.return_value = None
    store.update_status.return_value = None

    return store


@pytest.fixture
def collection_manager(mock_qdrant_client) -> CollectionManager:
    """Create a collection manager with mock client."""
    return CollectionManager(client=mock_qdrant_client)


@pytest.fixture
def migrator(mock_qdrant_client, mock_progress_store) -> EmbeddingMigrator:
    """Create a migrator with mock dependencies."""
    return EmbeddingMigrator(
        qdrant_client=mock_qdrant_client,
        progress_store=mock_progress_store,
    )


@pytest_asyncio.fixture
async def real_progress_store() -> AsyncGenerator[MigrationProgressStore, None]:
    """Create a real progress store connected to test Redis.

    This fixture requires a running Redis instance.
    Skip tests using this fixture if Redis is not available.
    """
    store = MigrationProgressStore(
        config=MigrationProgressStoreConfig(
            redis_url="redis://localhost:6379",
            key_prefix="test_migration:",
        )
    )

    try:
        await store.connect()
        yield store
    finally:
        # Cleanup test keys
        if store._client:
            async for key in store._client.scan_iter(match="test_migration:*"):
                await store._client.delete(key)
        await store.disconnect()
