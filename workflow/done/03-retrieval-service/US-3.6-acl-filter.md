# US-3.6: ACL Filter

> **Story ID:** US-3.6  
> **Epic:** Retrieval Service  
> **Priority:** Critical  
> **Estimated Effort:** 1-2 days  
> **Dependencies:** Epic 1 (Infrastructure Setup)

## User Story

**As a** developer  
**I want** access control enforcement  
**So that** users only see documents they are permitted to access

## Context

Access Control Lists (ACL) ensure that search results are filtered based on user permissions before being returned. Per the architecture, ACL context comes from JWT claims containing tenant_id, groups, and permissions. Filters are applied at the database query level (pre-filtering) in both Qdrant and OpenSearch for efficiency.

## Technical Requirements

### Directory Structure

```
retrieval-service/
└── acl/
    ├── __init__.py
    ├── filter.py            # ACL filter builder
    ├── context.py           # User context extraction
    ├── models.py            # Pydantic models
    └── middleware.py        # FastAPI middleware
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from enum import Enum

class Visibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    GROUP = "group"  # Visible to specific groups
    TENANT = "tenant"  # Visible to entire tenant

class UserContext(BaseModel):
    """
    User context extracted from JWT claims.
    
    This represents the authenticated user's identity
    and permissions for ACL filtering.
    """
    user_id: UUID
    tenant_id: UUID
    groups: list[str] = []
    roles: list[str] = []
    permissions: list[str] = []
    
    # Optional metadata
    email: Optional[str] = None
    name: Optional[str] = None
    
    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission."""
        return permission in self.permissions
    
    def has_role(self, role: str) -> bool:
        """Check if user has a specific role."""
        return role in self.roles
    
    def is_admin(self) -> bool:
        """Check if user is an admin."""
        return "admin" in self.roles

class DocumentACL(BaseModel):
    """
    ACL metadata stored with each document.
    
    Documents are indexed with these fields for filtering.
    """
    tenant_id: UUID
    visibility: Visibility = Visibility.PRIVATE
    owner_id: Optional[UUID] = None
    allowed_groups: list[str] = []
    allowed_users: list[UUID] = []
    denied_groups: list[str] = []
    denied_users: list[UUID] = []

class ACLFilterConfig(BaseModel):
    """Configuration for ACL filtering."""
    # Enable/disable ACL
    enabled: bool = True
    
    # Admin bypass
    admin_bypass: bool = True  # Admins see all documents
    
    # Super tenant (can see all tenants)
    super_tenant_id: Optional[UUID] = None
    
    # Default visibility for documents without ACL
    default_visibility: Visibility = Visibility.PRIVATE
```

### ACL Filter Builder

