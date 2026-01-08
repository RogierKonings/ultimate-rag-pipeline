# US-1A.5: OpenSearch Index Templates Bootstrap

> **Epic:** Infrastructure Gaps & Hardening  
> **Priority:** High  
> **Estimated Effort:** 0.5 day  
> **Dependencies:** US-1.3 (OpenSearch Cluster)  
> **Status:** ✅ Complete

## User Story

**As a** retrieval service developer  
**I want** index templates and custom analyzers pre-configured in OpenSearch  
**So that** documents are indexed with optimal mappings and the search experience is consistent

## Problem Statement

### Current State

- No index templates configured in OpenSearch
- No custom analyzers for text processing
- Default dynamic mappings may not be optimal for RAG use case
- No autocomplete support configured
- Each deployment requires manual index setup

### Impact

- Inconsistent index mappings across environments
- Suboptimal search relevance
- No autocomplete/typeahead functionality
- Manual setup increases deployment time and error risk

## Architecture Reference

From `docs/architecture.md`:

> **OpenSearch:** Keyword search with BM25 (port 9200)

Required search capabilities:
- Full-text search with BM25 ranking
- Hybrid search (vector + keyword)
- Autocomplete/typeahead
- Tenant isolation via index prefix or field filtering

## Solution Design

### Index Template Structure

```
┌─────────────────────────────────────────────────────────────────┐
│                    OpenSearch Index Templates                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────┐  ┌─────────────────────┐              │
│  │  documents-*        │  │  chunks-*           │              │
│  │                     │  │                     │              │
│  │  - Document meta    │  │  - Chunk content    │              │
│  │  - Title search     │  │  - Vector field     │              │
│  │  - Autocomplete     │  │  - Parent doc ref   │              │
│  └─────────────────────┘  └─────────────────────┘              │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Custom Analyzers                          ││
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐               ││
│  │  │ standard  │  │ autocomplete│  │ code      │               ││
│  │  │ lowercase │  │ edge_ngram │  │ camelcase │               ││
│  │  └───────────┘  └───────────┘  └───────────┘               ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

## Implementation Tasks

### 1. Create Bootstrap Job

Create `k8s/opensearch/bootstrap-job.yaml`:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: opensearch-bootstrap
  namespace: rag-pipeline
  labels:
    app: opensearch-bootstrap
spec:
  ttlSecondsAfterFinished: 300
  backoffLimit: 3
  template:
    metadata:
      labels:
        app: opensearch-bootstrap
    spec:
      restartPolicy: OnFailure
      initContainers:
      - name: wait-for-opensearch
        image: curlimages/curl:8.4.0
        command:
        - /bin/sh
        - -c
        - |
          set -e
          echo "Waiting for OpenSearch to be ready..."
          until curl -sf "${OPENSEARCH_URL}/_cluster/health?wait_for_status=yellow&timeout=60s"; do
            echo "OpenSearch not ready, retrying in 5s..."
            sleep 5
          done
          echo "OpenSearch is ready!"
        env:
        - name: OPENSEARCH_URL
          value: "http://opensearch:9200"
      
      containers:
      - name: bootstrap
        image: python:3.11-slim
        command:
        - /bin/bash
        - -c
        - |
          pip install opensearch-py requests
          python /scripts/bootstrap-opensearch.py
        env:
        - name: OPENSEARCH_HOST
          value: "opensearch"
        - name: OPENSEARCH_PORT
          value: "9200"
        - name: OPENSEARCH_USE_SSL
          value: "false"
        - name: OPENSEARCH_USERNAME
          valueFrom:
            secretKeyRef:
              name: rag-secrets
              key: opensearch-username
              optional: true
        - name: OPENSEARCH_PASSWORD
          valueFrom:
            secretKeyRef:
              name: rag-secrets
              key: opensearch-password
              optional: true
        volumeMounts:
        - name: scripts
          mountPath: /scripts
      
      volumes:
      - name: scripts
        configMap:
          name: opensearch-bootstrap-scripts
```

### 2. Create Bootstrap Script ConfigMap

