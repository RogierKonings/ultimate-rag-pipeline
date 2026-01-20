"""
Database models package.
"""

from database.models.audit import AuditLog
from database.models.base import Base, SoftDeleteMixin, TimestampMixin
from database.models.document import Chunk, Document, IndexStatus
from database.models.feedback import QueryFeedback
from database.models.usage import TenantQuota, TokenUsage
from database.models.user import (
    ApiKey,
    Group,
    RoleModel,
    Tenant,
    User,
    UserGroup,
    UserRole,
)
from database.models.verification_log import VerificationLog
from database.models.video import (
    ProcessingStage,
    SourceVideo,
    VideoKeyframe,
    VideoStatus,
    VideoTranscript,
)

__all__ = [
    # Base
    "Base",
    "TimestampMixin",
    "SoftDeleteMixin",
    # Documents
    "Document",
    "Chunk",
    "IndexStatus",
    # Videos
    "SourceVideo",
    "VideoTranscript",
    "VideoKeyframe",
    "VideoStatus",
    "ProcessingStage",
    # Audit
    "AuditLog",
    # Feedback (US-10.3.3)
    "QueryFeedback",
    # Verification (US-10.4.2)
    "VerificationLog",
    # User management
    "Tenant",
    "User",
    "RoleModel",
    "Group",
    "UserRole",
    "UserGroup",
    "ApiKey",
    # Usage tracking (US-10.5.4)
    "TokenUsage",
    "TenantQuota",
]
