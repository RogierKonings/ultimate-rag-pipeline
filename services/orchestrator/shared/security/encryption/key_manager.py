"""
Encryption key management with support for multiple providers.

This module provides key management including key storage, retrieval,
rotation, and integration with HashiCorp Vault.
"""

import base64
import logging
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Key size for AES-256
KEY_SIZE = 32


class KeyProvider(ABC):
    """Abstract base class for key providers."""

    @abstractmethod
    def get_key(self, key_name: str) -> bytes | None:
        """
        Retrieve an encryption key.

        Args:
            key_name: Name/identifier of the key.

        Returns:
            Key bytes if found, None otherwise.
        """

    @abstractmethod
    def set_key(self, key_name: str, key: bytes) -> None:
        """
        Store an encryption key.

        Args:
            key_name: Name/identifier for the key.
            key: Key bytes to store.
        """

    @abstractmethod
    def delete_key(self, key_name: str) -> None:
        """
        Delete an encryption key.

        Args:
            key_name: Name/identifier of the key to delete.
        """

    @abstractmethod
    def list_keys(self) -> list[str]:
        """
        List all available key names.

        Returns:
            List of key names.
        """


class EnvironmentKeyProvider(KeyProvider):
    """
    Key provider using environment variables.

    Keys are stored as base64-encoded strings in environment variables.
    Key names are converted to uppercase with underscores.

    Example:
        Key name "field-encryption" -> ENV var "FIELD_ENCRYPTION_KEY"
    """

    def __init__(self, prefix: str = ""):
        """
        Initialize environment key provider.

        Args:
            prefix: Optional prefix for environment variable names.
        """
        self._prefix = prefix

    def _env_name(self, key_name: str) -> str:
        """Convert key name to environment variable name."""
        name = key_name.upper().replace("-", "_").replace(".", "_")
        if self._prefix:
            return f"{self._prefix}_{name}_KEY"
        return f"{name}_KEY"

    def get_key(self, key_name: str) -> bytes | None:
        """Get key from environment variable."""
        env_name = self._env_name(key_name)
        key_b64 = os.environ.get(env_name)

        if key_b64 is None:
            return None

        try:
            return base64.b64decode(key_b64)
        except Exception as e:
            logger.error(f"Failed to decode key {key_name}: {e}")
            return None

    def set_key(self, key_name: str, key: bytes) -> None:
        """Set key in environment variable (for current process only)."""
        env_name = self._env_name(key_name)
        os.environ[env_name] = base64.b64encode(key).decode("utf-8")
        logger.debug(f"Set key {key_name} in environment")

    def delete_key(self, key_name: str) -> None:
        """Delete key from environment variable."""
        env_name = self._env_name(key_name)
        os.environ.pop(env_name, None)

    def list_keys(self) -> list[str]:
        """List keys based on environment variables."""
        suffix = "_KEY"
        prefix = f"{self._prefix}_" if self._prefix else ""

        keys = []
        for env_name in os.environ:
            if env_name.endswith(suffix):
                if prefix and env_name.startswith(prefix):
                    name = env_name[len(prefix) : -len(suffix)]
                    keys.append(name.lower().replace("_", "-"))
                elif not prefix:
                    name = env_name[: -len(suffix)]
                    keys.append(name.lower().replace("_", "-"))

        return keys


