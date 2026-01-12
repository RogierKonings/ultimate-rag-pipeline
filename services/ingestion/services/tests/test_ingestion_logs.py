"""
Tests for US-2.12: Ingestion event logging to PostgreSQL.

Verifies:
- IngestionLogEntry creation with trace context
- Async batch buffering and flushing
- Periodic flush background task
- Graceful shutdown with final flush
- Error handling and retry
- Bulk insert to retrieval_logs table
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from .. import ingestion_logs
from ..ingestion_logs import (
    IngestionLogEntry,
    IngestionLogWriter,
    get_ingestion_log_writer,
    reset_ingestion_log_writer,
)


class TestIngestionLogEntry:
    """Tests for IngestionLogEntry dataclass."""

    def test_entry_creates_with_required_fields(self):
        """Entry can be created with only required fields."""
        tenant_id = uuid4()
        entry = IngestionLogEntry(
            tenant_id=tenant_id,
            event_type="document_ingested",
        )

        assert entry.tenant_id == tenant_id
        assert entry.event_type == "document_ingested"
        assert entry.timestamp is not None
        assert entry.document_id is None
        assert entry.job_id is None
        assert entry.chunk_count == 0
        assert entry.latency_ms is None
        assert entry.metadata is None

    def test_entry_creates_with_all_fields(self):
        """Entry can be created with all optional fields."""
        tenant_id = uuid4()
        document_id = uuid4()
        job_id = uuid4()
        timestamp = datetime.now(UTC)
        metadata = {"source_type": "file", "file_size": 1024}

        entry = IngestionLogEntry(
            tenant_id=tenant_id,
            event_type="chunk_created",
            timestamp=timestamp,
            document_id=document_id,
            job_id=job_id,
            chunk_count=15,
            latency_ms=250,
            metadata=metadata,
            trace_id="abc123",
            span_id="def456",
        )

        assert entry.tenant_id == tenant_id
        assert entry.event_type == "chunk_created"
        assert entry.timestamp == timestamp
        assert entry.document_id == document_id
        assert entry.job_id == job_id
        assert entry.chunk_count == 15
        assert entry.latency_ms == 250
        assert entry.metadata == metadata
        assert entry.trace_id == "abc123"
        assert entry.span_id == "def456"

    def test_entry_captures_trace_context_automatically(self):
        """Entry captures OpenTelemetry trace context if not provided."""
        # Patch the function object directly in the module
        with patch.object(
            ingestion_logs,
            "get_current_trace_context",
            return_value={"trace_id": "auto_trace_123", "span_id": "auto_span_456"},
        ):
            entry = IngestionLogEntry(
                tenant_id=uuid4(),
                event_type="document_ingested",
            )

            assert entry.trace_id == "auto_trace_123"
            assert entry.span_id == "auto_span_456"

    def test_entry_uses_provided_trace_context_over_auto(self):
        """Provided trace context takes precedence over auto-captured."""
        with patch.object(
            ingestion_logs,
            "get_current_trace_context",
            return_value={"trace_id": "auto_trace", "span_id": "auto_span"},
        ):
            entry = IngestionLogEntry(
                tenant_id=uuid4(),
                event_type="document_ingested",
                trace_id="provided_trace",
                span_id="provided_span",
            )

            assert entry.trace_id == "provided_trace"
            assert entry.span_id == "provided_span"

    def test_entry_timestamp_defaults_to_now(self):
        """Timestamp defaults to current UTC time."""
        before = datetime.now(UTC)
        entry = IngestionLogEntry(
            tenant_id=uuid4(),
            event_type="test",
        )
        after = datetime.now(UTC)

        assert before <= entry.timestamp <= after


class TestIngestionLogWriterBuffering:
    """Tests for async batch buffering."""

    @pytest.fixture
    def writer(self):
        """Create a writer with test configuration."""
        return IngestionLogWriter(batch_size=5, flush_interval=10.0)

    @pytest.mark.asyncio
    async def test_log_adds_entry_to_buffer(self, writer):
        """Log adds entry to internal buffer."""
        entry = IngestionLogEntry(
            tenant_id=uuid4(),
            event_type="test_event",
        )

        # Mock flush to prevent actual DB calls
        writer._flush_entries = AsyncMock()

        await writer.log(entry)

        assert writer.buffer_size == 1

    @pytest.mark.asyncio
    async def test_log_triggers_flush_at_batch_size(self, writer):
        """Flush is triggered when buffer reaches batch_size."""
        writer._flush_entries = AsyncMock()

        # Add entries up to batch size
        for i in range(5):
            entry = IngestionLogEntry(
                tenant_id=uuid4(),
                event_type=f"event_{i}",
            )
            await writer.log(entry)

        # Flush should have been called
        writer._flush_entries.assert_called_once()
        # Buffer should be empty after flush
        assert writer.buffer_size == 0

    @pytest.mark.asyncio
    async def test_log_event_convenience_method(self, writer):
        """log_event creates entry and logs it."""
        writer._flush_entries = AsyncMock()
        tenant_id = uuid4()
        document_id = uuid4()

        await writer.log_event(
            tenant_id=tenant_id,
            event_type="document_ingested",
            document_id=document_id,
            chunk_count=10,
            latency_ms=100,
            metadata={"test": "value"},
        )

        assert writer.buffer_size == 1


class TestIngestionLogWriterLifecycle:
    """Tests for writer start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_background_task(self):
        """Start creates background flush task."""
        writer = IngestionLogWriter(batch_size=10, flush_interval=0.1)

        await writer.start()

        assert writer._running is True
        assert writer._flush_task is not None

        # Cleanup
        await writer.stop()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self):
        """Multiple start calls don't create multiple tasks."""
        writer = IngestionLogWriter(batch_size=10, flush_interval=1.0)

        await writer.start()
        task1 = writer._flush_task
        await writer.start()
        task2 = writer._flush_task

        assert task1 is task2

        # Cleanup
        await writer.stop()

    @pytest.mark.asyncio
    async def test_stop_flushes_remaining_entries(self):
        """Stop flushes any remaining buffered entries."""
        writer = IngestionLogWriter(batch_size=100, flush_interval=10.0)
        writer._bulk_insert = AsyncMock()

        await writer.start()

        # Add some entries without reaching batch size
        for i in range(3):
            await writer.log(
                IngestionLogEntry(tenant_id=uuid4(), event_type=f"event_{i}"),
            )

        assert writer.buffer_size == 3

        await writer.stop()

        # Buffer should be flushed
        writer._bulk_insert.assert_called_once()
        assert writer.buffer_size == 0
        assert writer._running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_background_task(self):
        """Stop cancels the periodic flush task."""
        writer = IngestionLogWriter(batch_size=100, flush_interval=10.0)
        writer._bulk_insert = AsyncMock()

        await writer.start()
        await writer.stop()

        assert writer._flush_task is None


