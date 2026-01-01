# US-7.1: JWT Authentication

> **Epic:** Security & Compliance  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** Epic 1 (Infrastructure)

## User Story

**As a** security engineer  
**I want** JWT-based authentication  
**So that** API access is authenticated and secure

## Objective

Implement JWT (JSON Web Token) authentication for all API endpoints with support for token validation, claims extraction, expiration handling, and refresh token flows. Integrate with external identity providers (Auth0, Keycloak, Azure AD).

## Architecture Reference

- **Algorithm:** RS256 (asymmetric) for production, HS256 for development
- **Token Types:** Access tokens (short-lived), Refresh tokens (long-lived)
- **Claims:** Standard JWT claims + custom tenant/role claims
- **Middleware:** FastAPI dependency injection pattern

## Implementation Tasks

### 1. Create JWT Configuration

`services/shared/security/jwt/config.py`:

```python
from pydantic_settings import BaseSettings
from typing import Optional, List
from functools import lru_cache

class JWTSettings(BaseSettings):
    # Signing configuration
    jwt_secret_key: str  # For HS256 or private key path for RS256
    jwt_public_key: Optional[str] = None  # Public key for RS256 verification
    jwt_algorithm: str = "RS256"
    
    # Token expiration
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    
    # Token validation
    jwt_issuer: str = "rag-pipeline"
    jwt_audience: str = "rag-api"
    jwt_leeway_seconds: int = 10  # Clock skew tolerance
    
    # Identity provider (optional)
    idp_type: Optional[str] = None  # auth0, keycloak, azure_ad
    idp_domain: Optional[str] = None
    idp_client_id: Optional[str] = None
    idp_jwks_uri: Optional[str] = None
    
    # Security settings
    token_url: str = "/auth/token"
    refresh_url: str = "/auth/refresh"
    
    class Config:
        env_prefix = ""
        case_sensitive = False

@lru_cache()
def get_jwt_settings() -> JWTSettings:
    return JWTSettings()
```

### 2. Create Token Claims Models

`services/shared/security/jwt/models.py`:

```python
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from enum import Enum

class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"

class TokenClaims(BaseModel):
    """Standard JWT claims with custom extensions."""
    
    # Standard claims (RFC 7519)
    sub: str = Field(..., description="Subject (user ID)")
    iss: str = Field(..., description="Issuer")
    aud: str = Field(..., description="Audience")
    exp: int = Field(..., description="Expiration time (Unix timestamp)")
    iat: int = Field(..., description="Issued at time (Unix timestamp)")
    nbf: Optional[int] = Field(None, description="Not before time")
    jti: str = Field(..., description="JWT ID (unique token identifier)")
    
    # Custom claims
    tenant_id: UUID = Field(..., description="Tenant identifier")
    roles: List[str] = Field(default_factory=list, description="User roles")
    groups: List[str] = Field(default_factory=list, description="User groups")
    permissions: List[str] = Field(default_factory=list, description="Direct permissions")
    email: Optional[str] = Field(None, description="User email")
    name: Optional[str] = Field(None, description="User display name")
    token_type: TokenType = Field(default=TokenType.ACCESS)
    
    @property
    def user_id(self) -> str:
        return self.sub
    
    @property
    def is_expired(self) -> bool:
        return datetime.utcnow().timestamp() > self.exp
    
    def has_role(self, role: str) -> bool:
        return role in self.roles
    
    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions
    
    def has_any_role(self, roles: List[str]) -> bool:
        return any(role in self.roles for role in roles)


class TokenPair(BaseModel):
    """Access and refresh token pair."""
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int  # Seconds until access token expires


class TokenRequest(BaseModel):
    """Token generation request."""
    grant_type: str = Field(..., pattern="^(password|refresh_token|client_credentials)$")
    username: Optional[str] = None
    password: Optional[str] = None
    refresh_token: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    scope: Optional[str] = None
```

### 3. Create JWT Handler

`services/shared/security/jwt/handler.py`:

