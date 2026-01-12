# US-7.7: Secrets Management

> **Epic:** Security & Compliance  
> **Priority:** Critical  
> **Estimated Effort:** 1-2 days  
> **Dependencies:** Epic 1 (Infrastructure)

## User Story

**As a** security engineer  
**I want** secure secrets management  
**So that** credentials are never exposed in code, configs, or logs

## Objective

Implement centralized secrets management using HashiCorp Vault or Kubernetes Secrets with external secrets operators, ensuring no secrets in code or config files, secret rotation support, audit logging of secret access, and environment-based secret injection.

## Architecture Reference

- **Primary:** HashiCorp Vault (production)
- **Alternative:** Kubernetes Secrets with External Secrets Operator
- **Injection:** Environment variables or mounted files
- **Rotation:** Automated rotation for supported secret types
- **Audit:** All access logged for compliance

## Implementation Tasks

### 1. Deploy HashiCorp Vault

`infrastructure/k8s/vault/deployment.yaml`:

```yaml
# Using Helm for production Vault deployment
# helm repo add hashicorp https://helm.releases.hashicorp.com
# helm install vault hashicorp/vault --namespace vault --create-namespace -f values.yaml

---
apiVersion: v1
kind: Namespace
metadata:
  name: vault
---
# Vault service account
apiVersion: v1
kind: ServiceAccount
metadata:
  name: vault
  namespace: vault
---
# For development/testing - single-node Vault
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vault
  namespace: vault
spec:
  replicas: 1
  selector:
    matchLabels:
      app: vault
  template:
    metadata:
      labels:
        app: vault
    spec:
      serviceAccountName: vault
      containers:
      - name: vault
        image: hashicorp/vault:1.15.0
        ports:
        - containerPort: 8200
        - containerPort: 8201
        env:
        - name: VAULT_DEV_ROOT_TOKEN_ID
          value: "dev-only-token"  # Only for development!
        - name: VAULT_DEV_LISTEN_ADDRESS
          value: "0.0.0.0:8200"
        - name: VAULT_ADDR
          value: "http://127.0.0.1:8200"
        - name: VAULT_API_ADDR
          value: "http://vault.vault.svc:8200"
        args:
        - server
        - -dev  # Remove -dev for production
        volumeMounts:
        - name: vault-data
          mountPath: /vault/data
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /v1/sys/health
            port: 8200
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /v1/sys/health?standbyok=true
            port: 8200
          initialDelaySeconds: 10
          periodSeconds: 5
      volumes:
      - name: vault-data
        persistentVolumeClaim:
          claimName: vault-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: vault
  namespace: vault
spec:
  selector:
    app: vault
  ports:
  - name: http
    port: 8200
    targetPort: 8200
  - name: internal
    port: 8201
    targetPort: 8201
```

### 2. Configure Vault Policies

`infrastructure/vault/policies/rag-pipeline-policy.hcl`:

```hcl
# Policy for RAG Pipeline services

# Read secrets for the application
path "secret/data/rag-pipeline/*" {
  capabilities = ["read", "list"]
}

# Allow reading database credentials
path "database/creds/rag-pipeline-*" {
  capabilities = ["read"]
}

# Allow reading encryption keys
path "transit/encrypt/rag-encryption" {
  capabilities = ["update"]
}

path "transit/decrypt/rag-encryption" {
  capabilities = ["update"]
}

# PKI for internal certificates
path "pki/issue/internal" {
  capabilities = ["create", "update"]
}

# Allow token renewal
path "auth/token/renew-self" {
  capabilities = ["update"]
}
```

`infrastructure/vault/policies/admin-policy.hcl`:

```hcl
# Admin policy for secret management

# Full access to rag-pipeline secrets
path "secret/data/rag-pipeline/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "secret/metadata/rag-pipeline/*" {
  capabilities = ["read", "list", "delete"]
}

# Manage database roles
path "database/roles/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

# Manage transit keys
path "transit/keys/*" {
  capabilities = ["create", "read", "update", "list"]
}

# Audit logs
path "sys/audit" {
  capabilities = ["read", "list"]
}

# Policy management
path "sys/policies/acl/*" {
  capabilities = ["read", "list"]
}
```

