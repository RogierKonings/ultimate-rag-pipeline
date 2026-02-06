"""
HashiCorp Vault client.

This module provides a client for interacting with HashiCorp Vault
for secrets management, dynamic credentials, and encryption.
"""

from pathlib import Path
from typing import Any

import structlog

from .config import VaultAuthMethod, VaultSettings

logger = structlog.get_logger(__name__)


class VaultError(Exception):
    """Base exception for Vault errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class VaultAuthError(VaultError):
    """Raised when Vault authentication fails."""


class VaultSecretError(VaultError):
    """Raised when secret operations fail."""


class VaultClient:
    """
    HashiCorp Vault client for secrets management.

    Supports:
    - KV secrets engine (v2)
    - Transit engine for encryption
    - Database engine for dynamic credentials
    - Multiple authentication methods

    Example:
        ```python
        from shared.security.secrets import VaultClient, VaultSettings

        settings = VaultSettings(
            url="https://vault.example.com",
            auth_method=VaultAuthMethod.KUBERNETES,
            kubernetes_role="rag-pipeline",
        )
        client = VaultClient(settings)

        # Read a secret
        secret = await client.read_secret("database/credentials")

        # Get database credentials (dynamic)
        creds = await client.get_database_credentials("postgres-role")

        # Encrypt data
        encrypted = await client.encrypt("sensitive data")
        decrypted = await client.decrypt(encrypted)
        ```
    """

    def __init__(self, settings: VaultSettings | None = None):
        """
        Initialize Vault client.

        Args:
            settings: Vault configuration. If None, uses defaults.
        """
        self.settings = settings or VaultSettings()
        self._client = None
        self._authenticated = False

    def _get_client(self):
        """Get or create Vault client."""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def _create_client(self):
        """Create hvac client."""
        try:
            import hvac
        except ImportError:
            raise VaultError(
                "hvac not installed. Install with: pip install hvac",
            ) from None

        # Create client
        client = hvac.Client(
            url=self.settings.url,
            namespace=self.settings.namespace,
            verify=self.settings.verify_ssl,
            timeout=self.settings.timeout,
        )

        # Set CA cert if configured
        if self.settings.ca_cert_path:
            client.session.verify = self.settings.ca_cert_path

        return client

    async def authenticate(self) -> None:
        """
        Authenticate with Vault.

        Uses the configured authentication method.

        Raises:
            VaultAuthError: If authentication fails.
        """
        client = self._get_client()

        try:
            if self.settings.auth_method == VaultAuthMethod.TOKEN:
                await self._auth_token(client)
            elif self.settings.auth_method == VaultAuthMethod.KUBERNETES:
                await self._auth_kubernetes(client)
            elif self.settings.auth_method == VaultAuthMethod.APPROLE:
                await self._auth_approle(client)
            else:
                raise VaultAuthError(
                    f"Unknown auth method: {self.settings.auth_method}",
                )

            self._authenticated = True
            logger.info(
                f"Authenticated with Vault using {self.settings.auth_method}",
            )

        except Exception as e:
            raise VaultAuthError(
                f"Vault authentication failed: {str(e)}",
                {"auth_method": self.settings.auth_method},
            ) from e

    async def _auth_token(self, client) -> None:
        """Authenticate using token."""
        import os

        token = self.settings.token or os.getenv(self.settings.token_env_var)
        if not token:
            raise VaultAuthError(
                f"Vault token not found in settings or {self.settings.token_env_var}",
            )
        client.token = token

    async def _auth_kubernetes(self, client) -> None:
        """Authenticate using Kubernetes service account."""
        if not self.settings.kubernetes_role:
            raise VaultAuthError("Kubernetes role not configured")

        # Read service account token
        sa_token_path = Path(self.settings.service_account_token_path)
        if not sa_token_path.exists():
            raise VaultAuthError(
                f"Service account token not found: {sa_token_path}",
            )

        sa_token = sa_token_path.read_text().strip()

        client.auth.kubernetes.login(
            role=self.settings.kubernetes_role,
            jwt=sa_token,
            mount_point=self.settings.kubernetes_mount_path,
        )

    async def _auth_approle(self, client) -> None:
        """Authenticate using AppRole."""
        if not self.settings.approle_role_id:
            raise VaultAuthError("AppRole role_id not configured")

        client.auth.approle.login(
            role_id=self.settings.approle_role_id,
            secret_id=self.settings.approle_secret_id,
            mount_point=self.settings.approle_mount_path,
        )

    async def _ensure_authenticated(self) -> None:
        """Ensure client is authenticated."""
        if not self._authenticated:
            await self.authenticate()

    async def read_secret(self, path: str) -> dict[str, Any]:
        """
        Read a secret from Vault KV store.

        Args:
            path: Secret path (relative to base path).

        Returns:
            Secret data as dictionary.

        Raises:
            VaultSecretError: If reading fails.
        """
        await self._ensure_authenticated()
        client = self._get_client()

        full_path = f"{self.settings.secrets_base_path}/{path}"

        try:
            response = client.secrets.kv.v2.read_secret_version(
                path=full_path,
                mount_point=self.settings.secrets_mount_path,
            )
            return response["data"]["data"]

        except Exception as e:
            raise VaultSecretError(
                f"Failed to read secret at {path}: {str(e)}",
                {"path": full_path},
            ) from e

    async def write_secret(self, path: str, data: dict[str, Any]) -> None:
        """
        Write a secret to Vault KV store.

        Args:
            path: Secret path (relative to base path).
            data: Secret data to write.

        Raises:
            VaultSecretError: If writing fails.
        """
        await self._ensure_authenticated()
        client = self._get_client()

        full_path = f"{self.settings.secrets_base_path}/{path}"

        try:
            client.secrets.kv.v2.create_or_update_secret(
                path=full_path,
                secret=data,
                mount_point=self.settings.secrets_mount_path,
            )
            logger.info(f"Wrote secret to {path}")

        except Exception as e:
            raise VaultSecretError(
                f"Failed to write secret at {path}: {str(e)}",
                {"path": full_path},
            ) from e

    async def delete_secret(self, path: str) -> None:
        """
        Delete a secret from Vault.

        Args:
            path: Secret path (relative to base path).

        Raises:
            VaultSecretError: If deletion fails.
        """
        await self._ensure_authenticated()
        client = self._get_client()

        full_path = f"{self.settings.secrets_base_path}/{path}"

        try:
            client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=full_path,
                mount_point=self.settings.secrets_mount_path,
            )
            logger.info(f"Deleted secret at {path}")

        except Exception as e:
            raise VaultSecretError(
                f"Failed to delete secret at {path}: {str(e)}",
                {"path": full_path},
            ) from e

    async def list_secrets(self, path: str = "") -> list[str]:
        """
        List secrets at a path.

        Args:
            path: Path to list (relative to base path).

        Returns:
            List of secret keys.

        Raises:
            VaultSecretError: If listing fails.
        """
        await self._ensure_authenticated()
        client = self._get_client()

        full_path = f"{self.settings.secrets_base_path}/{path}".rstrip("/")

        try:
            response = client.secrets.kv.v2.list_secrets(
                path=full_path,
                mount_point=self.settings.secrets_mount_path,
            )
            return response["data"]["keys"]

        except Exception as e:
            # Path might not exist - return empty list
            if "path does not exist" in str(e).lower():
                return []
            raise VaultSecretError(
                f"Failed to list secrets at {path}: {str(e)}",
                {"path": full_path},
            ) from e

    async def get_database_credentials(
        self,
        role: str,
    ) -> dict[str, str]:
        """
        Get dynamic database credentials.

        Uses Vault's database secrets engine to generate
        short-lived credentials.

        Args:
            role: Database role name.

        Returns:
            Dict with username and password.

        Raises:
            VaultSecretError: If credential generation fails.
        """
        await self._ensure_authenticated()
        client = self._get_client()

        try:
            response = client.secrets.database.generate_credentials(
                name=role,
                mount_point=self.settings.database_mount_path,
            )
            return {
                "username": response["data"]["username"],
                "password": response["data"]["password"],
                "lease_id": response["lease_id"],
                "lease_duration": response["lease_duration"],
            }

        except Exception as e:
            raise VaultSecretError(
                f"Failed to get database credentials for role {role}: {str(e)}",
                {"role": role},
            ) from e

    async def encrypt(self, plaintext: str) -> str:
        """
        Encrypt data using Vault Transit engine.

        Args:
            plaintext: Data to encrypt.

        Returns:
            Ciphertext (Vault cipher format).

        Raises:
            VaultSecretError: If encryption fails.
        """
        await self._ensure_authenticated()
        client = self._get_client()

        import base64

        try:
            # Transit expects base64-encoded plaintext
            encoded = base64.b64encode(plaintext.encode()).decode()

            response = client.secrets.transit.encrypt_data(
                name=self.settings.transit_key_name,
                plaintext=encoded,
                mount_point=self.settings.transit_mount_path,
            )
            return response["data"]["ciphertext"]

        except Exception as e:
            raise VaultSecretError(
                f"Transit encryption failed: {str(e)}",
            ) from e

    async def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt data using Vault Transit engine.

        Args:
            ciphertext: Vault ciphertext to decrypt.

        Returns:
            Decrypted plaintext.

        Raises:
            VaultSecretError: If decryption fails.
        """
        await self._ensure_authenticated()
        client = self._get_client()

        import base64

        try:
            response = client.secrets.transit.decrypt_data(
                name=self.settings.transit_key_name,
                ciphertext=ciphertext,
                mount_point=self.settings.transit_mount_path,
            )

            # Decode base64 result
            return base64.b64decode(response["data"]["plaintext"]).decode()

        except Exception as e:
            raise VaultSecretError(
                f"Transit decryption failed: {str(e)}",
            ) from e

    async def rewrap(self, ciphertext: str) -> str:
        """
        Rewrap ciphertext with latest key version.

        Used for key rotation without decrypting data.

        Args:
            ciphertext: Existing ciphertext.

        Returns:
            Re-encrypted ciphertext with latest key.

        Raises:
            VaultSecretError: If rewrap fails.
        """
        await self._ensure_authenticated()
        client = self._get_client()

        try:
            response = client.secrets.transit.rewrap_data(
                name=self.settings.transit_key_name,
                ciphertext=ciphertext,
                mount_point=self.settings.transit_mount_path,
            )
            return response["data"]["ciphertext"]

        except Exception as e:
            raise VaultSecretError(
                f"Transit rewrap failed: {str(e)}",
            ) from e

    async def rotate_key(self) -> None:
        """
        Rotate the transit encryption key.

        Creates a new key version. Old ciphertext can still
        be decrypted but new encryptions use the new key.

        Raises:
            VaultSecretError: If rotation fails.
        """
        await self._ensure_authenticated()
        client = self._get_client()

        try:
            client.secrets.transit.rotate_key(
                name=self.settings.transit_key_name,
                mount_point=self.settings.transit_mount_path,
            )
            logger.info(
                f"Rotated transit key: {self.settings.transit_key_name}",
            )

        except Exception as e:
            raise VaultSecretError(
                f"Key rotation failed: {str(e)}",
            ) from e

    def is_authenticated(self) -> bool:
        """Check if client is authenticated."""
        if not self._authenticated:
            return False

        client = self._get_client()
        return client.is_authenticated()

    async def health_check(self) -> dict[str, Any]:
        """
        Check Vault health status.

        Returns:
            Health status information.
        """
        client = self._get_client()

        try:
            response = client.sys.read_health_status(method="GET")
            return {
                "initialized": response.get("initialized", False),
                "sealed": response.get("sealed", True),
                "standby": response.get("standby", False),
                "version": response.get("version", "unknown"),
            }
        except Exception as e:
            return {
                "error": str(e),
                "healthy": False,
            }