```python
import jwt
from jwt import PyJWKClient
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from uuid import uuid4
import httpx
from cryptography.hazmat.primitives import serialization

from .config import get_jwt_settings, JWTSettings
from .models import TokenClaims, TokenPair, TokenType


class JWTError(Exception):
    """Base JWT exception."""
    pass


class TokenExpiredError(JWTError):
    """Token has expired."""
    pass


class InvalidTokenError(JWTError):
    """Token is invalid."""
    pass


class JWTHandler:
    """Handles JWT token generation and validation."""
    
    def __init__(self, settings: Optional[JWTSettings] = None):
        self.settings = settings or get_jwt_settings()
        self._jwks_client: Optional[PyJWKClient] = None
        self._private_key: Optional[bytes] = None
        self._public_key: Optional[bytes] = None
        self._load_keys()
    
    def _load_keys(self):
        """Load signing/verification keys."""
        if self.settings.jwt_algorithm.startswith("RS"):
            # RSA keys - load from file or string
            if self.settings.jwt_secret_key.startswith("-----BEGIN"):
                self._private_key = self.settings.jwt_secret_key.encode()
            else:
                # Assume it's a file path
                with open(self.settings.jwt_secret_key, "rb") as f:
                    self._private_key = f.read()
            
            if self.settings.jwt_public_key:
                if self.settings.jwt_public_key.startswith("-----BEGIN"):
                    self._public_key = self.settings.jwt_public_key.encode()
                else:
                    with open(self.settings.jwt_public_key, "rb") as f:
                        self._public_key = f.read()
        
        # Initialize JWKS client for external IdP
        if self.settings.idp_jwks_uri:
            self._jwks_client = PyJWKClient(self.settings.idp_jwks_uri)
    
    def create_access_token(
        self,
        user_id: str,
        tenant_id: str,
        roles: list[str],
        groups: list[str] = None,
        permissions: list[str] = None,
        email: str = None,
        name: str = None,
        additional_claims: Dict[str, Any] = None
    ) -> str:
        """Create a new access token."""
        now = datetime.utcnow()
        expire = now + timedelta(minutes=self.settings.access_token_expire_minutes)
        
        claims = {
            "sub": user_id,
            "iss": self.settings.jwt_issuer,
            "aud": self.settings.jwt_audience,
            "exp": int(expire.timestamp()),
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "jti": str(uuid4()),
            "tenant_id": str(tenant_id),
            "roles": roles or [],
            "groups": groups or [],
            "permissions": permissions or [],
            "token_type": TokenType.ACCESS.value,
        }
        
        if email:
            claims["email"] = email
        if name:
            claims["name"] = name
        if additional_claims:
            claims.update(additional_claims)
        
        return self._encode_token(claims)
    
    def create_refresh_token(
        self,
        user_id: str,
        tenant_id: str,
    ) -> str:
        """Create a new refresh token."""
        now = datetime.utcnow()
        expire = now + timedelta(days=self.settings.refresh_token_expire_days)
        
        claims = {
            "sub": user_id,
            "iss": self.settings.jwt_issuer,
            "aud": self.settings.jwt_audience,
            "exp": int(expire.timestamp()),
            "iat": int(now.timestamp()),
            "jti": str(uuid4()),
            "tenant_id": str(tenant_id),
            "token_type": TokenType.REFRESH.value,
        }
        
        return self._encode_token(claims)
    
    def create_token_pair(
        self,
        user_id: str,
        tenant_id: str,
        roles: list[str],
        groups: list[str] = None,
        permissions: list[str] = None,
        email: str = None,
        name: str = None,
    ) -> TokenPair:
        """Create an access/refresh token pair."""
        access_token = self.create_access_token(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
            groups=groups,
            permissions=permissions,
            email=email,
            name=name,
        )
        refresh_token = self.create_refresh_token(
            user_id=user_id,
            tenant_id=tenant_id,
        )
        
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.settings.access_token_expire_minutes * 60,
        )
    
    def verify_token(self, token: str, token_type: TokenType = TokenType.ACCESS) -> TokenClaims:
        """Verify and decode a JWT token."""
        try:
            # Determine verification key
            if self._jwks_client:
                # External IdP - fetch key from JWKS
                signing_key = self._jwks_client.get_signing_key_from_jwt(token)
                key = signing_key.key
            elif self._public_key:
                key = self._public_key
            else:
                key = self.settings.jwt_secret_key
            
            # Decode and verify
            payload = jwt.decode(
                token,
                key,
                algorithms=[self.settings.jwt_algorithm],
                issuer=self.settings.jwt_issuer,
                audience=self.settings.jwt_audience,
                leeway=timedelta(seconds=self.settings.jwt_leeway_seconds),
                options={
                    "require": ["exp", "iat", "sub", "iss", "aud"],
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_iss": True,
                    "verify_aud": True,
                }
            )
            
            # Validate token type
            if payload.get("token_type") != token_type.value:
                raise InvalidTokenError(f"Expected {token_type.value} token")
            
            return TokenClaims(**payload)
            
        except jwt.ExpiredSignatureError:
            raise TokenExpiredError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise InvalidTokenError(f"Invalid token: {str(e)}")
    
    def refresh_access_token(self, refresh_token: str) -> TokenPair:
        """Generate new token pair from refresh token."""
        claims = self.verify_token(refresh_token, TokenType.REFRESH)
        
        # In production, you'd fetch fresh user data from database
        return self.create_token_pair(
            user_id=claims.sub,
            tenant_id=str(claims.tenant_id),
            roles=claims.roles,
            groups=claims.groups,
            permissions=claims.permissions,
            email=claims.email,
            name=claims.name,
        )
    
    def _encode_token(self, claims: Dict[str, Any]) -> str:
        """Encode claims to JWT."""
        if self._private_key:
            key = self._private_key
        else:
            key = self.settings.jwt_secret_key
        
        return jwt.encode(
            claims,
            key,
            algorithm=self.settings.jwt_algorithm,
        )
    
    def decode_token_unverified(self, token: str) -> Dict[str, Any]:
        """Decode token without verification (for debugging)."""
        return jwt.decode(token, options={"verify_signature": False})


# Singleton instance
_jwt_handler: Optional[JWTHandler] = None

def get_jwt_handler() -> JWTHandler:
    global _jwt_handler
    if _jwt_handler is None:
        _jwt_handler = JWTHandler()
    return _jwt_handler
```

