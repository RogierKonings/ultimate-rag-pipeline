"""
Access Control List (ACL) module for the RAG Pipeline.

This module provides document-level access control with visibility levels,
group-based permissions, and integration with vector stores.
"""

from .models import (
    Visibility,
    ACLEntry,
    DocumentACL,
    ACLUpdateRequest,
    ShareRequest,
    BulkACLUpdateRequest,
)
from .service import (
    ACLService,
    ACLError,
    DocumentNotFoundError,
    AccessDeniedError,
)
from .filters import (
    ACLFilterBuilder,
    QdrantACLFilter,
    OpenSearchACLFilter,
    build_chunk_acl_payload,
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
