# US-1A.2: Redis TLS Encryption

> **Epic:** Infrastructure Gaps & Hardening  
> **Priority:** Critical  
> **Estimated Effort:** 0.5 day  
> **Dependencies:** US-1A.1 (Redis Sentinel HA)  
> **Status:** ⏳ Deferred to Production Deployment

## User Story

**As a** security engineer  
**I want** all Redis traffic encrypted with TLS  
**So that** sensitive cache data is protected in transit and compliant with security requirements

## Problem Statement

### Current State

- All Redis connections use plaintext TCP on port 6379
- Sentinel communication is unencrypted on port 26379
- Cache data (including potential PII) transmitted in clear text
- Non-compliant with security requirements for data in transit

### Impact

- Potential data exposure via network sniffing
- Non-compliance with SOC 2, HIPAA, PCI-DSS requirements
- Security audit findings
- Risk of credential interception

## Architecture Reference

From `docs/architecture.md`:

> **Security:** TLS 1.3 for all data in transit

All inter-service communication must be encrypted, including cache layer.

## Solution Options

### Option 1: Native Redis TLS (Recommended for Production)

Configure Redis with built-in TLS support.

**Pros:**
- Native support, no additional components
- Full TLS termination at Redis
- Supports mTLS for client authentication

**Cons:**
- Requires certificate management
- Slightly higher CPU overhead

### Option 2: Stunnel Sidecar

Use stunnel as a TLS termination proxy.

**Pros:**
- No Redis configuration changes
- Works with any Redis version

**Cons:**
- Additional sidecar container
- More complex deployment
- Double network hop

### Option 3: Managed Redis (ElastiCache/Memorystore)

Use cloud-managed Redis with built-in TLS.

**Pros:**
- No certificate management
- Built-in HA and encryption
- Reduced operational burden

**Cons:**
- Higher cost
- Vendor lock-in
- Less control over configuration

## Implementation Tasks (Option 1: Native TLS)

### 1. Create Certificate Resources

Using cert-manager for automatic certificate provisioning:

```yaml
# k8s/redis/certificate.yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: redis-tls
  namespace: rag-pipeline
spec:
  secretName: redis-tls-secret
  duration: 8760h  # 1 year
  renewBefore: 720h  # 30 days
  subject:
    organizations:
    - rag-pipeline
  isCA: false
  privateKey:
    algorithm: ECDSA
    size: 256
  usages:
  - server auth
  - client auth
  dnsNames:
  - redis
  - redis.rag-pipeline.svc
  - redis.rag-pipeline.svc.cluster.local
  - redis-headless
  - redis-headless.rag-pipeline.svc
  - redis-headless.rag-pipeline.svc.cluster.local
  - "*.redis-headless.rag-pipeline.svc.cluster.local"
  issuerRef:
    name: rag-ca-issuer
    kind: ClusterIssuer
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: redis-sentinel-tls
  namespace: rag-pipeline
spec:
  secretName: redis-sentinel-tls-secret
  duration: 8760h
  renewBefore: 720h
  subject:
    organizations:
    - rag-pipeline
  isCA: false
  privateKey:
    algorithm: ECDSA
    size: 256
  usages:
  - server auth
  - client auth
  dnsNames:
  - redis-sentinel
  - redis-sentinel.rag-pipeline.svc
  - redis-sentinel.rag-pipeline.svc.cluster.local
  - redis-sentinel-headless
  - "*.redis-sentinel-headless.rag-pipeline.svc.cluster.local"
  issuerRef:
    name: rag-ca-issuer
    kind: ClusterIssuer
```

### 2. Update Redis ConfigMap for TLS

Update `k8s/redis/configmap.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-config
  namespace: rag-pipeline
data:
  redis.conf: |
    # Require password
    requirepass ${REDIS_PASSWORD}
    masterauth ${REDIS_PASSWORD}
    
    # Disable non-TLS port (production)
    port 0
    
    # Enable TLS
    tls-port 6379
    tls-cert-file /tls/tls.crt
    tls-key-file /tls/tls.key
    tls-ca-cert-file /tls/ca.crt
    
    # TLS settings
    tls-auth-clients optional
    tls-protocols "TLSv1.2 TLSv1.3"
    tls-ciphers "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384"
    tls-ciphersuites "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256"
    tls-prefer-server-ciphers yes
    
    # Replication with TLS
    tls-replication yes
    
    # Memory management
    maxmemory 1gb
    maxmemory-policy allkeys-lru
    
    # Persistence
    appendonly yes
    appendfsync everysec
```