### 4. Create FastAPI Authentication Middleware

`services/shared/security/jwt/middleware.py`:

```python
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional, List
import structlog

from .handler import get_jwt_handler, JWTHandler, TokenExpiredError, InvalidTokenError
from .models import TokenClaims, TokenType

logger = structlog.get_logger(__name__)

# Security scheme for OpenAPI docs
bearer_scheme = HTTPBearer(auto_error=False)


class AuthenticationError(HTTPException):
    """Authentication failed."""
    def __init__(self, detail: str = "Authentication required"):
        super().__init__(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """Middleware for JWT authentication on all routes."""
    
    def __init__(self, app, exclude_paths: List[str] = None):
        super().__init__(app)
        self.exclude_paths = exclude_paths or [
            "/health",
            "/ready",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/auth/token",
            "/auth/refresh",
        ]
        self.jwt_handler = get_jwt_handler()
    
    async def dispatch(self, request: Request, call_next):
        # Skip authentication for excluded paths
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            return await call_next(request)
        
        # Extract and verify token
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return await self._unauthorized_response("Missing authorization header")
        
        try:
            scheme, token = auth_header.split(" ", 1)
            if scheme.lower() != "bearer":
                return await self._unauthorized_response("Invalid authentication scheme")
            
            claims = self.jwt_handler.verify_token(token, TokenType.ACCESS)
            
            # Attach claims to request state for downstream access
            request.state.user = claims
            request.state.tenant_id = claims.tenant_id
            request.state.user_id = claims.user_id
            
            logger.info(
                "authenticated_request",
                user_id=claims.user_id,
                tenant_id=str(claims.tenant_id),
                path=request.url.path,
            )
            
        except TokenExpiredError:
            return await self._unauthorized_response("Token has expired")
        except InvalidTokenError as e:
            return await self._unauthorized_response(str(e))
        except Exception as e:
            logger.error("authentication_error", error=str(e))
            return await self._unauthorized_response("Authentication failed")
        
        return await call_next(request)
    
    async def _unauthorized_response(self, detail: str):
        from starlette.responses import JSONResponse
        return JSONResponse(
            status_code=401,
            content={"detail": detail},
            headers={"WWW-Authenticate": "Bearer"},
        )


# Dependency injection for route-level authentication
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    jwt_handler: JWTHandler = Depends(get_jwt_handler),
) -> TokenClaims:
    """FastAPI dependency to get current authenticated user."""
    if not credentials:
        raise AuthenticationError("Missing authorization header")
    
    try:
        return jwt_handler.verify_token(credentials.credentials, TokenType.ACCESS)
    except TokenExpiredError:
        raise AuthenticationError("Token has expired")
    except InvalidTokenError as e:
        raise AuthenticationError(str(e))


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    jwt_handler: JWTHandler = Depends(get_jwt_handler),
) -> Optional[TokenClaims]:
    """Optional authentication - returns None if not authenticated."""
    if not credentials:
        return None
    
    try:
        return jwt_handler.verify_token(credentials.credentials, TokenType.ACCESS)
    except (TokenExpiredError, InvalidTokenError):
        return None


def require_roles(*roles: str):
    """Decorator/dependency to require specific roles."""
    async def role_checker(user: TokenClaims = Depends(get_current_user)):
        if not user.has_any_role(list(roles)):
            raise HTTPException(
                status_code=403,
                detail=f"Required roles: {', '.join(roles)}"
            )
        return user
    return role_checker
```

