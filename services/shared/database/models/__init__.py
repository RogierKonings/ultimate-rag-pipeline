"""
Database models package.
"""

from database.models.base import Base, TimestampMixin, SoftDeleteMixin
from database.models.document import Document, Chunk
from database.models.audit import AuditLog
from database.models.user import (
    Tenant,
    User,
    RoleModel,
    Group,
    UserRole,
    UserGroup,
    ApiKey,
)

__all__ = [
    # Base
    "Base",
    "TimestampMixin",
    "SoftDeleteMixin",
    # Documents
    "Document",
    "Chunk",
    # Audit
    "AuditLog",
    # User management
    "Tenant",
    "User",
    "RoleModel",
    "Group",
    "UserRole",
    "UserGroup",
    "ApiKey",
]