```python
from typing import Optional, Any
from uuid import UUID

class ACLFilter:
    """
    Builds database filters for ACL enforcement.
    
    Generates filter clauses for Qdrant and OpenSearch that
    restrict results to documents the user is authorized to see.
    
    ACL Logic:
    1. Document must belong to user's tenant (unless super tenant)
    2. Document must be:
       - PUBLIC visibility, OR
       - TENANT visibility (same tenant), OR
       - GROUP visibility with matching groups, OR
       - Explicitly allowed for user
    3. User must not be in denied_groups or denied_users
    """
    
    def __init__(self, config: ACLFilterConfig = ACLFilterConfig()):
        self.config = config
    
    def build_filter(
        self,
        user_context: UserContext,
        additional_filters: Optional[dict] = None
    ) -> dict:
        """
        Build filter dict for Qdrant/OpenSearch.
        
        Args:
            user_context: Authenticated user's context
            additional_filters: Extra filters to merge (metadata, etc.)
        
        Returns:
            Filter dict in unified format for both backends
        """
        if not self.config.enabled:
            return additional_filters or {}
        
        # Admin bypass
        if self.config.admin_bypass and user_context.is_admin():
            return self._merge_filters({}, additional_filters)
        
        # Build ACL filter
        acl_filter = self._build_acl_clauses(user_context)
        
        return self._merge_filters(acl_filter, additional_filters)
    
    def _build_acl_clauses(self, user: UserContext) -> dict:
        """
        Build the core ACL filter clauses.
        
        Structure:
        {
            "must": [
                {"key": "tenant_id", "match": {"value": <tenant>}}  # Tenant filter
            ],
            "should": [  # Visibility options (OR)
                {"key": "visibility", "match": {"value": "public"}},
                {"key": "visibility", "match": {"value": "tenant"}},
                {"key": "allowed_groups", "match": {"any": <groups>}},
                {"key": "allowed_users", "match": {"any": <user_ids>}}
            ],
            "must_not": [  # Denied access
                {"key": "denied_groups", "match": {"any": <groups>}},
                {"key": "denied_users", "match": {"any": <user_ids>}}
            ]
        }
        """
        must_clauses = []
        should_clauses = []
        must_not_clauses = []
        
        # Tenant isolation (always required unless super tenant)
        if (self.config.super_tenant_id is None or 
            user.tenant_id != self.config.super_tenant_id):
            must_clauses.append({
                "key": "tenant_id",
                "match": {"value": str(user.tenant_id)}
            })
        
        # Visibility options (document must match at least one)
        # 1. Public documents
        should_clauses.append({
            "key": "visibility",
            "match": {"value": "public"}
        })
        
        # 2. Tenant-wide documents (same tenant)
        should_clauses.append({
            "key": "visibility",
            "match": {"value": "tenant"}
        })
        
        # 3. Documents allowed for user's groups
        if user.groups:
            should_clauses.append({
                "key": "allowed_groups",
                "match": {"any": user.groups}
            })
        
        # 4. Documents explicitly allowed for this user
        should_clauses.append({
            "key": "allowed_users",
            "match": {"any": [str(user.user_id)]}
        })
        
        # 5. Documents owned by this user (owner always has access)
        should_clauses.append({
            "key": "owner_id",
            "match": {"value": str(user.user_id)}
        })
        
        # Denied access (must not match any)
        if user.groups:
            must_not_clauses.append({
                "key": "denied_groups",
                "match": {"any": user.groups}
            })
        
        must_not_clauses.append({
            "key": "denied_users",
            "match": {"any": [str(user.user_id)]}
        })
        
        result = {}
        if must_clauses:
            result["must"] = must_clauses
        if should_clauses:
            result["should"] = should_clauses
        if must_not_clauses:
            result["must_not"] = must_not_clauses
        
        return result
    
    def _merge_filters(
        self,
        acl_filter: dict,
        additional_filters: Optional[dict]
    ) -> dict:
        """
        Merge ACL filters with additional filters.
        
        Additional filters are added to the must clause.
        """
        if not additional_filters:
            return acl_filter
        
        result = acl_filter.copy()
        
        # Merge must clauses
        if "must" not in result:
            result["must"] = []
        
        for key, value in additional_filters.items():
            if key in ["must", "should", "must_not"]:
                if key not in result:
                    result[key] = []
                result[key].extend(value)
            else:
                # Simple key-value filter
                result["must"].append({
                    "key": key,
                    "match": {"value": value}
                })
        
        return result
    
    def build_qdrant_filter(
        self,
        user_context: UserContext,
        additional_filters: Optional[dict] = None
    ) -> "Filter":
        """
        Build Qdrant-specific Filter object.
        
        Converts the unified filter format to Qdrant Filter.
        """
        from qdrant_client.models import (
            Filter, FieldCondition, MatchValue, MatchAny
        )
        
        unified = self.build_filter(user_context, additional_filters)
        
        if not unified:
            return None
        
        must_conditions = []
        should_conditions = []
        must_not_conditions = []
        
        def build_condition(clause: dict) -> FieldCondition:
            key = clause["key"]
            match = clause["match"]
            
            if "value" in match:
                return FieldCondition(
                    key=key,
                    match=MatchValue(value=match["value"])
                )
            elif "any" in match:
                return FieldCondition(
                    key=key,
                    match=MatchAny(any=match["any"])
                )
        
        for clause in unified.get("must", []):
            must_conditions.append(build_condition(clause))
        
        for clause in unified.get("should", []):
            should_conditions.append(build_condition(clause))
        
        for clause in unified.get("must_not", []):
            must_not_conditions.append(build_condition(clause))
        
        return Filter(
            must=must_conditions if must_conditions else None,
            should=should_conditions if should_conditions else None,
            must_not=must_not_conditions if must_not_conditions else None
        )
    
    def build_opensearch_filter(
        self,
        user_context: UserContext,
        additional_filters: Optional[dict] = None
    ) -> list[dict]:
        """
        Build OpenSearch filter clauses.
        
        Returns list of filter clauses for bool query.
        """
        unified = self.build_filter(user_context, additional_filters)
        
        if not unified:
            return []
        
        clauses = []
        
        def build_clause(condition: dict) -> dict:
            key = condition["key"]
            match = condition["match"]
            
            if "value" in match:
                return {"term": {key: match["value"]}}
            elif "any" in match:
                return {"terms": {key: match["any"]}}
        
        # Must clauses
        for condition in unified.get("must", []):
            clauses.append(build_clause(condition))
        
        # Should clauses (wrap in bool with minimum_should_match)
        if unified.get("should"):
            should_clauses = [
                build_clause(c) for c in unified["should"]
            ]
            clauses.append({
                "bool": {
                    "should": should_clauses,
                    "minimum_should_match": 1
                }
            })
        
        # Must not clauses
        if unified.get("must_not"):
            must_not_clauses = [
                build_clause(c) for c in unified["must_not"]
            ]
            clauses.append({
                "bool": {
                    "must_not": must_not_clauses
                }
            })
        
        return clauses
```

