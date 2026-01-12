"""
Secrets management module.

This module provides centralized secrets management with support
for multiple backends including HashiCorp Vault, Kubernetes Secrets,
environment variables, and file-based storage.

Features:
- Multiple backend support (Vault, Kubernetes, Environment, File)
- Automatic caching with configurable TTL
- FastAPI dependency injection
- Dynamic database credentials (via Vault)
- Transit encryption (via Vault)

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

    # Get database URL (constructs from components if needed)
    db_url = await service.get_database_url()

    # Production: use Vault
    from services.shared.security.secrets import VaultSettings, VaultAuthMethod

    settings = SecretsSettings(
        backend=SecretsBackend.VAULT,
        vault=VaultSettings(
            url="https://vault.example.com",
            auth_method=VaultAuthMethod.KUBERNETES,
            kubernetes_role="rag-pipeline",
        ),
    )

    # FastAPI integration
    from services.shared.security.secrets import (
        SecretsInjector,
        get_database_url,
        require_secret,
    )

    @app.get("/")
    async def handler(
        db_url: str = Depends(get_database_url),
        api_key: str = Depends(require_secret("EXTERNAL_API_KEY")),
    ):
        pass
    ```
"""

from .config import (
    FileSecretsSettings,
    KubernetesSecretsSettings,
    SecretsBackend,
    SecretsSettings,
    VaultAuthMethod,
    VaultSettings,
    create_secrets_settings_from_env,
)
from .vault import (
    VaultClient,
    VaultError,
    VaultAuthError,
    VaultSecretError,
)
from .k8s_secrets import (
    K8sSecretsClient,
    K8sSecretsError,
)
from .service import (
    SecretsService,
    SecretsError,
    get_secrets_service,
    get_secret,
)
from .injection import (
    SecretsInjector,
    get_secrets_injector,
    get_database_url,
    get_redis_url,
    get_jwt_secret,
    get_encryption_key,
    require_secret,
    optional_secret,
)

__all__ = [
    # Config
    "SecretsBackend",
    "SecretsSettings",
    "VaultSettings",
    "VaultAuthMethod",
    "KubernetesSecretsSettings",
    "FileSecretsSettings",
    "create_secrets_settings_from_env",
    # Vault
    "VaultClient",
    "VaultError",
    "VaultAuthError",
    "VaultSecretError",
    # Kubernetes
    "K8sSecretsClient",
    "K8sSecretsError",
    # Service
    "SecretsService",
    "SecretsError",
    "get_secrets_service",
    "get_secret",
    # Injection
    "SecretsInjector",
    "get_secrets_injector",
    "get_database_url",
    "get_redis_url",
    "get_jwt_secret",
    "get_encryption_key",
    "require_secret",
    "optional_secret",
]
