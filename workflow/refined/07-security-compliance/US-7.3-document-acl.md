# US-7.3: Document ACL

> **Epic:** Security & Compliance  
> **Priority:** High  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-7.1 (JWT Authentication), US-7.2 (Authorization & RBAC)

## User Story

**As a** developer  
**I want** document-level access control  
**So that** users only see documents they are permitted to access

## Objective

Implement fine-grained Access Control Lists (ACLs) for documents, enabling visibility levels (public, private, group), ACL inheritance for chunks, ACL filtering in vector/keyword searches, and an ACL management API.

## Architecture Reference

- **ACL Model:** Document → visibility + allowed_users + allowed_groups
- **Inheritance:** Chunks inherit parent document ACL
- **Filtering:** Applied at Qdrant/OpenSearch query level
- **Storage:** ACL metadata stored with document and indexed for filtering

## Implementation Tasks

### 1. Define ACL Data Models

`services/shared/security/acl/models.py`:

```python
from enum import Enum
from typing import List, Optional, Set
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class Visibility(str, Enum):
    """Document visibility levels."""
    PUBLIC = "public"       # Visible to all users in tenant
    PRIVATE = "private"     # Visible only to owner
    GROUP = "group"         # Visible to specified groups
    RESTRICTED = "restricted"  # Visible to specified users/groups


class ACLEntry(BaseModel):
    """Individual ACL entry."""
    principal_type: str = Field(..., pattern="^(user|group|role)$")
    principal_id: str
    permissions: List[str] = Field(default_factory=lambda: ["read"])
    
    def matches(self, user_id: str, groups: List[str], roles: List[str]) -> bool:
        """Check if this entry matches the given principal."""
        if self.principal_type == "user":
            return self.principal_id == user_id
        elif self.principal_type == "group":
            return self.principal_id in groups
        elif self.principal_type == "role":
            return self.principal_id in roles
        return False


class DocumentACL(BaseModel):
    """Complete ACL for a document."""
    document_id: UUID
    tenant_id: UUID
    owner_id: str
    
    visibility: Visibility = Visibility.PRIVATE
    
    # Explicit access lists
    allowed_users: List[str] = Field(default_factory=list)
    allowed_groups: List[str] = Field(default_factory=list)
    allowed_roles: List[str] = Field(default_factory=list)
    
    # Denied access (takes precedence over allowed)
    denied_users: List[str] = Field(default_factory=list)
    denied_groups: List[str] = Field(default_factory=list)
    
    # Detailed ACL entries for granular permissions
    acl_entries: List[ACLEntry] = Field(default_factory=list)
    
    # Metadata
    inherit_to_chunks: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    def can_access(
        self,
        user_id: str,
        user_groups: List[str],
        user_roles: List[str],
        is_super_admin: bool = False
    ) -> bool:
        """Check if user can access this document."""
        # Super admin bypass
        if is_super_admin:
            return True
        
        # Owner always has access
        if user_id == self.owner_id:
            return True
        
        # Check denials first
        if user_id in self.denied_users:
            return False
        if any(g in self.denied_groups for g in user_groups):
            return False
        
        # Check visibility
        if self.visibility == Visibility.PUBLIC:
            return True
        
        if self.visibility == Visibility.PRIVATE:
            return False  # Only owner (checked above)
        
        if self.visibility in (Visibility.GROUP, Visibility.RESTRICTED):
            # Check allowed lists
            if user_id in self.allowed_users:
                return True
            if any(g in self.allowed_groups for g in user_groups):
                return True
            if any(r in self.allowed_roles for r in user_roles):
                return True
            
            # Check detailed ACL entries
            for entry in self.acl_entries:
                if entry.matches(user_id, user_groups, user_roles):
                    if "read" in entry.permissions:
                        return True
        
        return False
    
    def to_filter_payload(self) -> dict:
        """Convert ACL to Qdrant filter payload."""
        return {
            "visibility": self.visibility.value,
            "owner_id": self.owner_id,
            "allowed_users": self.allowed_users,
            "allowed_groups": self.allowed_groups,
            "allowed_roles": self.allowed_roles,
        }


class ACLUpdateRequest(BaseModel):
    """Request to update document ACL."""
    visibility: Optional[Visibility] = None
    allowed_users: Optional[List[str]] = None
    allowed_groups: Optional[List[str]] = None
    allowed_roles: Optional[List[str]] = None
    denied_users: Optional[List[str]] = None
    denied_groups: Optional[List[str]] = None
    add_users: Optional[List[str]] = None
    remove_users: Optional[List[str]] = None
    add_groups: Optional[List[str]] = None
    remove_groups: Optional[List[str]] = None


class BulkACLUpdateRequest(BaseModel):
    """Bulk ACL update for multiple documents."""
    document_ids: List[UUID]
    visibility: Optional[Visibility] = None
    add_users: Optional[List[str]] = None
    add_groups: Optional[List[str]] = None
    remove_users: Optional[List[str]] = None
    remove_groups: Optional[List[str]] = None
```

