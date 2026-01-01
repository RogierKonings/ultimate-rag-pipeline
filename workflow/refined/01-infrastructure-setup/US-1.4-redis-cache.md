# US-1.4: Redis Cache

> **Epic:** Infrastructure Setup  
> **Priority:** Critical  
> **Estimated Effort:** 1-2 days  
> **Dependencies:** None

## Objective

Deploy Redis with Sentinel for high availability caching of embeddings and query results.

## Architecture Reference

- **Technology:** Redis (per `docs/architecture.md` - Cache layer)
- **Port:** 6379
- **Purpose:** Query cache, embedding cache, Celery broker

## Implementation Tasks

### 1. Create Docker Compose Configuration

Add to `docker-compose.yml`:

```yaml
redis:
  image: redis:7-alpine
  container_name: rag-redis
  ports:
    - "6379:6379"
  command: >
    redis-server
    --appendonly yes
    --maxmemory 512mb
    --maxmemory-policy allkeys-lru
    --save 60 1000
    --requirepass ${REDIS_PASSWORD:-ragredis}
  volumes:
    - redis_data:/data
  healthcheck:
    test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD:-ragredis}", "ping"]
    interval: 10s
    timeout: 5s
    retries: 5
```

### 2. Create Kubernetes Deployment with Sentinel

Create `k8s/redis/statefulset.yaml`:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
  namespace: rag-pipeline
spec:
  serviceName: redis
  replicas: 3
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        ports:
        - containerPort: 6379
          name: redis
        command:
        - redis-server
        - /etc/redis/redis.conf
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "1Gi"
            cpu: "500m"
        volumeMounts:
        - name: redis-config
          mountPath: /etc/redis
        - name: redis-data
          mountPath: /data
      volumes:
      - name: redis-config
        configMap:
          name: redis-config
  volumeClaimTemplates:
  - metadata:
      name: redis-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

Create `k8s/redis/configmap.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-config
  namespace: rag-pipeline
data:
  redis.conf: |
    bind 0.0.0.0
    port 6379
    appendonly yes
    maxmemory 1gb
    maxmemory-policy allkeys-lru
    save 60 1000
    requirepass ${REDIS_PASSWORD}
    masterauth ${REDIS_PASSWORD}
    replica-announce-ip ${POD_IP}
```

### 3. Create Redis Client Wrapper

Create `services/shared/cache/redis_client.py`:

```python
import redis.asyncio as redis
from typing import Optional, Any
import json
import os
import hashlib

class RedisCache:
    def __init__(self):
        self.redis = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            password=os.getenv("REDIS_PASSWORD", "ragredis"),
            decode_responses=True,
        )
        self.default_ttl = int(os.getenv("REDIS_DEFAULT_TTL", 3600))
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        value = await self.redis.get(key)
        if value:
            return json.loads(value)
        return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> None:
        """Set value in cache with optional TTL."""
        await self.redis.set(
            key,
            json.dumps(value),
            ex=ttl or self.default_ttl,
        )
    
    async def delete(self, key: str) -> None:
        """Delete key from cache."""
        await self.redis.delete(key)
    
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        return await self.redis.exists(key) > 0
    
    @staticmethod
    def generate_key(prefix: str, *args) -> str:
        """Generate cache key from prefix and arguments."""
        content = ":".join(str(arg) for arg in args)
        hash_val = hashlib.md5(content.encode()).hexdigest()[:16]
        return f"{prefix}:{hash_val}"
    
    async def health_check(self) -> bool:
        """Check Redis connectivity."""
        try:
            await self.redis.ping()
            return True
        except Exception:
            return False
    
    async def close(self):
        """Close Redis connection."""
        await self.redis.close()
```

### 4. Create Embedding Cache

Create `services/shared/cache/embedding_cache.py`:

```python
from .redis_client import RedisCache
from typing import List, Optional
import numpy as np

class EmbeddingCache:
    """Cache for storing computed embeddings."""
    
    PREFIX = "emb"
    TTL = 86400 * 7  # 7 days
    
    def __init__(self, redis_cache: RedisCache):
        self.cache = redis_cache
    
    async def get_embedding(self, text_hash: str) -> Optional[List[float]]:
        """Get cached embedding for text."""
        key = f"{self.PREFIX}:{text_hash}"
        return await self.cache.get(key)
    
    async def set_embedding(
        self,
        text_hash: str,
        embedding: List[float],
    ) -> None:
        """Cache embedding for text."""
        key = f"{self.PREFIX}:{text_hash}"
        await self.cache.set(key, embedding, ttl=self.TTL)
    
    async def get_embeddings_batch(
        self,
        text_hashes: List[str],
    ) -> dict[str, Optional[List[float]]]:
        """Get multiple cached embeddings."""
        keys = [f"{self.PREFIX}:{h}" for h in text_hashes]
        # Use pipeline for efficiency
        async with self.cache.redis.pipeline() as pipe:
            for key in keys:
                pipe.get(key)
            results = await pipe.execute()
        
        return {
            text_hashes[i]: json.loads(r) if r else None
            for i, r in enumerate(results)
        }
```

### 5. Create Query Cache

Create `services/shared/cache/query_cache.py`:

```python
from .redis_client import RedisCache
from typing import Optional, Dict, Any
import hashlib

class QueryCache:
    """Cache for storing query results."""
    
    PREFIX = "query"
    TTL = 300  # 5 minutes
    
    def __init__(self, redis_cache: RedisCache):
        self.cache = redis_cache
    
    def _generate_key(
        self,
        query: str,
        tenant_id: str,
        top_k: int,
    ) -> str:
        """Generate unique key for query."""
        content = f"{query}:{tenant_id}:{top_k}"
        hash_val = hashlib.sha256(content.encode()).hexdigest()[:32]
        return f"{self.PREFIX}:{hash_val}"
    
    async def get_results(
        self,
        query: str,
        tenant_id: str,
        top_k: int = 10,
    ) -> Optional[Dict[str, Any]]:
        """Get cached query results."""
        key = self._generate_key(query, tenant_id, top_k)
        return await self.cache.get(key)
    
    async def set_results(
        self,
        query: str,
        tenant_id: str,
        results: Dict[str, Any],
        top_k: int = 10,
    ) -> None:
        """Cache query results."""
        key = self._generate_key(query, tenant_id, top_k)
        await self.cache.set(key, results, ttl=self.TTL)
    
    async def invalidate_tenant(self, tenant_id: str) -> int:
        """Invalidate all cached queries for a tenant."""
        pattern = f"{self.PREFIX}:*"
        # Note: This is a simplified version
        # In production, use tenant-specific key patterns
        return 0
```

## Acceptance Criteria

- [ ] Redis deployed with persistence enabled (AOF)
- [ ] Memory limit set (512MB dev, 1GB+ prod)
- [ ] Eviction policy set to `allkeys-lru`
- [ ] Password authentication configured
- [ ] TLS enabled in production
- [ ] Redis Sentinel configured for HA (production)
- [ ] Python client wrapper with async support
- [ ] Embedding cache with 7-day TTL
- [ ] Query cache with 5-minute TTL

## Verification Commands

```bash
# Test Redis connection
docker-compose exec redis redis-cli -a ragredis ping

# Check memory usage
docker-compose exec redis redis-cli -a ragredis info memory

# Set/get test
docker-compose exec redis redis-cli -a ragredis set test "hello"
docker-compose exec redis redis-cli -a ragredis get test

# Check persistence
docker-compose exec redis redis-cli -a ragredis bgsave
```

## Files to Create

1. `docker-compose.yml` (redis service entry)
2. `k8s/redis/statefulset.yaml`
3. `k8s/redis/service.yaml`
4. `k8s/redis/configmap.yaml`
5. `services/shared/cache/__init__.py`
6. `services/shared/cache/redis_client.py`
7. `services/shared/cache/embedding_cache.py`
8. `services/shared/cache/query_cache.py`
