"""Redis cache module for embedding and query caching.

This module provides:
- RedisCache: Base async Redis client wrapper
- KeyBuilder: Namespaced key generation for multi-tenant isolation
- EmbeddingCache: Cache for computed embeddings (7-day TTL)
- QueryCache: Cache for query results (5-minute TTL)
"""

from .embedding_cache import EmbeddingCache
from .key_builder import KeyBuilder, KeyType, ServicePrefix
from .query_cache import QueryCache
from .redis_client import RedisCache

__all__ = [
    "RedisCache",
    "KeyBuilder",
    "ServicePrefix",
    "KeyType",
    "EmbeddingCache",
    "QueryCache",
]
