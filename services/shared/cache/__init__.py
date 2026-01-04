"""Redis cache module for embedding and query caching.

This module provides:
- RedisCache: Base async Redis client wrapper
- KeyBuilder: Namespaced key generation for multi-tenant isolation
- EmbeddingCache: Cache for computed embeddings (7-day TTL)
- QueryCache: Cache for query results (5-minute TTL)
"""

from .redis_client import RedisCache
from .key_builder import KeyBuilder, ServicePrefix, KeyType
from .embedding_cache import EmbeddingCache
from .query_cache import QueryCache

__all__ = [
    "RedisCache",
    "KeyBuilder",
    "ServicePrefix",
    "KeyType",
    "EmbeddingCache",
    "QueryCache",
]