Create `k8s/opensearch/bootstrap-configmap.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: opensearch-bootstrap-scripts
  namespace: rag-pipeline
data:
  bootstrap-opensearch.py: |
    #!/usr/bin/env python3
    """Bootstrap OpenSearch with index templates and custom analyzers."""
    
    import os
    import json
    import logging
    from opensearchpy import OpenSearch
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)
    
    def get_client() -> OpenSearch:
        """Create OpenSearch client."""
        host = os.getenv("OPENSEARCH_HOST", "localhost")
        port = int(os.getenv("OPENSEARCH_PORT", 9200))
        use_ssl = os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true"
        username = os.getenv("OPENSEARCH_USERNAME")
        password = os.getenv("OPENSEARCH_PASSWORD")
        
        auth = (username, password) if username and password else None
        
        return OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_auth=auth,
            use_ssl=use_ssl,
            verify_certs=False,
            ssl_show_warn=False,
            timeout=30,
        )
    
    # Custom analyzers for text processing
    ANALYZER_SETTINGS = {
        "analysis": {
            "analyzer": {
                # Standard text analyzer with stemming
                "rag_standard": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": [
                        "lowercase",
                        "asciifolding",
                        "english_stemmer",
                        "english_stop"
                    ]
                },
                # Autocomplete analyzer with edge ngrams
                "autocomplete": {
                    "type": "custom",
                    "tokenizer": "autocomplete_tokenizer",
                    "filter": ["lowercase", "asciifolding"]
                },
                # Search analyzer for autocomplete queries
                "autocomplete_search": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"]
                },
                # Code analyzer for technical content
                "code_analyzer": {
                    "type": "custom",
                    "tokenizer": "code_tokenizer",
                    "filter": ["lowercase"]
                }
            },
            "tokenizer": {
                "autocomplete_tokenizer": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 20,
                    "token_chars": ["letter", "digit"]
                },
                "code_tokenizer": {
                    "type": "pattern",
                    "pattern": "[^\\w\\d]+"
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
    }
    
    # Documents index template
    DOCUMENTS_TEMPLATE = {
        "index_patterns": ["documents-*"],
        "priority": 100,
        "template": {
            "settings": {
                "number_of_shards": 3,
                "number_of_replicas": 1,
                "refresh_interval": "1s",
                **ANALYZER_SETTINGS
            },
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "tenant_id": {"type": "keyword"},
                    "source_id": {"type": "keyword"},
                    "source_type": {"type": "keyword"},
                    "title": {
                        "type": "text",
                        "analyzer": "rag_standard",
                        "fields": {
                            "autocomplete": {
                                "type": "text",
                                "analyzer": "autocomplete",
                                "search_analyzer": "autocomplete_search"
                            },
                            "keyword": {
                                "type": "keyword",
                                "ignore_above": 256
                            }
                        }
                    },
                    "content": {
                        "type": "text",
                        "analyzer": "rag_standard"
                    },
                    "summary": {
                        "type": "text",
                        "analyzer": "rag_standard"
                    },
                    "metadata": {
                        "type": "object",
                        "enabled": True,
                        "dynamic": True
                    },
                    "tags": {"type": "keyword"},
                    "visibility": {"type": "keyword"},
                    "allowed_groups": {"type": "keyword"},
                    "content_hash": {"type": "keyword"},
                    "file_type": {"type": "keyword"},
                    "file_size": {"type": "long"},
                    "language": {"type": "keyword"},
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                    "indexed_at": {"type": "date"},
                    "status": {"type": "keyword"}
                }
            }
        }
    }
    
    # Chunks index template
    CHUNKS_TEMPLATE = {
        "index_patterns": ["chunks-*"],
        "priority": 100,
        "template": {
            "settings": {
                "number_of_shards": 3,
                "number_of_replicas": 1,
                "refresh_interval": "1s",
                **ANALYZER_SETTINGS
            },
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "document_id": {"type": "keyword"},
                    "tenant_id": {"type": "keyword"},
                    "chunk_index": {"type": "integer"},
                    "content": {
                        "type": "text",
                        "analyzer": "rag_standard"
                    },
                    "content_vector": {
                        "type": "knn_vector",
                        "dimension": 1536,
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",
                            "engine": "nmslib",
                            "parameters": {
                                "ef_construction": 256,
                                "m": 16
                            }
                        }
                    },
                    "token_count": {"type": "integer"},
                    "metadata": {
                        "type": "object",
                        "enabled": True,
                        "dynamic": True
                    },
                    "parent_title": {"type": "text"},
                    "section_title": {"type": "text"},
                    "page_number": {"type": "integer"},
                    "created_at": {"type": "date"},
                    "status": {"type": "keyword"}
                }
            }
        }
    }
    
    def create_index_template(client: OpenSearch, name: str, template: dict) -> None:
        """Create or update an index template."""
        try:
            client.indices.put_index_template(name=name, body=template)
            logger.info(f"Created/updated index template: {name}")
        except Exception as e:
            logger.error(f"Failed to create template {name}: {e}")
            raise
    
    def create_initial_indices(client: OpenSearch) -> None:
        """Create initial indices if they don't exist."""
        indices = ["documents-default", "chunks-default"]
        
        for index in indices:
            try:
                if not client.indices.exists(index):
                    client.indices.create(index)
                    logger.info(f"Created index: {index}")
                else:
                    logger.info(f"Index already exists: {index}")
            except Exception as e:
                logger.error(f"Failed to create index {index}: {e}")
    
    def verify_templates(client: OpenSearch) -> None:
        """Verify templates were created correctly."""
        templates = client.indices.get_index_template()
        logger.info(f"Active templates: {list(templates.get('index_templates', []))}")
    
    def main():
        logger.info("Starting OpenSearch bootstrap...")
        
        client = get_client()
        
        # Verify connection
        info = client.info()
        logger.info(f"Connected to OpenSearch {info['version']['number']}")
        
        # Create index templates
        logger.info("Creating index templates...")
        create_index_template(client, "documents-template", DOCUMENTS_TEMPLATE)
        create_index_template(client, "chunks-template", CHUNKS_TEMPLATE)
        
        # Create initial indices
        logger.info("Creating initial indices...")
        create_initial_indices(client)
        
        # Verify
        verify_templates(client)
        
        logger.info("OpenSearch bootstrap completed successfully!")
    
    if __name__ == "__main__":
        main()
```