### User Context Extraction

```python
from typing import Optional
from uuid import UUID
from fastapi import Request, HTTPException
from jose import jwt, JWTError

class UserContextExtractor:
    """
    Extracts user context from JWT tokens.
    
    Validates the token and extracts claims for ACL filtering.
    """
    
    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        issuer: Optional[str] = None,
        audience: Optional[str] = None
    ):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.issuer = issuer
        self.audience = audience
    
    async def extract(self, request: Request) -> UserContext:
        """
        Extract user context from request Authorization header.
        
        Args:
            request: FastAPI request object
        
        Returns:
            UserContext with user's identity and permissions
        
        Raises:
            HTTPException 401 if token is missing or invalid
        """
        # Get token from header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(
                status_code=401,
                detail="Missing Authorization header"
            )
        
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Invalid Authorization header format"
            )
        
        token = auth_header[7:]  # Remove "Bearer "
        
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                issuer=self.issuer,
                audience=self.audience
            )
        except JWTError as e:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token: {str(e)}"
            )
        
        # Extract claims
        try:
            return UserContext(
                user_id=UUID(payload["sub"]),
                tenant_id=UUID(payload["tenant_id"]),
                groups=payload.get("groups", []),
                roles=payload.get("roles", []),
                permissions=payload.get("permissions", []),
                email=payload.get("email"),
                name=payload.get("name")
            )
        except (KeyError, ValueError) as e:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token claims: {str(e)}"
            )
    
    def create_anonymous_context(self, tenant_id: UUID) -> UserContext:
        """
        Create context for anonymous/unauthenticated users.
        
        Anonymous users can only see public documents.
        """
        return UserContext(
            user_id=UUID(int=0),
            tenant_id=tenant_id,
            groups=[],
            roles=["anonymous"],
            permissions=["read:public"]
        )


class AnonymousAccessFilter(ACLFilter):
    """
    ACL filter for anonymous access.
    
    Only allows access to public documents.
    """
    
    def _build_acl_clauses(self, user: UserContext) -> dict:
        """Build filter for public documents only."""
        return {
            "must": [
                {
                    "key": "tenant_id",
                    "match": {"value": str(user.tenant_id)}
                },
                {
                    "key": "visibility",
                    "match": {"value": "public"}
                }
            ]
        }
```

### FastAPI Middleware

```python
from fastapi import Request, Depends
from typing import Optional

class ACLMiddleware:
    """
    FastAPI dependency for ACL context injection.
    
    Usage:
        @app.get("/retrieve")
        async def retrieve(
            user_context: UserContext = Depends(get_user_context)
        ):
            ...
    """
    
    def __init__(
        self,
        extractor: UserContextExtractor,
        acl_filter: ACLFilter
    ):
        self.extractor = extractor
        self.acl_filter = acl_filter
    
    async def get_user_context(self, request: Request) -> UserContext:
        """Extract user context from request."""
        return await self.extractor.extract(request)
    
    async def get_acl_filter(
        self,
        request: Request,
        additional_filters: Optional[dict] = None
    ) -> dict:
        """Get ACL filter dict for current user."""
        user_context = await self.extractor.extract(request)
        return self.acl_filter.build_filter(user_context, additional_filters)


# Dependency functions for FastAPI
def create_acl_dependencies(
    secret_key: str,
    config: ACLFilterConfig = ACLFilterConfig()
):
    """
    Create FastAPI dependencies for ACL.
    
    Usage:
        get_user, get_filter = create_acl_dependencies("secret")
        
        @app.get("/retrieve")
        async def retrieve(user: UserContext = Depends(get_user)):
            ...
    """
    extractor = UserContextExtractor(secret_key)
    acl_filter = ACLFilter(config)
    middleware = ACLMiddleware(extractor, acl_filter)
    
    return middleware.get_user_context, middleware.get_acl_filter
```