class FileKeyProvider(KeyProvider):
    """
    Key provider using file system.

    Keys are stored as files in a directory. Suitable for development
    and testing. In production, use Vault or a managed KMS.

    WARNING: Ensure the key directory has appropriate permissions.
    """

    def __init__(self, key_directory: str):
        """
        Initialize file key provider.

        Args:
            key_directory: Directory to store key files.
        """
        self._dir = Path(key_directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _key_path(self, key_name: str) -> Path:
        """Get path for a key file."""
        # Sanitize key name
        safe_name = key_name.replace("/", "_").replace("\\", "_")
        return self._dir / f"{safe_name}.key"

    def get_key(self, key_name: str) -> bytes | None:
        """Get key from file."""
        path = self._key_path(key_name)

        if not path.exists():
            return None

        try:
            content = path.read_text().strip()
            return base64.b64decode(content)
        except Exception as e:
            logger.error(f"Failed to read key {key_name}: {e}")
            return None

    def set_key(self, key_name: str, key: bytes) -> None:
        """Store key in file."""
        path = self._key_path(key_name)

        try:
            path.write_text(base64.b64encode(key).decode("utf-8"))
            # Set restrictive permissions
            path.chmod(0o600)
            logger.debug(f"Stored key {key_name}")
        except Exception as e:
            logger.error(f"Failed to store key {key_name}: {e}")
            raise

    def delete_key(self, key_name: str) -> None:
        """Delete key file."""
        path = self._key_path(key_name)

        if path.exists():
            path.unlink()
            logger.debug(f"Deleted key {key_name}")

    def list_keys(self) -> list[str]:
        """List all key files."""
        return [p.stem for p in self._dir.glob("*.key")]


class VaultKeyProvider(KeyProvider):
    """
    Key provider using HashiCorp Vault.

    Stores keys in Vault's KV secrets engine.

    Example:
        ```python
        provider = VaultKeyProvider(
            url="https://vault.example.com",
            token="hvs.xxx",
            mount_path="secret",
            path_prefix="rag-pipeline/encryption",
        )

        key = provider.get_key("field-encryption")
        ```
    """

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        mount_path: str = "secret",
        path_prefix: str = "encryption",
        namespace: str | None = None,
    ):
        """
        Initialize Vault key provider.

        Args:
            url: Vault server URL (or VAULT_ADDR env var).
            token: Vault token (or VAULT_TOKEN env var).
            mount_path: KV secrets engine mount path.
            path_prefix: Path prefix for keys within the mount.
            namespace: Vault namespace (Enterprise feature).
        """
        self._url = url or os.environ.get("VAULT_ADDR")
        self._token = token or os.environ.get("VAULT_TOKEN")
        self._mount = mount_path
        self._prefix = path_prefix
        self._namespace = namespace
        self._client = None

    def _get_client(self):
        """Get or create Vault client."""
        if self._client is None:
            try:
                import hvac

                self._client = hvac.Client(
                    url=self._url,
                    token=self._token,
                    namespace=self._namespace,
                )

                if not self._client.is_authenticated():
                    raise RuntimeError("Vault authentication failed")

            except ImportError:
                raise ImportError(
                    "hvac package required for Vault integration. Install with: pip install hvac",
                ) from None

        return self._client

    def _key_path(self, key_name: str) -> str:
        """Get Vault path for a key."""
        return f"{self._prefix}/{key_name}"

    def get_key(self, key_name: str) -> bytes | None:
        """Get key from Vault."""
        try:
            client = self._get_client()
            path = self._key_path(key_name)

            response = client.secrets.kv.v2.read_secret_version(
                mount_point=self._mount,
                path=path,
            )

            if response and response.get("data", {}).get("data"):
                key_b64 = response["data"]["data"].get("key")
                if key_b64:
                    return base64.b64decode(key_b64)

            return None

        except Exception as e:
            logger.error(f"Failed to get key {key_name} from Vault: {e}")
            return None

    def set_key(self, key_name: str, key: bytes) -> None:
        """Store key in Vault."""
        try:
            client = self._get_client()
            path = self._key_path(key_name)

            client.secrets.kv.v2.create_or_update_secret(
                mount_point=self._mount,
                path=path,
                secret={
                    "key": base64.b64encode(key).decode("utf-8"),
                    "created_at": datetime.now(UTC).isoformat(),
                    "algorithm": "AES-256-GCM",
                },
            )

            logger.info(f"Stored key {key_name} in Vault")

        except Exception as e:
            logger.error(f"Failed to store key {key_name} in Vault: {e}")
            raise

    def delete_key(self, key_name: str) -> None:
        """Delete key from Vault."""
        try:
            client = self._get_client()
            path = self._key_path(key_name)

            client.secrets.kv.v2.delete_metadata_and_all_versions(
                mount_point=self._mount,
                path=path,
            )

            logger.info(f"Deleted key {key_name} from Vault")

        except Exception as e:
            logger.error(f"Failed to delete key {key_name} from Vault: {e}")
            raise

    def list_keys(self) -> list[str]:
        """List all keys in Vault path."""
        try:
            client = self._get_client()

            response = client.secrets.kv.v2.list_secrets(
                mount_point=self._mount,
                path=self._prefix,
            )

            if response and response.get("data", {}).get("keys"):
                return response["data"]["keys"]

            return []

        except Exception as e:
            logger.error(f"Failed to list keys in Vault: {e}")
            return []


