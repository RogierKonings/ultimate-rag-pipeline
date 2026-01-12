"""
Unified secrets service.

This module provides a unified interface for secrets management
across different backends (Environment, Vault, Kubernetes, File).
"""

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from .config import SecretsBackend, SecretsSettings
from .vault import VaultClient, VaultError
from .k8s_secrets import K8sSecretsClient, K8sSecretsError

logger = logging.getLogger(__name__)


class SecretsError(Exception):
    """Base exception for secrets service errors."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SecretsService:
    """
    Unified secrets management service.

    Provides a consistent interface for secrets operations
    across multiple backends. Supports caching and automatic
    backend selection.

    Example:
        ```python
        from services.shared.security.secrets import (
            SecretsService,
            SecretsSettings,
            SecretsBackend,
        )

        # Development: use environment variables
        settings = SecretsSettings(
            backend=SecretsBackend.ENVIRONMENT,
            prefix="RAG_",
        )
        service = SecretsService(settings)

        # Read secrets
        db_password = await service.get_secret("DATABASE_PASSWORD")

        # Get database URL
        db_url = await service.get_database_url()

        # Get JWT keys
        jwt_secret = await service.get_jwt_secret()
        ```
    """

    def __init__(self, settings: Optional[SecretsSettings] = None):
        """
        Initialize secrets service.

        Args:
            settings: Service settings. If None, uses defaults.
        """
        self.settings = settings or SecretsSettings()
        self._vault_client: Optional[VaultClient] = None
        self._k8s_client: Optional[K8sSecretsClient] = None
        self._cache: dict[str, tuple[Any, float]] = {}

    def _get_vault_client(self) -> VaultClient:
        """Get or create Vault client."""
        if self._vault_client is None:
            self._vault_client = VaultClient(self.settings.vault)
        return self._vault_client

    def _get_k8s_client(self) -> K8sSecretsClient:
        """Get or create Kubernetes client."""
        if self._k8s_client is None:
            self._k8s_client = K8sSecretsClient(self.settings.kubernetes)
        return self._k8s_client

    def _cache_get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        if not self.settings.cache_enabled:
            return None

        if key not in self._cache:
            return None

        value, timestamp = self._cache[key]
        if time.time() - timestamp > self.settings.cache_ttl_seconds:
            del self._cache[key]
            return None

        return value

    def _cache_set(self, key: str, value: Any) -> None:
        """Set value in cache."""
        if self.settings.cache_enabled:
            self._cache[key] = (value, time.time())

    def clear_cache(self) -> None:
        """Clear the secrets cache."""
        self._cache.clear()

    async def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get a secret value.

        Args:
            key: Secret key/name.
            default: Default value if secret not found.

        Returns:
            Secret value or default.

        Raises:
            SecretsError: If retrieval fails (and no default provided).
        """
        # Check cache
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        try:
            value = await self._get_secret_from_backend(key)

            if value is None:
                return default

            self._cache_set(key, value)

            if self.settings.log_access:
                logger.debug(f"Read secret: {key}")

            return value

        except Exception as e:
            if default is not None:
                return default
            raise SecretsError(
                f"Failed to get secret '{key}': {str(e)}",
                {"key": key, "backend": self.settings.backend},
            )

    async def _get_secret_from_backend(self, key: str) -> Optional[str]:
        """Get secret from configured backend."""
        if self.settings.backend == SecretsBackend.ENVIRONMENT:
            return self._get_from_environment(key)

        elif self.settings.backend == SecretsBackend.VAULT:
            return await self._get_from_vault(key)

        elif self.settings.backend == SecretsBackend.KUBERNETES:
            return await self._get_from_kubernetes(key)

        elif self.settings.backend == SecretsBackend.FILE:
            return self._get_from_file(key)

        else:
            raise SecretsError(f"Unknown backend: {self.settings.backend}")

    def _get_from_environment(self, key: str) -> Optional[str]:
        """Get secret from environment variable."""
        env_key = f"{self.settings.prefix}{key}"
        return os.getenv(env_key)

    async def _get_from_vault(self, key: str) -> Optional[str]:
        """Get secret from Vault."""
        client = self._get_vault_client()

        # Try to read as a single key first
        try:
            data = await client.read_secret(key)
            # Return 'value' key if present, else first value
            if "value" in data:
                return data["value"]
            if data:
                return list(data.values())[0]
            return None
        except VaultError:
            return None

    async def _get_from_kubernetes(self, key: str) -> Optional[str]:
        """Get secret from Kubernetes Secrets."""
        client = self._get_k8s_client()
        return await client.read_secret(key)

    def _get_from_file(self, key: str) -> Optional[str]:
        """Get secret from file."""
        secrets_dir = Path(self.settings.file.secrets_dir)
        ext = self.settings.file.file_extension
        filename = f"{key}{ext}" if ext else key
        file_path = secrets_dir / filename

        if not file_path.exists():
            return None

        return file_path.read_text().strip()

    async def set_secret(self, key: str, value: str) -> None:
        """
        Set a secret value.

        Note: Not all backends support writing.

        Args:
            key: Secret key/name.
            value: Secret value.

        Raises:
            SecretsError: If setting fails.
        """
        try:
            await self._set_secret_in_backend(key, value)
            self._cache_set(key, value)

            if self.settings.log_access:
                logger.info(f"Set secret: {key}")

        except Exception as e:
            raise SecretsError(
                f"Failed to set secret '{key}': {str(e)}",
                {"key": key, "backend": self.settings.backend},
            )

    async def _set_secret_in_backend(self, key: str, value: str) -> None:
        """Set secret in configured backend."""
        if self.settings.backend == SecretsBackend.ENVIRONMENT:
            os.environ[f"{self.settings.prefix}{key}"] = value

        elif self.settings.backend == SecretsBackend.VAULT:
            client = self._get_vault_client()
            await client.write_secret(key, {"value": value})

        elif self.settings.backend == SecretsBackend.KUBERNETES:
            client = self._get_k8s_client()
            await client.write_secret(key, value)

        elif self.settings.backend == SecretsBackend.FILE:
            secrets_dir = Path(self.settings.file.secrets_dir)
            secrets_dir.mkdir(parents=True, exist_ok=True)
            ext = self.settings.file.file_extension
            filename = f"{key}{ext}" if ext else key
            file_path = secrets_dir / filename
            file_path.write_text(value)
            # Set restrictive permissions
            file_path.chmod(0o600)

        else:
            raise SecretsError(f"Unknown backend: {self.settings.backend}")

    async def delete_secret(self, key: str) -> None:
        """
        Delete a secret.

        Note: Not all backends support deletion.

        Args:
            key: Secret key/name.

        Raises:
            SecretsError: If deletion fails.
        """
        try:
            await self._delete_secret_from_backend(key)

            # Remove from cache
            cache_key = key
            if cache_key in self._cache:
                del self._cache[cache_key]

            if self.settings.log_access:
                logger.info(f"Deleted secret: {key}")

        except Exception as e:
            raise SecretsError(
                f"Failed to delete secret '{key}': {str(e)}",
                {"key": key, "backend": self.settings.backend},
            )

    async def _delete_secret_from_backend(self, key: str) -> None:
        """Delete secret from configured backend."""
        if self.settings.backend == SecretsBackend.ENVIRONMENT:
            env_key = f"{self.settings.prefix}{key}"
            if env_key in os.environ:
                del os.environ[env_key]

        elif self.settings.backend == SecretsBackend.VAULT:
            client = self._get_vault_client()
            await client.delete_secret(key)

        elif self.settings.backend == SecretsBackend.KUBERNETES:
            client = self._get_k8s_client()
            await client.delete_secret(key)

        elif self.settings.backend == SecretsBackend.FILE:
            secrets_dir = Path(self.settings.file.secrets_dir)
            ext = self.settings.file.file_extension
            filename = f"{key}{ext}" if ext else key
            file_path = secrets_dir / filename
            if file_path.exists():
                file_path.unlink()

        else:
            raise SecretsError(f"Unknown backend: {self.settings.backend}")

    # Convenience methods for common secrets

    async def get_database_url(
        self,
        key: str = "DATABASE_URL",
        components_prefix: str = "DATABASE",
    ) -> str:
        """
        Get database URL.

        Tries to get full URL first, then constructs from components.

        Args:
            key: Key for full database URL.
            components_prefix: Prefix for component keys.

        Returns:
            Database URL string.

        Raises:
            SecretsError: If URL cannot be constructed.
        """
        # Try full URL first
        url = await self.get_secret(key)
        if url:
            return url

        # Try to construct from components
        host = await self.get_secret(f"{components_prefix}_HOST")
        port = await self.get_secret(f"{components_prefix}_PORT", "5432")
        user = await self.get_secret(f"{components_prefix}_USER")
        password = await self.get_secret(f"{components_prefix}_PASSWORD")
        database = await self.get_secret(f"{components_prefix}_NAME")

        if all([host, user, password, database]):
            return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"

        raise SecretsError(
            "Could not construct database URL - missing components",
            {"key": key, "prefix": components_prefix},
        )

    async def get_redis_url(
        self,
        key: str = "REDIS_URL",
        components_prefix: str = "REDIS",
    ) -> str:
        """
        Get Redis URL.

        Args:
            key: Key for full Redis URL.
            components_prefix: Prefix for component keys.

        Returns:
            Redis URL string.
        """
        # Try full URL first
        url = await self.get_secret(key)
        if url:
            return url

        # Try to construct from components
        host = await self.get_secret(f"{components_prefix}_HOST", "localhost")
        port = await self.get_secret(f"{components_prefix}_PORT", "6379")
        password = await self.get_secret(f"{components_prefix}_PASSWORD")

        if password:
            return f"redis://:{password}@{host}:{port}"
        return f"redis://{host}:{port}"

    async def get_jwt_secret(self, key: str = "JWT_SECRET") -> str:
        """
        Get JWT signing secret.

        Args:
            key: Secret key name.

        Returns:
            JWT secret string.

        Raises:
            SecretsError: If secret not found.
        """
        secret = await self.get_secret(key)
        if not secret:
            raise SecretsError(
                f"JWT secret not found: {key}",
                {"key": key},
            )
        return secret

    async def get_encryption_key(self, key: str = "ENCRYPTION_KEY") -> bytes:
        """
        Get encryption key.

        Args:
            key: Secret key name.

        Returns:
            Encryption key as bytes.

        Raises:
            SecretsError: If key not found.
        """
        import base64

        secret = await self.get_secret(key)
        if not secret:
            raise SecretsError(
                f"Encryption key not found: {key}",
                {"key": key},
            )

        # Assume base64 encoded
        try:
            return base64.b64decode(secret)
        except Exception:
            # Return as raw bytes if not base64
            return secret.encode()

    async def get_api_key(self, service: str) -> str:
        """
        Get API key for external service.

        Args:
            service: Service name (e.g., "openai", "anthropic").

        Returns:
            API key string.

        Raises:
            SecretsError: If key not found.
        """
        key = f"{service.upper()}_API_KEY"
        api_key = await self.get_secret(key)
        if not api_key:
            raise SecretsError(
                f"API key not found for service: {service}",
                {"service": service, "key": key},
            )
        return api_key

    async def health_check(self) -> dict[str, Any]:
        """
        Check secrets service health.

        Returns:
            Health status for configured backend.
        """
        try:
            if self.settings.backend == SecretsBackend.VAULT:
                client = self._get_vault_client()
                return await client.health_check()

            elif self.settings.backend == SecretsBackend.KUBERNETES:
                client = self._get_k8s_client()
                return await client.health_check()

            elif self.settings.backend == SecretsBackend.ENVIRONMENT:
                return {
                    "healthy": True,
                    "backend": "environment",
                }

            elif self.settings.backend == SecretsBackend.FILE:
                secrets_dir = Path(self.settings.file.secrets_dir)
                return {
                    "healthy": secrets_dir.exists(),
                    "backend": "file",
                    "secrets_dir": str(secrets_dir),
                    "dir_exists": secrets_dir.exists(),
                }

            return {"healthy": False, "error": "Unknown backend"}

        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
            }


# Module-level convenience
_default_service: Optional[SecretsService] = None


def get_secrets_service(
    settings: Optional[SecretsSettings] = None,
) -> SecretsService:
    """
    Get or create default secrets service.

    Args:
        settings: Service settings. If None and no default exists,
                  creates from environment.

    Returns:
        SecretsService instance.
    """
    global _default_service

    if settings is not None:
        return SecretsService(settings)

    if _default_service is None:
        from .config import create_secrets_settings_from_env

        _default_service = SecretsService(create_secrets_settings_from_env())

    return _default_service


async def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    """Convenience function to get a secret with default service."""
    service = get_secrets_service()
    return await service.get_secret(key, default)
