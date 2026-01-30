"""
Tests for service-to-service authentication.

This module tests the service authentication functionality including:
- ServiceTokenClaims model
- JWTHandler service token methods
- ServiceAuthMiddleware
- AuthenticatedServiceClient
"""

import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ..config import JWTAlgorithm, JWTSettings
from ..handler import (
    JWTHandler,
    TokenExpiredError,
    TokenInvalidError,
)
from ..models import ServiceTokenClaims, TokenType
from ..service_auth_config import (
    ServiceAuthSettings,
    get_allowed_endpoints,
    is_service_authorized,
)
from ..service_auth_middleware import ServiceAuthMiddleware, get_caller_service


# Test fixtures
@pytest.fixture
def jwt_settings():
    """Create JWT settings with HMAC for testing."""
    return JWTSettings(
        secret_key="test-secret-key-for-testing-only-32chars",
        algorithm=JWTAlgorithm.HS256,
        issuer="test-issuer",
        audience="test-audience",
    )


@pytest.fixture
def jwt_handler(jwt_settings):
    """Create JWT handler for testing."""
    return JWTHandler(settings=jwt_settings)


@pytest.fixture
def service_auth_settings():
    """Create service auth settings for testing."""
    return ServiceAuthSettings(
        service_name="retrieval",
        enabled=True,
        token_ttl_seconds=300,
        trusted_services=["orchestrator", "ingestion"],
    )


# ServiceTokenClaims Tests
class TestServiceTokenClaims:
    """Tests for ServiceTokenClaims model."""

    def test_create_service_claims(self):
        """Should create valid service token claims."""
        claims = ServiceTokenClaims(
            service_name="orchestrator",
            target_service="retrieval",
            allowed_endpoints=["/internal/*"],
        )

        assert claims.service_name == "orchestrator"
        assert claims.target_service == "retrieval"
        assert claims.allowed_endpoints == ["/internal/*"]
        assert claims.token_type == TokenType.SERVICE

    def test_to_dict(self):
        """Should convert claims to dictionary."""
        claims = ServiceTokenClaims(
            service_name="orchestrator",
            target_service="retrieval",
            allowed_endpoints=["/internal/*", "/api/v1/search"],
            iss="test-issuer",
            aud="retrieval",
        )

        data = claims.to_dict()

        assert data["service_name"] == "orchestrator"
        assert data["target_service"] == "retrieval"
        assert data["allowed_endpoints"] == ["/internal/*", "/api/v1/search"]
        assert data["token_type"] == "service"
        assert data["iss"] == "test-issuer"
        assert data["aud"] == "retrieval"

    def test_from_dict(self):
        """Should create claims from dictionary."""
        data = {
            "service_name": "orchestrator",
            "target_service": "retrieval",
            "allowed_endpoints": ["/internal/*"],
            "iss": "test-issuer",
            "aud": "retrieval",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
            "jti": "test-jti",
        }

        claims = ServiceTokenClaims.from_dict(data)

        assert claims.service_name == "orchestrator"
        assert claims.target_service == "retrieval"
        assert claims.token_type == TokenType.SERVICE

    def test_can_access_endpoint_exact_match(self):
        """Should allow exact endpoint match."""
        claims = ServiceTokenClaims(
            service_name="orchestrator",
            target_service="retrieval",
            allowed_endpoints=["/internal/search"],
        )

        assert claims.can_access_endpoint("/internal/search") is True
        assert claims.can_access_endpoint("/internal/other") is False

    def test_can_access_endpoint_wildcard(self):
        """Should allow wildcard endpoint match."""
        claims = ServiceTokenClaims(
            service_name="orchestrator",
            target_service="retrieval",
            allowed_endpoints=["/internal/*"],
        )

        assert claims.can_access_endpoint("/internal/search") is True
        assert claims.can_access_endpoint("/internal/rerank") is True
        assert claims.can_access_endpoint("/api/v1/search") is False

    def test_can_access_endpoint_multiple_patterns(self):
        """Should match against multiple patterns."""
        claims = ServiceTokenClaims(
            service_name="orchestrator",
            target_service="retrieval",
            allowed_endpoints=["/internal/*", "/api/v1/search/*"],
        )

        assert claims.can_access_endpoint("/internal/search") is True
        assert claims.can_access_endpoint("/api/v1/search/documents") is True
        assert claims.can_access_endpoint("/api/v1/admin") is False


