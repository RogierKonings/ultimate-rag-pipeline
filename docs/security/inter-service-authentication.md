# Inter-Service Authentication

> **Version:** 1.0
> **Status:** Production Implementation
> **Cross-Reference:** US-10.7.1 (Security Hardening)

## Overview

The RAG Pipeline implements JWT-based service-to-service authentication to prevent unauthorized internal communication. Each service has a unique identity with RSA key pairs, and all inter-service requests include signed JWT tokens that are validated by the receiving service.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Key Management                               │
│     ┌──────────────────────────────────────────────────────────┐    │
│     │  /etc/service-auth/                                       │    │
│     │  ├── orchestrator.key  (private)                          │    │
│     │  ├── orchestrator.pub  (public)                           │    │
│     │  ├── retrieval.key                                        │    │
│     │  ├── retrieval.pub                                        │    │
│     │  ├── ingestion.key                                        │    │
│     │  └── ingestion.pub                                        │    │
│     └──────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   Orchestrator  │─────▶│    Retrieval    │─────▶│    Embedding    │
│   (Caller)      │      │   (Validates)   │      │   (Validates)   │
│                 │      │                 │      │                 │
│ ServiceAuthClient│      │ServiceAuthMiddleware│  │ServiceAuthMiddleware│
└─────────────────┘      └─────────────────┘      └─────────────────┘
        │
        │ JWT Token
        │ Authorization: Bearer <token>
        ▼
```

## Key Features

| Feature | Description |
|---------|-------------|
| **Service Identity** | Each service has unique RSA-2048 key pairs |
| **JWT Tokens** | RS256-signed tokens with short TTL (5 minutes) |
| **Token Caching** | Cached tokens avoid re-signing overhead |
| **Authorization Matrix** | Configurable service-to-endpoint permissions |
| **Audit Logging** | All auth events logged for compliance |

## Components

| Component | Location | Purpose |
|-----------|----------|---------|
| ServiceAuthClient | [services/shared/security/jwt/service_client.py](../../services/shared/security/jwt/service_client.py) | Generate auth headers for outgoing requests |
| ServiceAuthMiddleware | [services/shared/security/jwt/service_auth_middleware.py](../../services/shared/security/jwt/service_auth_middleware.py) | Validate incoming service requests |
| ServiceAuthConfig | [services/shared/security/jwt/service_auth_config.py](../../services/shared/security/jwt/service_auth_config.py) | Authorization matrix configuration |

## JWT Token Structure

Service-to-service tokens include:

```json
{
  "iss": "orchestrator",
  "sub": "orchestrator",
  "aud": "retrieval",
  "iat": 1737312000,
  "exp": 1737312300,
  "jti": "orchestrator-1737312000"
}
```

| Claim | Description |
|-------|-------------|
| `iss` | Issuing service name |
| `sub` | Subject (same as issuer for service tokens) |
| `aud` | Target service that should accept this token |
| `iat` | Issued at timestamp |
| `exp` | Expiration time (default: 5 minutes) |
| `jti` | Unique token identifier |

## Configuration

### Service Identity Setup

Each service requires its key pair mounted from Kubernetes Secrets:

```yaml
# k8s/base/service-auth-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: service-auth-keys
  namespace: rag-pipeline
type: Opaque
data:
  orchestrator.key: <base64-private-key>
  orchestrator.pub: <base64-public-key>
  retrieval.key: <base64-private-key>
  retrieval.pub: <base64-public-key>
  ingestion.key: <base64-private-key>
  ingestion.pub: <base64-public-key>
```

### Authorization Matrix

The authorization matrix defines which services can call which endpoints:

```yaml
# config/service_auth.yaml
services:
  orchestrator:
    allowed_targets:
      - retrieval
      - ingestion
      - llm-gateway

  retrieval:
    allowed_targets:
      - embedding

  ingestion:
    allowed_targets:
      - embedding
      - retrieval

authorization_matrix:
  orchestrator:
    retrieval:
      - "/internal/search"
      - "/internal/rerank"
    ingestion:
      - "/internal/status/*"
    llm-gateway:
      - "/internal/generate"
      - "/internal/embed"

  retrieval:
    embedding:
      - "/internal/embed"

  ingestion:
    embedding:
      - "/internal/embed"
    retrieval:
      - "/internal/index/notify"
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SERVICE_NAME` | Current service identity | Required |
| `SERVICE_AUTH_KEYS_DIR` | Path to key files | `/etc/service-auth` |
| `SERVICE_AUTH_TOKEN_TTL` | Token TTL in seconds | `300` |
| `SERVICE_AUTH_ENABLED` | Enable/disable auth | `true` |
| `SERVICE_AUTH_CONFIG_PATH` | Authorization matrix file | `/config/service_auth.yaml` |

## Usage

### Client Side (Making Requests)

```python
from shared.security.jwt import ServiceAuthClient, KeyManager

# Initialize client with service identity
key_manager = KeyManager("/etc/service-auth")
private_key = key_manager.load_private_key("orchestrator")
public_key = key_manager.load_public_key("orchestrator")