### 5. Create Auth Router

`services/api-gateway/routers/auth.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from typing import Optional
import structlog

from shared.security.jwt.handler import get_jwt_handler, JWTHandler
from shared.security.jwt.models import TokenPair, TokenRequest

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/token", response_model=TokenPair)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    jwt_handler: JWTHandler = Depends(get_jwt_handler),
):
    """
    OAuth2 compatible token login endpoint.
    
    In production, this would validate credentials against a user store
    or delegate to an external identity provider.
    """
    # TODO: Replace with actual user authentication
    # This is a placeholder - implement proper user validation
    user = await authenticate_user(form_data.username, form_data.password)
    
    if not user:
        logger.warning("login_failed", username=form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token_pair = jwt_handler.create_token_pair(
        user_id=str(user.id),
        tenant_id=str(user.tenant_id),
        roles=user.roles,
        groups=user.groups,
        permissions=user.permissions,
        email=user.email,
        name=user.name,
    )
    
    logger.info("login_success", user_id=str(user.id), tenant_id=str(user.tenant_id))
    return token_pair


@router.post("/refresh", response_model=TokenPair)
async def refresh_token(
    refresh_token: str,
    jwt_handler: JWTHandler = Depends(get_jwt_handler),
):
    """Generate new access token using refresh token."""
    try:
        token_pair = jwt_handler.refresh_access_token(refresh_token)
        logger.info("token_refreshed")
        return token_pair
    except Exception as e:
        logger.warning("refresh_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )


@router.post("/logout")
async def logout(
    # In a real implementation, you'd invalidate the token
    # by adding it to a blocklist or revoking from IdP
):
    """
    Logout endpoint.
    
    For stateless JWT, client should discard the token.
    For enhanced security, implement token blocklist.
    """
    # TODO: Add token to blocklist in Redis
    return {"message": "Successfully logged out"}


async def authenticate_user(username: str, password: str):
    """
    Authenticate user against user store.
    
    TODO: Implement actual authentication logic:
    - Query user from database
    - Verify password hash
    - Check account status
    - Return user object or None
    """
    # Placeholder implementation
    from shared.database.repositories.user import UserRepository
    
    user_repo = UserRepository()
    user = await user_repo.get_by_username(username)
    
    if not user or not user.verify_password(password):
        return None
    
    if not user.is_active:
        return None
    
    return user
```

### 6. Register Middleware in FastAPI App

`services/api-gateway/main.py`:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.security.jwt.middleware import JWTAuthMiddleware
from .routers import auth, documents, query

