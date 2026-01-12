"""Redis key builder for namespaced key generation."""

import hashlib
from enum import Enum


class ServicePrefix(str, Enum):
    """Service prefixes for key namespacing."""

    INGESTION = "ing"
    RETRIEVAL = "ret"
    ORCHESTRATOR = "orc"
    CELERY = "cel"


class KeyType(str, Enum):
    """Key types for data classification."""

    EMBEDDING = "emb"
    QUERY = "query"
    SESSION = "sess"
    JOB = "job"
    LOCK = "lock"


class KeyBuilder:
    """Build namespaced Redis keys to prevent collisions.

    Key format: {service}:{type}:{tenant}:{identifier}

    Examples:
        - ing:emb:tenant-123:abc123def456 (embeddings during ingestion)
        - ret:query:tenant-123:hash789... (cached query results)
        - cel:job:*:job-uuid (Celery job metadata, global)
    """

    def __init__(self, service: ServicePrefix):
        """Initialize key builder for a service.

        Args:
            service: The service prefix to use for all keys.
        """
        self.service = service

    def build(
        self,
        key_type: KeyType,
        tenant_id: str,
        identifier: str,
    ) -> str:
        """Build a fully namespaced Redis key.

        Args:
            key_type: Type of data being cached.
            tenant_id: Tenant ID for isolation.
            identifier: Unique identifier for the cached item.

        Returns:
            Namespaced Redis key.
        """
        return f"{self.service}:{key_type}:{tenant_id}:{identifier}"

    def build_global(self, key_type: KeyType, identifier: str) -> str:
        """Build a global key (no tenant isolation).

        Args:
            key_type: Type of data being cached.
            identifier: Unique identifier for the cached item.

        Returns:
            Global namespaced Redis key.
        """
        return f"{self.service}:{key_type}:*:{identifier}"

    def pattern(self, key_type: KeyType, tenant_id: str = "*") -> str:
        """Build a pattern for scanning keys.

        Args:
            key_type: Type of data to match.
            tenant_id: Tenant ID to match, or "*" for all tenants.

        Returns:
            Redis key pattern for SCAN operations.
        """
        return f"{self.service}:{key_type}:{tenant_id}:*"

    @staticmethod
    def hash_content(*args) -> str:
        """Generate a hash from content for use as identifier.

        Args:
            *args: Content to hash.

        Returns:
            32-character SHA256 hash.
        """
        content = ":".join(str(arg) for arg in args)
        return hashlib.sha256(content.encode()).hexdigest()[:32]