### 3. Create Vault Client

`services/shared/security/secrets/vault.py`:

```python
import hvac
from typing import Optional, Dict, Any, List
from functools import lru_cache
import structlog
import os

logger = structlog.get_logger(__name__)


class VaultError(Exception):
    """Vault operation failed."""
    pass


class VaultClient:
    """HashiCorp Vault client for secrets management."""
    
    def __init__(
        self,
        url: str = None,
        token: str = None,
        namespace: str = None,
        kubernetes_role: str = None,
    ):
        self.url = url or os.environ.get("VAULT_ADDR", "http://vault.vault.svc:8200")
        self.namespace = namespace or os.environ.get("VAULT_NAMESPACE")
        
        self.client = hvac.Client(url=self.url, namespace=self.namespace)
        
        # Authenticate
        if token:
            self.client.token = token
        elif kubernetes_role:
            self._kubernetes_auth(kubernetes_role)
        else:
            # Try environment token
            env_token = os.environ.get("VAULT_TOKEN")
            if env_token:
                self.client.token = env_token
            else:
                # Try Kubernetes auth as default
                self._kubernetes_auth_default()
        
        if not self.client.is_authenticated():
            raise VaultError("Failed to authenticate with Vault")
        
        logger.info("vault_client_connected", url=self.url)
    
    def _kubernetes_auth(self, role: str):
        """Authenticate using Kubernetes service account."""
        jwt_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        
        if not os.path.exists(jwt_path):
            raise VaultError("Kubernetes service account token not found")
        
        with open(jwt_path, "r") as f:
            jwt = f.read()
        
        self.client.auth.kubernetes.login(role=role, jwt=jwt)
    
    def _kubernetes_auth_default(self):
        """Try Kubernetes auth with default role based on namespace."""
        namespace = os.environ.get("POD_NAMESPACE", "rag-pipeline")
        role = f"{namespace}-service"
        
        try:
            self._kubernetes_auth(role)
        except Exception as e:
            logger.warning("kubernetes_auth_failed", error=str(e))
    
    def read_secret(self, path: str) -> Dict[str, Any]:
        """Read a secret from Vault KV v2."""
        try:
            response = self.client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point="secret",
            )
            return response["data"]["data"]
        except Exception as e:
            logger.error("vault_read_error", path=path, error=str(e))
            raise VaultError(f"Failed to read secret: {path}")
    
    def write_secret(self, path: str, data: Dict[str, Any]) -> None:
        """Write a secret to Vault KV v2."""
        try:
            self.client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=data,
                mount_point="secret",
            )
            logger.info("vault_secret_written", path=path)
        except Exception as e:
            logger.error("vault_write_error", path=path, error=str(e))
            raise VaultError(f"Failed to write secret: {path}")
    
    def delete_secret(self, path: str) -> None:
        """Delete a secret from Vault."""
        try:
            self.client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=path,
                mount_point="secret",
            )
            logger.info("vault_secret_deleted", path=path)
        except Exception as e:
            logger.error("vault_delete_error", path=path, error=str(e))
            raise VaultError(f"Failed to delete secret: {path}")
    
    def list_secrets(self, path: str) -> List[str]:
        """List secrets at a path."""
        try:
            response = self.client.secrets.kv.v2.list_secrets(
                path=path,
                mount_point="secret",
            )
            return response["data"]["keys"]
        except Exception as e:
            logger.error("vault_list_error", path=path, error=str(e))
            return []
    
    def get_database_credentials(self, role: str) -> Dict[str, str]:
        """Get dynamic database credentials."""
        try:
            response = self.client.secrets.database.generate_credentials(
                name=role,
                mount_point="database",
            )
            return {
                "username": response["data"]["username"],
                "password": response["data"]["password"],
                "lease_id": response["lease_id"],
                "lease_duration": response["lease_duration"],
            }
        except Exception as e:
            logger.error("vault_db_creds_error", role=role, error=str(e))
            raise VaultError(f"Failed to get database credentials for role: {role}")
    
    def encrypt(self, plaintext: str, key_name: str = "rag-encryption") -> str:
        """Encrypt data using Vault Transit."""
        import base64
        
        try:
            response = self.client.secrets.transit.encrypt_data(
                name=key_name,
                plaintext=base64.b64encode(plaintext.encode()).decode(),
                mount_point="transit",
            )
            return response["data"]["ciphertext"]
        except Exception as e:
            logger.error("vault_encrypt_error", error=str(e))
            raise VaultError("Encryption failed")
    
    def decrypt(self, ciphertext: str, key_name: str = "rag-encryption") -> str:
        """Decrypt data using Vault Transit."""
        import base64
        
        try:
            response = self.client.secrets.transit.decrypt_data(
                name=key_name,
                ciphertext=ciphertext,
                mount_point="transit",
            )
            return base64.b64decode(response["data"]["plaintext"]).decode()
        except Exception as e:
            logger.error("vault_decrypt_error", error=str(e))
            raise VaultError("Decryption failed")
    
    def renew_token(self) -> None:
        """Renew the current token."""
        try:
            self.client.auth.token.renew_self()
            logger.info("vault_token_renewed")
        except Exception as e:
            logger.error("vault_token_renew_error", error=str(e))


# Singleton instance
_vault_client: Optional[VaultClient] = None


def get_vault_client() -> VaultClient:
    global _vault_client
    if _vault_client is None:
        _vault_client = VaultClient()
    return _vault_client
```