## Acceptance Criteria

- [ ] ACLFilter builds correct filter clauses for Qdrant and OpenSearch
- [ ] Tenant isolation: users only see their tenant's documents
- [ ] Visibility levels work: PUBLIC, PRIVATE, GROUP, TENANT
- [ ] Group-based access: documents visible to user's groups
- [ ] User-based access: explicitly allowed users can access
- [ ] Owner access: document owners always have access
- [ ] Denied access: denied_groups and denied_users block access
- [ ] Admin bypass: admins see all documents when configured
- [ ] Super tenant: can see all tenants when configured
- [ ] UserContextExtractor validates and parses JWT tokens
- [ ] Anonymous access filter only allows public documents
- [ ] FastAPI middleware integrates cleanly

## Testing Requirements

```python
import pytest
from uuid import uuid4

@pytest.fixture
def user_context():
    return UserContext(
        user_id=uuid4(),
        tenant_id=uuid4(),
        groups=["engineering", "ml-team"],
        roles=["user"],
        permissions=["read:documents"]
    )

@pytest.fixture
def admin_context():
    return UserContext(
        user_id=uuid4(),
        tenant_id=uuid4(),
        groups=["admins"],
        roles=["admin"],
        permissions=["read:documents", "write:documents"]
    )

@pytest.fixture
def acl_filter():
    return ACLFilter()

def test_tenant_isolation(acl_filter, user_context):
    """Test that tenant_id is always required."""
    filter_dict = acl_filter.build_filter(user_context)
    
    must_clauses = filter_dict.get("must", [])
    tenant_clause = next(
        (c for c in must_clauses if c["key"] == "tenant_id"),
        None
    )
    
    assert tenant_clause is not None
    assert tenant_clause["match"]["value"] == str(user_context.tenant_id)

def test_visibility_options(acl_filter, user_context):
    """Test that visibility options are included."""
    filter_dict = acl_filter.build_filter(user_context)
    
    should_clauses = filter_dict.get("should", [])
    
    # Should include public visibility
    public_clause = next(
        (c for c in should_clauses 
         if c["key"] == "visibility" and c["match"]["value"] == "public"),
        None
    )
    assert public_clause is not None
    
    # Should include tenant visibility
    tenant_clause = next(
        (c for c in should_clauses 
         if c["key"] == "visibility" and c["match"]["value"] == "tenant"),
        None
    )
    assert tenant_clause is not None

def test_group_access(acl_filter, user_context):
    """Test that user's groups are included in filter."""
    filter_dict = acl_filter.build_filter(user_context)
    
    should_clauses = filter_dict.get("should", [])
    
    group_clause = next(
        (c for c in should_clauses if c["key"] == "allowed_groups"),
        None
    )
    
    assert group_clause is not None
    assert set(group_clause["match"]["any"]) == {"engineering", "ml-team"}

def test_denied_access(acl_filter, user_context):
    """Test that denied access is enforced."""
    filter_dict = acl_filter.build_filter(user_context)
    
    must_not_clauses = filter_dict.get("must_not", [])
    
    # Should block denied groups
    denied_groups = next(
        (c for c in must_not_clauses if c["key"] == "denied_groups"),
        None
    )
    assert denied_groups is not None
    
    # Should block denied users
    denied_users = next(
        (c for c in must_not_clauses if c["key"] == "denied_users"),
        None
    )
    assert denied_users is not None

def test_admin_bypass(acl_filter, admin_context):
    """Test that admins bypass ACL when configured."""
    config = ACLFilterConfig(admin_bypass=True)
    acl = ACLFilter(config)
    
    filter_dict = acl.build_filter(admin_context)
    
    # Should be empty (no restrictions)
    assert filter_dict == {}

def test_admin_no_bypass(acl_filter, admin_context):
    """Test that admins don't bypass when disabled."""
    config = ACLFilterConfig(admin_bypass=False)
    acl = ACLFilter(config)
    
    filter_dict = acl.build_filter(admin_context)
    
    # Should have normal ACL filters
    assert "must" in filter_dict or "should" in filter_dict

def test_merge_additional_filters(acl_filter, user_context):
    """Test merging ACL with additional filters."""
    additional = {
        "source_type": "pdf"
    }
    
    filter_dict = acl_filter.build_filter(user_context, additional)
    
    must_clauses = filter_dict.get("must", [])
    
    # Should include additional filter
    source_clause = next(
        (c for c in must_clauses if c["key"] == "source_type"),
        None
    )
    assert source_clause is not None
    assert source_clause["match"]["value"] == "pdf"

def test_qdrant_filter_conversion(acl_filter, user_context):
    """Test conversion to Qdrant Filter object."""
    qdrant_filter = acl_filter.build_qdrant_filter(user_context)
    
    assert qdrant_filter is not None
    assert qdrant_filter.must is not None
    assert qdrant_filter.should is not None

def test_opensearch_filter_conversion(acl_filter, user_context):
    """Test conversion to OpenSearch filter clauses."""
    os_filter = acl_filter.build_opensearch_filter(user_context)
    
    assert isinstance(os_filter, list)
    assert len(os_filter) > 0

@pytest.mark.asyncio
async def test_user_context_extraction():
    """Test JWT token parsing."""
    from jose import jwt
    
    secret = "test-secret"
    extractor = UserContextExtractor(secret)
    
    # Create valid token
    payload = {
        "sub": str(uuid4()),
        "tenant_id": str(uuid4()),
        "groups": ["team-a"],
        "roles": ["user"],
        "permissions": ["read:documents"]
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    
    # Mock request
    class MockRequest:
        headers = {"Authorization": f"Bearer {token}"}
    
    context = await extractor.extract(MockRequest())
    
    assert str(context.user_id) == payload["sub"]
    assert str(context.tenant_id) == payload["tenant_id"]
    assert context.groups == ["team-a"]

@pytest.mark.asyncio
async def test_invalid_token_rejected():
    """Test that invalid tokens are rejected."""
    extractor = UserContextExtractor("secret")
    
    class MockRequest:
        headers = {"Authorization": "Bearer invalid-token"}
    
    with pytest.raises(HTTPException) as exc:
        await extractor.extract(MockRequest())
    
    assert exc.value.status_code == 401

def test_anonymous_filter():
    """Test anonymous access filter."""
    tenant_id = uuid4()
    extractor = UserContextExtractor("secret")
    anon = extractor.create_anonymous_context(tenant_id)
    
    anon_filter = AnonymousAccessFilter()
    filter_dict = anon_filter.build_filter(anon)
    
    must_clauses = filter_dict.get("must", [])
    
    # Should only allow public documents
    visibility_clause = next(
        (c for c in must_clauses if c["key"] == "visibility"),
        None
    )
    assert visibility_clause is not None
    assert visibility_clause["match"]["value"] == "public"
```