### 2. Create ACL Service

`services/shared/security/acl/service.py`:

```python
from typing import List, Optional, Dict, Any
from uuid import UUID
import structlog

from .models import DocumentACL, Visibility, ACLUpdateRequest
from ..jwt.models import TokenClaims
from ..rbac.permissions import Role

logger = structlog.get_logger(__name__)


class ACLService:
    """Service for managing document ACLs."""
    
    def __init__(self, acl_repository, document_repository):
        self.acl_repo = acl_repository
        self.doc_repo = document_repository
    
    async def get_document_acl(self, document_id: UUID) -> Optional[DocumentACL]:
        """Get ACL for a document."""
        return await self.acl_repo.get_by_document_id(document_id)
    
    async def create_acl(
        self,
        document_id: UUID,
        tenant_id: UUID,
        owner_id: str,
        visibility: Visibility = Visibility.PRIVATE,
        allowed_users: List[str] = None,
        allowed_groups: List[str] = None,
    ) -> DocumentACL:
        """Create ACL for a new document."""
        acl = DocumentACL(
            document_id=document_id,
            tenant_id=tenant_id,
            owner_id=owner_id,
            visibility=visibility,
            allowed_users=allowed_users or [],
            allowed_groups=allowed_groups or [],
        )
        
        await self.acl_repo.create(acl)
        
        logger.info(
            "acl_created",
            document_id=str(document_id),
            visibility=visibility.value,
            owner_id=owner_id,
        )
        
        return acl
    
    async def update_acl(
        self,
        document_id: UUID,
        update: ACLUpdateRequest,
        updated_by: str,
    ) -> DocumentACL:
        """Update document ACL."""
        acl = await self.get_document_acl(document_id)
        if not acl:
            raise ValueError(f"ACL not found for document {document_id}")
        
        # Apply updates
        if update.visibility is not None:
            acl.visibility = update.visibility
        
        if update.allowed_users is not None:
            acl.allowed_users = update.allowed_users
        elif update.add_users:
            acl.allowed_users = list(set(acl.allowed_users + update.add_users))
        if update.remove_users:
            acl.allowed_users = [u for u in acl.allowed_users if u not in update.remove_users]
        
        if update.allowed_groups is not None:
            acl.allowed_groups = update.allowed_groups
        elif update.add_groups:
            acl.allowed_groups = list(set(acl.allowed_groups + update.add_groups))
        if update.remove_groups:
            acl.allowed_groups = [g for g in acl.allowed_groups if g not in update.remove_groups]
        
        if update.allowed_roles is not None:
            acl.allowed_roles = update.allowed_roles
        
        if update.denied_users is not None:
            acl.denied_users = update.denied_users
        if update.denied_groups is not None:
            acl.denied_groups = update.denied_groups
        
        await self.acl_repo.update(acl)
        
        # Update chunks if inheritance is enabled
        if acl.inherit_to_chunks:
            await self._propagate_acl_to_chunks(document_id, acl)
        
        logger.info(
            "acl_updated",
            document_id=str(document_id),
            updated_by=updated_by,
        )
        
        return acl
    
    async def check_access(
        self,
        document_id: UUID,
        user: TokenClaims,
    ) -> bool:
        """Check if user can access document."""
        acl = await self.get_document_acl(document_id)
        if not acl:
            return False
        
        is_super_admin = user.has_role(Role.SUPER_ADMIN.value)
        
        return acl.can_access(
            user_id=user.user_id,
            user_groups=user.groups,
            user_roles=user.roles,
            is_super_admin=is_super_admin,
        )
    
    async def filter_accessible_documents(
        self,
        document_ids: List[UUID],
        user: TokenClaims,
    ) -> List[UUID]:
        """Filter list of documents to only those accessible by user."""
        accessible = []
        
        for doc_id in document_ids:
            if await self.check_access(doc_id, user):
                accessible.append(doc_id)
        
        return accessible
    
    async def get_acl_filter_for_user(
        self,
        user: TokenClaims,
        tenant_id: UUID,
    ) -> Dict[str, Any]:
        """
        Get filter conditions for Qdrant/OpenSearch queries.
        
        Returns filter that matches documents accessible to user.
        """
        is_super_admin = user.has_role(Role.SUPER_ADMIN.value)
        
        if is_super_admin:
            # Super admin sees all (within tenant)
            return {"tenant_id": str(tenant_id)}
        
        # Build OR conditions for access
        return {
            "tenant_id": str(tenant_id),
            "$or": [
                # Public documents
                {"visibility": Visibility.PUBLIC.value},
                # User is owner
                {"owner_id": user.user_id},
                # User is in allowed_users
                {"allowed_users": {"$contains": user.user_id}},
                # User's groups intersect with allowed_groups
                *[
                    {"allowed_groups": {"$contains": group}}
                    for group in user.groups
                ],
                # User's roles intersect with allowed_roles
                *[
                    {"allowed_roles": {"$contains": role}}
                    for role in user.roles
                ],
            ]
        }
    
    async def _propagate_acl_to_chunks(
        self,
        document_id: UUID,
        acl: DocumentACL,
    ) -> None:
        """Propagate ACL updates to all chunks of a document."""
        # Update chunk ACL metadata in vector store
        # This is handled by the vector store service
        pass
    
    async def share_document(
        self,
        document_id: UUID,
        share_with_users: List[str] = None,
        share_with_groups: List[str] = None,
        sharer: TokenClaims = None,
    ) -> DocumentACL:
        """Share document with additional users/groups."""
        update = ACLUpdateRequest(
            add_users=share_with_users,
            add_groups=share_with_groups,
        )
        
        # If visibility is private, upgrade to group/restricted
        acl = await self.get_document_acl(document_id)
        if acl and acl.visibility == Visibility.PRIVATE:
            update.visibility = Visibility.RESTRICTED
        
        return await self.update_acl(document_id, update, sharer.user_id if sharer else "system")
    
    async def make_public(self, document_id: UUID, updated_by: str) -> DocumentACL:
        """Make document public within tenant."""
        update = ACLUpdateRequest(visibility=Visibility.PUBLIC)
        return await self.update_acl(document_id, update, updated_by)
    
    async def make_private(self, document_id: UUID, updated_by: str) -> DocumentACL:
        """Make document private (owner only)."""
        update = ACLUpdateRequest(
            visibility=Visibility.PRIVATE,
            allowed_users=[],
            allowed_groups=[],
        )
        return await self.update_acl(document_id, update, updated_by)
```

