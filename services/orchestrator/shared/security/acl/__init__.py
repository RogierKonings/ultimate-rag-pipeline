"""
Access Control List (ACL) module for the RAG Pipeline.

This module provides document-level access control with visibility levels,
group-based permissions, and integration with vector stores.
"""

from .filters import (
    ACLFilterBuilder,
    OpenSearchACLFilter,
    QdrantACLFilter,
    build_chunk_acl_payload,
)
from .models import (
    ACLEntry,
    ACLUpdateRequest,
    BulkACLUpdateRequest,
    DocumentACL,
    ShareRequest,
    Visibility,
)
from .service import (
    AccessDeniedError,
    ACLError,
    ACLService,
    DocumentNotFoundError,
)

__all__ = [
    # Models
    "Visibility",
    "ACLEntry",
    "DocumentACL",
    "ACLUpdateRequest",
    "ShareRequest",
    "BulkACLUpdateRequest",
    # Service
    "ACLService",
    "ACLError",
    "DocumentNotFoundError",
    "AccessDeniedError",
    # Filters
    "ACLFilterBuilder",
    "QdrantACLFilter",
    "OpenSearchACLFilter",
    "build_chunk_acl_payload",
]
