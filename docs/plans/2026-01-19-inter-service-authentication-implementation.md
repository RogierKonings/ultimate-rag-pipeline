# Inter-Service Authentication Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement JWT-based service-to-service authentication so only authorized services can call internal APIs.

**Architecture:** Extend the existing `JWTHandler` with service token methods. Create an `AuthenticatedServiceClient` wrapper for outbound calls and `ServiceAuthMiddleware` for inbound validation. Use RBAC with endpoint-level permissions.

**Tech Stack:** PyJWT, cryptography, FastAPI, httpx, Pydantic, pytest

---

## Task 1: Add ServiceTokenPayload Model

**Files:**
- Modify: `services/shared/security/jwt/models.py`
- Test: `tests/security/test_service_auth.py`

**Step 1: Write the failing test**

Create `tests/security/test_service_auth.py`:

```python
"""Tests for service-to-service authentication."""

import pytest
from datetime import datetime, UTC, timedelta


class TestServiceTokenPayload:
    """Tests for ServiceTokenPayload model."""

    def test_create_service_token_payload(self):
        """Should create payload with required fields."""
        from shared.security.jwt.models import ServiceTokenPayload

        now = datetime.now(UTC)
        payload = ServiceTokenPayload(
            issuer="orchestrator",
            subject="orchestrator",
            audience="retrieval",
            roles=["orchestrator-role"],
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
            jti="test-jti-123",
        )

        assert payload.issuer == "orchestrator"
        assert payload.subject == "orchestrator"
        assert payload.audience == "retrieval"
        assert payload.roles == ["orchestrator-role"]
        assert payload.jti == "test-jti-123"

    def test_service_token_payload_to_dict(self):
        """Should convert payload to dict for JWT encoding."""
        from shared.security.jwt.models import ServiceTokenPayload

        now = datetime.now(UTC)
        payload = ServiceTokenPayload(
            issuer="orchestrator",
            subject="orchestrator",
            audience="retrieval",
            roles=["orchestrator-role"],
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
            jti="test-jti-123",
        )

        data = payload.to_dict()

        assert data["iss"] == "orchestrator"
        assert data["sub"] == "orchestrator"
        assert data["aud"] == "retrieval"
        assert data["roles"] == ["orchestrator-role"]
        assert data["jti"] == "test-jti-123"
        assert "iat" in data
        assert "exp" in data

    def test_service_token_payload_from_dict(self):
        """Should create payload from decoded JWT dict."""
        from shared.security.jwt.models import ServiceTokenPayload

        now = datetime.now(UTC)
        data = {
            "iss": "orchestrator",
            "sub": "orchestrator",
            "aud": "retrieval",
            "roles": ["orchestrator-role"],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "jti": "test-jti-123",
        }

        payload = ServiceTokenPayload.from_dict(data)

        assert payload.issuer == "orchestrator"
        assert payload.audience == "retrieval"
        assert payload.roles == ["orchestrator-role"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/security/test_service_auth.py -v`
Expected: FAIL with "cannot import name 'ServiceTokenPayload'"

**Step 3: Write the implementation**

Add to `services/shared/security/jwt/models.py` after `TokenRevocationRequest`:

```python
@dataclass
class ServiceTokenPayload:
    """
    Payload for service-to-service JWT tokens.

    Unlike user tokens, service tokens:
    - Use service name as issuer/subject (not user ID)
    - Include target service as audience
    - Include service roles for RBAC
    - Have shorter TTL (5 minutes default)
    """

    issuer: str
    subject: str
    audience: str
    roles: list[str]
    issued_at: datetime
    expires_at: datetime
    jti: str

    def to_dict(self) -> dict:
        """Convert to dict for JWT encoding."""
        return {
            "iss": self.issuer,
            "sub": self.subject,
            "aud": self.audience,
            "roles": self.roles,
            "iat": int(self.issued_at.timestamp()),
            "exp": int(self.expires_at.timestamp()),
            "jti": self.jti,
            "token_type": "service",
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ServiceTokenPayload":
        """Create from decoded JWT payload."""
        return cls(
            issuer=data["iss"],
            subject=data["sub"],
            audience=data["aud"],
            roles=data.get("roles", []),
            issued_at=datetime.fromtimestamp(data["iat"], tz=UTC),
            expires_at=datetime.fromtimestamp(data["exp"], tz=UTC),
            jti=data["jti"],
        )
```

Also add the import at the top of the file:

```python
from dataclasses import dataclass
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/security/test_service_auth.py::TestServiceTokenPayload -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add services/shared/security/jwt/models.py tests/security/test_service_auth.py
git commit -m "feat(auth): add ServiceTokenPayload model for service-to-service auth"
```

---

## Task 2: Extend JWTHandler with create_service_token

**Files:**
- Modify: `services/shared/security/jwt/handler.py`
- Test: `tests/security/test_service_auth.py`

**Step 1: Write the failing test**

Add to `tests/security/test_service_auth.py`:

```python
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend


@pytest.fixture
def rsa_keypair():
    """Generate RSA keypair for testing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


@pytest.fixture
def jwt_handler(rsa_keypair):
    """Create JWTHandler with test keys."""
    from shared.security.jwt.config import JWTSettings
    from shared.security.jwt.handler import JWTHandler

    private_pem, public_pem = rsa_keypair
    settings = JWTSettings(
        secret_key=private_pem,
        public_key=public_pem,
        algorithm="RS256",
        issuer="rag-pipeline",
    )
    return JWTHandler(settings)


class TestJWTHandlerServiceTokens:
    """Tests for service token creation and verification."""

    def test_create_service_token(self, jwt_handler, rsa_keypair):
        """Should create valid JWT for service-to-service auth."""
        token = jwt_handler.create_service_token(
            source_service="orchestrator",
            target_service="retrieval",
            roles=["orchestrator-role"],
        )

        assert token is not None
        assert isinstance(token, str)

        # Decode and verify structure
        _, public_pem = rsa_keypair
        decoded = jwt.decode(token, public_pem, algorithms=["RS256"], audience="retrieval")

        assert decoded["iss"] == "orchestrator"
        assert decoded["sub"] == "orchestrator"
        assert decoded["aud"] == "retrieval"
        assert decoded["roles"] == ["orchestrator-role"]
        assert decoded["token_type"] == "service"
        assert "jti" in decoded
        assert "exp" in decoded
        assert "iat" in decoded

    def test_create_service_token_custom_ttl(self, jwt_handler):
        """Should respect custom TTL."""
        import time

        token = jwt_handler.create_service_token(
            source_service="orchestrator",
            target_service="retrieval",
            roles=["orchestrator-role"],
            ttl_seconds=60,  # 1 minute
        )

        decoded = jwt.decode(token, options={"verify_signature": False})
        ttl = decoded["exp"] - decoded["iat"]

        assert ttl == 60

    def test_create_service_token_default_ttl(self, jwt_handler):
        """Should use 5 minute default TTL."""
        token = jwt_handler.create_service_token(
            source_service="orchestrator",
            target_service="retrieval",
            roles=["orchestrator-role"],
        )

        decoded = jwt.decode(token, options={"verify_signature": False})
        ttl = decoded["exp"] - decoded["iat"]

        assert ttl == 300  # 5 minutes
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/security/test_service_auth.py::TestJWTHandlerServiceTokens -v`
Expected: FAIL with "JWTHandler has no attribute 'create_service_token'"

**Step 3: Write the implementation**

Add to `services/shared/security/jwt/handler.py` in the `JWTHandler` class, after `create_token_pair`:

```python
def create_service_token(
    self,
    source_service: str,
    target_service: str,
    roles: list[str],
    ttl_seconds: int = 300,
) -> str:
    """
    Create a JWT for service-to-service authentication.

    Args:
        source_service: Name of the calling service (becomes iss/sub)
        target_service: Name of the target service (becomes aud)
        roles: Service roles for RBAC permission checks
        ttl_seconds: Token lifetime in seconds (default 5 minutes)

    Returns:
        Signed JWT string

    Example:
        ```python
        token = handler.create_service_token(
            source_service="orchestrator",
            target_service="retrieval",
            roles=["orchestrator-role"],
        )
        headers = {"Authorization": f"Bearer {token}"}
        ```
    """
    if not self._private_key:
        raise JWTError("Private key not configured for token creation")

    now = datetime.now(UTC)
    expires = now + timedelta(seconds=ttl_seconds)

    payload = {
        "iss": source_service,
        "sub": source_service,
        "aud": target_service,
        "roles": roles,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": str(uuid.uuid4()),
        "token_type": "service",
    }

    return jwt.encode(
        payload,
        self._private_key,
        algorithm=self.settings.algorithm.value,
    )
```

Also update the import at the top to include `timedelta`:

```python
from datetime import UTC, datetime, timedelta
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/security/test_service_auth.py::TestJWTHandlerServiceTokens -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add services/shared/security/jwt/handler.py tests/security/test_service_auth.py
git commit -m "feat(auth): add create_service_token to JWTHandler"
```

---

## Task 3: Add verify_service_token to JWTHandler

**Files:**
- Modify: `services/shared/security/jwt/handler.py`
- Test: `tests/security/test_service_auth.py`

**Step 1: Write the failing test**

Add to `tests/security/test_service_auth.py` in `TestJWTHandlerServiceTokens`:

```python
def test_verify_service_token_valid(self, jwt_handler):
    """Should verify valid service token and return payload."""
    from shared.security.jwt.models import ServiceTokenPayload

    token = jwt_handler.create_service_token(
        source_service="orchestrator",
        target_service="retrieval",
        roles=["orchestrator-role"],
    )

    payload = jwt_handler.verify_service_token(token, expected_audience="retrieval")

    assert isinstance(payload, ServiceTokenPayload)
    assert payload.issuer == "orchestrator"
    assert payload.subject == "orchestrator"
    assert payload.audience == "retrieval"
    assert payload.roles == ["orchestrator-role"]

def test_verify_service_token_wrong_audience(self, jwt_handler):
    """Should reject token with wrong audience."""
    from shared.security.jwt.handler import TokenInvalidError

    token = jwt_handler.create_service_token(
        source_service="orchestrator",
        target_service="retrieval",
        roles=["orchestrator-role"],
    )

    with pytest.raises(TokenInvalidError, match="audience"):
        jwt_handler.verify_service_token(token, expected_audience="ingestion")

def test_verify_service_token_expired(self, jwt_handler):
    """Should reject expired token."""
    from shared.security.jwt.handler import TokenExpiredError
    import time

    token = jwt_handler.create_service_token(
        source_service="orchestrator",
        target_service="retrieval",
        roles=["orchestrator-role"],
        ttl_seconds=-10,  # Already expired
    )

    with pytest.raises(TokenExpiredError):
        jwt_handler.verify_service_token(token, expected_audience="retrieval")

def test_verify_service_token_invalid_signature(self, jwt_handler):
    """Should reject token with invalid signature."""
    from shared.security.jwt.handler import TokenInvalidError

    # Create token with different key
    other_private = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    other_private_pem = other_private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    fake_token = jwt.encode(
        {"iss": "orchestrator", "sub": "orchestrator", "aud": "retrieval",
         "roles": [], "iat": 0, "exp": 9999999999, "jti": "x", "token_type": "service"},
        other_private_pem,
        algorithm="RS256",
    )

    with pytest.raises(TokenInvalidError):
        jwt_handler.verify_service_token(fake_token, expected_audience="retrieval")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/security/test_service_auth.py::TestJWTHandlerServiceTokens::test_verify_service_token_valid -v`
