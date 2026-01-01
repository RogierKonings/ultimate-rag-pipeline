# US-7.5: Encryption in Transit

> **Epic:** Security & Compliance  
> **Priority:** High  
> **Estimated Effort:** 1-2 days  
> **Dependencies:** Epic 1 (Infrastructure)

## User Story

**As a** security engineer  
**I want** TLS for all connections  
**So that** data is protected in transit between services and clients

## Objective

Configure TLS 1.3 for all external API connections, implement mTLS for internal service-to-service communication (optional), set up certificate management with cert-manager, configure TLS termination at ingress, and ensure no plaintext transmission of sensitive data.

## Architecture Reference

- **External:** TLS 1.3 termination at Ingress/Load Balancer
- **Internal:** mTLS between services (optional but recommended)
- **Certificates:** Let's Encrypt (external) + self-signed CA (internal)
- **Management:** cert-manager for automatic renewal

## Implementation Tasks

### 1. Install and Configure cert-manager

`infrastructure/k8s/cert-manager/cert-manager.yaml`:

```yaml
# Install via Helm or apply manifests
# helm repo add jetstack https://charts.jetstack.io
# helm install cert-manager jetstack/cert-manager --namespace cert-manager --create-namespace --set installCRDs=true

---
apiVersion: v1
kind: Namespace
metadata:
  name: cert-manager
---
# Or apply official manifests:
# kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml
```

### 2. Create Certificate Issuers

`infrastructure/k8s/certificates/cluster-issuer.yaml`:

```yaml
# Let's Encrypt Production Issuer (for external certificates)
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: security@yourcompany.com
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
    - http01:
        ingress:
          class: nginx
---
# Let's Encrypt Staging (for testing)
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: security@yourcompany.com
    privateKeySecretRef:
      name: letsencrypt-staging-key
    solvers:
    - http01:
        ingress:
          class: nginx
---
# Internal CA for mTLS (self-signed)
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: internal-ca-issuer
spec:
  ca:
    secretName: internal-ca-key-pair
---
# Self-signed issuer for internal CA root
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: selfsigned-issuer
spec:
  selfSigned: {}
```

### 3. Create Internal CA

`infrastructure/k8s/certificates/internal-ca.yaml`:

```yaml
# Create the root CA certificate
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: internal-ca
  namespace: rag-pipeline
spec:
  isCA: true
  commonName: rag-pipeline-internal-ca
  secretName: internal-ca-key-pair
  duration: 87600h  # 10 years
  renewBefore: 8760h  # 1 year
  privateKey:
    algorithm: ECDSA
    size: 256
  issuerRef:
    name: selfsigned-issuer
    kind: ClusterIssuer
---
# Issuer that uses the internal CA
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: internal-ca
  namespace: rag-pipeline
spec:
  ca:
    secretName: internal-ca-key-pair
```

### 4. Configure Ingress with TLS

`infrastructure/k8s/ingress/ingress-tls.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: rag-api-ingress
  namespace: rag-pipeline
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    # TLS 1.3 only
    nginx.ingress.kubernetes.io/ssl-protocols: "TLSv1.3"
    nginx.ingress.kubernetes.io/ssl-ciphers: "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256"
    # HSTS
    nginx.ingress.kubernetes.io/hsts: "true"
    nginx.ingress.kubernetes.io/hsts-max-age: "31536000"
    nginx.ingress.kubernetes.io/hsts-include-subdomains: "true"
    # Security headers
    nginx.ingress.kubernetes.io/configuration-snippet: |
      add_header X-Content-Type-Options "nosniff" always;
      add_header X-Frame-Options "DENY" always;
      add_header X-XSS-Protection "1; mode=block" always;
      add_header Referrer-Policy "strict-origin-when-cross-origin" always;
spec:
  tls:
  - hosts:
    - api.rag-pipeline.example.com
    secretName: rag-api-tls
  rules:
  - host: api.rag-pipeline.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: api-gateway
            port:
              number: 8000
```

### 5. Create Service Certificates for mTLS

`infrastructure/k8s/certificates/service-certs.yaml`:

