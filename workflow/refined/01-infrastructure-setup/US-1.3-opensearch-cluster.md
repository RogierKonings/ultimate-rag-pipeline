# US-1.3: OpenSearch Cluster

> **Epic:** Infrastructure Setup  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** None

## Objective

Deploy OpenSearch cluster for BM25 keyword search with custom analyzers for domain-specific terms.

## Architecture Reference

- **Technology:** OpenSearch (per `docs/architecture.md` - Keyword Search)
- **Port:** 9200 (HTTP), 9300 (Transport)
- **Purpose:** BM25 full-text search, rich analyzers, production-ready

## Implementation Tasks

### 1. Create Docker Compose Configuration

Add to `docker-compose.yml`:

```yaml
opensearch:
  image: opensearchproject/opensearch:2.11.1
  container_name: rag-opensearch
  ports:
    - "9200:9200"
    - "9600:9600"
  environment:
    - cluster.name=rag-cluster
    - node.name=opensearch-node1
    - discovery.type=single-node
    - bootstrap.memory_lock=true
    - "OPENSEARCH_JAVA_OPTS=-Xms1g -Xmx1g"
    - DISABLE_INSTALL_DEMO_CONFIG=true
    - DISABLE_SECURITY_PLUGIN=true  # Enable in production
  ulimits:
    memlock:
      soft: -1
      hard: -1
    nofile:
      soft: 65536
      hard: 65536
  volumes:
    - opensearch_data:/usr/share/opensearch/data
  healthcheck:
    test: ["CMD-SHELL", "curl -s http://localhost:9200/_cluster/health | grep -q 'green\\|yellow'"]
    interval: 10s
    timeout: 5s
    retries: 5

opensearch-dashboards:
  image: opensearchproject/opensearch-dashboards:2.11.1
  container_name: rag-opensearch-dashboards
  ports:
    - "5601:5601"
  environment:
    - OPENSEARCH_HOSTS=["http://opensearch:9200"]
    - DISABLE_SECURITY_DASHBOARDS_PLUGIN=true
  depends_on:
    - opensearch
```

### 2. Create Kubernetes StatefulSet (3-node cluster)

Create `k8s/opensearch/statefulset.yaml`:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: opensearch
  namespace: rag-pipeline
spec:
  serviceName: opensearch
  replicas: 3
  selector:
    matchLabels:
      app: opensearch
  template:
    metadata:
      labels:
        app: opensearch
    spec:
      initContainers:
      - name: sysctl
        image: busybox
        command: ["sysctl", "-w", "vm.max_map_count=262144"]
        securityContext:
          privileged: true
      containers:
      - name: opensearch
        image: opensearchproject/opensearch:2.11.1
        ports:
        - containerPort: 9200
          name: http
        - containerPort: 9300
          name: transport
        env:
        - name: cluster.name
          value: rag-cluster
        - name: node.name
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: discovery.seed_hosts
          value: "opensearch-0.opensearch,opensearch-1.opensearch,opensearch-2.opensearch"
        - name: cluster.initial_cluster_manager_nodes
          value: "opensearch-0,opensearch-1,opensearch-2"
        - name: OPENSEARCH_JAVA_OPTS
          value: "-Xms2g -Xmx2g"
        resources:
          requests:
            memory: "4Gi"
            cpu: "1000m"
          limits:
            memory: "8Gi"
            cpu: "2000m"
        volumeMounts:
        - name: opensearch-storage
          mountPath: /usr/share/opensearch/data
  volumeClaimTemplates:
  - metadata:
      name: opensearch-storage
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 100Gi
```

### 3. Create Index Template

Create `scripts/init-opensearch-index.py`:

```python
from opensearchpy import OpenSearch
import os

OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
INDEX_NAME = "documents"

client = OpenSearch(
    hosts=[OPENSEARCH_URL],
    http_compress=True,
    timeout=30,
)