# JWTHandler Service Token Tests
class TestJWTHandlerServiceTokens:
    """Tests for JWTHandler service token methods."""

    def test_create_service_token(self, jwt_handler):
        """Should create valid service token."""
        token = jwt_handler.create_service_token(
            service_name="orchestrator",
            target_service="retrieval",
            allowed_endpoints=["/internal/*"],
        )

        assert token is not None
        assert isinstance(token, str)

        # Decode and verify structure
        payload = jwt_handler.decode_token_unverified(token)
        assert payload["service_name"] == "orchestrator"
        assert payload["target_service"] == "retrieval"
        assert payload["token_type"] == "service"
        assert payload["aud"] == "retrieval"

    def test_create_service_token_custom_ttl(self, jwt_handler):
        """Should create token with custom TTL."""
        token = jwt_handler.create_service_token(
            service_name="orchestrator",
            target_service="retrieval",
            expires_delta=timedelta(minutes=1),
        )

        payload = jwt_handler.decode_token_unverified(token)
        exp = payload["exp"]
        iat = payload["iat"]

        # TTL should be approximately 60 seconds
        assert 55 <= (exp - iat) <= 65

    def test_verify_service_token(self, jwt_handler):
        """Should verify valid service token."""
        token = jwt_handler.create_service_token(
            service_name="orchestrator",
            target_service="retrieval",
            allowed_endpoints=["/internal/*"],
        )

        claims = jwt_handler.verify_service_token(
            token=token,
            expected_audience="retrieval",
        )

        assert claims.service_name == "orchestrator"
        assert claims.target_service == "retrieval"
        assert claims.token_type == TokenType.SERVICE

    def test_verify_service_token_with_endpoint_check(self, jwt_handler):
        """Should verify token and check endpoint authorization."""
        token = jwt_handler.create_service_token(
            service_name="orchestrator",
            target_service="retrieval",
            allowed_endpoints=["/internal/*"],
        )

        # Should succeed for allowed endpoint
        claims = jwt_handler.verify_service_token(
            token=token,
            expected_audience="retrieval",
            endpoint="/internal/search",
        )
        assert claims.service_name == "orchestrator"

        # Should fail for unauthorized endpoint
        with pytest.raises(TokenInvalidError, match="not authorized for endpoint"):
            jwt_handler.verify_service_token(
                token=token,
                expected_audience="retrieval",
                endpoint="/admin/secrets",
            )

    def test_verify_service_token_wrong_audience(self, jwt_handler):
        """Should reject token with wrong audience."""
        token = jwt_handler.create_service_token(
            service_name="orchestrator",
            target_service="retrieval",
        )

        with pytest.raises(TokenInvalidError, match="audience"):
            jwt_handler.verify_service_token(
                token=token,
                expected_audience="ingestion",  # Wrong audience
            )

    def test_verify_expired_service_token(self, jwt_handler):
        """Should reject expired service token."""
        token = jwt_handler.create_service_token(
            service_name="orchestrator",
            target_service="retrieval",
            expires_delta=timedelta(seconds=-10),  # Already expired
        )

        with pytest.raises(TokenExpiredError):
            jwt_handler.verify_service_token(
                token=token,
                expected_audience="retrieval",
            )

    def test_verify_non_service_token(self, jwt_handler):
        """Should reject non-service token."""
        from uuid import uuid4

        from ..models import TokenClaims

        # Create a user token
        user_claims = TokenClaims(
            sub=uuid4(),
            tenant_id=uuid4(),
            roles=["user"],
        )
        user_token = jwt_handler.create_access_token(user_claims)

        # Should reject - either because it's missing service claims or wrong token type
        with pytest.raises(TokenInvalidError):
            jwt_handler.verify_service_token(
                token=user_token,
                expected_audience="retrieval",
            )

    def test_is_service_token(self, jwt_handler):
        """Should correctly identify service tokens."""
        service_token = jwt_handler.create_service_token(
            service_name="orchestrator",
            target_service="retrieval",
        )

        assert jwt_handler.is_service_token(service_token) is True

        # User token should not be identified as service token
        from uuid import uuid4

        from ..models import TokenClaims

        user_claims = TokenClaims(sub=uuid4(), tenant_id=uuid4())
        user_token = jwt_handler.create_access_token(user_claims)

        assert jwt_handler.is_service_token(user_token) is False


# ServiceAuthSettings Tests
class TestServiceAuthSettings:
    """Tests for ServiceAuthSettings configuration."""

    def test_default_settings(self):
        """Should have sensible defaults."""
        settings = ServiceAuthSettings()

        assert settings.enabled is True
        assert settings.token_ttl_seconds == 300
        assert "/health" in settings.exclude_paths
        assert "/metrics" in settings.exclude_paths

    def test_custom_settings(self):
        """Should accept custom settings."""
        settings = ServiceAuthSettings(
            service_name="my-service",
            enabled=False,
            token_ttl_seconds=600,
            trusted_services=["service-a", "service-b"],
        )

        assert settings.service_name == "my-service"
        assert settings.enabled is False
        assert settings.token_ttl_seconds == 600
        assert settings.trusted_services == ["service-a", "service-b"]


# Authorization Matrix Tests
class TestAuthorizationMatrix:
    """Tests for authorization matrix functions."""

    def test_get_allowed_endpoints(self):
        """Should return allowed endpoints for service pair."""
        endpoints = get_allowed_endpoints("orchestrator", "retrieval")

        assert "/internal/*" in endpoints or any("/internal" in e for e in endpoints)

    def test_get_allowed_endpoints_unknown_service(self):
        """Should return empty list for unknown service."""
        endpoints = get_allowed_endpoints("unknown", "retrieval")

        assert endpoints == []

    def test_is_service_authorized(self):
        """Should check service authorization correctly."""
        # Orchestrator should be able to call retrieval internal endpoints
        assert is_service_authorized("orchestrator", "retrieval", "/internal/search") is True

        # Unknown service should not be authorized
        assert is_service_authorized("unknown", "retrieval", "/internal/search") is False

    def test_custom_authorization_matrix(self):
        """Should use custom authorization matrix."""
        custom_matrix = {
            "service-a": {
                "service-b": ["/custom/*"],
            },
        }

        assert (
            is_service_authorized("service-a", "service-b", "/custom/endpoint", custom_matrix)
            is True
        )

        assert (
            is_service_authorized("service-a", "service-b", "/other/endpoint", custom_matrix)
            is False
        )


