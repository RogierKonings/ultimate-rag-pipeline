"""
Secrets injection for FastAPI.

This module provides FastAPI dependencies for injecting
secrets into request handlers.
"""

import logging
from typing import Any, Callable, Optional

from fastapi import Depends, HTTPException, Request

from .config import SecretsSettings
from .service import SecretsService, get_secrets_service

logger = logging.getLogger(__name__)


class SecretsInjector:
    """
    FastAPI dependency for secrets injection.

    Provides a clean way to access secrets in route handlers
    with caching and error handling.

    Example:
        ```python
        from fastapi import FastAPI, Depends
        from services.shared.security.secrets import SecretsInjector

        app = FastAPI()
        secrets = SecretsInjector()

        @app.get("/protected")
        async def protected_endpoint(
            api_key: str = Depends(secrets.get_secret("EXTERNAL_API_KEY"))
        ):
            # api_key is automatically injected
            return {"status": "ok"}

        # Or use the dependency directly
        @app.get("/database")
        async def database_endpoint(
            db_url: str = Depends(secrets.get_database_url)
        ):
            return {"database": "connected"}
        ```
    """

    def __init__(
        self,
        settings: Optional[SecretsSettings] = None,
        service: Optional[SecretsService] = None,
    ):
        """
        Initialize secrets injector.

        Args:
            settings: Secrets settings.
            service: Existing secrets service to use.
        """
        self._settings = settings
        self._service = service

    def _get_service(self) -> SecretsService:
        """Get or create secrets service."""
        if self._service is None:
            self._service = get_secrets_service(self._settings)
        return self._service

    def get_secret(
        self,
        key: str,
        required: bool = True,
        default: Optional[str] = None,
    ) -> Callable:
        """
        Create a dependency for getting a specific secret.

        Args:
            key: Secret key name.
            required: Whether the secret is required.
            default: Default value if not found.

        Returns:
            FastAPI dependency function.
        """

        async def dependency() -> Optional[str]:
            service = self._get_service()
            value = await service.get_secret(key, default)

            if value is None and required:
                logger.error(f"Required secret not found: {key}")
                raise HTTPException(
                    status_code=500,
                    detail="Service configuration error",
                )

            return value

        return dependency

    async def get_database_url(self) -> str:
        """FastAPI dependency for database URL."""
        service = self._get_service()
        try:
            return await service.get_database_url()
        except Exception as e:
            logger.error(f"Failed to get database URL: {e}")
            raise HTTPException(
                status_code=500,
                detail="Database configuration error",
            )

    async def get_redis_url(self) -> str:
        """FastAPI dependency for Redis URL."""
        service = self._get_service()
        try:
            return await service.get_redis_url()
        except Exception as e:
            logger.error(f"Failed to get Redis URL: {e}")
            raise HTTPException(
                status_code=500,
                detail="Redis configuration error",
            )

    async def get_jwt_secret(self) -> str:
        """FastAPI dependency for JWT secret."""
        service = self._get_service()
        try:
            return await service.get_jwt_secret()
        except Exception as e:
            logger.error(f"Failed to get JWT secret: {e}")
            raise HTTPException(
                status_code=500,
                detail="JWT configuration error",
            )

    async def get_encryption_key(self) -> bytes:
        """FastAPI dependency for encryption key."""
        service = self._get_service()
        try:
            return await service.get_encryption_key()
        except Exception as e:
            logger.error(f"Failed to get encryption key: {e}")
            raise HTTPException(
                status_code=500,
                detail="Encryption configuration error",
            )

    def get_api_key(self, service_name: str, required: bool = True) -> Callable:
        """
        Create a dependency for getting an API key.

        Args:
            service_name: External service name.
            required: Whether the key is required.

        Returns:
            FastAPI dependency function.
        """

        async def dependency() -> Optional[str]:
            service = self._get_service()
            try:
                return await service.get_api_key(service_name)
            except Exception as e:
                if required:
                    logger.error(f"Failed to get API key for {service_name}: {e}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"API key configuration error for {service_name}",
                    )
                return None

        return dependency


# Global injector instance
_injector: Optional[SecretsInjector] = None


def get_secrets_injector(
    settings: Optional[SecretsSettings] = None,
) -> SecretsInjector:
    """
    Get or create global secrets injector.

    Args:
        settings: Secrets settings for new injector.

    Returns:
        SecretsInjector instance.
    """
    global _injector

    if settings is not None:
        return SecretsInjector(settings)

    if _injector is None:
        _injector = SecretsInjector()

    return _injector


# Convenience dependencies
async def get_database_url() -> str:
    """FastAPI dependency for database URL."""
    injector = get_secrets_injector()
    return await injector.get_database_url()


async def get_redis_url() -> str:
    """FastAPI dependency for Redis URL."""
    injector = get_secrets_injector()
    return await injector.get_redis_url()


async def get_jwt_secret() -> str:
    """FastAPI dependency for JWT secret."""
    injector = get_secrets_injector()
    return await injector.get_jwt_secret()


async def get_encryption_key() -> bytes:
    """FastAPI dependency for encryption key."""
    injector = get_secrets_injector()
    return await injector.get_encryption_key()


def require_secret(key: str) -> Callable:
    """
    Create a dependency that requires a specific secret.

    Args:
        key: Secret key name.

    Returns:
        FastAPI dependency function.
    """
    injector = get_secrets_injector()
    return injector.get_secret(key, required=True)


def optional_secret(key: str, default: Optional[str] = None) -> Callable:
    """
    Create a dependency for an optional secret.

    Args:
        key: Secret key name.
        default: Default value if not found.

    Returns:
        FastAPI dependency function.
    """
    injector = get_secrets_injector()
    return injector.get_secret(key, required=False, default=default)