### 3. Create ACL Query Filters for Vector Stores

`services/shared/security/acl/filters.py`:

```python
from typing import Dict, Any, List
from uuid import UUID

from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

from .models import Visibility
from ..jwt.models import TokenClaims
from ..rbac.permissions import Role


class QdrantACLFilter:
    """Build Qdrant filters for ACL enforcement."""
    
    @staticmethod
    def build_access_filter(
        user: TokenClaims,
        tenant_id: UUID,
        additional_filters: Dict[str, Any] = None,
    ) -> Filter:
        """
        Build Qdrant filter that enforces ACL.
        
        Documents match if:
        - Same tenant AND
        - (visibility=public OR owner=user OR user in allowed_users OR user's groups in allowed_groups)
        """
        is_super_admin = user.has_role(Role.SUPER_ADMIN.value)
        
        # Base tenant filter
        must_conditions = [
            FieldCondition(
                key="tenant_id",
                match=MatchValue(value=str(tenant_id)),
            )
        ]
        
        # Add additional filters if provided
        if additional_filters:
            for key, value in additional_filters.items():
                if isinstance(value, list):
                    must_conditions.append(
                        FieldCondition(key=key, match=MatchAny(any=value))
                    )
                else:
                    must_conditions.append(
                        FieldCondition(key=key, match=MatchValue(value=value))
                    )
        
        # Super admin: only tenant filter
        if is_super_admin:
            return Filter(must=must_conditions)
        
        # Build ACL conditions (OR logic)
        acl_conditions = [
            # Public visibility
            FieldCondition(
                key="visibility",
                match=MatchValue(value=Visibility.PUBLIC.value),
            ),
            # Owner
            FieldCondition(
                key="owner_id",
                match=MatchValue(value=user.user_id),
            ),
            # User in allowed_users
            FieldCondition(
                key="allowed_users",
                match=MatchAny(any=[user.user_id]),
            ),
        ]
        
        # User's groups in allowed_groups
        if user.groups:
            acl_conditions.append(
                FieldCondition(
                    key="allowed_groups",
                    match=MatchAny(any=user.groups),
                )
            )
        
        # User's roles in allowed_roles
        if user.roles:
            acl_conditions.append(
                FieldCondition(
                    key="allowed_roles",
                    match=MatchAny(any=user.roles),
                )
            )
        
        return Filter(
            must=must_conditions,
            should=acl_conditions,
            min_should={"min_count": 1},  # At least one ACL condition must match
        )


class OpenSearchACLFilter:
    """Build OpenSearch queries for ACL enforcement."""
    
    @staticmethod
    def build_access_filter(
        user: TokenClaims,
        tenant_id: UUID,
        base_query: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Build OpenSearch query with ACL enforcement.
        
        Wraps base query with ACL filter.
        """
        is_super_admin = user.has_role(Role.SUPER_ADMIN.value)
        
        # Base tenant filter
        must_filters = [
            {"term": {"tenant_id": str(tenant_id)}}
        ]
        
        # Add base query if provided
        if base_query:
            must_filters.append(base_query)
        
        # Super admin: only tenant filter
        if is_super_admin:
            return {
                "bool": {
                    "must": must_filters
                }
            }
        
        # ACL conditions
        should_filters = [
            # Public visibility
            {"term": {"visibility": Visibility.PUBLIC.value}},
            # Owner
            {"term": {"owner_id": user.user_id}},
            # User in allowed_users
            {"terms": {"allowed_users": [user.user_id]}},
        ]
        
        # User's groups
        if user.groups:
            should_filters.append(
                {"terms": {"allowed_groups": user.groups}}
            )
        
        # User's roles
        if user.roles:
            should_filters.append(
                {"terms": {"allowed_roles": user.roles}}
            )
        
        return {
            "bool": {
                "must": must_filters,
                "should": should_filters,
                "minimum_should_match": 1,
            }
        }


def build_chunk_acl_payload(document_acl: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build ACL payload to store with vector chunks.
    
    Chunks inherit parent document's ACL.
    """
    return {
        "tenant_id": document_acl.get("tenant_id"),
        "document_id": document_acl.get("document_id"),
        "visibility": document_acl.get("visibility", Visibility.PRIVATE.value),
        "owner_id": document_acl.get("owner_id"),
        "allowed_users": document_acl.get("allowed_users", []),
        "allowed_groups": document_acl.get("allowed_groups", []),
        "allowed_roles": document_acl.get("allowed_roles", []),
    }
```

