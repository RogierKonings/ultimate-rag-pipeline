"""
Kubernetes Secrets client.

This module provides a client for reading and writing
Kubernetes Secrets as a secrets backend.
"""

import base64
import logging
from typing import Any

from .config import KubernetesSecretsSettings

logger = logging.getLogger(__name__)


class K8sSecretsError(Exception):
    """Base exception for Kubernetes Secrets errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class K8sSecretsClient:
    """
    Kubernetes Secrets client.

    Provides access to Kubernetes Secrets as a secrets backend.
    Useful when Vault is not available but you need centralized
    secrets management within Kubernetes.

    Example:
        ```python
        from services.shared.security.secrets import (
            K8sSecretsClient,
            KubernetesSecretsSettings,
        )

        settings = KubernetesSecretsSettings(
            namespace="rag-pipeline",
            secret_name="app-secrets",
        )
        client = K8sSecretsClient(settings)

        # Read all secrets
        secrets = await client.read_all_secrets()

        # Read specific secret
        value = await client.read_secret("database-password")

        # Update a secret
        await client.write_secret("api-key", "new-value")
        ```
    """

    def __init__(self, settings: KubernetesSecretsSettings | None = None):
        """
        Initialize Kubernetes Secrets client.

        Args:
            settings: K8s settings. If None, uses defaults.
        """
        self.settings = settings or KubernetesSecretsSettings()
        self._api = None
        self._namespace = None

    def _get_api(self):
        """Get or create Kubernetes API client."""
        if self._api is None:
            self._api, self._namespace = self._create_api()
        return self._api

    def _create_api(self):
        """Create Kubernetes API client."""
        try:
            from kubernetes import client, config
        except ImportError:
            raise K8sSecretsError(
                "kubernetes not installed. Install with: pip install kubernetes",
            ) from None

        try:
            if self.settings.kubeconfig_path:
                # Use specified kubeconfig
                config.load_kube_config(
                    config_file=self.settings.kubeconfig_path,
                )
            else:
                # Try in-cluster config, fall back to kubeconfig
                try:
                    config.load_incluster_config()
                except config.ConfigException:
                    config.load_kube_config()

        except Exception as e:
            raise K8sSecretsError(
                f"Failed to load Kubernetes config: {str(e)}",
            ) from e

        api = client.CoreV1Api()

        # Determine namespace
        namespace = self.settings.namespace
        if namespace is None:
            # Try to get current namespace from service account
            try:
                with open(
                    "/var/run/secrets/kubernetes.io/serviceaccount/namespace",
                ) as f:
                    namespace = f.read().strip()
            except FileNotFoundError:
                namespace = "default"

        return api, namespace

    async def read_secret(self, key: str) -> str | None:
        """
        Read a single secret value.

        Args:
            key: Secret key to read.

        Returns:
            Secret value as string, or None if not found.

        Raises:
            K8sSecretsError: If reading fails.
        """
        secrets = await self.read_all_secrets()
        return secrets.get(key)

    async def read_all_secrets(self) -> dict[str, str]:
        """
        Read all secrets from the Kubernetes Secret.

        Returns:
            Dictionary of secret key-value pairs.

        Raises:
            K8sSecretsError: If reading fails.
        """
        api = self._get_api()

        try:
            secret = api.read_namespaced_secret(
                name=self.settings.secret_name,
                namespace=self._namespace,
            )

            if secret.data is None:
                return {}

            # Decode base64 values
            return {
                key: base64.b64decode(value).decode("utf-8")
                for key, value in secret.data.items()
            }

        except Exception as e:
            if "not found" in str(e).lower():
                return {}
            raise K8sSecretsError(
                f"Failed to read Kubernetes secret: {str(e)}",
                {
                    "secret_name": self.settings.secret_name,
                    "namespace": self._namespace,
                },
            ) from e

    async def write_secret(self, key: str, value: str) -> None:
        """
        Write or update a single secret value.

        Creates the Secret if it doesn't exist.

        Args:
            key: Secret key.
            value: Secret value.

        Raises:
            K8sSecretsError: If writing fails.
        """
        await self.write_secrets({key: value})

    async def write_secrets(self, data: dict[str, str]) -> None:
        """
        Write or update multiple secret values.

        Merges with existing secrets.

        Args:
            data: Dictionary of key-value pairs to write.

        Raises:
            K8sSecretsError: If writing fails.
        """
        try:
            from kubernetes import client
        except ImportError:
            raise K8sSecretsError(
                "kubernetes not installed. Install with: pip install kubernetes",
            ) from None

        api = self._get_api()

        # Read existing secrets
        existing = await self.read_all_secrets()

        # Merge with new data
        merged = {**existing, **data}

        # Encode as base64
        encoded = {
            key: base64.b64encode(value.encode("utf-8")).decode("utf-8")
            for key, value in merged.items()
        }

        body = client.V1Secret(
            metadata=client.V1ObjectMeta(
                name=self.settings.secret_name,
                namespace=self._namespace,
            ),
            type="Opaque",
            data=encoded,
        )

        try:
            # Try to update existing
            api.replace_namespaced_secret(
                name=self.settings.secret_name,
                namespace=self._namespace,
                body=body,
            )
            logger.info(f"Updated Kubernetes secret: {self.settings.secret_name}")

        except Exception as e:
            if "not found" in str(e).lower():
                # Create new secret
                api.create_namespaced_secret(
                    namespace=self._namespace,
                    body=body,
                )
                logger.info(
                    f"Created Kubernetes secret: {self.settings.secret_name}",
                )
            else:
                raise K8sSecretsError(
                    f"Failed to write Kubernetes secret: {str(e)}",
                    {"secret_name": self.settings.secret_name},
                ) from e

    async def delete_secret(self, key: str) -> None:
        """
        Delete a single secret key.

        Args:
            key: Secret key to delete.

        Raises:
            K8sSecretsError: If deletion fails.
        """
        try:
            from kubernetes import client
        except ImportError:
            raise K8sSecretsError(
                "kubernetes not installed. Install with: pip install kubernetes",
            ) from None

        api = self._get_api()

        # Read existing secrets
        existing = await self.read_all_secrets()

        if key not in existing:
            return  # Nothing to delete

        # Remove key
        del existing[key]

        # Re-encode
        encoded = {
            k: base64.b64encode(v.encode("utf-8")).decode("utf-8")
            for k, v in existing.items()
        }

        body = client.V1Secret(
            metadata=client.V1ObjectMeta(
                name=self.settings.secret_name,
                namespace=self._namespace,
            ),
            type="Opaque",
            data=encoded,
        )

        try:
            api.replace_namespaced_secret(
                name=self.settings.secret_name,
                namespace=self._namespace,
                body=body,
            )
            logger.info(f"Deleted key '{key}' from Kubernetes secret")

        except Exception as e:
            raise K8sSecretsError(
                f"Failed to delete secret key: {str(e)}",
                {"key": key},
            ) from e

    async def delete_all_secrets(self) -> None:
        """
        Delete the entire Kubernetes Secret.

        Raises:
            K8sSecretsError: If deletion fails.
        """
        api = self._get_api()

        try:
            api.delete_namespaced_secret(
                name=self.settings.secret_name,
                namespace=self._namespace,
            )
            logger.info(f"Deleted Kubernetes secret: {self.settings.secret_name}")

        except Exception as e:
            if "not found" in str(e).lower():
                return  # Already deleted
            raise K8sSecretsError(
                f"Failed to delete Kubernetes secret: {str(e)}",
                {"secret_name": self.settings.secret_name},
            ) from e

    async def list_keys(self) -> list[str]:
        """
        List all secret keys.

        Returns:
            List of secret key names.
        """
        secrets = await self.read_all_secrets()
        return list(secrets.keys())

    async def health_check(self) -> dict[str, Any]:
        """
        Check Kubernetes Secrets health.

        Returns:
            Health status information.
        """
        try:
            api = self._get_api()

            # Try to read the secret
            api.read_namespaced_secret(
                name=self.settings.secret_name,
                namespace=self._namespace,
            )

            return {
                "healthy": True,
                "namespace": self._namespace,
                "secret_name": self.settings.secret_name,
            }

        except Exception as e:
            if "not found" in str(e).lower():
                return {
                    "healthy": True,  # API works, secret just doesn't exist
                    "namespace": self._namespace,
                    "secret_name": self.settings.secret_name,
                    "secret_exists": False,
                }
            return {
                "healthy": False,
                "error": str(e),
            }
