"""
Core reranking service using cross-encoder models.

This module provides high-throughput document reranking with GPU acceleration.
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from ..api.models import (
    DocumentPair,
    HealthResponse,
    RerankResponse,
    ScoredDocument,
)

logger = logging.getLogger(__name__)


class RerankerService:
    """
    Core reranking service using cross-encoder models.

    Cross-encoders process query and document together through
    a transformer, producing a relevance score. More accurate
    than bi-encoder (embedding) similarity but slower.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        model_revision: str | None = None,
        max_sequence_length: int = 512,
        device: str = "cuda",
        use_fp16: bool = True,
        normalize_scores: bool = False,
        max_batch_size: int = 32,
        worker_count: int = 1,
    ):
        """
        Initialize the reranker service.

        Args:
            model_name: HuggingFace model ID
            model_revision: Optional model revision
            max_sequence_length: Maximum sequence length for tokenization
            device: Device to run on (cuda or cpu)
            use_fp16: Whether to use FP16 inference
            normalize_scores: Whether to apply sigmoid to scores
            max_batch_size: Maximum batch size for inference
            worker_count: Number of worker threads
        """
        self.model_name = model_name
        self.model_revision = model_revision
        self.max_sequence_length = max_sequence_length
        self.device = device
        self.use_fp16 = use_fp16
        self.normalize_scores = normalize_scores
        self.max_batch_size = max_batch_size

        self._model = None
        self._tokenizer = None
        self._actual_device: torch.device | None = None
        self._executor = ThreadPoolExecutor(max_workers=worker_count)
        self._startup_time = time.time()

    async def load_model(self) -> None:
        """Load the reranker model and tokenizer."""
        logger.info(f"Loading reranker model: {self.model_name}")

        def _load():
            tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                revision=self.model_revision,
            )

            model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name,
                revision=self.model_revision,
            )

            # Determine actual device
            actual_device = self.device
            if self.device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA not available, falling back to CPU")
                actual_device = "cpu"

            device = torch.device(actual_device)
            model = model.to(device)
            model.eval()

            # Enable FP16 if configured and on CUDA
            if self.use_fp16 and device.type == "cuda":
                model = model.half()

            return tokenizer, model, device

        loop = asyncio.get_event_loop()
        self._tokenizer, self._model, self._actual_device = await loop.run_in_executor(
            self._executor, _load,
        )

        logger.info(f"Reranker model loaded on {self._actual_device}")

    async def rerank(
        self,
        query: str,
        documents: list[str],
        doc_ids: list[str] | None = None,
        top_k: int | None = None,
        min_score: float | None = None,
        return_documents: bool = True,
    ) -> RerankResponse:
        """
        Rerank documents for a query.

        Args:
            query: The search query
            documents: List of documents to rerank
            doc_ids: Optional document IDs
            top_k: Return only top K results
            min_score: Minimum score threshold
            return_documents: Include document text in response

        Returns:
            RerankResponse with scored and sorted documents
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        start_time = time.time()

        # Score all pairs
        scores = await self._score_pairs(query, documents)

        # Build results with indices
        results = []
        for i, (score, doc) in enumerate(zip(scores, documents, strict=True)):
            doc_id = doc_ids[i] if doc_ids else None

            results.append(ScoredDocument(
                index=i,
                score=float(score),
                document=doc if return_documents else None,
                doc_id=doc_id,
            ))

        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)

        # Apply min_score filter
        if min_score is not None:
            results = [r for r in results if r.score >= min_score]

        # Apply top_k limit
        if top_k is not None:
            results = results[:top_k]

        processing_time = (time.time() - start_time) * 1000

        # Estimate token usage
        total_tokens = sum(len(query.split()) + len(d.split()) for d in documents)

        return RerankResponse(
            model=self.model_name,
            results=results,
            usage={
                "prompt_tokens": total_tokens,
                "total_tokens": total_tokens,
            },
            processing_time_ms=processing_time,
        )

    async def rerank_pairs(
        self,
        pairs: list[DocumentPair],
        top_k: int | None = None,
        min_score: float | None = None,
        return_documents: bool = True,
    ) -> RerankResponse:
        """
        Rerank pre-formed query-document pairs.

        Useful when each document has a different query
        or for multi-query scenarios.
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        start_time = time.time()

        # Extract queries and documents
        queries = [p.query for p in pairs]
        documents = [p.document for p in pairs]

        # Score all pairs
        scores = await self._score_pairs_batch(queries, documents)

        # Build results
        results = []
        for i, (pair, score) in enumerate(zip(pairs, scores, strict=True)):
            results.append(ScoredDocument(
                index=i,
                score=float(score),
                document=pair.document if return_documents else None,
                doc_id=pair.doc_id,
                metadata=pair.metadata,
            ))

        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)

        # Apply filters
        if min_score is not None:
            results = [r for r in results if r.score >= min_score]

        if top_k is not None:
            results = results[:top_k]

        processing_time = (time.time() - start_time) * 1000

        return RerankResponse(
            model=self.model_name,
            results=results,
            usage={
                "prompt_tokens": sum(len(q.split()) + len(d.split()) for q, d in zip(queries, documents, strict=True)),
                "total_tokens": sum(len(q.split()) + len(d.split()) for q, d in zip(queries, documents, strict=True)),
            },
            processing_time_ms=processing_time,
        )

    async def _score_pairs(
        self,
        query: str,
        documents: list[str],
    ) -> list[float]:
        """Score a single query against multiple documents."""
        queries = [query] * len(documents)
        return await self._score_pairs_batch(queries, documents)

    async def _score_pairs_batch(
        self,
        queries: list[str],
        documents: list[str],
    ) -> list[float]:
        """Score multiple query-document pairs."""
        if not queries:
            return []

        loop = asyncio.get_event_loop()
        all_scores: list[float] = []

        # Process in batches
        for i in range(0, len(queries), self.max_batch_size):
            batch_queries = queries[i:i + self.max_batch_size]
            batch_docs = documents[i:i + self.max_batch_size]

            def _score(q_batch=batch_queries, d_batch=batch_docs):
                # Tokenize pairs
                inputs = self._tokenizer(
                    q_batch,
                    d_batch,
                    padding=True,
                    truncation=True,
                    max_length=self.max_sequence_length,
                    return_tensors="pt",
                )

                # Move to device
                inputs = {k: v.to(self._actual_device) for k, v in inputs.items()}

                # Run inference
                with torch.no_grad():
                    outputs = self._model(**inputs)

                    # Get logits (relevance scores)
                    logits = outputs.logits

                    if self.normalize_scores:
                        # Apply sigmoid to normalize to [0, 1]
                        scores = torch.sigmoid(logits).squeeze(-1)
                    else:
                        # Return raw logits
                        scores = logits.squeeze(-1)

                    # Handle single element case
                    if scores.dim() == 0:
                        return [scores.cpu().item()]
                    return scores.cpu().numpy().tolist()

            batch_scores = await loop.run_in_executor(self._executor, _score)
            all_scores.extend(batch_scores)

        return all_scores

    def get_health(self) -> HealthResponse:
        """Get service health status."""
        gpu_available = torch.cuda.is_available()
        gpu_memory = None

        if gpu_available and self._actual_device and self._actual_device.type == "cuda":
            gpu_memory = torch.cuda.memory_allocated() / 1024 / 1024

        return HealthResponse(
            status="healthy" if self._model is not None else "unhealthy",
            model_loaded=self._model is not None,
            model_name=self.model_name,
            device=str(self._actual_device) if self._actual_device else "unknown",
            gpu_available=gpu_available,
            gpu_memory_used_mb=gpu_memory,
            queue_size=0,
            uptime_seconds=time.time() - self._startup_time,
        )

    async def close(self) -> None:
        """Cleanup resources."""
        self._executor.shutdown(wait=True)
        if self._model is not None:
            del self._model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
