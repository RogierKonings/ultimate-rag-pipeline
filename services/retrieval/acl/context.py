"""User context extraction from JWT tokens.

This module handles extracting user identity and permissions from
JWT tokens in the Authorization header.
"""

from uuid import UUID

from fastapi import HTTPException, Request
from jose import JWTError, jwt

from .models import UserContext


class UserContextExtractor:
    """Extracts user context from JWT tokens.

    Validates the token and extracts claims for ACL filtering.
    """

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        issuer: str | None = None,
        audience: str | None = None,
    ):
        """Initialize user context extractor.

        Args:
            secret_key: Secret key for JWT validation.
            algorithm: JWT algorithm (default: HS256).
            issuer: Expected token issuer (optional).
            audience: Expected token audience (optional).
        """
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.issuer = issuer
        self.audience = audience

    async def extract(self, request: Request) -> UserContext:
        """Extract user context from request Authorization header.

        Args:
            request: FastAPI request object.

        Returns:
            UserContext with user's identity and permissions.

        Raises:
            HTTPException: 401 if token is missing or invalid.
        """
        # Get token from header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(
                status_code=401,
                detail="Missing Authorization header",
            )

        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Invalid Authorization header format",
            )

        token = auth_header[7:]  # Remove "Bearer "

        return await self.extract_from_token(token)

    async def extract_from_token(self, token: str) -> UserContext:
        """Extract user context from a JWT token string.

        Args:
            token: JWT token string (without Bearer prefix).

        Returns:
            UserContext with user's identity and permissions.

        Raises:
            HTTPException: 401 if token is invalid.
        """
        try:
            # Build decode options
            options = {}
            if self.issuer:
                options["verify_iss"] = True
            if self.audience:
                options["verify_aud"] = True

            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                issuer=self.issuer,
                audience=self.audience,
                options=options,
            )
        except JWTError as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}") from e

        # Extract claims
        try:
            return UserContext(
                user_id=UUID(payload["sub"]),
                tenant_id=UUID(payload["tenant_id"]),
                groups=payload.get("groups", []),
                roles=payload.get("roles", []),
                permissions=payload.get("permissions", []),
                email=payload.get("email"),
                name=payload.get("name"),
            )
        except KeyError as e:
            raise HTTPException(
                status_code=401,
                detail=f"Missing required token claim: {str(e)}",
            ) from e
        except ValueError as e:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token claim format: {str(e)}",
            ) from e

    def create_anonymous_context(self, tenant_id: UUID) -> UserContext:
        """Create context for anonymous/unauthenticated users.

        Anonymous users can only see public documents within the
        specified tenant.

        Args:
            tenant_id: Tenant ID for the anonymous context.

        Returns:
            UserContext with anonymous user identity.
        """
        return UserContext(
            user_id=UUID(int=0),
            tenant_id=tenant_id,
            groups=[],
            roles=["anonymous"],
            permissions=["read:public"],
        )

    def create_service_context(self, tenant_id: UUID) -> UserContext:
        """Create context for internal service-to-service calls.

        Service context has elevated permissions for internal operations.

        Args:
            tenant_id: Tenant ID for the service context.

        Returns:
            UserContext with service account identity.
        """
        return UserContext(
            user_id=UUID(int=1),
            tenant_id=tenant_id,
            groups=[],
            roles=["service"],
            permissions=["read:all", "write:all"],
        )
