#!/usr/bin/env python3
"""Initialize OpenSearch index with custom analyzers for BM25 keyword search."""

import os
import sys

from opensearchpy import OpenSearch

OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
INDEX_NAME = os.getenv("OPENSEARCH_INDEX", "documents")


def get_client() -> OpenSearch:
    """Create OpenSearch client."""
    return OpenSearch(
        hosts=[OPENSEARCH_URL],
        http_compress=True,
        timeout=30,
    )


# Index template with custom analyzers for English text
INDEX_TEMPLATE = {
    "settings": {
        "number_of_shards": 3,
        "number_of_replicas": 1,
        "analysis": {
            "analyzer": {
                "default": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "english_stemmer", "english_stop"],
                },
                "keyword_analyzer": {
                    "type": "custom",
                    "tokenizer": "keyword",
                    "filter": ["lowercase"],
                },
            },
            "filter": {
                "english_stemmer": {
                    "type": "stemmer",
                    "language": "english",
                },
                "english_stop": {
                    "type": "stop",
                    "stopwords": "_english_",
                },
            },
        },
    },
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "document_id": {"type": "keyword"},
            "content": {
                "type": "text",
                "analyzer": "default",
                "search_analyzer": "default",
            },
            "title": {
                "type": "text",
                "analyzer": "default",
                "fields": {"keyword": {"type": "keyword"}},
            },
            "source_type": {"type": "keyword"},
            "tenant_id": {"type": "keyword"},
            "visibility": {"type": "keyword"},
            "allowed_groups": {"type": "keyword"},
            "metadata": {"type": "object", "enabled": True},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    },
}


def init_index() -> bool:
    """Initialize the documents index with custom analyzers.

    Returns:
        True if index was created, False if it already exists.
    """
    client = get_client()

    # Check if index already exists
    if client.indices.exists(index=INDEX_NAME):
        print(f"Index '{INDEX_NAME}' already exists")
        return False

    # Create index with custom analyzers
    client.indices.create(index=INDEX_NAME, body=INDEX_TEMPLATE)
    print(f"Index '{INDEX_NAME}' created successfully")
    return True


def get_index_info() -> None:
    """Print index information."""
    client = get_client()

    if not client.indices.exists(index=INDEX_NAME):
        print(f"Index '{INDEX_NAME}' does not exist")
        return

    # Get index mapping
    mapping = client.indices.get_mapping(index=INDEX_NAME)
    print(f"\nIndex: {INDEX_NAME}")
    print(f"  Properties: {list(mapping[INDEX_NAME]['mappings']['properties'].keys())}")

    # Get cluster health
    health = client.cluster.health()
    print(f"\nCluster Health:")
    print(f"  Status: {health['status']}")
    print(f"  Number of nodes: {health['number_of_nodes']}")
    print(f"  Active shards: {health['active_shards']}")


def delete_index() -> bool:
    """Delete the index (for testing/reset purposes).

    Returns:
        True if index was deleted, False if it didn't exist.
    """
    client = get_client()

    if not client.indices.exists(index=INDEX_NAME):
        print(f"Index '{INDEX_NAME}' does not exist")
        return False

    client.indices.delete(index=INDEX_NAME)
    print(f"Index '{INDEX_NAME}' deleted successfully")
    return True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--info":
            get_index_info()
        elif sys.argv[1] == "--delete":
            delete_index()
        else:
            print(f"Unknown argument: {sys.argv[1]}")
            print("Usage: python init-opensearch-index.py [--info|--delete]")
            sys.exit(1)
    else:
        init_index()
        get_index_info()
