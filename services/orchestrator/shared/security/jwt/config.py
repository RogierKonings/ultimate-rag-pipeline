"""
JWT configuration module.

This module defines the configuration settings for JWT authentication,
including algorithm selection, token expiration, and IdP integration.
"""

from enum import StrEnum

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class JWTAlgorithm(StrEnum):
    """Supported JWT signing algorithms."""

    RS256 = "RS256"  # RSA with SHA-256 (production recommended)
    RS384 = "RS384"  # RSA with SHA-384
    RS512 = "RS512"  # RSA with SHA-512
    HS256 = "HS256"  # HMAC with SHA-256 (development only)
    HS384 = "HS384"  # HMAC with SHA-384
    HS512 = "HS512"  # HMAC with SHA-512


class JWTSettings(BaseSettings):
    """
    JWT configuration settings.

    These settings control JWT token creation, validation, and integration
    with external Identity Providers.

    Environment Variables:
        JWT_SECRET_KEY: Secret key for HS256 or path to RSA private key
        JWT_PUBLIC_KEY: Path to RSA public key (for RS256)
        JWT_ALGORITHM: Signing algorithm (RS256 recommended for production)
        JWT_ACCESS_TOKEN_EXPIRE_MINUTES: Access token lifetime (default: 30)
        JWT_REFRESH_TOKEN_EXPIRE_DAYS: Refresh token lifetime (default: 7)
        JWT_ISSUER: Token issuer claim
        JWT_AUDIENCE: Token audience claim
        JWT_JWKS_URL: URL to external IdP JWKS endpoint (optional)
    """

    # Key configuration
    secret_key: str | None = Field(
        default=None,
        description="Secret key for HMAC or path/content of RSA private key",
        alias="JWT_SECRET_KEY",
    )
    public_key: str | None = Field(
        default=None,
        description="Path or content of RSA public key for RS256",
        alias="JWT_PUBLIC_KEY",
    )

    # Algorithm
    algorithm: JWTAlgorithm = Field(
        default=JWTAlgorithm.RS256,
        description="JWT signing algorithm",
        alias="JWT_ALGORITHM",
    )

    # Token expiration
    access_token_expire_minutes: int = Field(
        default=30,
        ge=1,
        le=1440,  # Max 24 hours
        description="Access token expiration in minutes",
        alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
    )
    refresh_token_expire_days: int = Field(
        default=7,
        ge=1,
        le=90,  # Max 90 days
        description="Refresh token expiration in days",
        alias="JWT_REFRESH_TOKEN_EXPIRE_DAYS",
    )

    # Token claims
    issuer: str = Field(
        default="rag-pipeline",
        description="Token issuer (iss claim)",
        alias="JWT_ISSUER",
    )
    audience: str = Field(
        default="rag-api",
        description="Token audience (aud claim)",
        alias="JWT_AUDIENCE",
    )

    # External IdP integration (optional)
    jwks_url: str | None = Field(
        default=None,
        description="URL to external IdP JWKS endpoint for token validation",
        alias="JWT_JWKS_URL",
    )
    idp_issuer: str | None = Field(
        default=None,
        description="Expected issuer from external IdP",
        alias="JWT_IDP_ISSUER",
    )

    # Security options
    verify_exp: bool = Field(
        default=True,
        description="Verify token expiration",
        alias="JWT_VERIFY_EXP",
    )
    verify_aud: bool = Field(
        default=True,
        description="Verify token audience",
        alias="JWT_VERIFY_AUD",
    )
    leeway_seconds: int = Field(
        default=0,
        ge=0,
        le=300,
        description="Clock skew tolerance in seconds",
        alias="JWT_LEEWAY_SECONDS",
    )

    # Token blocklist (for logout/revocation)
    blocklist_enabled: bool = Field(
        default=True,
        description="Enable token blocklist for logout/revocation",
        alias="JWT_BLOCKLIST_ENABLED",
    )
    blocklist_prefix: str = Field(
        default="jwt:blocklist:",
        description="Redis key prefix for blocklist",
        alias="JWT_BLOCKLIST_PREFIX",
    )

    model_config = {
        "env_prefix": "",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "populate_by_name": True,  # Allow using field names (not just aliases) in constructor
    }

    @field_validator("algorithm", mode="before")
    @classmethod
    def validate_algorithm(cls, v: str) -> JWTAlgorithm:
        """Convert string to JWTAlgorithm enum."""
        if isinstance(v, JWTAlgorithm):
            return v
        try:
            return JWTAlgorithm(v.upper())
        except ValueError:
            valid = [alg.value for alg in JWTAlgorithm]
            raise ValueError(f"Invalid algorithm '{v}'. Must be one of: {valid}") from None

    @property
    def is_asymmetric(self) -> bool:
        """Check if the algorithm uses asymmetric keys (RSA)."""
        return self.algorithm.value.startswith("RS")

    @property
    def requires_private_key(self) -> bool:
        """Check if a private key is required for token creation."""
        return self.is_asymmetric

    def validate_keys(self) -> None:
        """
        Validate that required keys are configured based on algorithm.

        Raises:
            ValueError: If required keys are missing
        """
        if self.is_asymmetric:
            if not self.secret_key and not self.public_key:
                raise ValueError(
                    f"Algorithm {self.algorithm.value} requires RSA keys. "
                    "Set JWT_SECRET_KEY (private) and/or JWT_PUBLIC_KEY (public).",
                )
        else:
            if not self.secret_key:
                raise ValueError(
                    f"Algorithm {self.algorithm.value} requires JWT_SECRET_KEY.",
                )