```yaml
# API Gateway certificate
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: api-gateway-cert
  namespace: rag-pipeline
spec:
  secretName: api-gateway-tls
  duration: 8760h  # 1 year
  renewBefore: 720h  # 30 days
  subject:
    organizations:
      - rag-pipeline
  commonName: api-gateway.rag-pipeline.svc.cluster.local
  dnsNames:
    - api-gateway
    - api-gateway.rag-pipeline
    - api-gateway.rag-pipeline.svc
    - api-gateway.rag-pipeline.svc.cluster.local
  issuerRef:
    name: internal-ca
    kind: Issuer
---
# Ingestion Service certificate
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: ingestion-service-cert
  namespace: rag-pipeline
spec:
  secretName: ingestion-service-tls
  duration: 8760h
  renewBefore: 720h
  subject:
    organizations:
      - rag-pipeline
  commonName: ingestion-service.rag-pipeline.svc.cluster.local
  dnsNames:
    - ingestion-service
    - ingestion-service.rag-pipeline
    - ingestion-service.rag-pipeline.svc
    - ingestion-service.rag-pipeline.svc.cluster.local
  issuerRef:
    name: internal-ca
    kind: Issuer
---
# Retrieval Service certificate
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: retrieval-service-cert
  namespace: rag-pipeline
spec:
  secretName: retrieval-service-tls
  duration: 8760h
  renewBefore: 720h
  subject:
    organizations:
      - rag-pipeline
  commonName: retrieval-service.rag-pipeline.svc.cluster.local
  dnsNames:
    - retrieval-service
    - retrieval-service.rag-pipeline
    - retrieval-service.rag-pipeline.svc
    - retrieval-service.rag-pipeline.svc.cluster.local
  issuerRef:
    name: internal-ca
    kind: Issuer
---
# Query Service certificate
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: query-service-cert
  namespace: rag-pipeline
spec:
  secretName: query-service-tls
  duration: 8760h
  renewBefore: 720h
  subject:
    organizations:
      - rag-pipeline
  commonName: query-service.rag-pipeline.svc.cluster.local
  dnsNames:
    - query-service
    - query-service.rag-pipeline
    - query-service.rag-pipeline.svc
    - query-service.rag-pipeline.svc.cluster.local
  issuerRef:
    name: internal-ca
    kind: Issuer
```

### 6. Configure FastAPI for TLS/mTLS

`services/shared/security/tls/config.py`:

```python
from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache
import ssl


class TLSSettings(BaseSettings):
    # Server TLS
    tls_enabled: bool = False
    tls_cert_file: Optional[str] = None
    tls_key_file: Optional[str] = None
    
    # mTLS (mutual TLS)
    mtls_enabled: bool = False
    mtls_ca_file: Optional[str] = None
    mtls_verify_client: bool = True
    
    # Client TLS (for outgoing connections)
    client_tls_verify: bool = True
    client_ca_bundle: Optional[str] = None
    client_cert_file: Optional[str] = None
    client_key_file: Optional[str] = None
    
    # TLS version requirements
    min_tls_version: str = "TLSv1.3"
    
    class Config:
        env_prefix = ""


@lru_cache()
def get_tls_settings() -> TLSSettings:
    return TLSSettings()


def create_server_ssl_context(settings: TLSSettings = None) -> Optional[ssl.SSLContext]:
    """Create SSL context for server (incoming connections)."""
    settings = settings or get_tls_settings()
    
    if not settings.tls_enabled:
        return None
    
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    
    # Load server certificate and key
    context.load_cert_chain(
        certfile=settings.tls_cert_file,
        keyfile=settings.tls_key_file,
    )
    
    # Configure mTLS if enabled
    if settings.mtls_enabled and settings.mtls_ca_file:
        context.load_verify_locations(settings.mtls_ca_file)
        context.verify_mode = ssl.CERT_REQUIRED if settings.mtls_verify_client else ssl.CERT_OPTIONAL
    
    return context


def create_client_ssl_context(settings: TLSSettings = None) -> ssl.SSLContext:
    """Create SSL context for client (outgoing connections)."""
    settings = settings or get_tls_settings()
    
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    
    if settings.client_tls_verify:
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = True
        
        if settings.client_ca_bundle:
            context.load_verify_locations(settings.client_ca_bundle)
        else:
            context.load_default_certs()
    else:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    
    # Client certificate for mTLS
    if settings.client_cert_file and settings.client_key_file:
        context.load_cert_chain(
            certfile=settings.client_cert_file,
            keyfile=settings.client_key_file,
        )
    
    return context
```

### 7. Configure Service Deployment with TLS

`infrastructure/k8s/api-gateway/deployment-tls.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-gateway
  namespace: rag-pipeline
spec:
  replicas: 3
  selector:
    matchLabels:
      app: api-gateway
  template:
    metadata:
      labels:
        app: api-gateway
    spec:
      containers:
      - name: api-gateway
        image: rag-pipeline/api-gateway:latest
        ports:
        - containerPort: 8000
        - containerPort: 8443  # TLS port
        env:
        - name: TLS_ENABLED
          value: "true"
        - name: TLS_CERT_FILE
          value: /certs/tls.crt
        - name: TLS_KEY_FILE
          value: /certs/tls.key
        - name: MTLS_ENABLED
          value: "true"
        - name: MTLS_CA_FILE
          value: /certs/ca.crt
        volumeMounts:
        - name: tls-certs
          mountPath: /certs
          readOnly: true
        - name: ca-certs
          mountPath: /ca
          readOnly: true
      volumes:
      - name: tls-certs
        secret:
          secretName: api-gateway-tls
      - name: ca-certs
        secret:
          secretName: internal-ca-key-pair
          items:
          - key: ca.crt
            path: ca.crt
```

