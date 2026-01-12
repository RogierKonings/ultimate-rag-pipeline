"""Ingestion event logging to PostgreSQL (US-2.12).

This module provides async batch writing of ingestion events to the retrieval_logs
table for downstream evaluation and debugging. Events are buffered and written
in batches to avoid blocking the ingestion pipeline.

Usage:
    from services.ingestion_logs import get_ingestion_log_writer, IngestionLogEntry

    # Get the singleton writer instance
    writer = get_ingestion_log_writer()

    # Start the writer (at application startup)
    await writer.start()

    # Log events
    entry = IngestionLogEntry(
        tenant_id=tenant_id,
        event_type="document_ingested",
        document_id=doc_id,
        job_id=job_id,
        chunk_count=10,
        latency_ms=150,
        metadata={"source_type": "file"},
    )
    await writer.log(entry)

    # Stop the writer (at application shutdown)
    await writer.stop()
"""

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession
from telemetry import get_current_trace_context

logger = logging.getLogger(__name__)

# Singleton instance
_writer_instance: Optional["IngestionLogWriter"] = None


@dataclass
class IngestionLogEntry:
    """Ingestion log entry for persistence to retrieval_logs table.

    Attributes:
        tenant_id: Tenant identifier (required).
        event_type: Type of event (e.g., "document_ingested", "chunk_created").
        timestamp: Event timestamp (defaults to now).
        document_id: Optional document identifier.
        job_id: Optional job identifier.
        chunk_count: Number of chunks created (for document ingestion events).
        latency_ms: Operation latency in milliseconds.
        metadata: Additional event-specific metadata.
        trace_id: OpenTelemetry trace ID (auto-captured if not provided).
        span_id: OpenTelemetry span ID (auto-captured if not provided).
    """

    tenant_id: uuid.UUID
    event_type: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    document_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    chunk_count: int = 0
    latency_ms: int | None = None
    metadata: dict[str, Any] | None = None
    trace_id: str | None = None
    span_id: str | None = None

    def __post_init__(self):
        """Capture trace context if not provided."""
        if self.trace_id is None or self.span_id is None:
            trace_context = get_current_trace_context()
            if self.trace_id is None:
                self.trace_id = trace_context.get("trace_id")
            if self.span_id is None:
                self.span_id = trace_context.get("span_id")