class TestIngestionLogWriterPeriodicFlush:
    """Tests for periodic flush behavior."""

    @pytest.mark.asyncio
    async def test_periodic_flush_flushes_buffer(self):
        """Periodic flush empties the buffer."""
        writer = IngestionLogWriter(batch_size=100, flush_interval=0.05)
        writer._bulk_insert = AsyncMock()

        # Add entries
        for i in range(3):
            await writer.log(
                IngestionLogEntry(tenant_id=uuid4(), event_type=f"event_{i}"),
            )

        await writer.start()

        # Wait for periodic flush
        await asyncio.sleep(0.1)

        # Buffer should be flushed
        assert writer.buffer_size == 0
        writer._bulk_insert.assert_called()

        await writer.stop()


class TestIngestionLogWriterErrorHandling:
    """Tests for error handling and retry."""

    @pytest.mark.asyncio
    async def test_flush_error_increments_counter(self):
        """Flush errors increment the error counter."""
        writer = IngestionLogWriter(batch_size=100, flush_interval=10.0)
        writer._bulk_insert = AsyncMock(side_effect=Exception("DB Error"))

        # Add an entry
        await writer.log(IngestionLogEntry(tenant_id=uuid4(), event_type="test"))

        # Trigger flush
        await writer._flush()

        assert writer.flush_errors == 1

    @pytest.mark.asyncio
    async def test_flush_error_re_adds_entries_to_buffer(self):
        """Failed entries are re-added to buffer for retry."""
        writer = IngestionLogWriter(batch_size=100, flush_interval=10.0)
        writer._bulk_insert = AsyncMock(side_effect=Exception("DB Error"))

        # Add entries
        for i in range(3):
            await writer.log(
                IngestionLogEntry(tenant_id=uuid4(), event_type=f"event_{i}"),
            )

        # Trigger flush (will fail)
        await writer._flush()

        # Entries should be re-added
        assert writer.buffer_size == 3

    @pytest.mark.asyncio
    async def test_entries_dropped_after_max_errors(self):
        """Entries are dropped after too many consecutive errors."""
        writer = IngestionLogWriter(batch_size=100, flush_interval=10.0)
        writer._bulk_insert = AsyncMock(side_effect=Exception("DB Error"))
        writer._flush_errors = 10  # Already at max

        # Add entries
        for i in range(3):
            await writer.log(
                IngestionLogEntry(tenant_id=uuid4(), event_type=f"event_{i}"),
            )

        # Trigger flush (will fail and drop entries)
        await writer._flush()

        # Entries should be dropped, not re-added
        assert writer.buffer_size == 0