### 8. Configure Database TLS Connections

`services/shared/database/connection.py`:

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import ssl
from typing import Optional


def create_postgres_ssl_context(
    ca_file: Optional[str] = None,
    cert_file: Optional[str] = None,
    key_file: Optional[str] = None,
    verify: bool = True,
) -> ssl.SSLContext:
    """Create SSL context for PostgreSQL connection."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    
    if verify:
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = True
        if ca_file:
            context.load_verify_locations(ca_file)
        else:
            context.load_default_certs()
    else:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    
    if cert_file and key_file:
        context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    
    return context


def get_database_url(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    ssl_mode: str = "require",
) -> str:
    """Build database URL with SSL parameters."""
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}?ssl={ssl_mode}"


async def create_engine_with_ssl(
    database_url: str,
    ca_file: Optional[str] = None,
    cert_file: Optional[str] = None,
    key_file: Optional[str] = None,
):
    """Create async engine with SSL configuration."""
    ssl_context = create_postgres_ssl_context(
        ca_file=ca_file,
        cert_file=cert_file,
        key_file=key_file,
    )
    
    engine = create_async_engine(
        database_url,
        connect_args={
            "ssl": ssl_context,
        },
        pool_size=20,
        max_overflow=10,
    )
    
    return engine
```

### 9. Configure Redis TLS

`services/shared/cache/redis_client.py`:

```python
import redis.asyncio as redis
import ssl
from typing import Optional


def create_redis_ssl_context(
    ca_file: Optional[str] = None,
    cert_file: Optional[str] = None,
    key_file: Optional[str] = None,
) -> ssl.SSLContext:
    """Create SSL context for Redis connection."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    
    if ca_file:
        context.load_verify_locations(ca_file)
    else:
        context.load_default_certs()
    
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    
    if cert_file and key_file:
        context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    
    return context


async def create_redis_client(
    host: str,
    port: int = 6379,
    password: Optional[str] = None,
    ssl_enabled: bool = True,
    ca_file: Optional[str] = None,
    cert_file: Optional[str] = None,
    key_file: Optional[str] = None,
) -> redis.Redis:
    """Create Redis client with optional TLS."""
    ssl_context = None
    if ssl_enabled:
        ssl_context = create_redis_ssl_context(
            ca_file=ca_file,
            cert_file=cert_file,
            key_file=key_file,
        )
    
    client = redis.Redis(
        host=host,
        port=port,
        password=password,
        ssl=ssl_context,
        decode_responses=True,
    )
    
    return client
```

### 10. TLS Health Check Endpoint

`services/api-gateway/routers/health.py`:

```python
from fastapi import APIRouter, Request
from typing import Dict, Any
import ssl

router = APIRouter(tags=["health"])


@router.get("/health/tls")
async def tls_health(request: Request) -> Dict[str, Any]:
    """Check TLS configuration status."""
    result = {
        "tls_enabled": False,
        "protocol": None,
        "cipher": None,
        "client_cert": None,
    }
    
    # Check if connection is TLS
    if hasattr(request, "scope") and "transport" in request.scope:
        transport = request.scope["transport"]
        if hasattr(transport, "get_extra_info"):
            ssl_object = transport.get_extra_info("ssl_object")
            if ssl_object:
                result["tls_enabled"] = True
                result["protocol"] = ssl_object.version()
                result["cipher"] = ssl_object.cipher()
                
                # Check client certificate (mTLS)
                peer_cert = ssl_object.getpeercert()
                if peer_cert:
                    result["client_cert"] = {
                        "subject": dict(x[0] for x in peer_cert.get("subject", [])),
                        "issuer": dict(x[0] for x in peer_cert.get("issuer", [])),
                        "not_before": peer_cert.get("notBefore"),
                        "not_after": peer_cert.get("notAfter"),
                    }
    
    return result
```

### 11. Create Tests

`tests/security/test_tls.py`:

```python
import pytest
import ssl
import httpx
from pathlib import Path