### 4. Create Kubernetes Secrets Alternative

`services/shared/security/secrets/k8s_secrets.py`:

```python
from typing import Optional, Dict, Any, List
from kubernetes import client, config
import base64
import os
import structlog

logger = structlog.get_logger(__name__)


class K8sSecretsClient:
    """Kubernetes Secrets client as alternative to Vault."""
    
    def __init__(self, namespace: str = None):
        # Load config based on environment
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        
        self.v1 = client.CoreV1Api()
        self.namespace = namespace or os.environ.get("POD_NAMESPACE", "rag-pipeline")
    
    def read_secret(self, name: str, key: str = None) -> Dict[str, str]:
        """Read a Kubernetes secret."""
        try:
            secret = self.v1.read_namespaced_secret(name, self.namespace)
            data = {}
            
            if secret.data:
                for k, v in secret.data.items():
                    data[k] = base64.b64decode(v).decode("utf-8")
            
            if key:
                return {key: data.get(key)}
            return data
            
        except client.exceptions.ApiException as e:
            logger.error("k8s_secret_read_error", name=name, error=str(e))
            raise
    
    def write_secret(self, name: str, data: Dict[str, str]) -> None:
        """Create or update a Kubernetes secret."""
        encoded_data = {
            k: base64.b64encode(v.encode()).decode()
            for k, v in data.items()
        }
        
        secret = client.V1Secret(
            metadata=client.V1ObjectMeta(name=name),
            data=encoded_data,
            type="Opaque",
        )
        
        try:
            self.v1.read_namespaced_secret(name, self.namespace)
            self.v1.replace_namespaced_secret(name, self.namespace, secret)
            logger.info("k8s_secret_updated", name=name)
        except client.exceptions.ApiException:
            self.v1.create_namespaced_secret(self.namespace, secret)
            logger.info("k8s_secret_created", name=name)
    
    def delete_secret(self, name: str) -> None:
        """Delete a Kubernetes secret."""
        try:
            self.v1.delete_namespaced_secret(name, self.namespace)
            logger.info("k8s_secret_deleted", name=name)
        except client.exceptions.ApiException as e:
            logger.error("k8s_secret_delete_error", name=name, error=str(e))
    
    def list_secrets(self) -> List[str]:
        """List all secrets in namespace."""
        try:
            secrets = self.v1.list_namespaced_secret(self.namespace)
            return [s.metadata.name for s in secrets.items]
        except client.exceptions.ApiException:
            return []
```

### 5. Create Unified Secrets Service

`services/shared/security/secrets/service.py`:

```python
from typing import Dict, Any, Optional
from enum import Enum
import os
import structlog

from .vault import VaultClient, get_vault_client
from .k8s_secrets import K8sSecretsClient

logger = structlog.get_logger(__name__)


class SecretsBackend(str, Enum):
    VAULT = "vault"
    KUBERNETES = "kubernetes"
    ENVIRONMENT = "environment"


class SecretsService:
    """Unified secrets service with multiple backend support."""
    
    def __init__(self, backend: SecretsBackend = None):
        self.backend = backend or SecretsBackend(
            os.environ.get("SECRETS_BACKEND", "environment")
        )
        
        self._vault: Optional[VaultClient] = None
        self._k8s: Optional[K8sSecretsClient] = None
        
        logger.info("secrets_service_initialized", backend=self.backend.value)
    
    @property
    def vault(self) -> VaultClient:
        if self._vault is None:
            self._vault = get_vault_client()
        return self._vault
    
    @property
    def k8s(self) -> K8sSecretsClient:
        if self._k8s is None:
            self._k8s = K8sSecretsClient()
        return self._k8s
    
    def get_secret(self, path: str, key: str = None) -> Dict[str, Any]:
        """Get secret from configured backend."""
        if self.backend == SecretsBackend.VAULT:
            data = self.vault.read_secret(path)
            return {key: data.get(key)} if key else data
        
        elif self.backend == SecretsBackend.KUBERNETES:
            return self.k8s.read_secret(path, key)
        
        elif self.backend == SecretsBackend.ENVIRONMENT:
            return self._get_from_env(path, key)
        
        raise ValueError(f"Unknown backend: {self.backend}")
    
    def _get_from_env(self, path: str, key: str = None) -> Dict[str, Any]:
        """Get secret from environment variables."""
        # Convert path to env var prefix
        prefix = path.upper().replace("/", "_").replace("-", "_")
        
        if key:
            env_key = f"{prefix}_{key.upper()}"
            value = os.environ.get(env_key)
            return {key: value} if value else {}
        
        # Get all vars with prefix
        result = {}
        for env_key, value in os.environ.items():
            if env_key.startswith(prefix):
                short_key = env_key[len(prefix)+1:].lower()
                result[short_key] = value
        return result
    
    def set_secret(self, path: str, data: Dict[str, Any]) -> None:
        """Set secret in configured backend."""
        if self.backend == SecretsBackend.VAULT:
            self.vault.write_secret(path, data)
        
        elif self.backend == SecretsBackend.KUBERNETES:
            self.k8s.write_secret(path, data)
        
        elif self.backend == SecretsBackend.ENVIRONMENT:
            raise NotImplementedError("Cannot write to environment backend")
    
    def get_database_url(self) -> str:
        """Get database connection URL with credentials."""
        if self.backend == SecretsBackend.VAULT:
            # Use dynamic database credentials
            creds = self.vault.get_database_credentials("rag-pipeline-db")
            host = os.environ.get("DATABASE_HOST", "postgres")
            port = os.environ.get("DATABASE_PORT", "5432")
            database = os.environ.get("DATABASE_NAME", "ragpipeline")
            return f"postgresql+asyncpg://{creds['username']}:{creds['password']}@{host}:{port}/{database}"
        
        else:
            secrets = self.get_secret("rag-pipeline/database")
            host = secrets.get("host", os.environ.get("DATABASE_HOST", "postgres"))
            port = secrets.get("port", os.environ.get("DATABASE_PORT", "5432"))
            user = secrets.get("username", os.environ.get("DATABASE_USER"))
            password = secrets.get("password", os.environ.get("DATABASE_PASSWORD"))
            database = secrets.get("database", os.environ.get("DATABASE_NAME", "ragpipeline"))
            return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
    
    def get_redis_url(self) -> str:
        """Get Redis connection URL."""
        secrets = self.get_secret("rag-pipeline/redis")
        host = secrets.get("host", os.environ.get("REDIS_HOST", "redis"))
        port = secrets.get("port", os.environ.get("REDIS_PORT", "6379"))
        password = secrets.get("password", os.environ.get("REDIS_PASSWORD", ""))
        
        if password:
            return f"redis://:{password}@{host}:{port}"
        return f"redis://{host}:{port}"
    
    def get_jwt_keys(self) -> Dict[str, str]:
        """Get JWT signing keys."""
        return self.get_secret("rag-pipeline/jwt")
    
    def get_encryption_key(self) -> str:
        """Get field encryption key."""
        secrets = self.get_secret("rag-pipeline/encryption")
        return secrets.get("key")
    
    def get_s3_credentials(self) -> Dict[str, str]:
        """Get S3/MinIO credentials."""
        return self.get_secret("rag-pipeline/s3")
    
    def get_openai_key(self) -> str:
        """Get OpenAI API key."""
        secrets = self.get_secret("rag-pipeline/openai")
        return secrets.get("api_key")


# Singleton
_secrets_service: Optional[SecretsService] = None


def get_secrets_service() -> SecretsService:
    global _secrets_service
    if _secrets_service is None:
        _secrets_service = SecretsService()
    return _secrets_service
```