class TestIngestionLogWriterBulkInsert:
    """Tests for bulk insert functionality."""

    @pytest.mark.asyncio
    async def test_bulk_insert_creates_correct_values(self):
        """Bulk insert prepares correct values for retrieval_logs table."""
        # Create a mock session
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        mock_factory = MagicMock(return_value=mock_session)

        writer = IngestionLogWriter(
            batch_size=100,
            flush_interval=10.0,
            session_factory=mock_factory,
        )

        tenant_id = uuid4()
        document_id = uuid4()
        job_id = uuid4()

        entries = [
            IngestionLogEntry(
                tenant_id=tenant_id,
                event_type="document_ingested",
                document_id=document_id,
                job_id=job_id,
                chunk_count=10,
                latency_ms=150,
                metadata={"source_type": "file"},
                trace_id="trace123",
                span_id="span456",
            ),
        ]

        await writer._bulk_insert(entries)

        # Verify session was used correctly
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_bulk_insert_rollback_on_error(self):
        """Bulk insert rolls back on error."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("Insert failed"))
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        mock_factory = MagicMock(return_value=mock_session)

        writer = IngestionLogWriter(
            batch_size=100,
            flush_interval=10.0,
            session_factory=mock_factory,
        )

        entries = [
            IngestionLogEntry(tenant_id=uuid4(), event_type="test"),
        ]

        with pytest.raises(Exception, match="Insert failed"):
            await writer._bulk_insert(entries)

        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()


class TestIngestionLogWriterMetrics:
    """Tests for writer metrics."""

    @pytest.mark.asyncio
    async def test_total_flushed_tracks_successful_inserts(self):
        """Total flushed counter tracks successful inserts."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.close = AsyncMock()

        mock_factory = MagicMock(return_value=mock_session)

        writer = IngestionLogWriter(
            batch_size=2,
            flush_interval=10.0,
            session_factory=mock_factory,
        )

        # Add entries to trigger flush
        for i in range(2):
            await writer.log(
                IngestionLogEntry(tenant_id=uuid4(), event_type=f"event_{i}"),
            )

        assert writer.total_flushed == 2


class TestSingletonPattern:
    """Tests for singleton writer instance."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_ingestion_log_writer()

    def teardown_method(self):
        """Reset singleton after each test."""
        reset_ingestion_log_writer()

    def test_get_ingestion_log_writer_returns_singleton(self):
        """get_ingestion_log_writer returns same instance."""
        writer1 = get_ingestion_log_writer()
        writer2 = get_ingestion_log_writer()

        assert writer1 is writer2

    def test_reset_creates_new_instance(self):
        """reset_ingestion_log_writer allows creating new instance."""
        writer1 = get_ingestion_log_writer()
        reset_ingestion_log_writer()
        writer2 = get_ingestion_log_writer()

        assert writer1 is not writer2

    def test_get_ingestion_log_writer_uses_provided_config(self):
        """get_ingestion_log_writer uses provided batch_size and flush_interval."""
        writer = get_ingestion_log_writer(batch_size=50, flush_interval=2.0)

        assert writer.batch_size == 50
        assert writer.flush_interval == 2.0