class TestTLSConfiguration:
    def test_server_ssl_context_creation(self):
        from shared.security.tls.config import TLSSettings, create_server_ssl_context
        
        # Without TLS enabled
        settings = TLSSettings(tls_enabled=False)
        context = create_server_ssl_context(settings)
        assert context is None
    
    def test_client_ssl_context_creation(self):
        from shared.security.tls.config import TLSSettings, create_client_ssl_context
        
        settings = TLSSettings(client_tls_verify=True)
        context = create_client_ssl_context(settings)
        
        assert context is not None
        assert context.minimum_version == ssl.TLSVersion.TLSv1_3
        assert context.verify_mode == ssl.CERT_REQUIRED
    
    def test_postgres_ssl_context(self):
        from shared.database.connection import create_postgres_ssl_context
        
        context = create_postgres_ssl_context(verify=True)
        
        assert context is not None
        assert context.verify_mode == ssl.CERT_REQUIRED
    
    def test_redis_ssl_context(self):
        from shared.cache.redis_client import create_redis_ssl_context
        
        context = create_redis_ssl_context()
        
        assert context is not None
        assert context.minimum_version == ssl.TLSVersion.TLSv1_2


@pytest.mark.integration
class TestTLSIntegration:
    """Integration tests requiring running services."""
    
    @pytest.mark.asyncio
    async def test_api_https_connection(self):
        """Test HTTPS connection to API."""
        async with httpx.AsyncClient(verify=True) as client:
            response = await client.get("https://api.rag-pipeline.example.com/health")
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_tls_version(self):
        """Verify TLS 1.3 is used."""
        async with httpx.AsyncClient(verify=True) as client:
            response = await client.get("https://api.rag-pipeline.example.com/health/tls")
            data = response.json()
            assert data["tls_enabled"] is True
            assert "TLSv1.3" in data["protocol"]
```

## Acceptance Criteria

- [ ] TLS 1.3 enforced for all external API endpoints
- [ ] Valid certificates from Let's Encrypt for external domains
- [ ] cert-manager configured for automatic certificate renewal
- [ ] Internal CA created for service certificates
- [ ] mTLS configured between services (optional)
- [ ] Database connections use TLS
- [ ] Redis connections use TLS
- [ ] No plaintext transmission of sensitive data
- [ ] HSTS headers configured on ingress
- [ ] TLS health check endpoint available

## Verification Commands

```bash
# Check certificate issuance
kubectl get certificates -n rag-pipeline
kubectl describe certificate rag-api-tls -n rag-pipeline

# Test TLS connection
openssl s_client -connect api.rag-pipeline.example.com:443 -tls1_3

# Verify TLS version and cipher
curl -v https://api.rag-pipeline.example.com/health 2>&1 | grep -i "ssl\|tls"

# Check certificate details
echo | openssl s_client -connect api.rag-pipeline.example.com:443 2>/dev/null | \
  openssl x509 -noout -text

# Test internal mTLS (from within cluster)
kubectl exec -it deploy/api-gateway -n rag-pipeline -- \
  curl --cacert /ca/ca.crt \
       --cert /certs/tls.crt \
       --key /certs/tls.key \
       https://ingestion-service.rag-pipeline.svc:8443/health

# Run TLS tests
pytest tests/security/test_tls.py -v
```

## Environment Variables

```bash
# Server TLS
TLS_ENABLED=true
TLS_CERT_FILE=/certs/tls.crt
TLS_KEY_FILE=/certs/tls.key

# mTLS
MTLS_ENABLED=true
MTLS_CA_FILE=/ca/ca.crt
MTLS_VERIFY_CLIENT=true

# Client TLS
CLIENT_TLS_VERIFY=true
CLIENT_CA_BUNDLE=/ca/ca.crt
CLIENT_CERT_FILE=/certs/tls.crt
CLIENT_KEY_FILE=/certs/tls.key

# Database SSL
DATABASE_SSL_MODE=require
DATABASE_CA_FILE=/ca/ca.crt
```

## Files to Create

1. `infrastructure/k8s/cert-manager/cert-manager.yaml`
2. `infrastructure/k8s/certificates/cluster-issuer.yaml`
3. `infrastructure/k8s/certificates/internal-ca.yaml`
4. `infrastructure/k8s/certificates/service-certs.yaml`
5. `infrastructure/k8s/ingress/ingress-tls.yaml`
6. `services/shared/security/tls/__init__.py`
7. `services/shared/security/tls/config.py`
8. `services/api-gateway/routers/health.py`
9. `tests/security/test_tls.py`

## Security Considerations

- **TLS 1.3 only** - Disable older TLS versions
- **Strong ciphers** - Use only recommended cipher suites
- **Certificate pinning** - Consider for high-security deployments
- **Private key protection** - Never expose private keys in logs or code
- **Regular rotation** - Certificates should auto-renew before expiry
- **Monitor expiration** - Alert on certificates nearing expiration
