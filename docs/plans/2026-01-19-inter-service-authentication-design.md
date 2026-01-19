# Inter-Service Authentication Design

> **User Story**: US-10.7.1
> **Date**: 2026-01-19
> **Status**: Approved

## Overview

Implement JWT-based service-to-service authentication to prevent unauthorized internal communication. Each service gets a unique RSA keypair, signs outbound requests with JWTs, and validates inbound requests against a full RBAC permission model.

## Architecture

### Authentication Flow

```
Orchestrator                         Retrieval
     |                                   |
     |-- POST /internal/search --------->|
     |   Authorization: Bearer <JWT>     |
     |   JWT contains:                   |
     |     iss: orchestrator             |
     |     aud: retrieval                |
     |     roles: [orchestrator-role]    |
     |                                   |
     |   Retrieval validates:            |
     |   1. Signature (orchestrator's    |
     |      public key)                  |
     |   2. Audience matches "retrieval" |
     |   3. Role has permission for      |
     |      "/internal/search"           |
     |                                   |
     |<-- 200 OK -----------------------|
```

### Service Communication Map

```
orchestrator → retrieval    (search, rerank)
orchestrator → ingestion    (status checks)
orchestrator → llm-gateway  (generate, embed)
retrieval    → embedding    (embed queries)
ingestion    → embedding    (embed documents)
ingestion    → retrieval    (index notifications)
```

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Auth mechanism | JWT with RSA keypairs | Leverages existing `JWTHandler`, no shared secrets |
| Key storage | Kubernetes Secrets | Simple, fits existing K8s deployment model |
| Authorization | Full RBAC per endpoint | Maximum flexibility for compliance |
| Client integration | Wrapper class | Centralizes auth logic, easy to test |
| Endpoint convention | `/internal/*` prefix | Clear separation from user-facing `/api/v1/*` |

## Detailed Design

### 1. JWTHandler Extensions

Extend existing `services/shared/security/jwt/handler.py`:

```python
def create_service_token(
    self,
    source_service: str,
    target_service: str,
    roles: list[str],
    ttl_seconds: int = 300,
) -> str:
    """Create JWT for service-to-service auth.

    Args:
        source_service: Name of the calling service (becomes iss/sub)
        target_service: Name of the target service (becomes aud)
        roles: Service roles for RBAC
        ttl_seconds: Token lifetime (default 5 minutes)

    Returns:
        Signed JWT string
    """

def verify_service_token(
    self,
    token: str,
    expected_audience: str,
) -> ServiceTokenPayload:
    """Verify incoming service token.

    Args:
        token: JWT string from Authorization header
        expected_audience: This service's name

    Returns:
        Validated payload with issuer, roles, etc.

    Raises:
        TokenExpiredError: Token has expired
        TokenInvalidError: Signature invalid or audience mismatch
    """
```

New dataclass in `services/shared/security/jwt/models.py`:

```python
@dataclass
class ServiceTokenPayload:
    issuer: str          # Source service name
    subject: str         # Same as issuer for services
    audience: str        # Target service name
    roles: list[str]     # Service roles for RBAC
    issued_at: datetime
    expires_at: datetime
    jti: str             # Unique token ID
```

### 2. RBAC Configuration

Configuration file `config/service_auth.yaml`:

```yaml
service_roles:
  orchestrator-role:
    permissions:
      - retrieval:search
      - retrieval:rerank
      - ingestion:status
      - llm-gateway:generate
      - llm-gateway:embed

  retrieval-role:
    permissions:
      - embedding:embed

  ingestion-role:
    permissions:
      - embedding:embed
      - retrieval:index-notify

services:
  orchestrator:
    roles: [orchestrator-role]
  retrieval:
    roles: [retrieval-role]
  ingestion:
    roles: [ingestion-role]
  embedding:
    roles: []
  llm-gateway:
    roles: []
```

Endpoint permission mapping (per service):

```python
# Example for retrieval service
ENDPOINT_PERMISSIONS = {
    "/internal/search": "retrieval:search",
    "/internal/rerank": "retrieval:rerank",
    "/internal/index/notify": "retrieval:index-notify",
}
```

### 3. AuthenticatedServiceClient

New file `services/shared/security/service_auth/client.py`:

```python
class AuthenticatedServiceClient:
    """HTTP client with automatic service-to-service auth."""

    def __init__(
        self,
        jwt_handler: JWTHandler,
        source_service: str,
        target_service: str,
        roles: list[str],
        base_url: str,
        timeout: float = 30.0,
    ):
        self.jwt_handler = jwt_handler
        self.source_service = source_service
        self.target_service = target_service
        self.roles = roles
        self.base_url = base_url
        self.timeout = timeout
        self._token_cache: tuple[str, float] | None = None

    def _get_token(self) -> str:
        """Get cached token or create new one."""
        now = time.time()
        if self._token_cache:
            token, expiry = self._token_cache
            if expiry > now + 30:  # 30s buffer before expiry
                return token

        token = self.jwt_handler.create_service_token(
            source_service=self.source_service,
            target_service=self.target_service,
            roles=self.roles,
        )
        self._token_cache = (token, now + 300)
        return token

    async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Make authenticated request."""
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._get_token()}"

        # Propagate correlation context
        ctx = get_correlation_context()
        if ctx:
            headers.update(ctx.to_headers())

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                **kwargs,
            )

    async def get(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> httpx.Response:
        return await self.request("POST", path, **kwargs)
```