Expected: FAIL with "JWTHandler has no attribute 'verify_service_token'"

**Step 3: Write the implementation**

Add to `services/shared/security/jwt/handler.py` in the `JWTHandler` class, after `create_service_token`:

```python
def verify_service_token(
    self,
    token: str,
    expected_audience: str,
) -> "ServiceTokenPayload":
    """
    Verify a service-to-service JWT token.

    Args:
        token: JWT token string from Authorization header
        expected_audience: This service's name (must match token's aud claim)

    Returns:
        Validated ServiceTokenPayload with issuer, roles, etc.

    Raises:
        TokenExpiredError: Token has expired
        TokenInvalidError: Signature invalid, wrong audience, or malformed

    Example:
        ```python
        token = request.headers.get("Authorization").removeprefix("Bearer ")
        payload = handler.verify_service_token(token, "retrieval")
        print(f"Request from {payload.issuer} with roles {payload.roles}")
        ```
    """
    from .models import ServiceTokenPayload

    if not self._public_key:
        raise JWTError("Public key not configured for token verification")

    try:
        payload = jwt.decode(
            token,
            self._public_key,
            algorithms=[self.settings.algorithm.value],
            audience=expected_audience,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": True,
                "require": ["exp", "iat", "iss", "sub", "aud", "jti", "roles"],
            },
        )

        # Verify it's a service token
        if payload.get("token_type") != "service":
            raise TokenInvalidError("Not a service token")

        return ServiceTokenPayload.from_dict(payload)

    except ExpiredSignatureError:
        raise TokenExpiredError("Service token has expired") from None
    except InvalidAudienceError:
        raise TokenInvalidError(f"Invalid audience: expected {expected_audience}") from None
    except (InvalidSignatureError, DecodeError):
        raise TokenInvalidError("Invalid token signature") from None
    except InvalidTokenError as e:
        raise TokenInvalidError(f"Invalid service token: {e}") from e
```

Also add `ServiceTokenPayload` to the imports at the top:

```python
from .models import TokenClaims, TokenPair, TokenType, ServiceTokenPayload
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/security/test_service_auth.py::TestJWTHandlerServiceTokens -v`
Expected: PASS (7 tests)

**Step 5: Commit**

```bash
git add services/shared/security/jwt/handler.py tests/security/test_service_auth.py
git commit -m "feat(auth): add verify_service_token to JWTHandler"
```

---

## Task 4: Create RBAC Config Loader

**Files:**
- Create: `services/shared/security/service_auth/__init__.py`
- Create: `services/shared/security/service_auth/config.py`
- Create: `config/service_auth.yaml`
- Test: `tests/security/test_service_auth.py`

**Step 1: Write the failing test**

Add to `tests/security/test_service_auth.py`:

```python
class TestServiceAuthConfig:
    """Tests for service auth RBAC configuration."""

    def test_load_config_from_yaml(self, tmp_path):
        """Should load RBAC config from YAML file."""
        from shared.security.service_auth.config import ServiceAuthConfig

        config_content = """
service_roles:
  orchestrator-role:
    permissions:
      - retrieval:search
      - retrieval:rerank

services:
  orchestrator:
    roles: [orchestrator-role]
  retrieval:
    roles: []
"""
        config_file = tmp_path / "service_auth.yaml"
        config_file.write_text(config_content)

        config = ServiceAuthConfig.from_yaml(str(config_file))

        assert "orchestrator-role" in config.service_roles
        assert "retrieval:search" in config.service_roles["orchestrator-role"].permissions
        assert config.services["orchestrator"].roles == ["orchestrator-role"]

    def test_has_permission(self, tmp_path):
        """Should check if roles have required permission."""
        from shared.security.service_auth.config import ServiceAuthConfig

        config_content = """
service_roles:
  orchestrator-role:
    permissions:
      - retrieval:search
      - retrieval:rerank

services:
  orchestrator:
    roles: [orchestrator-role]
"""
        config_file = tmp_path / "service_auth.yaml"
        config_file.write_text(config_content)

        config = ServiceAuthConfig.from_yaml(str(config_file))

        assert config.has_permission(["orchestrator-role"], "retrieval:search")
        assert config.has_permission(["orchestrator-role"], "retrieval:rerank")
        assert not config.has_permission(["orchestrator-role"], "ingestion:ingest")
        assert not config.has_permission(["unknown-role"], "retrieval:search")

    def test_get_service_roles(self, tmp_path):
        """Should get roles for a service."""
        from shared.security.service_auth.config import ServiceAuthConfig

        config_content = """
service_roles:
  orchestrator-role:
    permissions: []

services:
  orchestrator:
    roles: [orchestrator-role]
  retrieval:
    roles: []
"""
        config_file = tmp_path / "service_auth.yaml"
        config_file.write_text(config_content)

        config = ServiceAuthConfig.from_yaml(str(config_file))

        assert config.get_service_roles("orchestrator") == ["orchestrator-role"]
        assert config.get_service_roles("retrieval") == []
        assert config.get_service_roles("unknown") == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/security/test_service_auth.py::TestServiceAuthConfig -v`
