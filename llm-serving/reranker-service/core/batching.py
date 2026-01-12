"""
Dynamic batching for reranking requests.

This module implements request batching to optimize GPU utilization
by collecting multiple rerank requests and processing them together.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


@dataclass
class PendingRerankRequest:
    """A pending rerank request in the queue."""

    request_id: UUID
    queries: list[str]
    documents: list[str]
    future: asyncio.Future
    timestamp: float


class RerankBatcher:
    """
    Dynamic batching for reranking requests.

    Collects incoming pairs and batches them for
    efficient GPU utilization.
    """

    def __init__(
        self,
        score_fn: Callable[[list[str], list[str]], Awaitable[list[float]]],
        max_batch_size: int = 32,
        batch_timeout_ms: float = 50.0,
        max_queue_size: int = 1000,
    ):
        """
        Initialize the rerank batcher.

        Args:
            score_fn: Function to call for scoring pairs
            max_batch_size: Maximum number of pairs in a batch
            batch_timeout_ms: Maximum time to wait for batch to fill
            max_queue_size: Maximum queue size
        """
        self.score_fn = score_fn
        self.max_batch_size = max_batch_size
        self.batch_timeout = batch_timeout_ms / 1000.0
        self.max_queue_size = max_queue_size

        self._queue: asyncio.Queue[PendingRerankRequest] = asyncio.Queue(maxsize=max_queue_size)
        self._processing_task: asyncio.Task | None = None
        self._running = False

        # Metrics
        self._requests_processed = 0
        self._batches_processed = 0
        self._total_pairs_processed = 0

    async def start(self) -> None:
        """Start the batching processor."""
        self._running = True
        self._processing_task = asyncio.create_task(self._process_loop())
        logger.info("Rerank batcher started")

    async def stop(self) -> None:
        """Stop the batching processor."""
        self._running = False
        if self._processing_task:
            self._processing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._processing_task

    async def submit(
        self,
        queries: list[str],
        documents: list[str],
    ) -> list[float]:
        """
        Submit pairs for scoring.

        Args:
            queries: List of queries
            documents: List of documents (same length as queries)

        Returns:
            List of scores
        """
        future: asyncio.Future[list[float]] = asyncio.get_event_loop().create_future()

        request = PendingRerankRequest(
            request_id=uuid4(),
            queries=queries,
            documents=documents,
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
                logger.error(f"Error in rerank processing loop: {e}")

    async def _collect_batch(self) -> list[PendingRerankRequest]:
        """Collect requests into a batch."""
        batch: list[PendingRerankRequest] = []
        total_pairs = 0

        deadline = time.time() + self.batch_timeout

        while True:
            try:
                timeout = max(0, deadline - time.time())
                request = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=timeout if batch else None,
                )

                request_pairs = len(request.queries)

                # Check batch size limit
                if batch and total_pairs + request_pairs > self.max_batch_size:
                    await self._queue.put(request)
                    break

                batch.append(request)
                total_pairs += request_pairs

                if total_pairs >= self.max_batch_size:
                    break

            except TimeoutError:
                break

        return batch

    async def _process_batch(self, batch: list[PendingRerankRequest]) -> None:
        """Process a collected batch."""
        if not batch:
            return

        # Combine all pairs
        all_queries: list[str] = []
        all_documents: list[str] = []
        pair_counts: list[int] = []

        for request in batch:
            all_queries.extend(request.queries)
            all_documents.extend(request.documents)
            pair_counts.append(len(request.queries))

        try:
            # Score all pairs
            scores = await self.score_fn(all_queries, all_documents)

            # Distribute results
            offset = 0
            for request, count in zip(batch, pair_counts, strict=True):
                request_scores = scores[offset:offset + count]
                request.future.set_result(request_scores)
                offset += count

                self._requests_processed += 1

            self._batches_processed += 1
            self._total_pairs_processed += len(scores)

        except Exception as e:
            for request in batch:
                if not request.future.done():
                    request.future.set_exception(e)

    def get_metrics(self) -> dict:
        """Get batcher metrics."""
        return {
            "queue_size": self._queue.qsize(),
            "requests_processed": self._requests_processed,
            "batches_processed": self._batches_processed,
            "total_pairs_processed": self._total_pairs_processed,
        }
