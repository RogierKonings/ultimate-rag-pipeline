"""Tests for user context extraction."""

import pytest
from uuid import uuid4

from fastapi import HTTPException
from jose import jwt

from acl.context import UserContextExtractor
from acl.models import UserContext


class MockRequest:
    """Mock FastAPI request for testing."""

    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}


class TestUserContextExtractor:
    """Tests for UserContextExtractor."""

    @pytest.fixture
    def secret_key(self):
        """Test secret key."""
        return "test-secret-key-for-jwt-validation"

    @pytest.fixture
    def extractor(self, secret_key):
        """Create extractor with test secret."""
        return UserContextExtractor(secret_key)

    @pytest.fixture
    def valid_payload(self):
        """Create valid JWT payload."""
        return {
            "sub": str(uuid4()),
            "tenant_id": str(uuid4()),
            "groups": ["engineering", "ml-team"],
            "roles": ["user"],
            "permissions": ["read:documents"],
            "email": "user@example.com",
            "name": "Test User",
        }

    @pytest.fixture
    def valid_token(self, secret_key, valid_payload):
        """Create valid JWT token."""
        return jwt.encode(valid_payload, secret_key, algorithm="HS256")

    @pytest.mark.asyncio
    async def test_extract_valid_token(self, extractor, valid_token, valid_payload):
        """Test extraction of valid JWT token."""
        request = MockRequest(headers={"Authorization": f"Bearer {valid_token}"})

        context = await extractor.extract(request)

        assert str(context.user_id) == valid_payload["sub"]
        assert str(context.tenant_id) == valid_payload["tenant_id"]
        assert context.groups == ["engineering", "ml-team"]
        assert context.roles == ["user"]
        assert context.permissions == ["read:documents"]
        assert context.email == "user@example.com"
        assert context.name == "Test User"

    @pytest.mark.asyncio
    async def test_extract_from_token_directly(
        self, extractor, valid_token, valid_payload
    ):
        """Test extraction from token string directly."""
        context = await extractor.extract_from_token(valid_token)

        assert str(context.user_id) == valid_payload["sub"]
        assert str(context.tenant_id) == valid_payload["tenant_id"]

    @pytest.mark.asyncio
    async def test_missing_authorization_header(self, extractor):
        """Test error when Authorization header is missing."""
        request = MockRequest(headers={})

        with pytest.raises(HTTPException) as exc:
            await extractor.extract(request)

        assert exc.value.status_code == 401
        assert "Missing Authorization header" in exc.value.detail

    @pytest.mark.asyncio
    async def test_invalid_authorization_format(self, extractor):
        """Test error when Authorization header format is wrong."""
        request = MockRequest(headers={"Authorization": "Basic abc123"})

        with pytest.raises(HTTPException) as exc:
            await extractor.extract(request)

        assert exc.value.status_code == 401
        assert "Invalid Authorization header format" in exc.value.detail

    @pytest.mark.asyncio
    async def test_invalid_token(self, extractor):
        """Test error when token is invalid."""
        request = MockRequest(headers={"Authorization": "Bearer invalid-token"})

        with pytest.raises(HTTPException) as exc:
            await extractor.extract(request)

        assert exc.value.status_code == 401
        assert "Invalid token" in exc.value.detail

    @pytest.mark.asyncio
    async def test_wrong_secret_key(self, secret_key, valid_payload):
        """Test error when token signed with wrong key."""
        wrong_key = "wrong-secret-key"
        token = jwt.encode(valid_payload, wrong_key, algorithm="HS256")

        extractor = UserContextExtractor(secret_key)
        request = MockRequest(headers={"Authorization": f"Bearer {token}"})

        with pytest.raises(HTTPException) as exc:
            await extractor.extract(request)

        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_required_claim_sub(self, secret_key):
        """Test error when 'sub' claim is missing."""
        payload = {
            "tenant_id": str(uuid4()),
            # 'sub' is missing
        }
        token = jwt.encode(payload, secret_key, algorithm="HS256")

        extractor = UserContextExtractor(secret_key)
        request = MockRequest(headers={"Authorization": f"Bearer {token}"})

        with pytest.raises(HTTPException) as exc:
            await extractor.extract(request)

        assert exc.value.status_code == 401
        assert "Missing required token claim" in exc.value.detail

    @pytest.mark.asyncio
    async def test_missing_required_claim_tenant_id(self, secret_key):
        """Test error when 'tenant_id' claim is missing."""
        payload = {
            "sub": str(uuid4()),
            # 'tenant_id' is missing
        }
        token = jwt.encode(payload, secret_key, algorithm="HS256")

        extractor = UserContextExtractor(secret_key)
        request = MockRequest(headers={"Authorization": f"Bearer {token}"})

        with pytest.raises(HTTPException) as exc:
            await extractor.extract(request)

        assert exc.value.status_code == 401
        assert "Missing required token claim" in exc.value.detail

    @pytest.mark.asyncio
    async def test_invalid_uuid_format(self, secret_key):
        """Test error when UUID format is invalid."""
        payload = {
            "sub": "not-a-valid-uuid",
            "tenant_id": str(uuid4()),
        }
        token = jwt.encode(payload, secret_key, algorithm="HS256")

        extractor = UserContextExtractor(secret_key)
        request = MockRequest(headers={"Authorization": f"Bearer {token}"})

        with pytest.raises(HTTPException) as exc:
            await extractor.extract(request)

        assert exc.value.status_code == 401
        assert "Invalid token claim format" in exc.value.detail

    @pytest.mark.asyncio
    async def test_optional_claims_default(self, secret_key):
        """Test that optional claims default properly."""
        payload = {
            "sub": str(uuid4()),
            "tenant_id": str(uuid4()),
            # groups, roles, permissions, email, name are optional
        }
        token = jwt.encode(payload, secret_key, algorithm="HS256")

        extractor = UserContextExtractor(secret_key)
        request = MockRequest(headers={"Authorization": f"Bearer {token}"})

        context = await extractor.extract(request)

        assert context.groups == []
        assert context.roles == []
        assert context.permissions == []
        assert context.email is None
        assert context.name is None

    @pytest.mark.asyncio
    async def test_issuer_validation(self, secret_key, valid_payload):
        """Test issuer validation when configured."""
        valid_payload["iss"] = "expected-issuer"
        token = jwt.encode(valid_payload, secret_key, algorithm="HS256")

        extractor = UserContextExtractor(secret_key, issuer="expected-issuer")
        request = MockRequest(headers={"Authorization": f"Bearer {token}"})

        context = await extractor.extract(request)
        assert context is not None

    @pytest.mark.asyncio
    async def test_issuer_validation_fails(self, secret_key, valid_payload):
        """Test error when issuer doesn't match."""
        valid_payload["iss"] = "wrong-issuer"
        token = jwt.encode(valid_payload, secret_key, algorithm="HS256")

        extractor = UserContextExtractor(secret_key, issuer="expected-issuer")
        request = MockRequest(headers={"Authorization": f"Bearer {token}"})

        with pytest.raises(HTTPException) as exc:
            await extractor.extract(request)

        assert exc.value.status_code == 401


class TestAnonymousContext:
    """Tests for anonymous context creation."""

    def test_create_anonymous_context(self):
        """Test anonymous context creation."""
        from uuid import UUID

        tenant_id = uuid4()
        extractor = UserContextExtractor("secret")

        context = extractor.create_anonymous_context(tenant_id)

        # Anonymous user has UUID with int=0 (all zeros)
        assert context.user_id == UUID(int=0)
        assert context.tenant_id == tenant_id
        assert context.groups == []
        assert "anonymous" in context.roles
        assert "read:public" in context.permissions

    def test_anonymous_is_not_admin(self):
        """Test anonymous user is not admin."""
        extractor = UserContextExtractor("secret")
        context = extractor.create_anonymous_context(uuid4())

        assert context.is_admin() is False


class TestServiceContext:
    """Tests for service context creation."""

    def test_create_service_context(self):
        """Test service context creation."""
        from uuid import UUID

        tenant_id = uuid4()
        extractor = UserContextExtractor("secret")

        context = extractor.create_service_context(tenant_id)

        # Service account has UUID with int=1
        assert context.user_id == UUID(int=1)
        assert context.tenant_id == tenant_id
        assert "service" in context.roles
        assert "read:all" in context.permissions
        assert "write:all" in context.permissions
