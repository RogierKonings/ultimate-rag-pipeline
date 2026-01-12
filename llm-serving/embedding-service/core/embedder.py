"""
Core embedding service using sentence-transformers.

This module provides high-throughput embedding generation with GPU acceleration.
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import torch
from sentence_transformers import SentenceTransformer

from ..api.models import BatchEmbeddingResult, HealthResponse

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Core embedding generation service.

    Loads a sentence-transformers model and provides
    efficient batch embedding generation with GPU acceleration.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-large-en-v1.5",
        model_revision: str | None = None,
        embedding_dim: int = 1024,
        max_sequence_length: int = 512,
        device: str = "cuda",
        use_fp16: bool = True,
        normalize_embeddings: bool = True,
        max_batch_size: int = 32,
        worker_count: int = 1,
    ):
        """
        Initialize the embedding service.

        Args:
            model_name: HuggingFace model ID
            model_revision: Optional model revision
            embedding_dim: Expected embedding dimension
            max_sequence_length: Maximum sequence length for tokenization
            device: Device to run on (cuda or cpu)
            use_fp16: Whether to use FP16 inference
            normalize_embeddings: Whether to normalize embeddings
            max_batch_size: Maximum batch size for inference
            worker_count: Number of worker threads
        """
        self.model_name = model_name
        self.model_revision = model_revision
        self.embedding_dim = embedding_dim
        self.max_sequence_length = max_sequence_length
        self.device = device
        self.use_fp16 = use_fp16
        self.normalize_embeddings = normalize_embeddings
        self.max_batch_size = max_batch_size

        self._model: SentenceTransformer | None = None
        self._actual_device: str | None = None
        self._executor = ThreadPoolExecutor(max_workers=worker_count)
        self._lock = asyncio.Lock()
        self._startup_time = time.time()

    async def load_model(self) -> None:
        """Load the embedding model."""
        logger.info(f"Loading model: {self.model_name}")

        def _load() -> SentenceTransformer:
            # Determine actual device
            actual_device = self.device
            if self.device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA not available, falling back to CPU")
                actual_device = "cpu"

            model = SentenceTransformer(
                self.model_name,
                revision=self.model_revision,
                device=actual_device,
            )

            # Set max sequence length
            model.max_seq_length = self.max_sequence_length

            # Enable FP16 if configured and on CUDA
            if self.use_fp16 and actual_device == "cuda":
                model.half()

            return model

        loop = asyncio.get_event_loop()
        self._model = await loop.run_in_executor(self._executor, _load)
        self._actual_device = str(self._model.device)

        logger.info(f"Model loaded on {self._actual_device}")
        logger.info(f"Embedding dimension: {self.embedding_dim}")

    async def embed(
        self,
        texts: list[str],
        input_type: str | None = None,
    ) -> BatchEmbeddingResult:
        """
        Generate embeddings for a list of texts.

        Args:
            texts: List of texts to embed
            input_type: "query" or "passage" for BGE prefix

        Returns:
            BatchEmbeddingResult with embeddings and metadata
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        start_time = time.time()

        # Add BGE prefix if specified
        if input_type == "query":
            texts = [f"query: {t}" for t in texts]
        elif input_type == "passage":
            texts = [f"passage: {t}" for t in texts]

        # Run embedding in thread pool to avoid blocking
        def _embed():
            with torch.no_grad():
                return self._model.encode(
                    texts,
                    batch_size=self.max_batch_size,
                    normalize_embeddings=self.normalize_embeddings,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )

        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(self._executor, _embed)

        # Calculate approximate token count
        total_tokens = sum(len(t.split()) for t in texts)

        processing_time = (time.time() - start_time) * 1000

        return BatchEmbeddingResult(
            embeddings=embeddings.tolist(),
            dimensions=embeddings.shape[1],
            total_tokens=total_tokens,
            processing_time_ms=processing_time,
        )

    async def embed_single(
        self,
        text: str,
        input_type: str | None = None,
    ) -> list[float]:
        """Embed a single text."""
        result = await self.embed([text], input_type)
        return result.embeddings[0]

    def get_health(self) -> HealthResponse:
        """Get service health status."""
        gpu_available = torch.cuda.is_available()
        gpu_memory = None

        if gpu_available and self._actual_device and "cuda" in self._actual_device:
            gpu_memory = torch.cuda.memory_allocated() / 1024 / 1024

        return HealthResponse(
            status="healthy" if self._model is not None else "unhealthy",
            model_loaded=self._model is not None,
            model_name=self.model_name,
            embedding_dim=self.embedding_dim,
            device=self._actual_device or "unknown",
            gpu_available=gpu_available,
            gpu_memory_used_mb=gpu_memory,
            queue_size=0,  # Will be updated by batching layer
            uptime_seconds=time.time() - self._startup_time,
        )

    async def close(self) -> None:
        """Cleanup resources."""
        self._executor.shutdown(wait=True)
        if self._model is not None:
            del self._model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
