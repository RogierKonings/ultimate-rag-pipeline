"""
Secret provider interface and implementations.

This module provides an abstract interface for secret providers with
support for caching, expiration metadata, and lease management.
"""

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from .config import SecretsBackend
from .vault import VaultClient, VaultError

logger = structlog.get_logger(__name__)


@dataclass
class SecretValue:
    """
    Wrapper for secret value with metadata.

    Provides additional context about the secret including
    version, expiration, and lease information for dynamic secrets.
    """

    value: Any
    version: str | None = None
    expires_at: float | None = None
    lease_id: str | None = None
    lease_duration: int | None = None
    created_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        """Check if secret has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    @property
    def time_until_expiry(self) -> float | None:
        """Get seconds until expiry (None if no expiry)."""
        if self.expires_at is None:
            return None
        return max(0, self.expires_at - time.time())


class SecretProviderError(Exception):
    """Base exception for secret provider errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SecretProvider(ABC):
    """
    Abstract interface for secret providers.

    Defines the contract for secret providers with support for
    caching, refresh, and metadata.

    Example:
        ```python
        class CustomProvider(SecretProvider):
            async def get(self, key: str) -> SecretValue:
                # Implementation
                pass

            async def refresh(self, key: str) -> SecretValue:
                # Implementation
                pass

        provider = CustomProvider()
        secret = await provider.get("database/password")
        print(secret.value)
        ```
    """

    @abstractmethod
    async def get(self, key: str) -> SecretValue:
        """
        Get a secret by key.

        May return cached value if not expired.

        Args:
            key: Secret key/path.

        Returns:
            SecretValue with value and metadata.

        Raises:
            SecretProviderError: If retrieval fails.
        """

    @abstractmethod
    async def refresh(self, key: str) -> SecretValue:
        """
        Refresh a secret (get latest version).

        Always fetches from source, ignoring cache.

        Args:
            key: Secret key/path.

        Returns:
            SecretValue with fresh value and metadata.

        Raises:
            SecretProviderError: If refresh fails.
        """

    async def get_or_default(
        self,
        key: str,
        default: Any = None,
    ) -> SecretValue:
        """
        Get a secret or return default value.

        Args:
            key: Secret key/path.
            default: Default value if secret not found.

        Returns:
            SecretValue with value or default.
        """
        try:
            return await self.get(key)
        except SecretProviderError:
            return SecretValue(value=default)


class VaultSecretProvider(SecretProvider):
    """
    Vault-backed secret provider.

    Provides secrets from HashiCorp Vault with caching
    and automatic expiration handling.

    Example:
        ```python
        from shared.security.secrets import (
            VaultSecretProvider,
            VaultClient,
            VaultSettings,
        )

        settings = VaultSettings(...)
        vault = VaultClient(settings)
        await vault.authenticate()

        provider = VaultSecretProvider(vault, "rag-pipeline")

        secret = await provider.get("database")
        print(secret.value["password"])
        ```
    """

    def __init__(
        self,
        vault_client: VaultClient,
        base_path: str = "",
        cache_ttl_seconds: int = 300,
    ):
        """
        Initialize Vault secret provider.

        Args:
            vault_client: Authenticated Vault client.
            base_path: Base path for secrets.
            cache_ttl_seconds: Cache TTL in seconds.
        """
        self.vault = vault_client
        self.base_path = base_path.rstrip("/")
        self.cache_ttl = cache_ttl_seconds
        self._cache: dict[str, SecretValue] = {}

    async def get(self, key: str) -> SecretValue:
        """Get secret, using cache if available and not expired."""
        if key in self._cache:
            cached = self._cache[key]
            if not cached.is_expired:
                return cached

        return await self.refresh(key)

    async def refresh(self, key: str) -> SecretValue:
        """Refresh secret from Vault."""
        path = f"{self.base_path}/{key}" if self.base_path else key

        try:
            value = await self.vault.read_secret(path)

            secret = SecretValue(
                value=value,
                expires_at=time.time() + self.cache_ttl,
            )

            self._cache[key] = secret

            logger.debug(
                "Fetched secret from Vault",
                extra={"path": path},
            )

            return secret

        except VaultError as e:
            raise SecretProviderError(
                f"Failed to read secret from Vault: {str(e)}",
                {"path": path},
            ) from e

    def clear_cache(self) -> None:
        """Clear the secrets cache."""
        self._cache.clear()

    def invalidate(self, key: str) -> None:
        """Invalidate a specific cached secret."""
        if key in self._cache:
            del self._cache[key]


class EnvironmentSecretProvider(SecretProvider):
    """
    Environment variable secret provider (for local development).

    Reads secrets from environment variables. Does not support
    expiration or versioning.

    Example:
        ```python
        # Set environment: RAG_DATABASE_PASSWORD=secret123

        provider = EnvironmentSecretProvider(prefix="RAG_")
        secret = await provider.get("database-password")
        # Looks up RAG_DATABASE_PASSWORD
        ```
    """

    def __init__(self, prefix: str = ""):
        """
        Initialize environment provider.

        Args:
            prefix: Prefix for environment variables.
        """
        self.prefix = prefix

    async def get(self, key: str) -> SecretValue:
        """Get secret from environment variable."""
        return await self.refresh(key)

    async def refresh(self, key: str) -> SecretValue:
        """Get secret from environment (no caching)."""
        env_key = self._key_to_env_var(key)
        value = os.getenv(env_key)

        if value is None:
            raise SecretProviderError(
                f"Environment variable not found: {env_key}",
                {"key": key, "env_key": env_key},
            )

        return SecretValue(value=value)

    def _key_to_env_var(self, key: str) -> str:
        """Convert key to environment variable name."""
        # Convert path-like keys to env var format
        # e.g., "database-password" -> "PREFIX_DATABASE_PASSWORD"
        normalized = key.upper().replace("-", "_").replace("/", "_")
        return f"{self.prefix}{normalized}"