# Index template with custom analyzers
INDEX_TEMPLATE = {
    "settings": {
        "number_of_shards": 3,
        "number_of_replicas": 1,
        "analysis": {
            "analyzer": {
                "default": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "english_stemmer", "english_stop"]
                },
                "keyword_analyzer": {
                    "type": "custom",
                    "tokenizer": "keyword",
                    "filter": ["lowercase"]
                }
            },
            "filter": {
                "english_stemmer": {
                    "type": "stemmer",
                    "language": "english"
                },
                "english_stop": {
                    "type": "stop",
                    "stopwords": "_english_"
                }
            }
        }
    },
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "document_id": {"type": "keyword"},
            "content": {
                "type": "text",
                "analyzer": "default",
                "search_analyzer": "default"
            },
            "title": {
                "type": "text",
                "analyzer": "default",
                "fields": {
                    "keyword": {"type": "keyword"}
                }
            },
            "source_type": {"type": "keyword"},
            "tenant_id": {"type": "keyword"},
            "visibility": {"type": "keyword"},
            "allowed_groups": {"type": "keyword"},
            "metadata": {"type": "object", "enabled": True},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"}
        }
    }
}

def init_index():
    if client.indices.exists(INDEX_NAME):
        print(f"Index {INDEX_NAME} already exists")
        return
    
    client.indices.create(index=INDEX_NAME, body=INDEX_TEMPLATE)
    print(f"Index {INDEX_NAME} created successfully")

if __name__ == "__main__":
    init_index()
```

### 4. Create OpenSearch Client Wrapper

Create `services/shared/search/opensearch_client.py`:

```python
from opensearchpy import OpenSearch, helpers
from typing import List, Dict, Any, Optional
import os

class OpenSearchClient:
    def __init__(self):
        self.client = OpenSearch(
            hosts=[os.getenv("OPENSEARCH_URL", "http://localhost:9200")],
            http_compress=True,
            timeout=30,
        )
        self.index_name = os.getenv("OPENSEARCH_INDEX", "documents")
    
    async def bulk_index(self, documents: List[Dict[str, Any]]) -> Dict:
        """Bulk index documents."""
        actions = [
            {
                "_index": self.index_name,
                "_id": doc["chunk_id"],
                "_source": doc,
            }
            for doc in documents
        ]
        
        success, errors = helpers.bulk(
            self.client,
            actions,
            raise_on_error=False,
        )
        
        return {"success": success, "errors": errors}
    
    async def search(
        self,
        query: str,
        top_k: int = 10,
        filter_conditions: Optional[Dict] = None,
    ) -> List[Dict]:
        """BM25 keyword search."""
        must = [
            {
                "multi_match": {
                    "query": query,
                    "fields": ["content^1.0", "title^2.0"],
                    "type": "best_fields",
                }
            }
        ]
        
        filter_clauses = []
        if filter_conditions:
            for key, value in filter_conditions.items():
                filter_clauses.append({"term": {key: value}})
        
        body = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": must,
                    "filter": filter_clauses,
                }
            },
            "_source": True,
        }
        
        response = self.client.search(index=self.index_name, body=body)
        
        return [
            {
                "id": hit["_id"],
                "score": hit["_score"],
                "source": hit["_source"],
            }
            for hit in response["hits"]["hits"]
        ]
    
    async def delete_by_document_id(self, document_id: str) -> Dict:
        """Delete all chunks for a document."""
        body = {
            "query": {
                "term": {"document_id": document_id}
            }
        }
        return self.client.delete_by_query(index=self.index_name, body=body)
    
    def health_check(self) -> bool:
        """Check OpenSearch connectivity."""
        try:
            health = self.client.cluster.health()
            return health["status"] in ["green", "yellow"]
        except Exception:
            return False
```

## Acceptance Criteria

- [ ] OpenSearch deployed with single node (dev) or 3-node cluster (prod)
- [ ] Index `documents` created with custom analyzers
- [ ] English stemmer and stopwords configured
- [ ] Field mappings for content, title, metadata, ACL fields
- [ ] Security plugin enabled in production (TLS, authentication)
- [ ] Python client wrapper created with bulk_index/search methods
- [ ] OpenSearch Dashboards accessible for debugging

## Verification Commands

```bash
# Check cluster health
curl http://localhost:9200/_cluster/health?pretty

# List indices
curl http://localhost:9200/_cat/indices?v

# Get index mapping
curl http://localhost:9200/documents/_mapping?pretty

# Test search
curl -X POST "http://localhost:9200/documents/_search" \
  -H "Content-Type: application/json" \
  -d '{"query": {"match": {"content": "test"}}}'
```

## Files to Create

1. `docker-compose.yml` (opensearch service entries)
2. `k8s/opensearch/statefulset.yaml`
3. `k8s/opensearch/service.yaml`
4. `k8s/opensearch/pvc.yaml`
5. `scripts/init-opensearch-index.py`
6. `services/shared/search/__init__.py`
7. `services/shared/search/opensearch_client.py`