Expected: FAIL with "No module named 'shared.security.service_auth'"

**Step 3: Write the implementation**

Create `services/shared/security/service_auth/__init__.py`:

```python
"""Service-to-service authentication module."""

from .config import ServiceAuthConfig, ServiceRole, ServiceConfig

__all__ = ["ServiceAuthConfig", "ServiceRole", "ServiceConfig"]
```

Create `services/shared/security/service_auth/config.py`:

```python
"""Configuration for service-to-service authentication RBAC."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ServiceRole:
    """A role that grants permissions to services."""

    permissions: list[str] = field(default_factory=list)


@dataclass
class ServiceConfig:
    """Configuration for a single service."""

    roles: list[str] = field(default_factory=list)


@dataclass
class ServiceAuthConfig:
    """
    RBAC configuration for service-to-service authentication.

    Loads from YAML file with structure:
        service_roles:
          role-name:
            permissions: [service:action, ...]
        services:
          service-name:
            roles: [role-name, ...]
    """

    service_roles: dict[str, ServiceRole] = field(default_factory=dict)
    services: dict[str, ServiceConfig] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str) -> "ServiceAuthConfig":
        """Load configuration from YAML file."""
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(config_path) as f:
            data = yaml.safe_load(f)

        # Parse service roles
        service_roles = {}
        for role_name, role_data in data.get("service_roles", {}).items():
            service_roles[role_name] = ServiceRole(
                permissions=role_data.get("permissions", []),
            )

        # Parse services
        services = {}
        for service_name, service_data in data.get("services", {}).items():
            services[service_name] = ServiceConfig(
                roles=service_data.get("roles", []),
            )

        return cls(service_roles=service_roles, services=services)

    def has_permission(self, roles: list[str], required_permission: str) -> bool:
        """Check if any of the given roles has the required permission."""
        for role_name in roles:
            role = self.service_roles.get(role_name)
            if role and required_permission in role.permissions:
                return True
        return False

    def get_service_roles(self, service_name: str) -> list[str]:
        """Get the roles assigned to a service."""
        service = self.services.get(service_name)
        return service.roles if service else []
```

Create `config/service_auth.yaml`:

```yaml
# Service-to-service authentication RBAC configuration
# See docs/plans/2026-01-19-inter-service-authentication-design.md

service_roles:
  orchestrator-role:
    permissions:
      - retrieval:search
      - retrieval:rerank
      - ingestion:status
      - llm-gateway:generate
      - llm-gateway:embed

  retrieval-role:
    permissions:
      - embedding:embed

  ingestion-role:
    permissions:
      - embedding:embed
      - retrieval:index-notify

services:
  orchestrator:
    roles: [orchestrator-role]
  retrieval:
    roles: [retrieval-role]
  ingestion:
    roles: [ingestion-role]
  embedding:
    roles: []  # Leaf service
  llm-gateway:
    roles: []  # Leaf service
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/security/test_service_auth.py::TestServiceAuthConfig -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add services/shared/security/service_auth/ config/service_auth.yaml tests/security/test_service_auth.py
git commit -m "feat(auth): add ServiceAuthConfig for RBAC configuration"
```

---

## Task 5: Create AuthenticatedServiceClient

**Files:**
- Create: `services/shared/security/service_auth/client.py`
- Modify: `services/shared/security/service_auth/__init__.py`
- Test: `tests/security/test_service_auth.py`

**Step 1: Write the failing test**

