# US-1.2: Qdrant Vector Database

> **Epic:** Infrastructure Setup  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** None

## Objective

Deploy Qdrant cluster for storing and querying document embeddings with high-performance HNSW indexing.

## Architecture Reference

- **Technology:** Qdrant (per `docs/architecture.md` - Vector Database choice)
- **Port:** 6333 (HTTP), 6334 (gRPC)
- **Purpose:** High-performance HNSW, excellent filtering, hybrid search

## Implementation Tasks

### 1. Create Docker Compose Configuration

Add to `docker-compose.yml`:

```yaml
qdrant:
  image: qdrant/qdrant:v1.7.4
  container_name: rag-qdrant
  ports:
    - "6333:6333"
    - "6334:6334"
  volumes:
    - qdrant_data:/qdrant/storage
    - ./config/qdrant/config.yaml:/qdrant/config/config.yaml
  environment:
    QDRANT__SERVICE__GRPC_PORT: 6334
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:6333/health"]
    interval: 10s
    timeout: 5s
    retries: 5
```

### 2. Create Qdrant Configuration

Create `config/qdrant/config.yaml`:

```yaml
storage:
  storage_path: /qdrant/storage
  optimizers:
    default_segment_number: 2
    max_segment_size_kb: 200000
    memmap_threshold_kb: 50000
    indexing_threshold_kb: 20000
    flush_interval_sec: 5
  performance:
    max_search_threads: 0  # auto-detect

service:
  host: 0.0.0.0
  http_port: 6333
  grpc_port: 6334
  max_request_size_mb: 32
  enable_cors: true

cluster:
  enabled: false  # Enable for production HA
```

### 3. Create Kubernetes Deployment (HA Mode)

Create `k8s/qdrant/statefulset.yaml`:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: qdrant
  namespace: rag-pipeline
spec:
  serviceName: qdrant
  replicas: 3
  selector:
    matchLabels:
      app: qdrant
  template:
    metadata:
      labels:
        app: qdrant
    spec:
      containers:
      - name: qdrant
        image: qdrant/qdrant:v1.7.4
        ports:
        - containerPort: 6333
          name: http
        - containerPort: 6334
          name: grpc
        - containerPort: 6335
          name: p2p
        env:
        - name: QDRANT__CLUSTER__ENABLED
          value: "true"
        - name: QDRANT__CLUSTER__P2P__PORT
          value: "6335"
        resources:
          requests:
            memory: "2Gi"
            cpu: "500m"
          limits:
            memory: "8Gi"
            cpu: "2000m"
        volumeMounts:
        - name: qdrant-storage
          mountPath: /qdrant/storage
        livenessProbe:
          httpGet:
            path: /health
            port: 6333
          initialDelaySeconds: 30
          periodSeconds: 10
  volumeClaimTemplates:
  - metadata:
      name: qdrant-storage
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 100Gi
```

### 4. Create Collection Initialization Script

Create `scripts/init-qdrant-collections.py`:

```python
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    HnswConfigDiff,
    OptimizersConfigDiff,
    PayloadSchemaType,
)

QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "documents"
EMBEDDING_DIM = 1024  # BGE-large-en-v1.5 dimension

def init_collection():
    client = QdrantClient(url=QDRANT_URL)
    
    # Delete if exists (for dev)
    if client.collection_exists(COLLECTION_NAME):
        print(f"Collection {COLLECTION_NAME} already exists")
        return
    
    # Create collection with optimized HNSW settings
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=EMBEDDING_DIM,
            distance=Distance.COSINE,
            hnsw_config=HnswConfigDiff(
                m=16,                    # Number of edges per node
                ef_construct=100,        # Build-time accuracy
                full_scan_threshold=10000,
                max_indexing_threads=0,  # Auto-detect
            ),
        ),
        optimizers_config=OptimizersConfigDiff(
            memmap_threshold=20000,
            indexing_threshold=20000,
            flush_interval_sec=5,
        ),
        on_disk_payload=True,  # Large payloads stored on disk
    )
    
    # Create payload indexes for filtering
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="tenant_id",
        field_schema=PayloadSchemaType.KEYWORD,
    )
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="document_id",
        field_schema=PayloadSchemaType.KEYWORD,
    )
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="visibility",
        field_schema=PayloadSchemaType.KEYWORD,
    )
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="allowed_groups",
        field_schema=PayloadSchemaType.KEYWORD,
    )
    
    print(f"Collection {COLLECTION_NAME} created successfully")

if __name__ == "__main__":
    init_collection()
```

### 5. Create Qdrant Client Wrapper

Create `services/shared/vectorstore/qdrant_client.py`:

```python
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue
from typing import List, Dict, Any, Optional
import os

class QdrantVectorStore:
    def __init__(self):
        self.client = QdrantClient(
            url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            timeout=30,
        )
        self.collection_name = os.getenv("QDRANT_COLLECTION", "documents")
    
    async def upsert(
        self,
        points: List[Dict[str, Any]],
    ) -> None:
        """Upsert vectors with metadata."""
        qdrant_points = [
            PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p["payload"],
            )
            for p in points
        ]
        self.client.upsert(
            collection_name=self.collection_name,
            points=qdrant_points,
        )
    
    async def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        filter_conditions: Optional[Dict] = None,
    ) -> List[Dict]:
        """Search for similar vectors."""
        qdrant_filter = self._build_filter(filter_conditions) if filter_conditions else None
        
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        
        return [
            {
                "id": str(hit.id),
                "score": hit.score,
                "payload": hit.payload,
            }
            for hit in results
        ]
    
    def _build_filter(self, conditions: Dict) -> Filter:
        """Build Qdrant filter from conditions dict."""
        must = []
        for key, value in conditions.items():
            must.append(
                FieldCondition(key=key, match=MatchValue(value=value))
            )
        return Filter(must=must)
    
    def health_check(self) -> bool:
        """Check Qdrant connectivity."""
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False
```

## Acceptance Criteria

- [ ] Qdrant deployed with single node (dev) or 3 replicas (prod)
- [ ] Collection `documents` created with 1024-dimension vectors
- [ ] HNSW settings optimized (m=16, ef_construct=100)
- [ ] Disk encryption enabled via volume encryption
- [ ] Payload indexes created for `tenant_id`, `document_id`, `visibility`, `allowed_groups`
- [ ] Health check endpoint responds at `/health`
- [ ] Python client wrapper created with upsert/search methods

## Verification Commands

```bash
# Check Qdrant health
curl http://localhost:6333/health

# List collections
curl http://localhost:6333/collections

# Get collection info
curl http://localhost:6333/collections/documents

# Run init script
python scripts/init-qdrant-collections.py
```

## Files to Create

1. `docker-compose.yml` (qdrant service entry)
2. `config/qdrant/config.yaml`
3. `k8s/qdrant/statefulset.yaml`
4. `k8s/qdrant/service.yaml`
5. `k8s/qdrant/pvc.yaml`
6. `scripts/init-qdrant-collections.py`
7. `services/shared/vectorstore/__init__.py`
8. `services/shared/vectorstore/qdrant_client.py`
