#!/usr/bin/env python3
"""Initialize Qdrant collections with optimized settings."""

import os
import sys

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    HnswConfigDiff,
    OptimizersConfigDiff,
    PayloadSchemaType,
    VectorParams,
)

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "documents")
EMBEDDING_DIM = 1024  # BGE-large-en-v1.5 dimension


def init_collection() -> bool:
    """Initialize the documents collection with optimized settings.

    Returns:
        True if collection was created, False if it already exists.
    """
    client = QdrantClient(url=QDRANT_URL)

    # Check if collection already exists
    if client.collection_exists(COLLECTION_NAME):
        print(f"Collection '{COLLECTION_NAME}' already exists")
        return False

    # Create collection with optimized HNSW settings
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=EMBEDDING_DIM,
            distance=Distance.COSINE,
            hnsw_config=HnswConfigDiff(
                m=16,  # Number of edges per node
                ef_construct=100,  # Build-time accuracy
                full_scan_threshold=10000,
                max_indexing_threads=0,  # Auto-detect
            ),
        ),
        optimizers_config=OptimizersConfigDiff(
            memmap_threshold=20000,
            indexing_threshold=20000,
            flush_interval_sec=5,
        ),
        on_disk_payload=True,  # Large payloads stored on disk
    )

    print(f"Collection '{COLLECTION_NAME}' created successfully")

    # Create payload indexes for efficient filtering
    indexes = [
        ("tenant_id", PayloadSchemaType.KEYWORD),
        ("document_id", PayloadSchemaType.KEYWORD),
        ("visibility", PayloadSchemaType.KEYWORD),
        ("allowed_groups", PayloadSchemaType.KEYWORD),
    ]

    for field_name, field_type in indexes:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field_name,
            field_schema=field_type,
        )
        print(f"  Created index for '{field_name}'")

    print(f"\nCollection '{COLLECTION_NAME}' initialized with {len(indexes)} indexes")
    return True


def get_collection_info() -> None:
    """Print collection information."""
    client = QdrantClient(url=QDRANT_URL)

    if not client.collection_exists(COLLECTION_NAME):
        print(f"Collection '{COLLECTION_NAME}' does not exist")
        return

    info = client.get_collection(COLLECTION_NAME)
    print(f"\nCollection: {COLLECTION_NAME}")
    print(f"  Status: {info.status.value}")
    print(f"  Points count: {info.points_count}")
    print(f"  Indexed vectors: {info.indexed_vectors_count}")
    print(f"  Vector size: {info.config.params.vectors.size}")
    print(f"  Distance: {info.config.params.vectors.distance.value}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--info":
        get_collection_info()
    else:
        init_collection()
        get_collection_info()
