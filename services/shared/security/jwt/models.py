"""
JWT token models.

This module defines the data models for JWT tokens, claims,
and token-related requests/responses.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TokenType(str, Enum):
    """Token types for different use cases."""

    ACCESS = "access"
    REFRESH = "refresh"


class TokenClaims(BaseModel):
    """
    JWT token claims model.

    This model represents the claims contained in a JWT token,
    including standard claims and custom claims for the RAG pipeline.

    Standard Claims (RFC 7519):
        sub: Subject (user ID)
        iss: Issuer
        aud: Audience
        exp: Expiration time
        iat: Issued at
        nbf: Not before
        jti: JWT ID (unique identifier)

    Custom Claims:
        tenant_id: Tenant identifier for multi-tenancy
        roles: User roles for RBAC
        groups: User groups for document ACL
        permissions: Explicit permissions
        token_type: Access or refresh token
    """

    # Standard claims
    sub: UUID = Field(..., description="Subject (user ID)")
    iss: Optional[str] = Field(default=None, description="Issuer")
    aud: Optional[str] = Field(default=None, description="Audience")
    exp: Optional[datetime] = Field(default=None, description="Expiration time")
    iat: Optional[datetime] = Field(default=None, description="Issued at")
    nbf: Optional[datetime] = Field(default=None, description="Not before")
    jti: Optional[str] = Field(default=None, description="JWT ID")

    # Custom claims
    tenant_id: UUID = Field(..., description="Tenant identifier")
    roles: list[str] = Field(default_factory=list, description="User roles")
    groups: list[str] = Field(default_factory=list, description="User groups")
    permissions: list[str] = Field(
        default_factory=list, description="Explicit permissions"
    )
    token_type: TokenType = Field(
        default=TokenType.ACCESS, description="Token type (access/refresh)"
    )

    # Optional user metadata
    email: Optional[str] = Field(default=None, description="User email")
    name: Optional[str] = Field(default=None, description="User display name")

    def to_dict(self) -> dict:
        """
        Convert claims to a dictionary for JWT encoding.

        Returns:
            Dict with claims, converting UUID and datetime to strings
        """
        data = {}

        # Standard claims
        data["sub"] = str(self.sub)
        if self.iss:
            data["iss"] = self.iss
        if self.aud:
            data["aud"] = self.aud
        if self.exp:
            data["exp"] = int(self.exp.timestamp())
        if self.iat:
            data["iat"] = int(self.iat.timestamp())
        if self.nbf:
            data["nbf"] = int(self.nbf.timestamp())
        if self.jti:
            data["jti"] = self.jti

        # Custom claims
        data["tenant_id"] = str(self.tenant_id)
        data["roles"] = self.roles
        data["groups"] = self.groups
        data["permissions"] = self.permissions
        data["token_type"] = self.token_type.value

        # Optional metadata
        if self.email:
            data["email"] = self.email
        if self.name:
            data["name"] = self.name

        return data

    @classmethod
    def from_dict(cls, data: dict) -> "TokenClaims":
        """
        Create TokenClaims from a decoded JWT payload.

        Args:
            data: Decoded JWT payload dictionary

        Returns:
            TokenClaims instance
        """
        # Convert timestamps back to datetime
        exp = None
        if "exp" in data:
            exp = datetime.fromtimestamp(data["exp"])

        iat = None
        if "iat" in data:
            iat = datetime.fromtimestamp(data["iat"])

        nbf = None
        if "nbf" in data:
            nbf = datetime.fromtimestamp(data["nbf"])

        # Parse token type
        token_type = TokenType.ACCESS
        if "token_type" in data:
            token_type = TokenType(data["token_type"])

        return cls(
            sub=UUID(data["sub"]),
            iss=data.get("iss"),
            aud=data.get("aud"),
            exp=exp,
            iat=iat,
            nbf=nbf,
            jti=data.get("jti"),
            tenant_id=UUID(data["tenant_id"]),
            roles=data.get("roles", []),
            groups=data.get("groups", []),
            permissions=data.get("permissions", []),
            token_type=token_type,
            email=data.get("email"),
            name=data.get("name"),
        )

    def has_role(self, role: str) -> bool:
        """Check if the token has a specific role."""
        return role in self.roles

    def has_permission(self, permission: str) -> bool:
        """Check if the token has a specific permission."""
        return permission in self.permissions

    def is_admin(self) -> bool:
        """Check if the token has admin role."""
        return "admin" in self.roles or "super_admin" in self.roles

    def is_member_of(self, group: str) -> bool:
        """Check if the token holder is a member of a group."""
        return group in self.groups


class TokenPair(BaseModel):
    """
    Token pair containing access and refresh tokens.

    Used as the response for authentication endpoints.
    """

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="Bearer", description="Token type for Authorization header")
    expires_in: int = Field(..., description="Access token expiration in seconds")
    refresh_expires_in: int = Field(
        ..., description="Refresh token expiration in seconds"
    )


class TokenRequest(BaseModel):
    """
    Token request for authentication.

    Supports multiple grant types:
    - password: Username/password authentication
    - refresh_token: Token refresh
    - client_credentials: Service-to-service authentication
    """

    grant_type: str = Field(
        ...,
        description="Grant type: password, refresh_token, or client_credentials",
        pattern="^(password|refresh_token|client_credentials)$",
    )

    # For password grant
    username: Optional[str] = Field(default=None, description="Username for password grant")
    password: Optional[str] = Field(default=None, description="Password for password grant")

    # For refresh_token grant
    refresh_token: Optional[str] = Field(
        default=None, description="Refresh token for token refresh"
    )

    # For client_credentials grant
    client_id: Optional[str] = Field(
        default=None, description="Client ID for service auth"
    )
    client_secret: Optional[str] = Field(
        default=None, description="Client secret for service auth"
    )

    # Common fields
    scope: Optional[str] = Field(
        default=None, description="Requested scopes (space-separated)"
    )
    tenant_id: Optional[UUID] = Field(
        default=None, description="Tenant ID for multi-tenant auth"
    )


class TokenIntrospectionResponse(BaseModel):
    """
    Token introspection response (RFC 7662).

    Used to check if a token is valid and get its claims.
    """

    active: bool = Field(..., description="Whether the token is active")
    sub: Optional[str] = Field(default=None, description="Subject")
    client_id: Optional[str] = Field(default=None, description="Client ID")
    username: Optional[str] = Field(default=None, description="Username")
    token_type: Optional[str] = Field(default=None, description="Token type")
    exp: Optional[int] = Field(default=None, description="Expiration timestamp")
    iat: Optional[int] = Field(default=None, description="Issued at timestamp")
    nbf: Optional[int] = Field(default=None, description="Not before timestamp")
    aud: Optional[str] = Field(default=None, description="Audience")
    iss: Optional[str] = Field(default=None, description="Issuer")
    jti: Optional[str] = Field(default=None, description="JWT ID")
    scope: Optional[str] = Field(default=None, description="Token scopes")

    # Custom claims
    tenant_id: Optional[str] = Field(default=None, description="Tenant ID")
    roles: Optional[list[str]] = Field(default=None, description="User roles")
    groups: Optional[list[str]] = Field(default=None, description="User groups")


class TokenRevocationRequest(BaseModel):
    """
    Token revocation request (RFC 7009).

    Used to revoke/logout tokens.
    """

    token: str = Field(..., description="Token to revoke")
    token_type_hint: Optional[str] = Field(
        default=None,
        description="Type of token: access_token or refresh_token",
        pattern="^(access_token|refresh_token)$",
    )