### 3. Update Redis StatefulSet with TLS Volumes

```yaml
# k8s/redis/statefulset.yaml (TLS additions)
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
  namespace: rag-pipeline
spec:
  template:
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        command:
        - redis-server
        - /data/redis.conf
        ports:
        - containerPort: 6379
          name: redis-tls
        volumeMounts:
        - name: data
          mountPath: /data
        - name: config
          mountPath: /etc/redis
        - name: tls
          mountPath: /tls
          readOnly: true
      
      volumes:
      - name: config
        configMap:
          name: redis-config
      - name: tls
        secret:
          secretName: redis-tls-secret
```

### 4. Update Sentinel Configuration for TLS

```yaml
# k8s/redis/sentinel-configmap.yaml (TLS additions)
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-sentinel-config
  namespace: rag-pipeline
data:
  sentinel.conf: |
    port 0
    tls-port 26379
    
    tls-cert-file /tls/tls.crt
    tls-key-file /tls/tls.key
    tls-ca-cert-file /tls/ca.crt
    tls-replication yes
    tls-auth-clients optional
    
    sentinel monitor mymaster redis-0.redis-headless.rag-pipeline.svc.cluster.local 6379 2
    sentinel auth-pass mymaster ${REDIS_PASSWORD}
    
    # Enable TLS for master/replica connections
    sentinel tls-replication yes
    
    sentinel down-after-milliseconds mymaster 5000
    sentinel failover-timeout mymaster 60000
    sentinel parallel-syncs mymaster 1
```

### 5. Update Python Client for TLS

```python
# services/shared/cache/redis_client.py
import ssl
from redis.sentinel import Sentinel
from redis import Redis
import os

def get_ssl_context() -> ssl.SSLContext:
    """Create SSL context for Redis TLS connections."""
    ssl_context = ssl.create_default_context()
    
    ca_cert = os.getenv("REDIS_TLS_CA_CERT")
    client_cert = os.getenv("REDIS_TLS_CERT")
    client_key = os.getenv("REDIS_TLS_KEY")
    
    if ca_cert:
        ssl_context.load_verify_locations(ca_cert)
    
    if client_cert and client_key:
        ssl_context.load_cert_chain(client_cert, client_key)
    
    ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
    ssl_context.check_hostname = True
    ssl_context.verify_mode = ssl.CERT_REQUIRED
    
    return ssl_context


def get_redis_client() -> Redis:
    """Get Redis client with TLS and Sentinel support."""
    
    use_tls = os.getenv("REDIS_TLS_ENABLED", "false").lower() == "true"
    use_sentinel = os.getenv("REDIS_USE_SENTINEL", "false").lower() == "true"
    password = os.getenv("REDIS_PASSWORD")
    
    ssl_context = get_ssl_context() if use_tls else None
    
    if use_sentinel:
        sentinel_hosts = os.getenv(
            "REDIS_SENTINEL_HOSTS",
            "redis-sentinel.rag-pipeline.svc.cluster.local:26379"
        )
        sentinel_master = os.getenv("REDIS_SENTINEL_MASTER", "mymaster")
        
        sentinels = []
        for host in sentinel_hosts.split(","):
            host, port = host.rsplit(":", 1)
            sentinels.append((host.strip(), int(port)))
        
        sentinel = Sentinel(
            sentinels,
            socket_timeout=0.5,
            password=password,
            ssl=use_tls,
            ssl_context=ssl_context,
            sentinel_kwargs={
                "password": password,
                "ssl": use_tls,
                "ssl_context": ssl_context
            }
        )
        
        return sentinel.master_for(
            sentinel_master,
            socket_timeout=0.5,
            password=password,
            ssl=use_tls,
            ssl_context=ssl_context
        )
    else:
        return Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            password=password,
            ssl=use_tls,
            ssl_context=ssl_context,
            decode_responses=True
        )
```

### 6. Environment Variables

Add to `.env.example`:

```bash
# Redis TLS Configuration
REDIS_TLS_ENABLED=false  # Set to true in production
REDIS_TLS_CA_CERT=/tls/ca.crt
REDIS_TLS_CERT=/tls/tls.crt
REDIS_TLS_KEY=/tls/tls.key
```

## Alternative: Stunnel Sidecar

For environments where native TLS is not feasible:

```yaml
# k8s/redis/stunnel-sidecar.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
spec:
  template:
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        ports:
        - containerPort: 6379
          name: redis-plain
        # Redis listens on plaintext, stunnel handles TLS
      
      - name: stunnel
        image: dweomer/stunnel:latest
        ports:
        - containerPort: 6380
          name: redis-tls
        volumeMounts:
        - name: stunnel-config
          mountPath: /etc/stunnel
        - name: tls
          mountPath: /tls
          readOnly: true
      
      volumes:
      - name: stunnel-config
        configMap:
          name: redis-stunnel-config
      - name: tls
        secret:
          secretName: redis-tls-secret
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-stunnel-config
  namespace: rag-pipeline
data:
  stunnel.conf: |
    foreground = yes
    
    [redis]
    accept = 6380
    connect = 127.0.0.1:6379
    cert = /tls/tls.crt
    key = /tls/tls.key
    CAfile = /tls/ca.crt
    verify = 2
```

## Alternative: Managed Redis

### AWS ElastiCache

```hcl
# terraform/elasticache.tf
resource "aws_elasticache_replication_group" "redis" {
  replication_group_id          = "rag-pipeline-redis"
  description                   = "Redis cluster for RAG pipeline"
  
  node_type                     = "cache.r6g.large"
  num_cache_clusters            = 3
  
  automatic_failover_enabled    = true
  multi_az_enabled              = true
  
  at_rest_encryption_enabled    = true
  transit_encryption_enabled    = true
  auth_token                    = var.redis_auth_token
  
  engine                        = "redis"
  engine_version                = "7.0"
  
  subnet_group_name             = aws_elasticache_subnet_group.redis.name
  security_group_ids            = [aws_security_group.redis.id]
  
  tags = {
    Environment = "production"
    Project     = "rag-pipeline"
  }
}
```

### GCP Memorystore

```hcl
# terraform/memorystore.tf
resource "google_redis_instance" "redis" {
  name           = "rag-pipeline-redis"
  tier           = "STANDARD_HA"
  memory_size_gb = 5
  
  region                  = var.region
  authorized_network      = google_compute_network.vpc.id
  
  transit_encryption_mode = "SERVER_AUTHENTICATION"
  auth_enabled           = true
  
  redis_version          = "REDIS_7_0"
  display_name           = "RAG Pipeline Redis"
  
  labels = {
    environment = "production"
    project     = "rag-pipeline"
  }
}
```

## Acceptance Criteria

- [ ] All Redis connections use TLS 1.2+
- [ ] Sentinel connections encrypted
- [ ] Replication traffic encrypted
- [ ] Application clients configured for TLS
- [ ] Certificate rotation automated via cert-manager
- [ ] Non-TLS port disabled in production
- [ ] Health checks work over TLS
- [ ] Connection strings use `rediss://` scheme

## Verification Commands

```bash
# Verify TLS is enabled
kubectl exec -it redis-0 -n rag-pipeline -- \
  redis-cli --tls --cert /tls/tls.crt --key /tls/tls.key --cacert /tls/ca.crt \
  -a $REDIS_PASSWORD INFO server | grep tls

# Test TLS connection
openssl s_client -connect redis.rag-pipeline.svc.cluster.local:6379 \
  -servername redis.rag-pipeline.svc.cluster.local

# Verify certificate
kubectl exec -it redis-0 -n rag-pipeline -- \
  openssl x509 -in /tls/tls.crt -text -noout

# Test from application
kubectl exec -it deployment/retrieval-service -n rag-pipeline -- \
  python -c "
from cache.redis_client import get_redis_client
r = get_redis_client()
print('TLS connection successful:', r.ping())
"
```

## Deployment Notes

### Prerequisites

1. **cert-manager** must be installed in the cluster
2. **ClusterIssuer** `rag-ca-issuer` must be configured
3. Applications must have TLS certificates mounted

### Rollout Strategy

1. Deploy certificates first (allow propagation)
2. Update Redis/Sentinel configs
3. Rolling restart Redis StatefulSet
4. Update application connection strings
5. Verify connectivity
6. Disable plaintext port

## Files to Create

| File | Description |
|------|-------------|
| `k8s/redis/certificate.yaml` | TLS certificates via cert-manager |
| `k8s/redis/configmap.yaml` | Updated Redis config with TLS |
| `k8s/redis/sentinel-configmap.yaml` | Updated Sentinel config with TLS |
| `services/shared/cache/redis_client.py` | TLS-enabled client |

## Related Stories

- **US-1A.1:** Redis Sentinel HA (prerequisite)
- **US-1.9:** Ingress, TLS, Network Policies (related)
