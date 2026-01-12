"""
Unified OpenAI-compatible Gateway for LLM Serving Layer.

Provides endpoints for:
- Chat completions (/v1/chat/completions)
- Embeddings (/v1/embeddings)
- Reranking (/v1/rerank)
"""

from .models import (
    ChatCompletionChoice,
    # Chat models
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    EmbeddingData,
    # Embedding models
    EmbeddingRequest,
    EmbeddingResponse,
    ErrorResponse,
    # Rerank models
    RerankRequest,
    RerankResponse,
    RerankResult,
    # Common models
    Usage,
)

__all__ = [
    # Chat
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "ChatCompletionChoice",
    "ChatMessage",
    # Embedding
    "EmbeddingRequest",
    "EmbeddingResponse",
    "EmbeddingData",
    # Rerank
    "RerankRequest",
    "RerankResponse",
    "RerankResult",
    # Common
    "Usage",
    "ErrorResponse",
]