### 4. Update Qdrant Service with ACL

`services/retrieval/vector_store.py` (partial):

```python
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Filter
from typing import List, Optional
from uuid import UUID

from shared.security.acl.filters import QdrantACLFilter, build_chunk_acl_payload
from shared.security.jwt.models import TokenClaims


class VectorStoreService:
    """Vector store service with ACL support."""
    
    def __init__(self, client: QdrantClient, collection_name: str):
        self.client = client
        self.collection_name = collection_name
    
    async def upsert_chunks(
        self,
        chunks: List[dict],
        document_acl: dict,
    ) -> None:
        """Insert chunks with ACL metadata."""
        acl_payload = build_chunk_acl_payload(document_acl)
        
        points = []
        for chunk in chunks:
            payload = {
                **chunk.get("metadata", {}),
                **acl_payload,  # ACL fields
                "content": chunk["content"],
                "chunk_id": chunk["chunk_id"],
                "document_id": str(document_acl["document_id"]),
            }
            
            points.append(
                PointStruct(
                    id=chunk["chunk_id"],
                    vector=chunk["embedding"],
                    payload=payload,
                )
            )
        
        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
        )
    
    async def search_with_acl(
        self,
        query_vector: List[float],
        user: TokenClaims,
        tenant_id: UUID,
        limit: int = 10,
        additional_filters: dict = None,
    ) -> List[dict]:
        """Search vectors with ACL filtering."""
        # Build ACL filter
        acl_filter = QdrantACLFilter.build_access_filter(
            user=user,
            tenant_id=tenant_id,
            additional_filters=additional_filters,
        )
        
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            query_filter=acl_filter,
            limit=limit,
            with_payload=True,
        )
        
        return [
            {
                "id": str(hit.id),
                "score": hit.score,
                "content": hit.payload.get("content"),
                "document_id": hit.payload.get("document_id"),
                "metadata": {
                    k: v for k, v in hit.payload.items()
                    if k not in ["content", "tenant_id", "visibility", 
                                 "owner_id", "allowed_users", "allowed_groups", "allowed_roles"]
                },
            }
            for hit in results
        ]
    
    async def update_document_acl(
        self,
        document_id: UUID,
        new_acl: dict,
    ) -> None:
        """Update ACL for all chunks of a document."""
        acl_payload = build_chunk_acl_payload(new_acl)
        
        # Update all points with matching document_id
        self.client.set_payload(
            collection_name=self.collection_name,
            payload=acl_payload,
            points=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=str(document_id)),
                    )
                ]
            ),
        )
```

