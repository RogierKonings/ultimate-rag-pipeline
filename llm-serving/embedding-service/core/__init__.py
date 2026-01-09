"""Embedding service core module."""

from .embedder import EmbeddingService
from .batching import DynamicBatcher

__all__ = ["EmbeddingService", "DynamicBatcher"]