### 4. ServiceAuthMiddleware

New file `services/shared/security/service_auth/middleware.py`:

```python
class ServiceAuthMiddleware(BaseHTTPMiddleware):
    """Validates service-to-service authentication on internal endpoints."""

    def __init__(
        self,
        app,
        jwt_handler: JWTHandler,
        service_name: str,
        endpoint_permissions: dict[str, str],
        rbac_config: dict,
        exclude_paths: list[str] | None = None,
    ):
        super().__init__(app)
        self.jwt_handler = jwt_handler
        self.service_name = service_name
        self.endpoint_permissions = endpoint_permissions
        self.rbac_config = rbac_config
        self.exclude_paths = exclude_paths or ["/health", "/metrics", "/docs", "/openapi.json"]

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip non-internal paths
        if not path.startswith("/internal/"):
            return await call_next(request)

        # Skip excluded paths
        if any(path.startswith(p) for p in self.exclude_paths):
            return await call_next(request)

        # Extract token
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.warning(
                "service_auth_missing",
                target=self.service_name,
                endpoint=path,
                correlation_id=get_correlation_id(),
            )
            service_auth_total.labels(caller="unknown", target=self.service_name, result="missing").inc()
            return JSONResponse(status_code=401, content={"detail": "Missing service token"})

        token = auth_header.removeprefix("Bearer ")

        # Verify token
        try:
            payload = self.jwt_handler.verify_service_token(token, self.service_name)
        except TokenExpiredError:
            logger.warning("service_auth_failed", reason="expired", endpoint=path)
            service_auth_total.labels(caller="unknown", target=self.service_name, result="failed").inc()
            return JSONResponse(status_code=401, content={"detail": "Token expired"})
        except TokenInvalidError as e:
            logger.warning("service_auth_failed", reason=str(e), endpoint=path)
            service_auth_total.labels(caller="unknown", target=self.service_name, result="failed").inc()
            return JSONResponse(status_code=401, content={"detail": str(e)})

        # Check permission
        required_permission = self._get_required_permission(path)
        if required_permission and not self._has_permission(payload.roles, required_permission):
            logger.warning(
                "service_auth_denied",
                caller=payload.issuer,
                target=self.service_name,
                endpoint=path,
                required_permission=required_permission,
                caller_roles=payload.roles,
            )
            service_auth_total.labels(caller=payload.issuer, target=self.service_name, result="denied").inc()
            return JSONResponse(status_code=403, content={"detail": f"Missing permission: {required_permission}"})

        # Success
        logger.debug(
            "service_auth_success",
            caller=payload.issuer,
            target=self.service_name,
            endpoint=path,
        )
        service_auth_total.labels(caller=payload.issuer, target=self.service_name, result="success").inc()

        # Add caller info to request state
        request.state.caller_service = payload.issuer
        request.state.caller_roles = payload.roles

        return await call_next(request)

    def _get_required_permission(self, path: str) -> str | None:
        """Match path to required permission using patterns."""
        for pattern, permission in self.endpoint_permissions.items():
            if fnmatch.fnmatch(path, pattern):
                return permission
        return None

    def _has_permission(self, roles: list[str], required_permission: str) -> bool:
        """Check if any role grants the required permission."""
        for role in roles:
            role_perms = self.rbac_config.get("service_roles", {}).get(role, {}).get("permissions", [])
            if required_permission in role_perms:
                return True
        return False
```

### 5. Kubernetes Configuration

Secret template `k8s/base/security/service-auth-keys.yaml`:

```yaml
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
  embedding.key: <base64-private-key>
  embedding.pub: <base64-public-key>
  llm-gateway.key: <base64-private-key>
  llm-gateway.pub: <base64-public-key>
```

Volume mount example for retrieval deployment:

```yaml
spec:
  containers:
    - name: retrieval
      volumeMounts:
        - name: service-auth-keys
          mountPath: /etc/service-auth
          readOnly: true
      env:
        - name: SERVICE_NAME
          value: "retrieval"
        - name: SERVICE_AUTH_KEYS_DIR
          value: "/etc/service-auth"
        - name: TRUSTED_CALLERS
          value: "orchestrator,ingestion"
  volumes:
    - name: service-auth-keys
      secret:
        secretName: service-auth-keys
        items:
          - key: retrieval.key
            path: retrieval.key
          - key: retrieval.pub
            path: retrieval.pub
          - key: orchestrator.pub
            path: orchestrator.pub
          - key: ingestion.pub
            path: ingestion.pub
```