### 5. Create ACL Management API

`services/api-gateway/routers/acl.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from uuid import UUID

from shared.security.jwt.models import TokenClaims
from shared.security.jwt.middleware import get_current_user
from shared.security.rbac.middleware import require_permission
from shared.security.rbac.permissions import Permission
from shared.security.acl.models import (
    DocumentACL,
    ACLUpdateRequest,
    BulkACLUpdateRequest,
    Visibility,
)
from shared.security.acl.service import ACLService

router = APIRouter(prefix="/documents/{document_id}/acl", tags=["acl"])


@router.get("", response_model=DocumentACL)
async def get_document_acl(
    document_id: UUID,
    user: TokenClaims = Depends(require_permission(Permission.DOCUMENTS_READ)),
    acl_service: ACLService = Depends(),
):
    """Get ACL for a document."""
    acl = await acl_service.get_document_acl(document_id)
    if not acl:
        raise HTTPException(status_code=404, detail="Document ACL not found")
    
    # Check if user can view this ACL (must have access to document)
    if not await acl_service.check_access(document_id, user):
        raise HTTPException(status_code=403, detail="Access denied")
    
    return acl


@router.put("", response_model=DocumentACL)
async def update_document_acl(
    document_id: UUID,
    update: ACLUpdateRequest,
    user: TokenClaims = Depends(require_permission(
        Permission.DOCUMENTS_UPDATE,
        Permission.DOCUMENTS_ADMIN,
    )),
    acl_service: ACLService = Depends(),
):
    """Update document ACL."""
    acl = await acl_service.get_document_acl(document_id)
    if not acl:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Only owner or admin can update ACL
    is_owner = acl.owner_id == user.user_id
    is_admin = user.has_role("tenant_admin") or user.has_role("super_admin")
    
    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="Only owner or admin can modify ACL")
    
    return await acl_service.update_acl(document_id, update, user.user_id)


@router.post("/share")
async def share_document(
    document_id: UUID,
    users: List[str] = None,
    groups: List[str] = None,
    user: TokenClaims = Depends(require_permission(Permission.DOCUMENTS_UPDATE)),
    acl_service: ACLService = Depends(),
):
    """Share document with users/groups."""
    acl = await acl_service.get_document_acl(document_id)
    if not acl:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Check ownership
    if acl.owner_id != user.user_id and not user.has_role("tenant_admin"):
        raise HTTPException(status_code=403, detail="Only owner can share")
    
    updated_acl = await acl_service.share_document(
        document_id=document_id,
        share_with_users=users,
        share_with_groups=groups,
        sharer=user,
    )
    
    return {"message": "Document shared", "acl": updated_acl}


@router.post("/make-public")
async def make_document_public(
    document_id: UUID,
    user: TokenClaims = Depends(require_permission(Permission.DOCUMENTS_UPDATE)),
    acl_service: ACLService = Depends(),
):
    """Make document public within tenant."""
    return await acl_service.make_public(document_id, user.user_id)


@router.post("/make-private")
async def make_document_private(
    document_id: UUID,
    user: TokenClaims = Depends(require_permission(Permission.DOCUMENTS_UPDATE)),
    acl_service: ACLService = Depends(),
):
    """Make document private (owner only)."""
    return await acl_service.make_private(document_id, user.user_id)


# Bulk operations router
bulk_router = APIRouter(prefix="/documents/acl/bulk", tags=["acl"])


@bulk_router.post("")
async def bulk_update_acl(
    request: BulkACLUpdateRequest,
    user: TokenClaims = Depends(require_permission(Permission.DOCUMENTS_ADMIN)),
    acl_service: ACLService = Depends(),
):
    """Bulk update ACL for multiple documents."""
    results = []
    
    for doc_id in request.document_ids:
        try:
            update = ACLUpdateRequest(
                visibility=request.visibility,
                add_users=request.add_users,
                add_groups=request.add_groups,
                remove_users=request.remove_users,
                remove_groups=request.remove_groups,
            )
            await acl_service.update_acl(doc_id, update, user.user_id)
            results.append({"document_id": str(doc_id), "status": "success"})
        except Exception as e:
            results.append({"document_id": str(doc_id), "status": "error", "error": str(e)})
    
    return {"results": results}
```

