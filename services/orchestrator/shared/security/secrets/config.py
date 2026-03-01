"""
Secrets management configuration.

This module defines configuration for secrets backends
and secret access patterns.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class SecretsBackend(StrEnum):
    """Supported secrets backends."""

    ENVIRONMENT = "environment"  # Environment variables (dev/test)
    VAULT = "vault"  # HashiCorp Vault
    KUBERNETES = "kubernetes"  # Kubernetes Secrets
    FILE = "file"  # File-based (for development)


class VaultAuthMethod(StrEnum):
    """Vault authentication methods."""

    TOKEN = "token"  # noqa: S105  # Direct token auth
    KUBERNETES = "kubernetes"  # Kubernetes service account
    APPROLE = "approle"  # AppRole auth


class VaultSettings(BaseModel):
    """
    HashiCorp Vault configuration.

    Example:
        ```python
        settings = VaultSettings(
            url="https://vault.example.com:8200",
            auth_method=VaultAuthMethod.KUBERNETES,
            kubernetes_role="rag-pipeline",
        )
        ```
    """

    url: str = Field(
        default="http://localhost:8200",
        description="Vault server URL",
    )
    namespace: str | None = Field(
        default=None,
        description="Vault namespace (enterprise feature)",
    )
    auth_method: VaultAuthMethod = Field(
        default=VaultAuthMethod.TOKEN,
        description="Authentication method",
    )

    # Token auth
    token: str | None = Field(
        default=None,
        description="Vault token (for token auth)",
    )
    token_env_var: str = Field(
        default="VAULT_TOKEN",
        description="Environment variable for token",
    )

    # Kubernetes auth
    kubernetes_role: str | None = Field(
        default=None,
        description="Kubernetes auth role name",
    )
    kubernetes_mount_path: str = Field(
        default="kubernetes",
        description="Kubernetes auth mount path",
    )
    service_account_token_path: str = Field(
        default="/var/run/secrets/kubernetes.io/serviceaccount/token",
        description="Path to service account token",
    )

    # AppRole auth
    approle_role_id: str | None = Field(
        default=None,
        description="AppRole role ID",
    )
    approle_secret_id: str | None = Field(
        default=None,
        description="AppRole secret ID",
    )
    approle_mount_path: str = Field(
        default="approle",
        description="AppRole auth mount path",
    )

    # Secrets paths
    secrets_mount_path: str = Field(
        default="secret",
        description="KV secrets engine mount path",
    )
    secrets_base_path: str = Field(
        default="rag-pipeline",
        description="Base path for application secrets",
    )

    # Transit engine
    transit_mount_path: str = Field(
        default="transit",
        description="Transit engine mount path",
    )
    transit_key_name: str = Field(
        default="rag-encryption",
        description="Transit encryption key name",
    )

    # Database engine
    database_mount_path: str = Field(
        default="database",
        description="Database secrets engine mount path",
    )

    # Connection settings
    timeout: int = Field(
        default=30,
        description="Request timeout in seconds",
    )
    verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates",
    )
    ca_cert_path: str | None = Field(
        default=None,
        description="Path to CA certificate",
    )


class KubernetesSecretsSettings(BaseModel):
    """
    Kubernetes Secrets configuration.

    Example:
        ```python
        settings = KubernetesSecretsSettings(
            namespace="rag-pipeline",
            secret_name="app-secrets",
        )
        ```
    """

    namespace: str | None = Field(
        default=None,
        description="Kubernetes namespace (None = use current)",
    )
    secret_name: str = Field(
        default="rag-pipeline-secrets",
        description="Name of the Kubernetes Secret",
    )
    kubeconfig_path: str | None = Field(
        default=None,
        description="Path to kubeconfig (None = in-cluster config)",
    )


class FileSecretsSettings(BaseModel):
    """
    File-based secrets configuration (for development).

    Example:
        ```python
        settings = FileSecretsSettings(
            secrets_dir="/secrets",
        )
        ```
    """

    secrets_dir: str = Field(
        default="/secrets",
        description="Directory containing secret files",
    )
    file_extension: str = Field(
        default="",
        description="File extension for secrets (empty = no extension)",
    )


class SecretsSettings(BaseModel):
    """
    Main secrets configuration.

    Defines which backend to use and backend-specific settings.

    Example:
        ```python
        # Development: use environment variables
        settings = SecretsSettings(
            backend=SecretsBackend.ENVIRONMENT,
            prefix="RAG_",
        )

        # Production: use Vault
        settings = SecretsSettings(
            backend=SecretsBackend.VAULT,
            vault=VaultSettings(
                url="https://vault.example.com",
                auth_method=VaultAuthMethod.KUBERNETES,
                kubernetes_role="rag-pipeline",
            ),
        )
        ```
    """

    backend: SecretsBackend = Field(
        default=SecretsBackend.ENVIRONMENT,
        description="Secrets backend to use",
    )

    # Backend-specific settings
    vault: VaultSettings = Field(
        default_factory=VaultSettings,
        description="Vault settings",
    )
    kubernetes: KubernetesSecretsSettings = Field(
        default_factory=KubernetesSecretsSettings,
        description="Kubernetes Secrets settings",
    )
    file: FileSecretsSettings = Field(
        default_factory=FileSecretsSettings,
        description="File-based secrets settings",
    )

    # Environment backend settings
    prefix: str = Field(
        default="",
        description="Prefix for environment variables",
    )

    # Caching
    cache_enabled: bool = Field(
        default=True,
        description="Enable secrets caching",
    )
    cache_ttl_seconds: int = Field(
        default=300,
        description="Cache TTL in seconds",
    )

    # Audit
    log_access: bool = Field(
        default=True,
        description="Log secret access (not values)",
    )


def create_secrets_settings_from_env() -> SecretsSettings:
    """
    Create secrets settings from environment variables.

    Environment variables:
        SECRETS_BACKEND: Backend type (environment, vault, kubernetes, file)
        VAULT_ADDR: Vault server URL
        VAULT_AUTH_METHOD: Vault auth method
        VAULT_ROLE: Kubernetes auth role
        SECRETS_PREFIX: Environment variable prefix
        SECRETS_CACHE_TTL: Cache TTL in seconds
    """
    import os

    backend = os.getenv("SECRETS_BACKEND", "environment")
    vault_url = os.getenv("VAULT_ADDR", "http://localhost:8200")
    vault_auth = os.getenv("VAULT_AUTH_METHOD", "token")
    vault_role = os.getenv("VAULT_ROLE")
    prefix = os.getenv("SECRETS_PREFIX", "")
    cache_ttl = int(os.getenv("SECRETS_CACHE_TTL", "300"))

    return SecretsSettings(
        backend=SecretsBackend(backend),
        vault=VaultSettings(
            url=vault_url,
            auth_method=VaultAuthMethod(vault_auth),
            kubernetes_role=vault_role,
        ),
        prefix=prefix,
        cache_ttl_seconds=cache_ttl,
    )
