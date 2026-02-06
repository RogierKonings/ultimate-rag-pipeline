"""SQLAlchemy event listeners for database models.

This module contains event listeners that trigger side effects when
model state changes, such as propagating soft-deletes to external stores.
"""

from typing import TYPE_CHECKING

import structlog
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import get_history

if TYPE_CHECKING:
    from .models.document import Document

logger = structlog.get_logger(__name__)


def _on_document_soft_delete(session: Session, document: "Document") -> None:
    """Enqueue tombstone task after document soft-delete is committed.

    This function is called after the session commits the status change
    to 'deleted'. It enqueues a Celery task to propagate the deletion
    to Qdrant and OpenSearch.

    Args:
        session: The SQLAlchemy session (unused, required by event signature).
        document: The document that was soft-deleted.
    """
    try:
        # Import here to avoid circular dependency
        from tasks.tombstone import propagate_deletion

        logger.info(
            "Enqueueing deletion propagation task",
            extra={
                "document_id": str(document.id),
                "tenant_id": str(document.tenant_id),
            },
        )

        propagate_deletion.delay(
            document_id=str(document.id),
            tenant_id=str(document.tenant_id),
        )
    except ImportError:
        # Tasks module not available (e.g., during migrations)
        logger.warning(
            "Could not import tombstone task - deletion propagation skipped",
            extra={"document_id": str(document.id)},
        )
    except Exception as e:
        # Don't let task enqueueing failures block the transaction
        logger.error(
            "Failed to enqueue deletion propagation task",
            extra={
                "document_id": str(document.id),
                "error": str(e),
            },
        )


def register_document_events() -> None:
    """Register SQLAlchemy event listeners for Document model.

    This function should be called once during application startup
    to set up event listeners for soft-delete propagation.
    """
    from .models.document import Document

    @event.listens_for(Document, "after_update")
    def on_document_update(mapper, connection, target: Document) -> None:
        """Check if document was soft-deleted and trigger propagation."""
        # Check if status changed to 'deleted'
        status_history = get_history(target, "status")

        if status_history.has_changes():
            old_status = status_history.deleted[0] if status_history.deleted else None
            new_status = status_history.added[0] if status_history.added else None

            if old_status != "deleted" and new_status == "deleted":
                # Register a callback to run after commit
                # This ensures the deletion is persisted before we propagate
                @event.listens_for(
                    Session.object_session(target),
                    "after_commit",
                    once=True,
                )
                def after_commit(session: Session) -> None:
                    _on_document_soft_delete(session, target)

    logger.info("Document soft-delete event listeners registered")


# Auto-register events when this module is imported
# This is safe because the event listener registration is idempotent
_events_registered = False


def ensure_events_registered() -> None:
    """Ensure event listeners are registered (idempotent)."""
    global _events_registered
    if not _events_registered:
        register_document_events()
        _events_registered = True