### 6. Database Migration for ACL

`services/shared/database/migrations/versions/xxx_add_acl_tables.py`:

```python
"""Add ACL tables.

Revision ID: xxx
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB

revision = 'xxx'
down_revision = 'yyy'
branch_labels = None
depends_on = None


def upgrade():
    # Document ACL table
    op.create_table(
        'document_acls',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('document_id', UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False),
        sa.Column('owner_id', sa.String(255), nullable=False),
        sa.Column('visibility', sa.String(20), nullable=False, default='private'),
        sa.Column('allowed_users', ARRAY(sa.String), default=[]),
        sa.Column('allowed_groups', ARRAY(sa.String), default=[]),
        sa.Column('allowed_roles', ARRAY(sa.String), default=[]),
        sa.Column('denied_users', ARRAY(sa.String), default=[]),
        sa.Column('denied_groups', ARRAY(sa.String), default=[]),
        sa.Column('acl_entries', JSONB, default=[]),
        sa.Column('inherit_to_chunks', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=False),
    )
    
    # Indexes for efficient filtering
    op.create_index('ix_document_acls_tenant_id', 'document_acls', ['tenant_id'])
    op.create_index('ix_document_acls_owner_id', 'document_acls', ['owner_id'])
    op.create_index('ix_document_acls_visibility', 'document_acls', ['visibility'])
    
    # GIN indexes for array columns
    op.execute("""
        CREATE INDEX ix_document_acls_allowed_users 
        ON document_acls USING GIN (allowed_users);
    """)
    op.execute("""
        CREATE INDEX ix_document_acls_allowed_groups 
        ON document_acls USING GIN (allowed_groups);
    """)


def downgrade():
    op.drop_table('document_acls')
```

### 7. Create Tests

`tests/security/test_document_acl.py`:

```python
import pytest
from uuid import uuid4

from shared.security.acl.models import DocumentACL, Visibility, ACLEntry
from shared.security.acl.filters import QdrantACLFilter, OpenSearchACLFilter
from shared.security.jwt.models import TokenClaims


@pytest.fixture
def owner_user():
    return TokenClaims(
        sub="owner-123",
        iss="test",
        aud="test",
        exp=9999999999,
        iat=1000000000,
        jti=str(uuid4()),
        tenant_id=uuid4(),
        roles=["tenant_user"],
        groups=["engineering"],
        permissions=[],
    )


@pytest.fixture
def other_user():
    return TokenClaims(
        sub="other-456",
        iss="test",
        aud="test",
        exp=9999999999,
        iat=1000000000,
        jti=str(uuid4()),
        tenant_id=uuid4(),  # Same tenant
        roles=["tenant_user"],
        groups=["marketing"],
        permissions=[],
    )


@pytest.fixture
def document_acl(owner_user):
    return DocumentACL(
        document_id=uuid4(),
        tenant_id=owner_user.tenant_id,
        owner_id=owner_user.user_id,
        visibility=Visibility.PRIVATE,
    )


class TestDocumentACL:
    def test_owner_can_access_private(self, document_acl, owner_user):
        assert document_acl.can_access(
            user_id=owner_user.user_id,
            user_groups=owner_user.groups,
            user_roles=owner_user.roles,
        )
    
    def test_other_cannot_access_private(self, document_acl, other_user):
        assert not document_acl.can_access(
            user_id=other_user.user_id,
            user_groups=other_user.groups,
            user_roles=other_user.roles,
        )
    
    def test_public_document_accessible(self, document_acl, other_user):
        document_acl.visibility = Visibility.PUBLIC
        assert document_acl.can_access(
            user_id=other_user.user_id,
            user_groups=other_user.groups,
            user_roles=other_user.roles,
        )
    
    def test_group_access(self, document_acl, other_user):
        document_acl.visibility = Visibility.GROUP
        document_acl.allowed_groups = ["marketing"]
        
        assert document_acl.can_access(
            user_id=other_user.user_id,
            user_groups=other_user.groups,
            user_roles=other_user.roles,
        )
    
    def test_user_access(self, document_acl, other_user):
        document_acl.visibility = Visibility.RESTRICTED
        document_acl.allowed_users = [other_user.user_id]
        
        assert document_acl.can_access(
            user_id=other_user.user_id,
            user_groups=other_user.groups,
            user_roles=other_user.roles,
        )
    
    def test_denied_overrides_allowed(self, document_acl, other_user):
        document_acl.visibility = Visibility.PUBLIC
        document_acl.denied_users = [other_user.user_id]
        
        assert not document_acl.can_access(
            user_id=other_user.user_id,
            user_groups=other_user.groups,
            user_roles=other_user.roles,
        )
    
    def test_super_admin_bypass(self, document_acl, other_user):
        document_acl.visibility = Visibility.PRIVATE
        
        assert document_acl.can_access(
            user_id=other_user.user_id,
            user_groups=other_user.groups,
            user_roles=other_user.roles,
            is_super_admin=True,
        )


class TestQdrantACLFilter:
    def test_builds_filter_for_regular_user(self, owner_user):
        filter_obj = QdrantACLFilter.build_access_filter(
            user=owner_user,
            tenant_id=owner_user.tenant_id,
        )
        
        assert filter_obj is not None
        assert filter_obj.must is not None
        assert filter_obj.should is not None
    
    def test_super_admin_filter(self, owner_user):
        owner_user.roles = ["super_admin"]
        
        filter_obj = QdrantACLFilter.build_access_filter(
            user=owner_user,
            tenant_id=owner_user.tenant_id,
        )
        
        # Super admin should only have tenant filter (no ACL conditions)
        assert filter_obj.should is None or len(filter_obj.should) == 0
```

## Acceptance Criteria

- [ ] ACL metadata stored with documents
- [ ] Visibility levels working (public, private, group, restricted)
- [ ] ACL filter applied in Qdrant vector searches
- [ ] ACL filter applied in OpenSearch keyword searches
- [ ] ACL inheritance to chunks implemented
- [ ] ACL management API endpoints working
- [ ] Bulk ACL update functionality
- [ ] Super admin bypass working correctly
- [ ] Denied lists override allowed lists
- [ ] Unit and integration tests passing

## Verification Commands

```bash
# Run ACL tests
pytest tests/security/test_document_acl.py -v

# Test ACL in search (should only return accessible documents)
TOKEN=$(get_user_token user1)
curl -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "test query"}'

# Update document ACL
curl -X PUT "http://localhost:8000/documents/{doc_id}/acl" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"visibility": "group", "allowed_groups": ["engineering"]}'

# Share document
curl -X POST "http://localhost:8000/documents/{doc_id}/acl/share" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"users": ["user2"], "groups": ["marketing"]}'
```

## Files to Create

1. `services/shared/security/acl/__init__.py`
2. `services/shared/security/acl/models.py`
3. `services/shared/security/acl/service.py`
4. `services/shared/security/acl/filters.py`
5. `services/api-gateway/routers/acl.py`
6. `services/shared/database/models/acl.py`
7. `services/shared/database/migrations/versions/xxx_add_acl_tables.py`
8. `tests/security/test_document_acl.py`

## Security Considerations

- **Tenant isolation first** - ACL operates within tenant boundaries
- **Deny overrides allow** - Explicit denials take precedence
- **Filter at query time** - Never return unauthorized data
- **Chunk inheritance** - Chunks inherit document ACL automatically
- **Audit ACL changes** - Log all ACL modifications
- **Owner immutability** - Document owner cannot be changed (transfer requires admin)