## Integration Test

```python
@pytest.mark.integration
def test_acl_with_qdrant():
    """Test ACL filter with real Qdrant."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter
    
    user = UserContext(
        user_id=uuid4(),
        tenant_id=uuid4(),
        groups=["engineering"]
    )
    
    acl = ACLFilter()
    qdrant_filter = acl.build_qdrant_filter(user)
    
    # Verify filter is valid Qdrant Filter
    assert isinstance(qdrant_filter, Filter)
    
    # Would work with client.search(..., query_filter=qdrant_filter)

@pytest.mark.integration
def test_acl_with_opensearch():
    """Test ACL filter with real OpenSearch."""
    user = UserContext(
        user_id=uuid4(),
        tenant_id=uuid4(),
        groups=["engineering"]
    )
    
    acl = ACLFilter()
    os_filter = acl.build_opensearch_filter(user)
    
    # Verify filter clauses are valid
    assert isinstance(os_filter, list)
    
    # Would work in bool query: {"bool": {"filter": os_filter}}
```

## Dependencies

- `python-jose[cryptography]>=3.3.0`
- `pydantic>=2.0.0`
- `fastapi>=0.104.0`

## Definition of Done

- [ ] ACLFilter builds unified filter format
- [ ] Tenant isolation enforced
- [ ] All visibility levels supported
- [ ] Group and user-based access works
- [ ] Owner access always granted
- [ ] Denied access enforced
- [ ] Admin bypass configurable
- [ ] Super tenant support
- [ ] Qdrant filter conversion works
- [ ] OpenSearch filter conversion works
- [ ] UserContextExtractor parses JWT correctly
- [ ] Invalid tokens rejected with 401
- [ ] Anonymous access filter implemented
- [ ] FastAPI middleware integration
- [ ] >90% test coverage
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