class IngestionLogWriter:
    """Async batch writer for ingestion logs to PostgreSQL.

    This writer buffers log entries and flushes them in batches to avoid
    blocking the ingestion pipeline. It supports:
    - Configurable batch size and flush interval
    - Background periodic flushing
    - Graceful shutdown with final flush
    - Error handling with retry capability

    Attributes:
        batch_size: Maximum entries before triggering a flush.
        flush_interval: Seconds between periodic flushes.
    """

    def __init__(
        self,
        batch_size: int = 100,
        flush_interval: float = 5.0,
        session_factory: Any | None = None,
    ):
        """Initialize the ingestion log writer.

        Args:
            batch_size: Maximum entries to buffer before flushing (default: 100).
            flush_interval: Seconds between periodic flushes (default: 5.0).
            session_factory: Optional SQLAlchemy session factory. If not provided,
                uses the default from shared.database.connection.
        """
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._session_factory = session_factory
        self._buffer: list[IngestionLogEntry] = []
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._running = False
        self._flush_errors: int = 0
        self._total_flushed: int = 0

    @property
    def buffer_size(self) -> int:
        """Current number of entries in the buffer."""
        return len(self._buffer)

    @property
    def total_flushed(self) -> int:
        """Total number of entries successfully flushed."""
        return self._total_flushed

    @property
    def flush_errors(self) -> int:
        """Total number of flush errors encountered."""
        return self._flush_errors

    async def start(self) -> None:
        """Start the background flush task.

        Call this at application startup to enable periodic flushing.
        """
        if self._running:
            logger.warning("IngestionLogWriter already running")
            return

        self._running = True
        self._flush_task = asyncio.create_task(self._periodic_flush())
        logger.info(
            "IngestionLogWriter started",
            extra={
                "batch_size": self.batch_size,
                "flush_interval": self.flush_interval,
            },
        )

    async def stop(self) -> None:
        """Stop the writer and flush remaining entries.

        Call this at application shutdown to ensure all buffered
        entries are persisted.
        """
        self._running = False

        if self._flush_task:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
            self._flush_task = None

        # Final flush
        await self._flush()
        logger.info(
            "IngestionLogWriter stopped",
            extra={
                "total_flushed": self._total_flushed,
                "flush_errors": self._flush_errors,
            },
        )

    async def log(self, entry: IngestionLogEntry) -> None:
        """Add a log entry to the buffer.

        If the buffer reaches batch_size, triggers an immediate flush.

        Args:
            entry: The ingestion log entry to persist.
        """
        entries_to_flush: list[IngestionLogEntry] = []
        async with self._lock:
            self._buffer.append(entry)
            if len(self._buffer) >= self.batch_size:
                # Release lock before flushing to avoid blocking other log calls
                entries_to_flush = self._buffer
                self._buffer = []

        # Flush outside the lock if batch size reached
        if entries_to_flush:
            await self._flush_entries(entries_to_flush)

    async def log_event(
        self,
        tenant_id: uuid.UUID,
        event_type: str,
        document_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
        chunk_count: int = 0,
        latency_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Convenience method to log an event without creating an entry object.

        Args:
            tenant_id: Tenant identifier.
            event_type: Type of event.
            document_id: Optional document identifier.
            job_id: Optional job identifier.
            chunk_count: Number of chunks created.
            latency_ms: Operation latency in milliseconds.
            metadata: Additional event-specific metadata.
        """
        entry = IngestionLogEntry(
            tenant_id=tenant_id,
            event_type=event_type,
            document_id=document_id,
            job_id=job_id,
            chunk_count=chunk_count,
            latency_ms=latency_ms,
            metadata=metadata,
        )
        await self.log(entry)

    async def _periodic_flush(self) -> None:
        """Background task that periodically flushes the buffer."""
        while self._running:
            try:
                await asyncio.sleep(self.flush_interval)
                await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic flush: {e}")

    async def _flush(self) -> None:
        """Flush all buffered entries to the database."""
        async with self._lock:
            if not self._buffer:
                return

            entries = self._buffer
            self._buffer = []

        await self._flush_entries(entries)

    async def _flush_entries(self, entries: list[IngestionLogEntry]) -> None:
        """Flush a list of entries to the database.

        Args:
            entries: List of entries to persist.
        """
        if not entries:
            return

        try:
            await self._bulk_insert(entries)
            self._total_flushed += len(entries)
            logger.debug(f"Flushed {len(entries)} ingestion log entries")
        except Exception as e:
            self._flush_errors += 1
            logger.error(
                f"Failed to flush ingestion logs: {e}",
                extra={"entry_count": len(entries)},
            )
            # Re-add entries to buffer for retry (up to a limit)
            if self._flush_errors < 10:
                async with self._lock:
                    self._buffer = entries + self._buffer
            else:
                logger.error(
                    f"Dropping {len(entries)} entries after too many flush errors",
                )

    async def _bulk_insert(self, entries: list[IngestionLogEntry]) -> None:
        """Bulk insert entries into the retrieval_logs table.

        Args:
            entries: List of entries to insert.
        """
        # Import here to avoid circular imports
        from shared.database.models.jobs import RetrievalLog

        # Get session factory
        if self._session_factory is None:
            from shared.database.connection import get_session_factory

            self._session_factory = get_session_factory()

        session: AsyncSession = self._session_factory()
        try:
            # Prepare insert values
            values = []
            for entry in entries:
                values.append(
                    {
                        "id": uuid.uuid4(),
                        "tenant_id": entry.tenant_id,
                        "query": entry.event_type,  # Use query field for event description
                        "event_type": entry.event_type,
                        "document_id": entry.document_id,
                        "job_id": entry.job_id,
                        "latency_ms": entry.latency_ms,
                        "trace_id": entry.trace_id,
                        "span_id": entry.span_id,
                        "event_metadata": {
                            "chunk_count": entry.chunk_count,
                            **(entry.metadata or {}),
                        },
                        "created_at": entry.timestamp,
                    },
                )

            # Bulk insert
            stmt = insert(RetrievalLog).values(values)
            await session.execute(stmt)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_ingestion_log_writer(
    batch_size: int = 100,
    flush_interval: float = 5.0,
) -> IngestionLogWriter:
    """Get or create the singleton IngestionLogWriter instance.

    This function provides a singleton pattern for the log writer to ensure
    all ingestion events go through a single buffer.

    Args:
        batch_size: Maximum entries before triggering a flush (default: 100).
        flush_interval: Seconds between periodic flushes (default: 5.0).

    Returns:
        The singleton IngestionLogWriter instance.
    """
    global _writer_instance
    if _writer_instance is None:
        _writer_instance = IngestionLogWriter(
            batch_size=batch_size,
            flush_interval=flush_interval,
        )
    return _writer_instance


def reset_ingestion_log_writer() -> None:
    """Reset the singleton writer instance.

    This is primarily useful for testing.
    """
    global _writer_instance
    _writer_instance = None