app = FastAPI(
    title="RAG Pipeline API",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# JWT Authentication middleware
app.add_middleware(
    JWTAuthMiddleware,
    exclude_paths=[
        "/health",
        "/ready", 
        "/metrics",
        "/docs",
        "/openapi.json",
        "/auth/token",
        "/auth/refresh",
    ],
)

# Include routers
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(query.router)


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/ready")
async def ready():
    return {"status": "ready"}
```

### 7. Generate RSA Keys for Production

`scripts/generate-jwt-keys.sh`:

```bash
#!/bin/bash
set -e

OUTPUT_DIR="${1:-./keys}"
mkdir -p "$OUTPUT_DIR"

echo "Generating RSA key pair for JWT signing..."

# Generate private key
openssl genrsa -out "$OUTPUT_DIR/jwt-private.pem" 4096

# Extract public key
openssl rsa -in "$OUTPUT_DIR/jwt-private.pem" -pubout -out "$OUTPUT_DIR/jwt-public.pem"

# Set restrictive permissions
chmod 600 "$OUTPUT_DIR/jwt-private.pem"
chmod 644 "$OUTPUT_DIR/jwt-public.pem"

echo "Keys generated successfully:"
echo "  Private key: $OUTPUT_DIR/jwt-private.pem"
echo "  Public key:  $OUTPUT_DIR/jwt-public.pem"
echo ""
echo "Store the private key in Vault or as a Kubernetes secret."
echo "The public key can be distributed to services that only need to verify tokens."
```

### 8. Create Token Blocklist (Optional Enhancement)

`services/shared/security/jwt/blocklist.py`:

```python
from typing import Optional
from datetime import datetime, timedelta
import redis.asyncio as redis
import structlog

logger = structlog.get_logger(__name__)


class TokenBlocklist:
    """Redis-based token blocklist for logout/revocation."""
    
    def __init__(self, redis_client: redis.Redis, prefix: str = "jwt:blocklist:"):
        self.redis = redis_client
        self.prefix = prefix
    
    async def add(self, jti: str, exp: int) -> None:
        """Add token to blocklist until its original expiration."""
        key = f"{self.prefix}{jti}"
        ttl = exp - int(datetime.utcnow().timestamp())
        
        if ttl > 0:
            await self.redis.setex(key, ttl, "1")
            logger.info("token_blocklisted", jti=jti, ttl=ttl)
    
    async def is_blocklisted(self, jti: str) -> bool:
        """Check if token is blocklisted."""
        key = f"{self.prefix}{jti}"
        return await self.redis.exists(key) > 0
    
    async def remove(self, jti: str) -> None:
        """Remove token from blocklist (if needed)."""
        key = f"{self.prefix}{jti}"
        await self.redis.delete(key)
```

### 9. Create Integration Tests

`tests/security/test_jwt_authentication.py`:

```python
import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from shared.security.jwt.handler import JWTHandler, TokenExpiredError, InvalidTokenError
from shared.security.jwt.models import TokenClaims, TokenType
from shared.security.jwt.config import JWTSettings


@pytest.fixture
def jwt_settings():
    return JWTSettings(
        jwt_secret_key="test-secret-key-for-testing-only",
        jwt_algorithm="HS256",
        access_token_expire_minutes=30,
        refresh_token_expire_days=7,
        jwt_issuer="test-issuer",
        jwt_audience="test-audience",
    )


@pytest.fixture
def jwt_handler(jwt_settings):
    return JWTHandler(settings=jwt_settings)


class TestJWTHandler:
    def test_create_access_token(self, jwt_handler):
        token = jwt_handler.create_access_token(
            user_id="user-123",
            tenant_id=str(uuid4()),
            roles=["user", "admin"],
            email="test@example.com",
        )
        
        assert token is not None
        assert len(token.split(".")) == 3  # JWT has 3 parts
    
    def test_verify_access_token(self, jwt_handler):
        tenant_id = str(uuid4())
        token = jwt_handler.create_access_token(
            user_id="user-123",
            tenant_id=tenant_id,
            roles=["user"],
        )
        
        claims = jwt_handler.verify_token(token, TokenType.ACCESS)
        
        assert claims.sub == "user-123"
        assert str(claims.tenant_id) == tenant_id
        assert "user" in claims.roles
    
    def test_create_token_pair(self, jwt_handler):
        token_pair = jwt_handler.create_token_pair(
            user_id="user-123",
            tenant_id=str(uuid4()),
            roles=["user"],
        )
        
        assert token_pair.access_token is not None
        assert token_pair.refresh_token is not None
        assert token_pair.token_type == "Bearer"
        assert token_pair.expires_in == 30 * 60
    
    def test_refresh_token_flow(self, jwt_handler):
        original_pair = jwt_handler.create_token_pair(
            user_id="user-123",
            tenant_id=str(uuid4()),
            roles=["user"],
        )
        
        new_pair = jwt_handler.refresh_access_token(original_pair.refresh_token)
        
        assert new_pair.access_token != original_pair.access_token
        assert new_pair.refresh_token != original_pair.refresh_token
    
    def test_expired_token_rejected(self, jwt_handler):
        # Create token with already-expired timestamp
        jwt_handler.settings.access_token_expire_minutes = -1
        token = jwt_handler.create_access_token(
            user_id="user-123",
            tenant_id=str(uuid4()),
            roles=["user"],
        )
        
        with pytest.raises(TokenExpiredError):
            jwt_handler.verify_token(token, TokenType.ACCESS)
    
    def test_invalid_token_rejected(self, jwt_handler):
        with pytest.raises(InvalidTokenError):
            jwt_handler.verify_token("invalid.token.here", TokenType.ACCESS)
    
    def test_wrong_token_type_rejected(self, jwt_handler):
        access_token = jwt_handler.create_access_token(
            user_id="user-123",
            tenant_id=str(uuid4()),
            roles=["user"],
        )
        
        # Try to verify access token as refresh token
        with pytest.raises(InvalidTokenError):
            jwt_handler.verify_token(access_token, TokenType.REFRESH)
    
    def test_claims_has_role(self, jwt_handler):
        token = jwt_handler.create_access_token(
            user_id="user-123",
            tenant_id=str(uuid4()),
            roles=["user", "admin"],
        )
        
        claims = jwt_handler.verify_token(token, TokenType.ACCESS)
        
        assert claims.has_role("admin") is True
        assert claims.has_role("superuser") is False
        assert claims.has_any_role(["admin", "superuser"]) is True
```

## Acceptance Criteria

- [ ] JWT validation middleware implemented for FastAPI
- [ ] Token claims extraction working correctly
- [ ] Access token expiration enforced (30 min default)
- [ ] Refresh token support with rotation
- [ ] Support for external identity providers (JWKS validation)
- [ ] RSA (RS256) signing for production environments
- [ ] Token blocklist for logout/revocation (Redis-based)
- [ ] Comprehensive error handling with proper HTTP status codes
- [ ] OpenAPI documentation includes security scheme
- [ ] Unit and integration tests passing

## Verification Commands

```bash
# Generate JWT keys
./scripts/generate-jwt-keys.sh ./keys

# Run unit tests
pytest tests/security/test_jwt_authentication.py -v

# Test token generation (curl)
curl -X POST "http://localhost:8000/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=testuser&password=testpass"

# Test authenticated endpoint
TOKEN="eyJ..."
curl -X GET "http://localhost:8000/documents" \
  -H "Authorization: Bearer $TOKEN"

# Test token refresh
curl -X POST "http://localhost:8000/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "eyJ..."}'

# Verify JWT structure (decode without verification)
echo "$TOKEN" | cut -d. -f2 | base64 -d | jq .
```

## Environment Variables

```bash
# JWT Configuration
JWT_SECRET_KEY=/path/to/jwt-private.pem
JWT_PUBLIC_KEY=/path/to/jwt-public.pem
JWT_ALGORITHM=RS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
JWT_ISSUER=rag-pipeline
JWT_AUDIENCE=rag-api

# External IdP (optional)
IDP_TYPE=auth0
IDP_DOMAIN=your-tenant.auth0.com
IDP_CLIENT_ID=your-client-id
IDP_JWKS_URI=https://your-tenant.auth0.com/.well-known/jwks.json
```

## Files to Create

1. `services/shared/security/jwt/__init__.py`
2. `services/shared/security/jwt/config.py`
3. `services/shared/security/jwt/models.py`
4. `services/shared/security/jwt/handler.py`
5. `services/shared/security/jwt/middleware.py`
6. `services/shared/security/jwt/blocklist.py`
7. `services/api-gateway/routers/auth.py`
8. `scripts/generate-jwt-keys.sh`
9. `tests/security/test_jwt_authentication.py`

## Security Considerations

- **Never log tokens** - Token values should never appear in logs
- **Use RS256 in production** - Asymmetric signing allows public key distribution
- **Short access token lifetime** - 15-30 minutes recommended
- **Implement token blocklist** - For immediate revocation on logout
- **Validate all claims** - Issuer, audience, expiration, and custom claims
- **Secure key storage** - Private keys in Vault or K8s Secrets only
- **HTTPS only** - Never transmit tokens over unencrypted connections