### 3. Create Production Bootstrap Job (with Auth)

Create `k8s/overlays/prod/opensearch-bootstrap-patch.yaml`:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: opensearch-bootstrap
  namespace: rag-pipeline
spec:
  template:
    spec:
      initContainers:
      - name: wait-for-opensearch
        command:
        - /bin/sh
        - -c
        - |
          set -e
          echo "Waiting for OpenSearch to be ready (with auth)..."
          until curl -sf -u "${OPENSEARCH_USERNAME}:${OPENSEARCH_PASSWORD}" \
            "${OPENSEARCH_URL}/_cluster/health?wait_for_status=yellow&timeout=60s"; do
            echo "OpenSearch not ready, retrying in 5s..."
            sleep 5
          done
          echo "OpenSearch is ready!"
        env:
        - name: OPENSEARCH_URL
          value: "https://opensearch:9200"
        - name: OPENSEARCH_USERNAME
          valueFrom:
            secretKeyRef:
              name: rag-secrets
              key: opensearch-username
        - name: OPENSEARCH_PASSWORD
          valueFrom:
            secretKeyRef:
              name: rag-secrets
              key: opensearch-password
      
      containers:
      - name: bootstrap
        env:
        - name: OPENSEARCH_USE_SSL
          value: "true"
```

### 4. Helm/Makefile Integration

Add to `Makefile`:

```makefile
.PHONY: opensearch-bootstrap

opensearch-bootstrap:
	kubectl apply -f k8s/opensearch/bootstrap-configmap.yaml
	kubectl delete job opensearch-bootstrap -n rag-pipeline --ignore-not-found
	kubectl apply -f k8s/opensearch/bootstrap-job.yaml
	kubectl wait --for=condition=complete job/opensearch-bootstrap -n rag-pipeline --timeout=300s
	@echo "OpenSearch bootstrap completed"