class EncryptionKeyManager:
    """
    High-level encryption key manager.

    Provides a unified interface for key management with support for
    multiple providers, key rotation, and caching.

    Example:
        ```python
        from shared.security.encryption import (
            EncryptionKeyManager,
            EnvironmentKeyProvider,
            VaultKeyProvider,
        )

        # Development: Use environment variables
        manager = EncryptionKeyManager(EnvironmentKeyProvider())

        # Production: Use Vault
        manager = EncryptionKeyManager(VaultKeyProvider(
            url="https://vault.example.com",
        ))

        # Get or create a key
        key = manager.get_or_create_key("field-encryption")

        # Rotate key
        new_key, old_key = manager.rotate_key("field-encryption")
        ```
    """

    def __init__(
        self,
        provider: KeyProvider,
        cache_keys: bool = True,
    ):
        """
        Initialize key manager.

        Args:
            provider: Key storage provider.
            cache_keys: Whether to cache keys in memory.
        """
        self._provider = provider
        self._cache_enabled = cache_keys
        self._cache: dict[str, bytes] = {}

    def get_key(self, key_name: str) -> bytes | None:
        """
        Get an encryption key.

        Args:
            key_name: Name of the key.

        Returns:
            Key bytes if found, None otherwise.
        """
        # Check cache first
        if self._cache_enabled and key_name in self._cache:
            return self._cache[key_name]

        key = self._provider.get_key(key_name)

        if key is not None and self._cache_enabled:
            self._cache[key_name] = key

        return key

    def set_key(self, key_name: str, key: bytes) -> None:
        """
        Store an encryption key.

        Args:
            key_name: Name for the key.
            key: Key bytes to store.
        """
        if len(key) != KEY_SIZE:
            raise ValueError(
                f"Invalid key size: {len(key)} bytes. Expected {KEY_SIZE} bytes for AES-256.",
            )

        self._provider.set_key(key_name, key)

        if self._cache_enabled:
            self._cache[key_name] = key

    def get_or_create_key(self, key_name: str) -> bytes:
        """
        Get existing key or create a new one.

        Args:
            key_name: Name of the key.

        Returns:
            Existing or newly generated key.
        """
        key = self.get_key(key_name)

        if key is None:
            import secrets

            key = secrets.token_bytes(KEY_SIZE)
            self.set_key(key_name, key)
            logger.info(f"Generated new key: {key_name}")

        return key

    def rotate_key(self, key_name: str) -> tuple[bytes, bytes | None]:
        """
        Rotate an encryption key.

        Creates a new key and stores the old key with a ".previous" suffix.

        Args:
            key_name: Name of the key to rotate.

        Returns:
            Tuple of (new_key, old_key). old_key is None if no previous key.
        """
        import secrets

        # Get current key
        old_key = self.get_key(key_name)

        # Store old key as previous (if exists)
        if old_key is not None:
            self._provider.set_key(f"{key_name}.previous", old_key)

        # Generate and store new key
        new_key = secrets.token_bytes(KEY_SIZE)
        self.set_key(key_name, new_key)

        # Update cache
        if self._cache_enabled:
            self._cache[key_name] = new_key
            if old_key:
                self._cache[f"{key_name}.previous"] = old_key

        logger.info(f"Rotated key: {key_name}")

        return new_key, old_key

    def get_previous_key(self, key_name: str) -> bytes | None:
        """Get the previous version of a rotated key."""
        return self.get_key(f"{key_name}.previous")

    def delete_key(self, key_name: str) -> None:
        """Delete a key."""
        self._provider.delete_key(key_name)

        if self._cache_enabled:
            self._cache.pop(key_name, None)

    def list_keys(self) -> list[str]:
        """List all key names."""
        return self._provider.list_keys()

    def clear_cache(self) -> None:
        """Clear the key cache."""
        self._cache.clear()
