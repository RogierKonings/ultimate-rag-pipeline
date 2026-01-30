"""
JWT Authentication module for the RAG Pipeline.

This module provides JWT token creation, validation, and management
with support for RS256 (production) and HS256 (development) algorithms.

Service-to-Service Authentication:
    For inter-service communication, use ServiceAuthMiddleware on the server
    side and AuthenticatedServiceClient on the client side.

    Example (server):
        ```python
        from shared.security.jwt import JWTHandler, ServiceAuthMiddleware, ServiceAuthSettings

        app = FastAPI()
        handler = JWTHandler()
        settings = ServiceAuthSettings(service_name="retrieval")

        app.add_middleware(ServiceAuthMiddleware, handler=handler, settings=settings)
        ```

    Example (client):
        ```python
        from shared.security.jwt import JWTHandler, AuthenticatedServiceClient, ServiceAuthSettings

        handler = JWTHandler()
        settings = ServiceAuthSettings(service_name="orchestrator")

        async with AuthenticatedServiceClient(
            base_url="http://retrieval:8002",
            target_service="retrieval",
            handler=handler,
            settings=settings,
        ) as client:
            response = await client.post("/internal/search", json={...})
        ```
"""

from .blocklist import (
    AsyncRedisTokenBlocklist,
    InMemoryTokenBlocklist,
    RedisTokenBlocklist,
)
from .config import JWTAlgorithm, JWTSettings
from .handler import (
    JWTError,
    JWTHandler,
    KeyLoadError,
    TokenBlocklist,
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
)
from .middleware import (
    CurrentUser,
    JWTAuthMiddleware,
    OptionalUser,
    create_auth_dependencies,
    require_permissions,
    require_roles,
    require_tenant,
)
from .models import (
    ServiceTokenClaims,
    TokenClaims,
    TokenIntrospectionResponse,
    TokenPair,
    TokenRequest,
    TokenRevocationRequest,
    TokenType,
)
from .service_auth_config import (
    DEFAULT_AUTHORIZATION_MATRIX,
    ServiceAuthSettings,
    get_allowed_endpoints,
    is_service_authorized,
)
from .service_auth_middleware import ServiceAuthMiddleware, get_caller_service
from .service_client import AuthenticatedServiceClient

__all__ = [
    # Config
    "JWTAlgorithm",
    "JWTSettings",
    # Models
    "ServiceTokenClaims",
    "TokenClaims",
    "TokenIntrospectionResponse",
    "TokenPair",
    "TokenRequest",
    "TokenRevocationRequest",
    "TokenType",
    # Handler
    "JWTError",
    "JWTHandler",
    "KeyLoadError",
    "TokenBlocklist",
    "TokenExpiredError",
    "TokenInvalidError",
    "TokenRevokedError",
    # Blocklist implementations
    "AsyncRedisTokenBlocklist",
    "InMemoryTokenBlocklist",
    "RedisTokenBlocklist",
    # User Auth Middleware
    "CurrentUser",
    "JWTAuthMiddleware",
    "OptionalUser",
    "create_auth_dependencies",
    "require_permissions",
    "require_roles",
    "require_tenant",
    # Service-to-Service Auth
    "AuthenticatedServiceClient",
    "DEFAULT_AUTHORIZATION_MATRIX",
    "ServiceAuthMiddleware",
    "ServiceAuthSettings",
    "get_allowed_endpoints",
    "get_caller_service",
    "is_service_authorized",
]