auth_client = ServiceAuthClient(
    service_name="orchestrator",
    private_key=private_key,
    allowed_targets=["retrieval", "ingestion"],
    token_ttl=300,
)

# Get auth headers for a request
headers = auth_client.get_auth_headers("retrieval")
# Returns: {"Authorization": "Bearer eyJ..."}

# Use with httpx
async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://retrieval:8002/internal/search",
        headers=headers,
        json={"query": "..."}
    )
```

### Server Side (Validating Requests)

```python
from fastapi import FastAPI
from shared.security.jwt import ServiceAuthMiddleware, ServiceAuthConfig

app = FastAPI()

# Load configuration
config = ServiceAuthConfig.from_file("/config/service_auth.yaml")

# Add middleware
app.add_middleware(
    ServiceAuthMiddleware,
    service_name="retrieval",
    config=config,
    keys_dir="/etc/service-auth",
    exclude_paths=["/health", "/metrics", "/docs"],
)
```

### Using AuthenticatedServiceClient

For convenience, use the pre-built authenticated client wrapper:

```python
from shared.security.jwt import AuthenticatedServiceClient

# Create client for retrieval service
retrieval_client = AuthenticatedServiceClient(
    base_url="http://retrieval:8002",
    target_service="retrieval",
    auth_client=auth_client,
)

# Make authenticated requests
response = await retrieval_client.post(
    "/internal/search",
    json={"query": "test query", "tenant_id": "tenant-1"}
)
```

## Middleware Behavior

### Request Flow

1. Check if path is excluded (health, metrics, docs)
2. Check if path is user-facing API (`/api/v1/`) - uses user auth instead
3. Extract Authorization header
4. Decode and verify JWT signature
5. Validate audience matches current service
6. Check authorization matrix for endpoint permission
7. Add caller identity to request state

### Error Responses

| Status | Condition | Detail |
|--------|-----------|--------|
| 401 | Missing Authorization header | "Service authentication required" |
| 401 | Invalid/expired token | "Invalid token: {reason}" |
| 401 | Unknown issuer | "Unknown issuer: {service}" |
| 403 | Endpoint not permitted | "Service {caller} not authorized for {endpoint}" |

## Key Management

### Key Generation

Generate RSA key pairs for each service:

```bash
# Generate private key
openssl genrsa -out orchestrator.key 2048

# Extract public key
openssl rsa -in orchestrator.key -pubout -out orchestrator.pub

# Create Kubernetes secret
kubectl create secret generic service-auth-keys \
  --from-file=orchestrator.key \
  --from-file=orchestrator.pub \
  --from-file=retrieval.key \
  --from-file=retrieval.pub \
  -n rag-pipeline
```

### Key Rotation

1. Generate new key pairs
2. Add new public keys to all services (dual-key period)
3. Update calling services with new private keys
4. Remove old public keys after grace period

```bash
# Key rotation script
./scripts/rotate-service-auth-keys.sh orchestrator
```

## Security Considerations

### Best Practices

1. **Short TTLs**: Use 5-minute token TTL to limit exposure
2. **Audience Validation**: Always verify token audience matches receiving service
3. **Endpoint Restrictions**: Only permit necessary endpoints per service
4. **Key Security**: Store private keys in Kubernetes Secrets or Vault
5. **Audit Logging**: Log all authentication events

### Attack Mitigations

| Threat | Mitigation |
|--------|------------|
| Token replay | Short TTL, JTI tracking |
| Key compromise | Regular rotation, Vault integration |
| Lateral movement | Authorization matrix limits endpoints |
| Man-in-the-middle | TLS for all communication |

## Testing

### Unit Tests

```bash
# Run service auth tests
pytest services/shared/security/jwt/tests/test_service_auth.py -v
```

### Integration Testing

```python
# Test authenticated endpoint
def test_service_auth_required():
    """Should require service authentication."""
    response = client.get("/internal/search")
    assert response.status_code == 401

def test_service_auth_valid():
    """Should accept valid service token."""
    headers = auth_client.get_auth_headers("retrieval")
    response = client.get("/internal/search", headers=headers)
    assert response.status_code == 200

def test_service_auth_wrong_audience():
    """Should reject token with wrong audience."""
    headers = auth_client.get_auth_headers("ingestion")  # Wrong target
    response = client.get("/internal/search", headers=headers)
    assert response.status_code == 401
```

## Troubleshooting

### Common Issues

**401 "Service authentication required"**
- Check Authorization header is present
- Verify header format: `Bearer <token>`

**401 "Unknown issuer"**
- Verify caller's public key is loaded
- Check service name in token matches expected

**403 "Not authorized for endpoint"**
- Review authorization matrix configuration
- Ensure endpoint pattern matches request path

### Debug Logging

Enable debug logging for auth events:

```python
import structlog
structlog.configure(
    processors=[...],
    wrapper_class=structlog.stdlib.BoundLogger,
)

# Set log level
import logging
logging.getLogger("shared.security.jwt").setLevel(logging.DEBUG)
```

## Related Documentation

- [Security Overview](./README.md)
- [JWT Authentication](./README.md#authentication-jwt)
- [Database Security](./database-security.md)
- [Secrets Management](./README.md#secrets-management)