### 6. Key Generation Script

`scripts/generate-service-keys.sh`:

```bash
#!/bin/bash
set -euo pipefail

SERVICES="orchestrator retrieval ingestion embedding llm-gateway"
OUTPUT_DIR="${1:-./service-keys}"

mkdir -p "$OUTPUT_DIR"

for service in $SERVICES; do
    echo "Generating keypair for $service..."
    openssl genrsa -out "$OUTPUT_DIR/${service}.key" 2048
    openssl rsa -in "$OUTPUT_DIR/${service}.key" -pubout -out "$OUTPUT_DIR/${service}.pub"
done

echo "Done. Keys written to $OUTPUT_DIR/"
echo ""
echo "To create Kubernetes secret:"
echo "  kubectl create secret generic service-auth-keys \\"
echo "    --namespace=rag-pipeline \\"
for service in $SERVICES; do
    echo "    --from-file=${service}.key=$OUTPUT_DIR/${service}.key \\"
    echo "    --from-file=${service}.pub=$OUTPUT_DIR/${service}.pub \\"
done
echo "    --dry-run=client -o yaml > k8s/base/security/service-auth-keys.yaml"
```

## Audit Logging

### Events

| Event | Level | When |
|-------|-------|------|
| `service_auth_success` | DEBUG | Valid token, authorized |
| `service_auth_denied` | WARN | Valid token, missing permission |
| `service_auth_failed` | WARN | Invalid/expired token |
| `service_auth_missing` | WARN | No token on `/internal/*` endpoint |

### Metrics

```python
service_auth_total = Counter(
    "service_auth_total",
    "Service authentication attempts",
    ["caller", "target", "result"]  # result: success, denied, failed, missing
)
```

## Implementation Plan

### Files to Create

| File | Purpose |
|------|---------|
| `services/shared/security/service_auth/__init__.py` | Module exports |
| `services/shared/security/service_auth/client.py` | `AuthenticatedServiceClient` |
| `services/shared/security/service_auth/middleware.py` | `ServiceAuthMiddleware` |
| `services/shared/security/service_auth/config.py` | RBAC config loader |
| `config/service_auth.yaml` | Roles, permissions, service mappings |
| `k8s/base/security/service-auth-keys.yaml` | Secret template |
| `scripts/generate-service-keys.sh` | Key generation script |
| `tests/unit/security/test_service_auth.py` | Unit tests |
| `tests/integration/test_service_auth_integration.py` | Integration tests |

### Files to Modify

| File | Change |
|------|--------|
| `services/shared/security/jwt/handler.py` | Add `create_service_token`, `verify_service_token` |
| `services/shared/security/jwt/models.py` | Add `ServiceTokenPayload` |
| `services/orchestrator/gateway/client.py` | Use `AuthenticatedServiceClient` |
| `services/ingestion/embedding/client.py` | Use `AuthenticatedServiceClient` |
| `services/orchestrator/main.py` | Register middleware, load keys |
| `services/retrieval/main.py` | Register middleware, load keys |
| `services/ingestion/main.py` | Register middleware, load keys |
| `k8s/base/*/deployment.yaml` | Add secret volume mounts |

### Implementation Order

1. Extend `JWTHandler` with service token methods
2. Create `AuthenticatedServiceClient`
3. Create `ServiceAuthMiddleware`
4. Create RBAC config and loader
5. Update service clients (orchestrator, ingestion)
6. Register middleware in each service
7. Set up K8s secrets and mounts
8. Write tests

## Testing Strategy

### Unit Tests

- Token creation with correct claims
- Token verification (valid, expired, wrong audience)
- Permission checking against RBAC config
- Token caching behavior

### Integration Tests

- Health endpoints without auth (should pass)
- Internal endpoints without auth (should return 401)
- Internal endpoints with valid auth (should pass)
- Internal endpoints with wrong permission (should return 403)
- Cross-service calls end-to-end

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Key compromise | Critical | Regular rotation, revocation via new keys |
| Clock skew | Medium | 30s buffer on expiry check, NTP sync |
| Performance overhead | Low | Token caching (5 min), async validation |
| Complexity | Medium | Clear documentation, centralized config |

## Definition of Done

- [ ] `JWTHandler` extended with service token methods
- [ ] `AuthenticatedServiceClient` implemented with token caching
- [ ] `ServiceAuthMiddleware` deployed to all services
- [ ] RBAC configuration complete
- [ ] Key generation script created
- [ ] All inter-service calls use authenticated clients
- [ ] Audit logging for auth events
- [ ] Prometheus metrics exposed
- [ ] Unit tests passing
- [ ] Integration tests passing
- [ ] K8s secrets and mounts configured