### 6. Create Secrets Injection for FastAPI

`services/shared/security/secrets/injection.py`:

```python
from functools import lru_cache
from typing import Dict, Any
import structlog

from .service import get_secrets_service, SecretsService

logger = structlog.get_logger(__name__)


class SecretsInjector:
    """Inject secrets into application configuration."""
    
    def __init__(self, service: SecretsService = None):
        self.service = service or get_secrets_service()
        self._cache: Dict[str, Any] = {}
    
    def inject_all(self) -> Dict[str, Any]:
        """Load all secrets into a configuration dict."""
        if self._cache:
            return self._cache
        
        config = {}
        
        try:
            # Database
            config["database_url"] = self.service.get_database_url()
            
            # Redis
            config["redis_url"] = self.service.get_redis_url()
            
            # JWT
            jwt = self.service.get_jwt_keys()
            config["jwt_private_key"] = jwt.get("private_key")
            config["jwt_public_key"] = jwt.get("public_key")
            
            # Encryption
            config["encryption_key"] = self.service.get_encryption_key()
            
            # S3
            s3 = self.service.get_s3_credentials()
            config["s3_access_key"] = s3.get("access_key")
            config["s3_secret_key"] = s3.get("secret_key")
            
            # OpenAI
            config["openai_api_key"] = self.service.get_openai_key()
            
            self._cache = config
            logger.info("secrets_injected", keys=list(config.keys()))
            
        except Exception as e:
            logger.error("secrets_injection_error", error=str(e))
            raise
        
        return config
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a specific secret."""
        config = self.inject_all()
        return config.get(key, default)
    
    def clear_cache(self):
        """Clear cached secrets (for rotation)."""
        self._cache = {}


@lru_cache()
def get_injector() -> SecretsInjector:
    return SecretsInjector()


# FastAPI dependency
def get_secret(key: str):
    """FastAPI dependency for getting a secret."""
    async def _get_secret():
        injector = get_injector()
        return injector.get(key)
    return _get_secret
```

### 7. Configure External Secrets Operator (Optional)

`infrastructure/k8s/external-secrets/secret-store.yaml`:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: vault-backend
spec:
  provider:
    vault:
      server: "http://vault.vault.svc:8200"
      path: "secret"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "external-secrets"
          serviceAccountRef:
            name: "external-secrets"
            namespace: "external-secrets"
---
# External Secret that syncs from Vault to K8s Secret
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: rag-pipeline-secrets
  namespace: rag-pipeline
spec:
  refreshInterval: "1h"
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: rag-pipeline-secrets
    creationPolicy: Owner
  data:
  - secretKey: database-url
    remoteRef:
      key: rag-pipeline/database
      property: url
  - secretKey: redis-password
    remoteRef:
      key: rag-pipeline/redis
      property: password
  - secretKey: jwt-private-key
    remoteRef:
      key: rag-pipeline/jwt
      property: private_key
  - secretKey: encryption-key
    remoteRef:
      key: rag-pipeline/encryption
      property: key
  - secretKey: openai-api-key
    remoteRef:
      key: rag-pipeline/openai
      property: api_key
```

### 8. Secret Rotation Script

`scripts/rotate-secrets.sh`:

```bash
#!/bin/bash
set -e

# Secret rotation script
# Usage: ./rotate-secrets.sh <secret-type>