class FileSecretProvider(SecretProvider):
    """
    File-based secret provider.

    Reads secrets from files in a directory. Useful for
    Docker secrets or Kubernetes secrets mounted as files.

    Example:
        ```python
        provider = FileSecretProvider("/run/secrets")
        secret = await provider.get("database_password")
        # Reads from /run/secrets/database_password
        ```
    """

    def __init__(
        self,
        secrets_dir: str = "/run/secrets",
        cache_ttl_seconds: int = 60,
    ):
        """
        Initialize file provider.

        Args:
            secrets_dir: Directory containing secret files.
            cache_ttl_seconds: Cache TTL in seconds.
        """
        from pathlib import Path

        self.secrets_dir = Path(secrets_dir)
        self.cache_ttl = cache_ttl_seconds
        self._cache: dict[str, SecretValue] = {}

    async def get(self, key: str) -> SecretValue:
        """Get secret, using cache if available."""
        if key in self._cache:
            cached = self._cache[key]
            if not cached.is_expired:
                return cached

        return await self.refresh(key)

    async def refresh(self, key: str) -> SecretValue:
        """Read secret from file."""
        file_path = self.secrets_dir / key

        if not file_path.exists():
            raise SecretProviderError(
                f"Secret file not found: {file_path}",
                {"key": key, "path": str(file_path)},
            )

        try:
            value = file_path.read_text().strip()

            # Get file modification time for version
            stat = file_path.stat()
            version = str(stat.st_mtime)

            secret = SecretValue(
                value=value,
                version=version,
                expires_at=time.time() + self.cache_ttl,
            )

            self._cache[key] = secret
            return secret

        except OSError as e:
            raise SecretProviderError(
                f"Failed to read secret file: {str(e)}",
                {"key": key, "path": str(file_path)},
            ) from e

    def clear_cache(self) -> None:
        """Clear the secrets cache."""
        self._cache.clear()


class CompositeSecretProvider(SecretProvider):
    """
    Composite provider that tries multiple providers in order.

    Useful for fallback scenarios where you want to try Vault
    first, then fall back to environment variables.

    Example:
        ```python
        vault_provider = VaultSecretProvider(vault, "rag-pipeline")
        env_provider = EnvironmentSecretProvider(prefix="RAG_")

        provider = CompositeSecretProvider([vault_provider, env_provider])

        # Tries Vault first, falls back to environment
        secret = await provider.get("database_password")
        ```
    """

    def __init__(self, providers: list[SecretProvider]):
        """
        Initialize composite provider.

        Args:
            providers: List of providers to try in order.
        """
        if not providers:
            raise ValueError("At least one provider required")
        self.providers = providers

    async def get(self, key: str) -> SecretValue:
        """Try providers in order until one succeeds."""
        errors = []

        for provider in self.providers:
            try:
                return await provider.get(key)
            except SecretProviderError as e:
                errors.append(str(e))
                continue

        raise SecretProviderError(
            f"All providers failed for key '{key}'",
            {"key": key, "errors": errors},
        )

    async def refresh(self, key: str) -> SecretValue:
        """Try providers in order for refresh."""
        errors = []

        for provider in self.providers:
            try:
                return await provider.refresh(key)
            except SecretProviderError as e:
                errors.append(str(e))
                continue

        raise SecretProviderError(
            f"All providers failed to refresh key '{key}'",
            {"key": key, "errors": errors},
        )


def create_secret_provider(
    backend: SecretsBackend | None = None,
    **kwargs,
) -> SecretProvider:
    """
    Factory function to create appropriate secret provider.

    Creates provider based on environment or explicit configuration.

    Args:
        backend: Backend type (auto-detected if None).
        **kwargs: Provider-specific configuration.

    Returns:
        SecretProvider instance.

    Example:
        ```python
        # Auto-detect from environment
        provider = create_secret_provider()

        # Explicit Vault
        provider = create_secret_provider(
            backend=SecretsBackend.VAULT,
            vault_client=vault,
            base_path="rag-pipeline",
        )
        ```
    """
    if backend is None:
        # Auto-detect from environment
        if os.getenv("VAULT_ADDR"):
            backend = SecretsBackend.VAULT
        elif Path("/run/secrets").exists():
            backend = SecretsBackend.FILE
        else:
            backend = SecretsBackend.ENVIRONMENT

    if backend == SecretsBackend.VAULT:
        vault_client = kwargs.get("vault_client")
        if vault_client is None:
            from .config import VaultSettings

            settings = VaultSettings(
                url=os.getenv("VAULT_ADDR", "http://localhost:8200"),
            )
            vault_client = VaultClient(settings)

        return VaultSecretProvider(
            vault_client=vault_client,
            base_path=kwargs.get("base_path", os.getenv("VAULT_SECRET_PATH", "rag-pipeline")),
            cache_ttl_seconds=kwargs.get("cache_ttl_seconds", 300),
        )

    if backend == SecretsBackend.ENVIRONMENT:
        return EnvironmentSecretProvider(
            prefix=kwargs.get("prefix", os.getenv("SECRETS_PREFIX", "RAG_")),
        )

    if backend == SecretsBackend.FILE:
        return FileSecretProvider(
            secrets_dir=kwargs.get("secrets_dir", "/run/secrets"),
            cache_ttl_seconds=kwargs.get("cache_ttl_seconds", 60),
        )

    raise ValueError(f"Unsupported backend: {backend}")