# ServiceAuthMiddleware Tests
class TestServiceAuthMiddleware:
    """Tests for ServiceAuthMiddleware."""

    @pytest.fixture
    def app_with_middleware(self, jwt_handler, service_auth_settings):
        """Create FastAPI app with service auth middleware."""
        from fastapi import Request as FastAPIRequest

        app = FastAPI()
        app.add_middleware(
            ServiceAuthMiddleware,
            handler=jwt_handler,
            settings=service_auth_settings,
        )

        @app.get("/health")
        async def health():
            return {"status": "healthy"}

        @app.get("/internal/search")
        async def internal_search(request: FastAPIRequest):
            caller = get_caller_service(request)
            return {"caller": caller}

        @app.get("/api/v1/public")
        async def public_endpoint():
            return {"public": True}

        return app

    def test_health_endpoint_no_auth(self, app_with_middleware):
        """Health endpoint should not require auth."""
        client = TestClient(app_with_middleware)
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_internal_endpoint_requires_auth(self, app_with_middleware):
        """Internal endpoints should require service auth."""
        client = TestClient(app_with_middleware)
        response = client.get("/internal/search")

        assert response.status_code == 401

    def test_internal_endpoint_with_valid_auth(self, app_with_middleware, jwt_handler):
        """Internal endpoints should accept valid service auth."""
        client = TestClient(app_with_middleware)

        token = jwt_handler.create_service_token(
            service_name="orchestrator",
            target_service="retrieval",
            allowed_endpoints=["/internal/*"],
        )

        response = client.get(
            "/internal/search",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json()["caller"] == "orchestrator"

    def test_internal_endpoint_with_expired_token(self, app_with_middleware, jwt_handler):
        """Should reject expired service tokens."""
        client = TestClient(app_with_middleware)

        token = jwt_handler.create_service_token(
            service_name="orchestrator",
            target_service="retrieval",
            expires_delta=timedelta(seconds=-10),
        )

        response = client.get(
            "/internal/search",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 401

    def test_internal_endpoint_untrusted_service(self, app_with_middleware, jwt_handler):
        """Should reject tokens from untrusted services."""
        client = TestClient(app_with_middleware)

        token = jwt_handler.create_service_token(
            service_name="untrusted-service",
            target_service="retrieval",
            allowed_endpoints=["/internal/*"],
        )

        response = client.get(
            "/internal/search",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403

    def test_public_endpoint_no_service_auth(self, app_with_middleware):
        """Public endpoints should not require service auth."""
        client = TestClient(app_with_middleware)
        response = client.get("/api/v1/public")

        # Should pass through (no service auth required for non-internal paths)
        assert response.status_code == 200


# AuthenticatedServiceClient Tests
class TestAuthenticatedServiceClient:
    """Tests for AuthenticatedServiceClient."""

    @pytest.fixture
    def service_client(self, jwt_handler):
        """Create service client for testing."""
        from ..service_client import AuthenticatedServiceClient

        settings = ServiceAuthSettings(service_name="orchestrator")

        return AuthenticatedServiceClient(
            base_url="http://retrieval:8002",
            target_service="retrieval",
            handler=jwt_handler,
            settings=settings,
        )

    @pytest.mark.asyncio
    async def test_client_adds_auth_header(self, service_client):
        """Client should add Authorization header to requests."""
        async with service_client:
            # Mock the underlying httpx client
            service_client._client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            service_client._client.get.return_value = mock_response

            await service_client.get("/internal/search")

            # Verify auth header was added
            call_kwargs = service_client._client.get.call_args
            headers = call_kwargs.kwargs.get("headers", {})
            assert "Authorization" in headers
            assert headers["Authorization"].startswith("Bearer ")

    @pytest.mark.asyncio
    async def test_client_caches_token(self, service_client):
        """Client should cache tokens."""
        async with service_client:
            # Get token twice
            token1 = service_client._get_or_create_token()
            token2 = service_client._get_or_create_token()

            # Should be the same cached token
            assert token1 == token2

    @pytest.mark.asyncio
    async def test_client_clears_cache(self, service_client):
        """Client should allow clearing token cache."""
        async with service_client:
            token1 = service_client._get_or_create_token()
            service_client.clear_token_cache()
            token2 = service_client._get_or_create_token()

            # Should be different tokens after cache clear
            assert token1 != token2

    @pytest.mark.asyncio
    async def test_client_not_initialized_error(self, service_client):
        """Client should raise error if not initialized."""
        with pytest.raises(RuntimeError, match="not initialized"):
            await service_client.get("/internal/search")