Add to `tests/security/test_service_auth.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
import time


class TestAuthenticatedServiceClient:
    """Tests for AuthenticatedServiceClient."""

    @pytest.fixture
    def mock_jwt_handler(self):
        """Create mock JWTHandler."""
        handler = MagicMock()
        handler.create_service_token.return_value = "mock-token-123"
        return handler

    def test_get_token_creates_new_token(self, mock_jwt_handler):
        """Should create token on first call."""
        from shared.security.service_auth.client import AuthenticatedServiceClient

        client = AuthenticatedServiceClient(
            jwt_handler=mock_jwt_handler,
            source_service="orchestrator",
            target_service="retrieval",
            roles=["orchestrator-role"],
            base_url="http://retrieval:8002",
        )

        token = client._get_token()

        assert token == "mock-token-123"
        mock_jwt_handler.create_service_token.assert_called_once_with(
            source_service="orchestrator",
            target_service="retrieval",
            roles=["orchestrator-role"],
        )

    def test_get_token_uses_cache(self, mock_jwt_handler):
        """Should return cached token on subsequent calls."""
        from shared.security.service_auth.client import AuthenticatedServiceClient

        client = AuthenticatedServiceClient(
            jwt_handler=mock_jwt_handler,
            source_service="orchestrator",
            target_service="retrieval",
            roles=["orchestrator-role"],
            base_url="http://retrieval:8002",
        )

        token1 = client._get_token()
        token2 = client._get_token()

        assert token1 == token2
        assert mock_jwt_handler.create_service_token.call_count == 1

    def test_get_token_refreshes_near_expiry(self, mock_jwt_handler):
        """Should refresh token when near expiry."""
        from shared.security.service_auth.client import AuthenticatedServiceClient

        client = AuthenticatedServiceClient(
            jwt_handler=mock_jwt_handler,
            source_service="orchestrator",
            target_service="retrieval",
            roles=["orchestrator-role"],
            base_url="http://retrieval:8002",
        )

        # First call
        client._get_token()

        # Simulate token near expiry (within 30s buffer)
        client._token_cache = ("old-token", time.time() + 10)

        # Should create new token
        mock_jwt_handler.create_service_token.return_value = "new-token-456"
        token = client._get_token()

        assert token == "new-token-456"
        assert mock_jwt_handler.create_service_token.call_count == 2

    @pytest.mark.asyncio
    async def test_request_adds_auth_header(self, mock_jwt_handler):
        """Should add Authorization header to requests."""
        from shared.security.service_auth.client import AuthenticatedServiceClient

        client = AuthenticatedServiceClient(
            jwt_handler=mock_jwt_handler,
            source_service="orchestrator",
            target_service="retrieval",
            roles=["orchestrator-role"],
            base_url="http://retrieval:8002",
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.request = AsyncMock()
            mock_client_class.return_value = mock_client

            await client.request("POST", "/internal/search", json={"query": "test"})

            mock_client.request.assert_called_once()
            call_kwargs = mock_client.request.call_args
            headers = call_kwargs.kwargs.get("headers", {})
            assert headers["Authorization"] == "Bearer mock-token-123"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/security/test_service_auth.py::TestAuthenticatedServiceClient -v`
Expected: FAIL with "No module named 'shared.security.service_auth.client'"

**Step 3: Write the implementation**

Create `services/shared/security/service_auth/client.py`:

```python
"""HTTP client with automatic service-to-service authentication."""

import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from shared.security.jwt.handler import JWTHandler


class AuthenticatedServiceClient:
    """
    HTTP client with automatic service-to-service authentication.

    Wraps httpx.AsyncClient to automatically add JWT auth headers
    to all requests. Tokens are cached until near expiry.

    Example:
        ```python
        client = AuthenticatedServiceClient(
            jwt_handler=jwt_handler,
            source_service="orchestrator",
            target_service="retrieval",
            roles=["orchestrator-role"],
            base_url="http://retrieval:8002",
        )

        response = await client.post("/internal/search", json={"query": "test"})
        ```
    """

    def __init__(
        self,
        jwt_handler: "JWTHandler",
        source_service: str,
        target_service: str,
        roles: list[str],
        base_url: str,
        timeout: float = 30.0,
        token_ttl_seconds: int = 300,
    ):
        """
        Initialize authenticated service client.

        Args:
            jwt_handler: JWTHandler instance for token creation
            source_service: This service's name (token issuer)
            target_service: Target service name (token audience)
            roles: Service roles for RBAC
            base_url: Base URL of target service
            timeout: Request timeout in seconds
            token_ttl_seconds: Token TTL (default 5 minutes)
        """
        self.jwt_handler = jwt_handler
        self.source_service = source_service
        self.target_service = target_service
        self.roles = roles
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token_ttl_seconds = token_ttl_seconds
        self._token_cache: tuple[str, float] | None = None

    def _get_token(self) -> str:
        """Get cached token or create new one."""
        now = time.time()

        # Check cache
        if self._token_cache:
            token, expiry = self._token_cache
            if expiry > now + 30:  # 30 second buffer before expiry
                return token

        # Create new token
        token = self.jwt_handler.create_service_token(
            source_service=self.source_service,
            target_service=self.target_service,
            roles=self.roles,
        )
        self._token_cache = (token, now + self.token_ttl_seconds)
        return token

    async def request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> httpx.Response:
        """
        Make authenticated request to target service.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path (will be joined with base_url)
            **kwargs: Additional arguments passed to httpx

        Returns:
            httpx.Response
        """
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._get_token()}"

        # Add correlation context if available
        try:
            from shared.observability.correlation import get_correlation_context

            ctx = get_correlation_context()
            if ctx:
                headers.update(ctx.to_headers())
        except ImportError:
            pass

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                **kwargs,
            )

    async def get(self, path: str, **kwargs) -> httpx.Response:
        """Make authenticated GET request."""
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> httpx.Response:
        """Make authenticated POST request."""
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs) -> httpx.Response:
        """Make authenticated PUT request."""
        return await self.request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs) -> httpx.Response:
        """Make authenticated DELETE request."""
        return await self.request("DELETE", path, **kwargs)
```

Update `services/shared/security/service_auth/__init__.py`:

```python
"""Service-to-service authentication module."""

from .client import AuthenticatedServiceClient
from .config import ServiceAuthConfig, ServiceConfig, ServiceRole

__all__ = [
    "AuthenticatedServiceClient",
    "ServiceAuthConfig",
    "ServiceConfig",
    "ServiceRole",
]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/security/test_service_auth.py::TestAuthenticatedServiceClient -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add services/shared/security/service_auth/ tests/security/test_service_auth.py
git commit -m "feat(auth): add AuthenticatedServiceClient with token caching"
```

---

## Task 6: Create ServiceAuthMiddleware

**Files:**
- Create: `services/shared/security/service_auth/middleware.py`
- Modify: `services/shared/security/service_auth/__init__.py`
- Test: `tests/security/test_service_auth.py`

**Step 1: Write the failing test**

Add to `tests/security/test_service_auth.py`:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestServiceAuthMiddleware:
    """Tests for ServiceAuthMiddleware."""

    @pytest.fixture
    def test_app(self, jwt_handler, tmp_path):
        """Create test FastAPI app with middleware."""
        from shared.security.service_auth.middleware import ServiceAuthMiddleware
        from shared.security.service_auth.config import ServiceAuthConfig

        # Create config
        config_content = """
service_roles:
  orchestrator-role:
    permissions:
      - retrieval:search

services:
  orchestrator:
    roles: [orchestrator-role]
"""
        config_file = tmp_path / "service_auth.yaml"
        config_file.write_text(config_content)
        auth_config = ServiceAuthConfig.from_yaml(str(config_file))

        # Endpoint permissions
        endpoint_permissions = {
            "/internal/search": "retrieval:search",
            "/internal/admin/*": "retrieval:admin",
        }

        app = FastAPI()
        app.add_middleware(
            ServiceAuthMiddleware,
            jwt_handler=jwt_handler,
            service_name="retrieval",
            endpoint_permissions=endpoint_permissions,
            auth_config=auth_config,
        )

        @app.get("/health")
        def health():
            return {"status": "healthy"}

        @app.get("/internal/search")
        def internal_search():
            return {"results": []}

        @app.get("/internal/admin/users")
        def internal_admin():
            return {"users": []}

        return app

    def test_health_endpoint_no_auth(self, test_app):
        """Health endpoint should not require auth."""
        client = TestClient(test_app)
        response = client.get("/health")

        assert response.status_code == 200

    def test_internal_endpoint_requires_auth(self, test_app):
        """Internal endpoint should require auth."""
        client = TestClient(test_app)
        response = client.get("/internal/search")

        assert response.status_code == 401
        assert "Missing service token" in response.json()["detail"]

    def test_internal_endpoint_with_valid_auth(self, test_app, jwt_handler):
        """Internal endpoint should accept valid auth."""
        client = TestClient(test_app)

        token = jwt_handler.create_service_token(
            source_service="orchestrator",
            target_service="retrieval",
            roles=["orchestrator-role"],
        )

        response = client.get(
            "/internal/search",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200

    def test_internal_endpoint_wrong_permission(self, test_app, jwt_handler):
        """Should reject request without required permission."""
        client = TestClient(test_app)

        token = jwt_handler.create_service_token(
            source_service="orchestrator",
            target_service="retrieval",
            roles=["orchestrator-role"],  # Has retrieval:search but not retrieval:admin
        )

        response = client.get(
            "/internal/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403
        assert "Missing permission" in response.json()["detail"]

    def test_internal_endpoint_expired_token(self, test_app, jwt_handler):
        """Should reject expired token."""
        client = TestClient(test_app)

        token = jwt_handler.create_service_token(
            source_service="orchestrator",
            target_service="retrieval",
            roles=["orchestrator-role"],
            ttl_seconds=-10,  # Already expired
        )

        response = client.get(
            "/internal/search",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/security/test_service_auth.py::TestServiceAuthMiddleware -v`
Expected: FAIL with "No module named 'shared.security.service_auth.middleware'"

**Step 3: Write the implementation**

Create `services/shared/security/service_auth/middleware.py`:

```python
"""FastAPI middleware for service-to-service authentication."""

import fnmatch
import logging
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from shared.security.jwt.handler import JWTHandler
    from shared.security.service_auth.config import ServiceAuthConfig

logger = logging.getLogger(__name__)


class ServiceAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware for validating service-to-service authentication.

    Protects endpoints under /internal/* prefix by requiring
    valid service JWT tokens and checking RBAC permissions.

    Example:
        ```python
        app.add_middleware(
            ServiceAuthMiddleware,
            jwt_handler=jwt_handler,
            service_name="retrieval",
            endpoint_permissions={"/internal/search": "retrieval:search"},
            auth_config=auth_config,
        )
        ```
    """

    def __init__(
        self,
        app,
        jwt_handler: "JWTHandler",
        service_name: str,
        endpoint_permissions: dict[str, str],
        auth_config: "ServiceAuthConfig",
        exclude_paths: list[str] | None = None,
    ):
        """
        Initialize middleware.

        Args:
            app: FastAPI application
            jwt_handler: JWTHandler for token verification
            service_name: This service's name (expected token audience)
            endpoint_permissions: Map of path patterns to required permissions
            auth_config: RBAC configuration
            exclude_paths: Paths to skip auth (default: health, metrics, docs)
        """
        super().__init__(app)
        self.jwt_handler = jwt_handler
        self.service_name = service_name
        self.endpoint_permissions = endpoint_permissions
        self.auth_config = auth_config
        self.exclude_paths = exclude_paths or [
            "/health",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]

    async def dispatch(self, request: Request, call_next):
        """Process request through auth middleware."""
        path = request.url.path

        # Skip non-internal paths
        if not path.startswith("/internal/"):
            return await call_next(request)

        # Skip excluded paths
        if any(path.startswith(p) for p in self.exclude_paths):
            return await call_next(request)

        # Extract token
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.warning(
                "service_auth_missing",
                extra={
                    "target": self.service_name,
                    "endpoint": path,
                    "client_host": request.client.host if request.client else "unknown",
                },
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing service token"},
            )

        token = auth_header.removeprefix("Bearer ")

        # Verify token
        try:
            from shared.security.jwt.handler import TokenExpiredError, TokenInvalidError

            payload = self.jwt_handler.verify_service_token(token, self.service_name)
        except TokenExpiredError:
            logger.warning(
                "service_auth_failed",
                extra={"reason": "expired", "endpoint": path},
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "Service token expired"},
            )
        except TokenInvalidError as e:
            logger.warning(
                "service_auth_failed",
                extra={"reason": str(e), "endpoint": path},
            )
            return JSONResponse(
                status_code=401,
                content={"detail": str(e)},
            )

        # Check permission
        required_permission = self._get_required_permission(path)
        if required_permission and not self.auth_config.has_permission(
            payload.roles, required_permission
        ):
            logger.warning(
                "service_auth_denied",
                extra={
                    "caller": payload.issuer,
                    "target": self.service_name,
                    "endpoint": path,
                    "required_permission": required_permission,
                    "caller_roles": payload.roles,
                },
            )
            return JSONResponse(
                status_code=403,
                content={"detail": f"Missing permission: {required_permission}"},
            )

        # Success - add caller info to request state
        logger.debug(
            "service_auth_success",
            extra={
                "caller": payload.issuer,
                "target": self.service_name,
                "endpoint": path,
            },
        )
        request.state.caller_service = payload.issuer
        request.state.caller_roles = payload.roles

        return await call_next(request)

    def _get_required_permission(self, path: str) -> str | None:
        """Match path to required permission using patterns."""
        for pattern, permission in self.endpoint_permissions.items():
            if fnmatch.fnmatch(path, pattern):
                return permission
        return None
```

Update `services/shared/security/service_auth/__init__.py`:

```python
"""Service-to-service authentication module."""

from .client import AuthenticatedServiceClient
from .config import ServiceAuthConfig, ServiceConfig, ServiceRole
from .middleware import ServiceAuthMiddleware

__all__ = [
    "AuthenticatedServiceClient",
    "ServiceAuthConfig",
    "ServiceConfig",
    "ServiceRole",
    "ServiceAuthMiddleware",
]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/security/test_service_auth.py::TestServiceAuthMiddleware -v`
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add services/shared/security/service_auth/ tests/security/test_service_auth.py
git commit -m "feat(auth): add ServiceAuthMiddleware for internal endpoint protection"
```

---

## Task 7: Create Key Generation Script

**Files:**
- Create: `scripts/generate-service-keys.sh`

**Step 1: Write the script**

Create `scripts/generate-service-keys.sh`:

```bash
#!/bin/bash
set -euo pipefail

# Service authentication key generation script
# Generates RSA keypairs for each service in the RAG pipeline

SERVICES="orchestrator retrieval ingestion embedding llm-gateway"
OUTPUT_DIR="${1:-./service-keys}"

echo "Generating service authentication keys..."
echo "Output directory: $OUTPUT_DIR"

mkdir -p "$OUTPUT_DIR"

for service in $SERVICES; do
    echo "  Generating keypair for $service..."
    openssl genrsa -out "$OUTPUT_DIR/${service}.key" 2048 2>/dev/null
    openssl rsa -in "$OUTPUT_DIR/${service}.key" -pubout -out "$OUTPUT_DIR/${service}.pub" 2>/dev/null
done

echo ""
echo "Keys generated successfully!"
echo ""
echo "Files created:"
ls -la "$OUTPUT_DIR"
echo ""
echo "To create Kubernetes secret, run:"
echo ""
echo "  kubectl create secret generic service-auth-keys \\"
echo "    --namespace=rag-pipeline \\"
for service in $SERVICES; do
    echo "    --from-file=${service}.key=$OUTPUT_DIR/${service}.key \\"
    echo "    --from-file=${service}.pub=$OUTPUT_DIR/${service}.pub \\"
done
echo "    --dry-run=client -o yaml > k8s/base/security/service-auth-keys.yaml"
echo ""
echo "WARNING: Keep these keys secure! Do not commit to version control."
```

**Step 2: Make executable and test**

Run: `chmod +x scripts/generate-service-keys.sh && ./scripts/generate-service-keys.sh /tmp/test-keys`
Expected: Keys generated for all services

**Step 3: Verify keys work**

Run: `openssl rsa -in /tmp/test-keys/orchestrator.key -check -noout`
Expected: "RSA key ok"

**Step 4: Commit**

```bash
git add scripts/generate-service-keys.sh
git commit -m "feat(auth): add service key generation script"
```

---

## Task 8: Create Kubernetes Secret Template

**Files:**
- Create: `k8s/base/security/service-auth-keys.yaml`
- Create: `k8s/base/security/kustomization.yaml`

**Step 1: Create secret template**

Create `k8s/base/security/service-auth-keys.yaml`:

```yaml
# Service authentication keys - TEMPLATE
# Generate actual keys using: scripts/generate-service-keys.sh
# Then create secret using the kubectl command shown by the script
#
# This template shows the expected structure.
# DO NOT commit actual key values to version control.

apiVersion: v1
kind: Secret
metadata:
  name: service-auth-keys
  namespace: rag-pipeline
  labels:
    app.kubernetes.io/component: security
    app.kubernetes.io/part-of: rag-pipeline
type: Opaque
data:
  # Base64-encoded RSA keys
  # orchestrator.key: <base64-encoded-private-key>
  # orchestrator.pub: <base64-encoded-public-key>
  # retrieval.key: <base64-encoded-private-key>
  # retrieval.pub: <base64-encoded-public-key>
  # ingestion.key: <base64-encoded-private-key>
  # ingestion.pub: <base64-encoded-public-key>
  # embedding.key: <base64-encoded-private-key>
  # embedding.pub: <base64-encoded-public-key>
  # llm-gateway.key: <base64-encoded-private-key>
  # llm-gateway.pub: <base64-encoded-public-key>
  placeholder: cGxhY2Vob2xkZXI=  # Remove this and add real keys
```

Create `k8s/base/security/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - service-auth-keys.yaml
```

**Step 2: Commit**

```bash
git add k8s/base/security/
git commit -m "feat(auth): add Kubernetes secret template for service keys"
```

---

## Task 9: Add Prometheus Metrics

**Files:**
- Modify: `services/shared/security/service_auth/middleware.py`
- Test: `tests/security/test_service_auth.py`

**Step 1: Write the failing test**

Add to `tests/security/test_service_auth.py`:

```python
class TestServiceAuthMetrics:
    """Tests for service auth Prometheus metrics."""

    def test_metrics_counter_exists(self):
        """Should expose service_auth_total counter."""
        from shared.security.service_auth.middleware import service_auth_total

        assert service_auth_total is not None
        assert service_auth_total._name == "service_auth_total"

    def test_metrics_labels(self):
        """Should have correct labels."""
        from shared.security.service_auth.middleware import service_auth_total

        assert "caller" in service_auth_total._labelnames
        assert "target" in service_auth_total._labelnames
        assert "result" in service_auth_total._labelnames
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/security/test_service_auth.py::TestServiceAuthMetrics -v`
Expected: FAIL with "cannot import name 'service_auth_total'"

**Step 3: Write the implementation**

Update `services/shared/security/service_auth/middleware.py`, add at the top after imports:

```python
from prometheus_client import Counter

# Metrics
service_auth_total = Counter(
    "service_auth_total",
    "Service authentication attempts",
    ["caller", "target", "result"],
)
```

Then update the middleware `dispatch` method to increment the counter:

After the "Missing service token" return:
```python
service_auth_total.labels(caller="unknown", target=self.service_name, result="missing").inc()
```

After "expired" return:
```python
service_auth_total.labels(caller="unknown", target=self.service_name, result="failed").inc()
```

After "invalid" return:
```python
service_auth_total.labels(caller="unknown", target=self.service_name, result="failed").inc()
```

After "denied" return:
```python
service_auth_total.labels(caller=payload.issuer, target=self.service_name, result="denied").inc()
```

Before success return:
```python
service_auth_total.labels(caller=payload.issuer, target=self.service_name, result="success").inc()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/security/test_service_auth.py::TestServiceAuthMetrics -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add services/shared/security/service_auth/middleware.py tests/security/test_service_auth.py
git commit -m "feat(auth): add Prometheus metrics for service authentication"
```

---

## Task 10: Run All Tests

**Step 1: Run complete test suite**

Run: `pytest tests/security/test_service_auth.py -v`
Expected: All tests pass (approximately 20 tests)

**Step 2: Run linting**

Run: `ruff check services/shared/security/service_auth/`
Expected: No errors

**Step 3: Commit if any fixes needed**

```bash
git add -A
git commit -m "fix(auth): address linting issues"
```

---

## Summary

This implementation plan covers:

1. **ServiceTokenPayload** - Model for service JWT claims
2. **create_service_token** - JWTHandler method to create service tokens
3. **verify_service_token** - JWTHandler method to verify service tokens
4. **ServiceAuthConfig** - RBAC configuration loader
5. **AuthenticatedServiceClient** - HTTP client with automatic auth
6. **ServiceAuthMiddleware** - FastAPI middleware for internal endpoints
7. **Key generation script** - Shell script for RSA keypair generation
8. **Kubernetes secrets** - Template for key distribution
9. **Prometheus metrics** - Observability for auth events

**Remaining work after this plan:**
- Update service clients (orchestrator/gateway/client.py, ingestion/embedding/client.py) to use AuthenticatedServiceClient
- Register ServiceAuthMiddleware in each service's main.py
- Update K8s deployments to mount secrets
- Integration tests with running services