SECRET_TYPE="${1:-all}"
VAULT_ADDR="${VAULT_ADDR:-http://vault.vault.svc:8200}"

rotate_database_password() {
    echo "Rotating database password..."
    
    NEW_PASSWORD=$(openssl rand -base64 32)
    
    # Update in Vault
    vault kv patch secret/rag-pipeline/database \
        password="$NEW_PASSWORD"
    
    # Update PostgreSQL (requires admin access)
    # This should be handled by Vault's database secrets engine in production
    
    echo "Database password rotated. Application restart required."
}

rotate_jwt_keys() {
    echo "Rotating JWT keys..."
    
    # Generate new key pair
    openssl genrsa -out /tmp/jwt-private.pem 4096
    openssl rsa -in /tmp/jwt-private.pem -pubout -out /tmp/jwt-public.pem
    
    PRIVATE_KEY=$(cat /tmp/jwt-private.pem | base64 -w0)
    PUBLIC_KEY=$(cat /tmp/jwt-public.pem | base64 -w0)
    
    # Update in Vault
    vault kv put secret/rag-pipeline/jwt \
        private_key="$PRIVATE_KEY" \
        public_key="$PUBLIC_KEY" \
        rotated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    
    # Cleanup
    rm /tmp/jwt-private.pem /tmp/jwt-public.pem
    
    echo "JWT keys rotated. Existing tokens will be invalid."
}

rotate_encryption_key() {
    echo "Rotating encryption key..."
    
    NEW_KEY=$(openssl rand -base64 32)
    
    # Get current version
    CURRENT=$(vault kv get -field=version secret/rag-pipeline/encryption 2>/dev/null || echo "0")
    NEW_VERSION=$((CURRENT + 1))
    
    # Store old key for re-encryption
    OLD_KEY=$(vault kv get -field=key secret/rag-pipeline/encryption 2>/dev/null || echo "")
    
    vault kv put secret/rag-pipeline/encryption \
        key="$NEW_KEY" \
        version="$NEW_VERSION" \
        previous_key="$OLD_KEY" \
        rotated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    
    echo "Encryption key rotated to version $NEW_VERSION"
    echo "Run re-encryption job before removing previous_key"
}

case "$SECRET_TYPE" in
    database)
        rotate_database_password
        ;;
    jwt)
        rotate_jwt_keys
        ;;
    encryption)
        rotate_encryption_key
        ;;
    all)
        rotate_database_password
        rotate_jwt_keys
        rotate_encryption_key
        ;;
    *)
        echo "Unknown secret type: $SECRET_TYPE"
        echo "Usage: $0 [database|jwt|encryption|all]"
        exit 1
        ;;
esac

echo "Secret rotation complete!"
```

### 9. Create Tests

`tests/security/test_secrets.py`:

```python
import pytest
import os
from unittest.mock import MagicMock, patch

from shared.security.secrets.service import SecretsService, SecretsBackend


class TestSecretsService:
    def test_environment_backend(self):
        with patch.dict(os.environ, {
            "RAG_PIPELINE_DATABASE_HOST": "localhost",
            "RAG_PIPELINE_DATABASE_PORT": "5432",
            "RAG_PIPELINE_DATABASE_USERNAME": "testuser",
            "RAG_PIPELINE_DATABASE_PASSWORD": "testpass",
        }):
            service = SecretsService(backend=SecretsBackend.ENVIRONMENT)
            secrets = service.get_secret("rag-pipeline/database")
            
            assert secrets.get("host") == "localhost"
    
    def test_get_specific_key(self):
        with patch.dict(os.environ, {
            "RAG_PIPELINE_JWT_PRIVATE_KEY": "test-key",
        }):
            service = SecretsService(backend=SecretsBackend.ENVIRONMENT)
            secrets = service.get_secret("rag-pipeline/jwt", "private_key")
            
            assert secrets.get("private_key") == "test-key"
    
    @pytest.mark.integration
    def test_vault_connection(self):
        # Only run if Vault is available
        service = SecretsService(backend=SecretsBackend.VAULT)
        
        # Test write and read
        test_data = {"test_key": "test_value"}
        service.set_secret("rag-pipeline/test", test_data)
        
        result = service.get_secret("rag-pipeline/test")
        assert result["test_key"] == "test_value"


