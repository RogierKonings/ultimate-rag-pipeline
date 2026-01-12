"""
Dynamic batching layer for embedding requests.

This module implements request batching to optimize GPU utilization
by collecting multiple requests and processing them together.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

from ..api.models import BatchEmbeddingResult

logger = logging.getLogger(__name__)


@dataclass
class PendingRequest:
    """A pending embedding request in the queue."""

    request_id: UUID
    texts: list[str]
    input_type: str | None
    future: asyncio.Future
    timestamp: float


class DynamicBatcher:
    """
    Dynamic batching layer for embedding requests.

    Collects incoming requests and batches them together
    for efficient GPU utilization. Batches are processed
    when either max_batch_size is reached or timeout expires.
    """

    def __init__(
        self,
        embed_fn: Callable[[list[str], str | None], Awaitable[BatchEmbeddingResult]],
        max_batch_size: int = 32,
        max_batch_tokens: int = 8192,
        batch_timeout_ms: float = 50.0,
        max_queue_size: int = 1000,
    ):
        """
        Initialize the dynamic batcher.

        Args:
            embed_fn: Function to call for actual embedding generation
            max_batch_size: Maximum number of texts in a batch
            max_batch_tokens: Maximum tokens in a batch
            batch_timeout_ms: Maximum time to wait for batch to fill
            max_queue_size: Maximum queue size
        """
        self.embed_fn = embed_fn
        self.max_batch_size = max_batch_size
        self.max_batch_tokens = max_batch_tokens
        self.batch_timeout = batch_timeout_ms / 1000.0
        self.max_queue_size = max_queue_size

        self._queue: asyncio.Queue[PendingRequest] = asyncio.Queue(maxsize=max_queue_size)
        self._processing_task: asyncio.Task | None = None
        self._running = False

        # Metrics
        self._requests_processed = 0
        self._batches_processed = 0
        self._total_wait_time_ms = 0.0

    async def start(self) -> None:
        """Start the batching processor."""
        self._running = True
        self._processing_task = asyncio.create_task(self._process_loop())
        logger.info("Dynamic batcher started")

    async def stop(self) -> None:
        """Stop the batching processor."""
        self._running = False
        if self._processing_task:
            self._processing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._processing_task
        logger.info("Dynamic batcher stopped")

    async def submit(
        self,
        texts: list[str],
        input_type: str | None = None,
    ) -> list[list[float]]:
        """
        Submit texts for embedding.

        Args:
            texts: List of texts to embed
            input_type: "query" or "passage" prefix

        Returns:
            List of embeddings
        """
        future: asyncio.Future[list[list[float]]] = asyncio.get_event_loop().create_future()

        request = PendingRequest(
            request_id=uuid4(),
            texts=texts,
            input_type=input_type,
            future=future,
            timestamp=time.time(),
        )

        await self._queue.put(request)

        return await future

    async def _process_loop(self) -> None:
        """Main processing loop."""
        while self._running:
            try:
                batch = await self._collect_batch()

                if batch:
                    await self._process_batch(batch)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in processing loop: {e}")

    async def _collect_batch(self) -> list[PendingRequest]:
        """Collect requests into a batch."""
        batch: list[PendingRequest] = []
        total_texts = 0
        total_tokens = 0
        batch_input_type: str | None = None

        deadline = time.time() + self.batch_timeout

        while True:
            try:
                timeout = max(0, deadline - time.time())
                request = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=timeout if batch else None,  # Wait indefinitely for first request
                )

                # Estimate tokens
                request_tokens = sum(len(t.split()) for t in request.texts)

                # Check if adding this request would exceed limits
                if batch and (
                    total_texts + len(request.texts) > self.max_batch_size or
                    total_tokens + request_tokens > self.max_batch_tokens or
                    (batch_input_type is not None and request.input_type != batch_input_type)
                ):
                    # Put request back and process current batch
                    await self._queue.put(request)
                    break

                batch.append(request)
                total_texts += len(request.texts)
                total_tokens += request_tokens
                batch_input_type = request.input_type

                # Check if batch is full
                if total_texts >= self.max_batch_size:
                    break

            except TimeoutError:
                # Timeout expired, process what we have
                break

        return batch

    async def _process_batch(self, batch: list[PendingRequest]) -> None:
        """Process a collected batch."""
        if not batch:
            return

        # Combine all texts
        all_texts: list[str] = []
        text_counts: list[int] = []
        input_type = batch[0].input_type

        for request in batch:
            all_texts.extend(request.texts)
            text_counts.append(len(request.texts))

        try:
            # Generate embeddings
            result = await self.embed_fn(all_texts, input_type)

            # Distribute results back to requests
            offset = 0
            for request, count in zip(batch, text_counts, strict=True):
                request_embeddings = result.embeddings[offset:offset + count]
                request.future.set_result(request_embeddings)
                offset += count

                # Update metrics
                wait_time = (time.time() - request.timestamp) * 1000
                self._total_wait_time_ms += wait_time
                self._requests_processed += 1

            self._batches_processed += 1

        except Exception as e:
            # Propagate error to all requests
            for request in batch:
                if not request.future.done():
                    request.future.set_exception(e)

    def get_metrics(self) -> dict:
        """Get batcher metrics."""
        return {
            "queue_size": self._queue.qsize(),
            "requests_processed": self._requests_processed,
            "batches_processed": self._batches_processed,
            "avg_wait_time_ms": (
                self._total_wait_time_ms / self._requests_processed
                if self._requests_processed > 0 else 0
            ),
        }
