"""Embedding service core module."""

from .batching import DynamicBatcher
from .embedder import EmbeddingService

__all__ = ["EmbeddingService", "DynamicBatcher"]
