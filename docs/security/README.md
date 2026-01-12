# Security & Compliance Documentation

> **Version:** 1.0
> **Status:** Production Implementation
> **Last Updated:** January 2026

This document provides comprehensive documentation for the security and compliance implementation in the RAG Pipeline.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Authentication (JWT)](#authentication-jwt)
4. [Authorization (RBAC)](#authorization-rbac)
5. [Document Access Control (ACL)](#document-access-control-acl)
6. [Encryption](#encryption)
7. [PII Detection](#pii-detection)
8. [Secrets Management](#secrets-management)
9. [Audit Logging](#audit-logging)
10. [TLS/mTLS Configuration](#tlsmtls-configuration)
11. [Security Scanning](#security-scanning)
12. [Quick Start](#quick-start)
13. [Compliance](#compliance)

---

## Overview

The RAG Pipeline implements defense-in-depth security with multiple layers:

| Layer | Components | Purpose |
|-------|------------|---------|
| **Authentication** | JWT tokens, RS256 signing, token blocklist | Verify user identity |
| **Authorization** | RBAC, permissions, tenant isolation | Control access to resources |
| **Document ACL** | Visibility levels, group access, owner permissions | Fine-grained document access |
| **Data Protection** | AES-256-GCM encryption, TLS 1.3, field encryption | Protect data at rest and in transit |
| **Privacy** | PII detection, response filtering, custom recognizers | Handle sensitive data |
| **Secrets** | Vault/K8s Secrets, key rotation, injection | Secure credential management |
| **Audit** | Structured logging, tamper-evident storage, Loki integration | Track security events |
| **Scanning** | SAST, dependency scanning, container scanning, secrets detection | Identify vulnerabilities |

---

## Architecture

```mermaid
flowchart TB
    subgraph Client["Client Layer"]
        UI[Web UI]
        API_CLIENT[API Client]
    end

    subgraph Gateway["API Gateway"]
        AUTH_MW[Auth Middleware]
        RBAC_MW[RBAC Middleware]
        AUDIT_MW[Audit Middleware]
        RATE_LIMIT[Rate Limiter]
    end

    subgraph Services["Application Services"]
        ING[Ingestion Service]
        RET[Retrieval Service]
        ORC[Orchestrator Service]
        LLM[LLM Gateway]
    end

    subgraph Security["Security Services"]
        JWT[JWT Handler]
        RBAC[RBAC Service]
        ACL[ACL Service]
        PII[PII Detector]
        ENCRYPT[Encryption Service]
        AUDIT[Audit Logger]
    end

    subgraph Storage["Secure Storage"]
        VAULT[(Vault/K8s Secrets)]
        PG[(PostgreSQL<br/>TDE Enabled)]
        AUDIT_DB[(Audit Log<br/>Hash Chained)]
    end

    Client --> Gateway
    Gateway --> Services
    Services --> Security
    Security --> Storage

    AUTH_MW --> JWT
    RBAC_MW --> RBAC
    RBAC_MW --> ACL
    AUDIT_MW --> AUDIT
    Services --> PII
    Services --> ENCRYPT
```

### Security Components Location

| Component | Location | Description |
|-----------|----------|-------------|
| JWT Handler | [services/shared/security/jwt/](../../services/shared/security/jwt/) | Token generation, validation, blocklist |
| RBAC Service | [services/shared/security/rbac/](../../services/shared/security/rbac/) | Roles, permissions, tenant isolation |
| ACL Service | [services/shared/security/acl/](../../services/shared/security/acl/) | Document-level access control |
| Encryption | [services/shared/security/encryption/](../../services/shared/security/encryption/) | Field encryption, key management |
| PII Detection | [services/shared/security/pii/](../../services/shared/security/pii/) | Presidio-based PII detection |
| Secrets Manager | [services/shared/security/secrets/](../../services/shared/security/secrets/) | Multi-backend secrets service |
| Audit Logger | [services/shared/security/audit/](../../services/shared/security/audit/) | Security event logging |
| TLS Config | [services/shared/security/tls/](../../services/shared/security/tls/) | SSL context configuration |
| API Auth | [services/shared/security/api/](../../services/shared/security/api/) | FastAPI authentication dependencies |

---

## Authentication (JWT)

### Overview

The system uses JWT (JSON Web Tokens) with RS256 (RSA-SHA256) asymmetric signing for stateless authentication. Tokens include tenant context, roles, groups, and permissions.

### Token Structure

```json
{
  "sub": "user-uuid",
  "iss": "https://auth.example.com",
  "aud": "rag-pipeline",
  "exp": 1735000000,
  "iat": 1734996400,
  "jti": "unique-token-id",
  "tenant_id": "tenant-uuid",
  "roles": ["tenant_user", "data_engineer"],
  "groups": ["engineering", "ml-team"],
  "permissions": ["documents:read", "query:execute"]
}
```

### Components

| File | Purpose |
|------|---------|
| [jwt/config.py](../../services/shared/security/jwt/config.py) | JWT configuration settings |
| [jwt/models.py](../../services/shared/security/jwt/models.py) | Token claims and validation models |
| [jwt/handler.py](../../services/shared/security/jwt/handler.py) | Token creation, validation, decoding |
| [jwt/middleware.py](../../services/shared/security/jwt/middleware.py) | FastAPI authentication middleware |
| [jwt/blocklist.py](../../services/shared/security/jwt/blocklist.py) | Redis-backed token revocation |

### Configuration

```python
from shared.security.jwt import JWTConfig

config = JWTConfig(
    algorithm="RS256",
    issuer="https://auth.example.com",
    audience="rag-pipeline",
    access_token_expire_minutes=30,
    refresh_token_expire_days=7,
    private_key_path="/secrets/jwt-private.pem",
    public_key_path="/secrets/jwt-public.pem",
)
```

### Usage

```python
from fastapi import Depends
from shared.security.jwt import get_current_user, TokenClaims

@router.get("/protected")
async def protected_endpoint(
    user: TokenClaims = Depends(get_current_user)
):
    return {"user_id": user.user_id, "tenant_id": str(user.tenant_id)}
```

### Token Blocklist

Revoked tokens are tracked in Redis with TTL matching token expiration:

```python
from shared.security.jwt import TokenBlocklist

blocklist = TokenBlocklist(redis_client)
await blocklist.revoke_token(token_jti, reason="logout")
await blocklist.is_blocked(token_jti)  # Returns True
```

### JWKS Support

The system supports JWKS (JSON Web Key Set) for public key distribution:

```python
# Fetch public keys from JWKS endpoint
jwks_url = "https://auth.example.com/.well-known/jwks.json"
```

---

## Authorization (RBAC)

### Overview

Role-Based Access Control (RBAC) provides hierarchical permissions through predefined roles, with mandatory tenant isolation for all operations.

### Role Hierarchy

```mermaid
graph TD
    SA[Super Admin] --> TA[Tenant Admin]
    TA --> TU[Tenant User]
    TA --> DE[Data Engineer]
    TA --> AN[Analyst]
    TA --> DEV[Developer]
    TA --> CO[Compliance Officer]
    TU --> TV[Tenant Viewer]

    style SA fill:#ff6b6b
    style TA fill:#4ecdc4
```

### Predefined Roles

| Role | Description | Key Permissions |
|------|-------------|-----------------|
| `super_admin` | Full system access | All permissions |
| `tenant_admin` | Full tenant access | User management, all tenant operations |
| `tenant_user` | Standard user | Read/write documents, query, view collections |
| `tenant_viewer` | Read-only access | Read documents, execute queries |
| `data_engineer` | Data management | Full ingestion control, collection management |
| `analyst` | Query focus | Execute queries, read audit logs |
| `developer` | API integration | API key management, basic operations |
| `compliance_officer` | Audit access | Read and export audit logs |
| `service_account` | Inter-service | System health, metrics, basic operations |

### Permission Categories

```python
class Permission(str, Enum):
    # Document permissions
    DOCUMENTS_READ = "documents:read"
    DOCUMENTS_CREATE = "documents:create"
    DOCUMENTS_UPDATE = "documents:update"
    DOCUMENTS_DELETE = "documents:delete"
    DOCUMENTS_ADMIN = "documents:admin"

    # Query permissions
    QUERY_EXECUTE = "query:execute"
    QUERY_HISTORY_READ = "query:history:read"
    QUERY_HISTORY_DELETE = "query:history:delete"

    # Ingestion permissions
    INGESTION_TRIGGER = "ingestion:trigger"
    INGESTION_STATUS = "ingestion:status"
    INGESTION_CANCEL = "ingestion:cancel"
    INGESTION_ADMIN = "ingestion:admin"

    # Collection permissions
    COLLECTIONS_READ = "collections:read"
    COLLECTIONS_CREATE = "collections:create"
    COLLECTIONS_UPDATE = "collections:update"
    COLLECTIONS_DELETE = "collections:delete"

    # User management
    USERS_READ = "users:read"
    USERS_CREATE = "users:create"
    USERS_UPDATE = "users:update"
    USERS_DELETE = "users:delete"
    USERS_ADMIN = "users:admin"

    # Tenant management
    TENANT_READ = "tenant:read"
    TENANT_UPDATE = "tenant:update"
    TENANT_ADMIN = "tenant:admin"

    # API key management
    API_KEYS_READ = "api_keys:read"
    API_KEYS_CREATE = "api_keys:create"
    API_KEYS_REVOKE = "api_keys:revoke"

    # Audit permissions
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"

    # System permissions
    SYSTEM_HEALTH = "system:health"
    SYSTEM_METRICS = "system:metrics"
    SYSTEM_CONFIG = "system:config"
    SYSTEM_ADMIN = "system:admin"
```

### Usage

```python
from fastapi import Depends
from shared.security.rbac import require_permission, require_role, Permission, Role

# Require specific permission
@router.get("/documents")
async def list_documents(
    user: TokenClaims = Depends(require_permission(Permission.DOCUMENTS_READ))
):
    pass

# Require specific role
@router.delete("/documents/{id}")
async def delete_document(
    user: TokenClaims = Depends(require_role(Role.TENANT_ADMIN.value))
):
    pass

# Multiple permissions (any)
@router.post("/documents")
async def create_document(
    user: TokenClaims = Depends(require_permission(
        Permission.DOCUMENTS_CREATE,
        Permission.DOCUMENTS_ADMIN,
    ))
):
    pass

# All permissions required
@router.post("/admin/operation")
async def admin_operation(
    user: TokenClaims = Depends(require_permission(
        Permission.SYSTEM_ADMIN,
        Permission.TENANT_ADMIN,
        require_all=True,
    ))
):
    pass
```

### Permission Checker Class

```python
from shared.security.rbac import PermissionChecker

# Reusable permission checker with role bypass
document_admin_checker = PermissionChecker(
    Permission.DOCUMENTS_ADMIN,
    allow_roles=[Role.SUPER_ADMIN.value, Role.TENANT_ADMIN.value],
)

@router.post("/{document_id}/reindex")
async def reindex_document(
    document_id: UUID,
    user: TokenClaims = Depends(document_admin_checker),
):
    pass
```

### Tenant Isolation

All operations enforce tenant boundaries:

```python
from shared.security.rbac import get_authorization_service

authz = get_authorization_service()

# Check tenant access
if not authz.can_access_tenant(user, resource_tenant_id):
    raise ForbiddenError("Tenant isolation violation")

# Get tenant filter for queries
filter_dict = authz.filter_for_tenant(user)
# Returns: {"tenant_id": user.tenant_id}

# Check permission with tenant validation
authz.check_permission(
    user,
    Permission.DOCUMENTS_READ,
    resource_tenant_id=document.tenant_id,
)
```

### Tenant Context Manager

```python
from shared.security.rbac import set_tenant_context, get_current_tenant_id

# Set context from authenticated user
set_tenant_context(user)

# Get current tenant in any function
tenant_id = get_current_tenant_id()
```

---

## Document Access Control (ACL)

### Overview

Fine-grained access control for documents with visibility levels, owner permissions, and group-based access. ACLs are inherited by document chunks for consistent search filtering.

### Visibility Levels

| Level | Description | Access |
|-------|-------------|--------|
| `public` | Visible to all tenant users | All authenticated users in tenant |
| `private` | Owner only | Document owner only |
| `group` | Group-based | Specified groups only |
| `restricted` | Explicit access | Specified users, groups, or roles |

### ACL Model

```python
from shared.security.acl import DocumentACL, Visibility

acl = DocumentACL(
    document_id=uuid,
    tenant_id=tenant_uuid,
    owner_id="user-123",
    visibility=Visibility.GROUP,
    allowed_users=["user-456"],
    allowed_groups=["engineering", "ml-team"],
    allowed_roles=["data_engineer"],
    denied_users=["user-789"],  # Explicit denials take precedence
    denied_groups=["contractors"],
    inherit_to_chunks=True,  # Chunks inherit document ACL
)

# Check access
can_access = acl.can_access(
    user_id="user-456",
    user_groups=["engineering"],
    user_roles=["tenant_user"],
)
```

### Access Rules

1. **Super admin** bypasses all ACL checks
2. **Owner** always has access to their documents
3. **Denied lists** take precedence over allowed lists
4. **Visibility** determines base access level
5. **Allowed lists** grant additional access for group/restricted visibility

### Search Integration

ACL filters are applied at query time in both Qdrant and OpenSearch:

```python
from shared.security.acl import QdrantACLFilter, OpenSearchACLFilter

# Build Qdrant filter
qdrant_filter = QdrantACLFilter.build_access_filter(
    user=user,
    tenant_id=tenant_id,
    additional_filters={"source_type": "pdf"},
)

# Build OpenSearch filter
opensearch_filter = OpenSearchACLFilter.build_access_filter(
    user=user,
    tenant_id=tenant_id,
    base_query={"match": {"content": "search term"}},
)
```

### ACL Management API

```bash
# Get document ACL
GET /documents/{document_id}/acl

# Update ACL
PUT /documents/{document_id}/acl
Content-Type: application/json
{
    "visibility": "group",
    "allowed_groups": ["engineering"],
    "add_users": ["user-456"],
    "remove_users": ["user-789"]
}

# Share document
POST /documents/{document_id}/acl/share
Content-Type: application/json
{
    "users": ["user-456"],
    "groups": ["marketing"]
}

# Make public/private
POST /documents/{document_id}/acl/make-public
POST /documents/{document_id}/acl/make-private

# Bulk ACL update
POST /documents/acl/bulk
Content-Type: application/json
{
    "document_ids": ["uuid-1", "uuid-2"],
    "visibility": "group",
    "add_groups": ["engineering"]
}
```

### Chunk ACL Inheritance

When documents are chunked, ACL metadata is automatically propagated:

```python
from shared.security.acl import build_chunk_acl_payload

# Build payload for vector store
chunk_payload = build_chunk_acl_payload(document_acl.dict())
# Includes: tenant_id, visibility, owner_id, allowed_users, allowed_groups, allowed_roles
```

---

## Encryption

### Overview

The system implements encryption at multiple levels:

1. **Volume-Level Encryption** - Encrypted storage classes for all persistent volumes
2. **Field-Level Encryption** - AES-256-GCM for sensitive database fields
3. **Transit Encryption** - TLS 1.3 for all network communication
4. **Vault Transit** - Optional encryption-as-a-service via Vault

### Field Encryption

```python
from shared.security.encryption import FieldEncryption

# Initialize with 32-byte key
encryptor = FieldEncryption(key)

# Or from base64-encoded key
encryptor = FieldEncryption.from_base64_key(encryption_key_b64)

# Or derive from password
encryptor = FieldEncryption.from_password("secure-password", salt)

# Encrypt/decrypt strings
encrypted = encryptor.encrypt("sensitive data")
decrypted = encryptor.decrypt(encrypted)

# Encrypt specific dict fields
data = {"email": "user@example.com", "ssn": "123-45-6789", "name": "John"}
encrypted_data = encryptor.encrypt_dict(data, ["email", "ssn"])
# Result: {"email": "encrypted...", "ssn": "encrypted...", "name": "John"}

decrypted_data = encryptor.decrypt_dict(encrypted_data, ["email", "ssn"])
```

### SQLAlchemy Encrypted Types

```python
from shared.database.types import EncryptedString, EncryptedJSON

class User(Base):
    __tablename__ = "users"

    id = Column(UUID, primary_key=True)
    email = Column(EncryptedString(255))  # Automatically encrypted
    ssn = Column(EncryptedString(20))
    sensitive_metadata = Column(EncryptedJSON())
```

### Key Management

```python
from shared.security.encryption import EncryptionKeyManager

# Initialize with Vault client (or None for env-based keys)
key_manager = EncryptionKeyManager(vault_client=vault, key_id="rag-encryption-key")

# Get current key
key, version = await key_manager.get_current_key()

# Rotate keys (stores previous for re-encryption)
new_key, new_version = await key_manager.rotate_key()
```

### Storage Encryption

All persistent volumes use encrypted storage classes:

```yaml
# Encrypted storage class (AWS EKS example)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: encrypted-gp3
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  encrypted: "true"
  kmsKeyId: "alias/rag-pipeline-encryption"
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
```

### S3/MinIO Server-Side Encryption

```python
from shared.storage import EncryptedS3Client

s3 = EncryptedS3Client(
    endpoint_url="http://minio:9000",
    access_key="...",
    secret_key="...",
    bucket="documents",
    sse_algorithm="AES256",  # or "aws:kms"
    kms_key_id="alias/rag-encryption",  # For KMS
)

# Uploads are automatically encrypted
await s3.upload_file("doc.pdf", file_data)

# Enable default bucket encryption
await s3.set_bucket_encryption()
```

### Key Rotation

```bash
# Generate new key and store in Vault
./scripts/rotate-encryption-keys.sh rag-encryption-key

# Run re-encryption job for existing data
python -m shared.security.encryption.reencrypt --old-version 1 --new-version 2
```

---

## PII Detection

### Overview

Microsoft Presidio-based PII detection with custom recognizers for domain-specific patterns. Used during ingestion and response filtering.

### Supported PII Types

| Entity Type | Description | Example |
|-------------|-------------|---------|
| `PERSON` | Person names | "John Smith" |
| `EMAIL_ADDRESS` | Email addresses | "user@example.com" |
| `PHONE_NUMBER` | Phone numbers | "+1-555-123-4567" |
| `CREDIT_CARD` | Credit card numbers | "4111-1111-1111-1111" |
| `US_SSN` | Social Security Numbers | "123-45-6789" |
| `IP_ADDRESS` | IP addresses | "192.168.1.1" |
| `US_BANK_NUMBER` | Bank account numbers | - |
| `CRYPTO` | Cryptocurrency addresses | - |
| `IBAN_CODE` | International bank numbers | - |
| Custom | API keys, internal IDs | Configurable |

### Configuration

```python
from shared.security.pii import PIIConfig

config = PIIConfig(
    enabled=True,
    language="en",
    score_threshold=0.7,
    entities=["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN"],
    custom_recognizers_path="config/custom_recognizers.yaml",
    redact_char="*",
    anonymize_fake_data=True,
)
```

### Custom Recognizers

```yaml
# pii/custom_recognizers.yaml
recognizers:
  - name: "APIKeyRecognizer"
    supported_entity: "API_KEY"
    patterns:
      - name: "openai_key"
        regex: "sk-[a-zA-Z0-9]{48}"
        score: 0.95
      - name: "generic_api_key"
        regex: "[a-zA-Z0-9]{32,64}"
        score: 0.6
    context:
      - "api"
      - "key"
      - "secret"
      - "token"

  - name: "InternalIDRecognizer"
    supported_entity: "INTERNAL_ID"
    patterns:
      - name: "employee_id"
        regex: "EMP-[0-9]{6}"
        score: 0.9
```

### Usage

```python
from shared.security.pii import PIIDetector

detector = PIIDetector(config)

# Detect PII entities
results = detector.detect("Contact John at john@example.com or 555-123-4567")
# Returns: [
#     PIIEntity(type="PERSON", text="John", start=8, end=12, score=0.85),
#     PIIEntity(type="EMAIL_ADDRESS", text="john@example.com", ...),
#     PIIEntity(type="PHONE_NUMBER", text="555-123-4567", ...),
# ]

# Redact PII (replace with entity type)
redacted = detector.redact("Contact John at john@example.com")
# Returns: "Contact <PERSON> at <EMAIL_ADDRESS>"

# Mask PII (replace with asterisks)
masked = detector.mask("SSN: 123-45-6789")
# Returns: "SSN: ***-**-****"

# Anonymize with fake data
anonymized = detector.anonymize("Contact John at john@example.com")
# Returns: "Contact Jane Doe at jane.doe@fake.example.com"
```

### Response Filtering

```python
from shared.security.pii import PIIResponseFilter

filter = PIIResponseFilter(config)

# Filter LLM responses before returning to user
async def generate_response(query: str) -> str:
    llm_output = await llm.generate(query)
    filtered_output = await filter.filter_response(llm_output)
    return filtered_output
```

### Ingestion Integration

```python
from shared.security.pii import PIIDetector

# During document processing
detector = PIIDetector(config)

for chunk in document.chunks:
    pii_entities = detector.detect(chunk.content)

    if pii_entities:
        # Option 1: Redact before indexing
        chunk.content = detector.redact(chunk.content)

        # Option 2: Flag for review
        chunk.metadata["contains_pii"] = True
        chunk.metadata["pii_types"] = [e.type for e in pii_entities]
```

---

## Secrets Management

### Overview

Multi-backend secrets management supporting HashiCorp Vault (production), Kubernetes Secrets, and environment variables (development).

### Backends

| Backend | Use Case | Features |
|---------|----------|----------|
| `vault` | Production | Dynamic credentials, encryption-as-service, audit logging |
| `kubernetes` | Staging | Native K8s integration, External Secrets Operator |
| `environment` | Development | Simple local development |

### Configuration

```python
from shared.security.secrets import SecretsService, SecretsBackend

# Auto-detect backend from SECRETS_BACKEND env var
service = SecretsService()

# Explicit backend
service = SecretsService(backend=SecretsBackend.VAULT)
```

### Environment Variables

```bash
# Select backend
SECRETS_BACKEND=vault  # vault, kubernetes, or environment

# Vault configuration
VAULT_ADDR=http://vault.vault.svc:8200
VAULT_TOKEN=s.xxxxx  # Or use Kubernetes auth
VAULT_NAMESPACE=rag

# Development fallback
DATABASE_HOST=postgres
DATABASE_PORT=5432
DATABASE_USER=raguser
DATABASE_PASSWORD=ragpass
```

### Usage

```python
from shared.security.secrets import get_secrets_service

secrets = get_secrets_service()

# Generic secret access
db_secrets = secrets.get_secret("rag-pipeline/database")
# Returns: {"host": "...", "port": "...", "username": "...", "password": "..."}

# Specific key
password = secrets.get_secret("rag-pipeline/database", "password")

# Convenience methods
database_url = secrets.get_database_url()
redis_url = secrets.get_redis_url()
jwt_keys = secrets.get_jwt_keys()
encryption_key = secrets.get_encryption_key()
s3_creds = secrets.get_s3_credentials()
openai_key = secrets.get_openai_key()
```

### Vault Client

```python
from shared.security.secrets import VaultClient

vault = VaultClient(
    url="http://vault:8200",
    kubernetes_role="rag-pipeline-service",  # Uses K8s service account auth
)

# Read/write secrets
secret = vault.read_secret("rag-pipeline/database")
vault.write_secret("rag-pipeline/new-secret", {"key": "value"})

# Get dynamic database credentials
creds = vault.get_database_credentials("rag-pipeline-db")
# Returns: {"username": "v-k8s-...", "password": "...", "lease_id": "...", "lease_duration": 3600}

# Use Vault Transit for encryption
ciphertext = vault.encrypt("plaintext", key_name="rag-encryption")
plaintext = vault.decrypt(ciphertext, key_name="rag-encryption")
```

### FastAPI Integration

```python
from shared.security.secrets import SecretsInjector, get_secret

# Inject all secrets at startup
@app.on_event("startup")
async def startup():
    injector = SecretsInjector()
    config = injector.inject_all()
    app.state.config = config

# Dependency injection for specific secrets
@router.get("/llm/generate")
async def generate(
    api_key: str = Depends(get_secret("openai_api_key"))
):
    pass
```

### External Secrets Operator

For Kubernetes environments, use External Secrets Operator to sync Vault secrets:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: rag-pipeline-secrets
spec:
  refreshInterval: "1h"
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: rag-pipeline-secrets
  data:
    - secretKey: database-url
      remoteRef:
        key: rag-pipeline/database
        property: url
    - secretKey: jwt-private-key
      remoteRef:
        key: rag-pipeline/jwt
        property: private_key
```

### Secret Rotation

```bash
# Rotate all secrets
./scripts/rotate-secrets.sh all

# Rotate specific secret type
./scripts/rotate-secrets.sh jwt
./scripts/rotate-secrets.sh database
./scripts/rotate-secrets.sh encryption

# Verify rotation
vault kv get secret/rag-pipeline/jwt
```

---

## Audit Logging

### Overview

Comprehensive audit logging with tamper-evident storage using hash chaining, structured JSON format, and integration with Loki for centralized log aggregation.

### Audit Event Structure

```python
@dataclass
class AuditEntry:
    id: UUID
    timestamp: datetime
    tenant_id: UUID
    user_id: str
    action: str              # e.g., "document.create", "query.execute"
    resource_type: str       # e.g., "document", "query", "user"
    resource_id: str
    ip_address: str
    user_agent: str
    trace_id: str            # OpenTelemetry trace correlation
    status: str              # "success", "failure", "denied"
    status_code: int
    error_message: Optional[str]
    metadata: dict           # Additional context
    previous_hash: str       # Hash chain for tamper detection
    entry_hash: str          # SHA-256 hash of this entry
```

### Audit Actions

```python
class AuditAction(str, Enum):
    # Authentication
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_TOKEN_REFRESH = "auth.token_refresh"
    AUTH_FAILED = "auth.failed"

    # Documents
    DOCUMENT_CREATE = "document.create"
    DOCUMENT_READ = "document.read"
    DOCUMENT_UPDATE = "document.update"
    DOCUMENT_DELETE = "document.delete"
    DOCUMENT_ACL_UPDATE = "document.acl_update"

    # Queries
    QUERY_EXECUTE = "query.execute"
    QUERY_STREAM = "query.stream"

    # Ingestion
    INGESTION_START = "ingestion.start"
    INGESTION_COMPLETE = "ingestion.complete"
    INGESTION_FAILED = "ingestion.failed"

    # Administration
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    USER_DELETE = "user.delete"
    ROLE_ASSIGN = "role.assign"
    ROLE_REVOKE = "role.revoke"

    # System
    CONFIG_UPDATE = "config.update"
    SECRET_ACCESS = "secret.access"
    SECRET_ROTATE = "secret.rotate"
```

### Usage

```python
from shared.security.audit import AuditLogger, AuditAction

logger = AuditLogger()

# Log an action
await logger.log(
    user=user,
    action=AuditAction.DOCUMENT_CREATE,
    resource_type="document",
    resource_id=str(document_id),
    status="success",
    metadata={"file_name": "document.pdf", "file_size": 1024},
)

# Log failure
await logger.log(
    user=user,
    action=AuditAction.DOCUMENT_DELETE,
    resource_type="document",
    resource_id=str(document_id),
    status="denied",
    status_code=403,
    error_message="Insufficient permissions",
)
```

### FastAPI Middleware

```python
from shared.security.audit import AuditMiddleware

app.add_middleware(AuditMiddleware)
```

The middleware automatically logs:
- All API requests with user context
- Response status codes
- Request duration
- Authentication failures (401)
- Authorization failures (403)
- Server errors (5xx)

### Hash Chain Verification

```python
from shared.security.audit import AuditRepository

repo = AuditRepository(db_session)

# Verify tamper-evidence for a date range
is_valid, errors = await repo.verify_chain(
    tenant_id=tenant_id,
    start_date=datetime(2026, 1, 1),
    end_date=datetime(2026, 1, 31),
)

if not is_valid:
    for error in errors:
        print(f"Tampering detected: {error}")
```

### PostgreSQL Storage

Audit logs are stored in the `audit_log` table with hash chaining:

```sql
CREATE TABLE audit_log (
    id UUID PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    tenant_id UUID NOT NULL,
    user_id VARCHAR(255),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id VARCHAR(255),
    ip_address INET,
    user_agent TEXT,
    trace_id VARCHAR(64),
    status VARCHAR(20) NOT NULL,
    status_code INTEGER,
    error_message TEXT,
    metadata JSONB DEFAULT '{}',
    previous_hash VARCHAR(64),
    entry_hash VARCHAR(64) NOT NULL
);

CREATE INDEX ix_audit_log_tenant_timestamp ON audit_log(tenant_id, timestamp);
CREATE INDEX ix_audit_log_user_id ON audit_log(user_id);
CREATE INDEX ix_audit_log_action ON audit_log(action);
CREATE INDEX ix_audit_log_trace_id ON audit_log(trace_id);
```

### Loki Integration

Audit logs are also shipped to Loki for centralized querying:

```python
# Query in Grafana
{job="rag-pipeline"} |= "audit" | json | action="document.create"
```

### Export

```bash
# Export audit logs for compliance
python scripts/export-audit-logs.py \
    --start-date 2026-01-01 \
    --end-date 2026-01-31 \
    --tenant-id <uuid> \
    --output audit-export.json \
    --format json  # or csv

# Verify integrity before export
python scripts/export-audit-logs.py \
    --verify-chain \
    --tenant-id <uuid>
```

---

## TLS/mTLS Configuration

### Overview

All services communicate over TLS 1.3 with optional mTLS for service-to-service authentication.

### Configuration

```python
from shared.security.tls import TLSConfig, create_ssl_context

config = TLSConfig(
    cert_file="/certs/server.crt",
    key_file="/certs/server.key",
    ca_file="/certs/ca.crt",
    verify_mode="CERT_REQUIRED",  # CERT_NONE, CERT_OPTIONAL, CERT_REQUIRED
    check_hostname=True,
    min_version="TLSv1_3",
    ciphers="ECDHE+AESGCM:DHE+AESGCM",
)

ssl_context = create_ssl_context(config)

# Use with uvicorn
uvicorn.run(app, ssl_keyfile=config.key_file, ssl_certfile=config.cert_file)
```

### Kubernetes Certificates

Certificates are managed via cert-manager:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: rag-pipeline-tls
  namespace: rag-pipeline
spec:
  secretName: rag-pipeline-tls
  issuerRef:
    name: internal-ca
    kind: ClusterIssuer
  dnsNames:
    - "*.rag-pipeline.svc.cluster.local"
    - "ingestion-service"
    - "retrieval-service"
    - "orchestrator-service"
  duration: 720h  # 30 days
  renewBefore: 168h  # 7 days
```

### Service Mesh (Istio)

For automated mTLS with Istio:

```yaml
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: rag-pipeline
spec:
  mtls:
    mode: STRICT
```

---

## Security Scanning

### CI/CD Workflows

| Workflow | Trigger | Tools | Purpose |
|----------|---------|-------|---------|
| `security-dependency-scan.yml` | Push, PR, Daily | pip-audit, safety | Dependency vulnerabilities |
| `security-container-scan.yml` | Push, PR, Weekly | Trivy | Container image vulnerabilities |
| `security-sast.yml` | Push, PR, Weekly | Bandit, Semgrep | Static code analysis |
| `security-secrets.yml` | Push, PR, Daily | Gitleaks, detect-secrets | Leaked secrets |

### Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/PyCQA/bandit
    rev: 1.7.5
    hooks:
      - id: bandit
        args: ["-c", "pyproject.toml"]

  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks

  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
        args: ["--baseline", ".secrets.baseline"]

  - repo: local
    hooks:
      - id: semgrep
        name: semgrep
        entry: semgrep scan --config .semgrep.yml
        language: system
        types: [python]
```

### Manual Scanning

```bash
# Install tools
pip install bandit safety pip-audit semgrep detect-secrets
brew install gitleaks trivy

# Run all security scans
./scripts/security-scan.sh

# Full scan including containers
./scripts/security-scan.sh --full

# Individual scans
bandit -c pyproject.toml -r services/
safety check
pip-audit
semgrep scan --config .semgrep.yml
gitleaks detect
trivy image rag-pipeline/ingestion-service:latest

# Generate consolidated report
python scripts/generate_security_report.py \
    --input-dir ./security-reports \
    --output ./security-reports/report.md
```

### Configuration Files

| File | Purpose |
|------|---------|
| `.gitleaks.toml` | Gitleaks secrets detection config |
| `.semgrep.yml` | Custom Semgrep rules |
| `.pre-commit-config.yaml` | Pre-commit hooks |
| `pyproject.toml` | Bandit configuration |
| `.secrets.baseline` | Known false positives for detect-secrets |

---

## Quick Start

### Install Security Tools

```bash
# Python security tools
pip install bandit safety pip-audit semgrep detect-secrets

# Pre-commit hooks
pip install pre-commit
pre-commit install

# macOS tools
brew install gitleaks trivy
```

### Run Security Scans

```bash
# Pre-commit hooks (runs on commit)
pre-commit run --all-files

# Manual security scan
./scripts/security-scan.sh
```

### Generate JWT Keys

```bash
# Generate RS256 key pair
./scripts/generate-jwt-keys.sh

# Keys are created at:
# - secrets/jwt-private.pem (keep secret!)
# - secrets/jwt-public.pem (can distribute)
```

### Configure Secrets

```bash
# For Vault (production)
export SECRETS_BACKEND=vault
export VAULT_ADDR=http://vault:8200
export VAULT_TOKEN=s.xxxxx

# For Kubernetes
export SECRETS_BACKEND=kubernetes

# For development
export SECRETS_BACKEND=environment
export DATABASE_URL=postgresql://raguser:ragpass@localhost:5432/ragpipeline
export REDIS_URL=redis://localhost:6379
export FIELD_ENCRYPTION_KEY=$(openssl rand -base64 32)
```

### Run Security Tests

```bash
# All security tests
pytest tests/security/ -v

# Specific test suites
pytest tests/security/test_jwt_authentication.py -v
pytest tests/security/test_rbac_authorization.py -v
pytest tests/security/test_document_acl.py -v
pytest tests/security/test_pii_detection.py -v
pytest tests/security/test_encryption.py -v
pytest tests/security/test_audit_logging.py -v
pytest tests/security/test_secrets.py -v
```

---

## Compliance

The security implementation supports compliance with:

### SOC 2 Type II

| Control Area | Implementation |
|--------------|----------------|
| **CC6.1** Access Control | JWT authentication, RBAC, tenant isolation |
| **CC6.2** Logical Access | Document ACLs, permission checks |
| **CC6.3** Access Removal | Token blocklist, role revocation |
| **CC7.1** Change Management | Audit logging, version control |
| **CC7.2** System Monitoring | Metrics, tracing, alerting |
| **CC8.1** Encryption | AES-256, TLS 1.3, key management |

### GDPR

| Requirement | Implementation |
|-------------|----------------|
| **Art. 5** Data Protection | Field encryption, access controls |
| **Art. 15** Right to Access | Audit log exports per user |
| **Art. 17** Right to Erasure | Document deletion with ACL cleanup |
| **Art. 25** Data Minimization | PII detection and redaction |
| **Art. 30** Records of Processing | Comprehensive audit logging |
| **Art. 32** Security Measures | Encryption, access control, monitoring |

### HIPAA (if applicable)

| Safeguard | Implementation |
|-----------|----------------|
| **164.312(a)** Access Control | RBAC, unique user IDs |
| **164.312(b)** Audit Controls | Tamper-evident audit logs |
| **164.312(c)** Integrity | Hash-chained audit logs, checksums |
| **164.312(d)** Authentication | JWT with RS256, MFA support |
| **164.312(e)** Transmission Security | TLS 1.3, mTLS for services |

---

## Security Best Practices

### For Developers

1. **Never commit secrets** - Use environment variables or secrets manager
2. **Run pre-commit hooks** - Install with `pre-commit install`
3. **Review security findings** - Check CI/CD results on PRs
4. **Use parameterized queries** - Prevent SQL injection
5. **Validate all input** - Trust nothing from external sources
6. **Encrypt sensitive data** - Use EncryptedString for PII fields
7. **Check permissions** - Use RBAC decorators on all endpoints
8. **Log security events** - Use AuditLogger for sensitive operations

### For Operations

1. **Rotate secrets regularly** - Use rotation scripts
2. **Monitor audit logs** - Set up alerts for suspicious activity
3. **Keep dependencies updated** - Address CVEs promptly
4. **Review access regularly** - Remove unused permissions
5. **Backup encryption keys** - Store securely offline
6. **Verify audit chain** - Run periodic integrity checks
7. **Run penetration tests** - Follow [penetration testing guide](./penetration-testing.md)

---

## Incident Response

If you discover a security vulnerability:

1. **Do not** create a public issue
2. **Do** contact security@example.com immediately
3. **Do** document what you found and how
4. **Do not** attempt to exploit beyond PoC
5. **Do** preserve evidence for investigation

---

## Related Documentation

- [Penetration Testing Guide](./penetration-testing.md)
- [Architecture Overview](../architecture.md)
- [Observability Guide](../observability/README.md)
- [Retrieval Service](../retrieval-service/README.md)
- [Deployment Runbook](../infrastructure/deployment-runbook.md)

---

## Security Contacts

| Role | Email | Responsibility |
|------|-------|----------------|
| Security Team | security@example.com | Security incidents, reviews |
| DevOps Team | devops@example.com | Infrastructure security |
| Development Lead | dev@example.com | Application security |

---

## References

- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)
- [CIS Kubernetes Benchmark](https://www.cisecurity.org/benchmark/kubernetes)
- [HashiCorp Vault Documentation](https://developer.hashicorp.com/vault/docs)
- [Microsoft Presidio](https://microsoft.github.io/presidio/)
- [OpenTelemetry Security](https://opentelemetry.io/docs/concepts/security/)