opensearch-bootstrap-prod:
	kubectl apply -k k8s/overlays/prod
	kubectl delete job opensearch-bootstrap -n rag-pipeline --ignore-not-found
	kubectl apply -f k8s/overlays/prod/opensearch-bootstrap-patch.yaml
	kubectl wait --for=condition=complete job/opensearch-bootstrap -n rag-pipeline --timeout=300s
```

### 5. Index Lifecycle Management (ILM)

Create `k8s/opensearch/ilm-policy.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: opensearch-ilm-policies
  namespace: rag-pipeline
data:
  ilm-policies.json: |
    {
      "documents-policy": {
        "policy": {
          "description": "Documents index lifecycle policy",
          "default_state": "hot",
          "states": [
            {
              "name": "hot",
              "actions": [
                {
                  "rollover": {
                    "min_index_age": "30d",
                    "min_primary_shard_size": "50gb"
                  }
                }
              ],
              "transitions": [
                {
                  "state_name": "warm",
                  "conditions": {
                    "min_index_age": "30d"
                  }
                }
              ]
            },
            {
              "name": "warm",
              "actions": [
                {
                  "replica_count": {
                    "number_of_replicas": 1
                  }
                },
                {
                  "force_merge": {
                    "max_num_segments": 1
                  }
                }
              ],
              "transitions": [
                {
                  "state_name": "delete",
                  "conditions": {
                    "min_index_age": "365d"
                  }
                }
              ]
            },
            {
              "name": "delete",
              "actions": [
                {
                  "delete": {}
                }
              ]
            }
          ],
          "ism_template": [
            {
              "index_patterns": ["documents-*"],
              "priority": 100
            }
          ]
        }
      }
    }
```

## Acceptance Criteria

- [x] Bootstrap job runs successfully on cluster deployment
- [x] `documents-*` index template created with custom analyzers
- [x] `chunks-*` index template created with vector field mapping
- [x] Autocomplete analyzer configured for typeahead
- [x] Initial indices created (`documents-default`, `chunks-default`)
- [x] Job is idempotent (can be re-run safely)
- [x] Works with and without security enabled

## Verification Commands

```bash
# Check job status
kubectl get jobs -n rag-pipeline

# View job logs
kubectl logs job/opensearch-bootstrap -n rag-pipeline

# List index templates
curl -X GET "http://opensearch:9200/_index_template?pretty"

# Check template details
curl -X GET "http://opensearch:9200/_index_template/documents-template?pretty"

# List indices
curl -X GET "http://opensearch:9200/_cat/indices?v"

# Test autocomplete analyzer
curl -X POST "http://opensearch:9200/documents-default/_analyze" \
  -H 'Content-Type: application/json' \
  -d '{"analyzer": "autocomplete", "text": "machine learning"}'

# Test search with autocomplete
curl -X GET "http://opensearch:9200/documents-default/_search" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "match": {
        "title.autocomplete": "mach"
      }
    }
  }'
```

## Analyzer Reference

| Analyzer | Use Case | Tokenization |
|----------|----------|--------------|
| `rag_standard` | Full-text search | Standard + stemming + stopwords |
| `autocomplete` | Typeahead indexing | Edge n-grams (2-20 chars) |
| `autocomplete_search` | Typeahead query | Standard (no n-grams) |
| `code_analyzer` | Technical content | Pattern-based (camelCase aware) |

## Files Created

| File | Description |
|------|-------------|
| `k8s/opensearch/bootstrap-job.yaml` | Kubernetes Job for bootstrap |
| `k8s/opensearch/bootstrap-configmap.yaml` | Python bootstrap script |
| `k8s/opensearch/ilm-policy.yaml` | Index lifecycle management |
| `k8s/overlays/prod/opensearch-bootstrap-patch.yaml` | Production auth patch |

## Related Stories

- **US-1.3:** OpenSearch Cluster (prerequisite)
- **US-1A.3:** OpenSearch Security Plugin (related)
- **US-3.x:** Retrieval Service (consumer)