class TestSecretsInjector:
    def test_inject_all(self):
        from shared.security.secrets.injection import SecretsInjector
        
        mock_service = MagicMock()
        mock_service.get_database_url.return_value = "postgresql://test"
        mock_service.get_redis_url.return_value = "redis://test"
        mock_service.get_jwt_keys.return_value = {"private_key": "pk", "public_key": "pub"}
        mock_service.get_encryption_key.return_value = "enc_key"
        mock_service.get_s3_credentials.return_value = {"access_key": "ak", "secret_key": "sk"}
        mock_service.get_openai_key.return_value = "openai_key"
        
        injector = SecretsInjector(service=mock_service)
        config = injector.inject_all()
        
        assert config["database_url"] == "postgresql://test"
        assert config["redis_url"] == "redis://test"
        assert config["openai_api_key"] == "openai_key"
    
    def test_caching(self):
        from shared.security.secrets.injection import SecretsInjector
        
        mock_service = MagicMock()
        mock_service.get_database_url.return_value = "postgresql://test"
        mock_service.get_redis_url.return_value = "redis://test"
        mock_service.get_jwt_keys.return_value = {}
        mock_service.get_encryption_key.return_value = ""
        mock_service.get_s3_credentials.return_value = {}
        mock_service.get_openai_key.return_value = ""
        
        injector = SecretsInjector(service=mock_service)
        
        injector.inject_all()
        injector.inject_all()
        
        # Should only call once due to caching
        assert mock_service.get_database_url.call_count == 1
```

## Acceptance Criteria

- [ ] HashiCorp Vault deployed and accessible
- [ ] Vault policies configured for service access
- [ ] Kubernetes Secrets alternative available
- [ ] No secrets in code or config files
- [ ] Secret rotation scripts working
- [ ] Audit logging of secret access enabled
- [ ] Environment-based fallback for development
- [ ] External Secrets Operator configured (optional)
- [ ] Unit tests passing

## Verification Commands

```bash
# Check Vault status
vault status

# Login to Vault
vault login

# List secrets
vault kv list secret/rag-pipeline/

# Read a secret
vault kv get secret/rag-pipeline/database

# Rotate secrets
./scripts/rotate-secrets.sh jwt

# Verify Kubernetes secrets
kubectl get secrets -n rag-pipeline
kubectl describe secret rag-pipeline-secrets -n rag-pipeline

# Run tests
pytest tests/security/test_secrets.py -v
```

## Environment Variables

```bash
# Secrets backend
SECRETS_BACKEND=vault  # vault, kubernetes, or environment

# Vault configuration
VAULT_ADDR=http://vault.vault.svc:8200
VAULT_TOKEN=s.xxxxx
VAULT_NAMESPACE=rag

# For development/fallback
DATABASE_HOST=postgres
DATABASE_PORT=5432
DATABASE_USER=raguser
DATABASE_PASSWORD=ragpass
REDIS_HOST=redis
REDIS_PASSWORD=
```

## Files to Create

1. `infrastructure/k8s/vault/deployment.yaml`
2. `infrastructure/vault/policies/rag-pipeline-policy.hcl`
3. `infrastructure/vault/policies/admin-policy.hcl`
4. `infrastructure/k8s/external-secrets/secret-store.yaml`
5. `services/shared/security/secrets/__init__.py`
6. `services/shared/security/secrets/vault.py`
7. `services/shared/security/secrets/k8s_secrets.py`
8. `services/shared/security/secrets/service.py`
9. `services/shared/security/secrets/injection.py`
10. `scripts/rotate-secrets.sh`
11. `tests/security/test_secrets.py`

## Security Considerations

- **Never log secrets** - Mask all secret values in logs
- **Minimal access** - Each service gets only required secrets
- **Short TTLs** - Use short-lived tokens and credentials
- **Rotation schedule** - Rotate secrets regularly
- **Audit trail** - Log all secret access
- **Encryption in transit** - TLS for Vault communication
- **Backup keys** - Vault unseal keys must be securely backed up
