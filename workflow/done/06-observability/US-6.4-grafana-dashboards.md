# US-6.4: Grafana Dashboards

> **Story ID:** US-6.4  
> **Epic:** Observability Stack  
> **Priority:** High  
> **Estimated Effort:** 3-4 days  
> **Dependencies:** US-6.2 (Prometheus Metrics), US-6.3 (Key Metrics Definition)

## User Story

**As a** SRE  
**I want** operational dashboards  
**So that** I can visualize system behavior

## Context

Grafana dashboards provide real-time visibility into the RAG pipeline's health, performance, and usage. This story covers creating a comprehensive dashboard suite that covers all aspects of the system, from high-level overview to deep-dive debugging views.

Dashboards will be provisioned as code (JSON/YAML) for version control and reproducibility.

## Technical Requirements

### Directory Structure

```
observability/
├── grafana/
│   ├── provisioning/
│   │   ├── dashboards/
│   │   │   ├── dashboards.yaml       # Dashboard provisioning config
│   │   │   ├── overview.json         # Main overview dashboard
│   │   │   ├── retrieval.json        # Retrieval service dashboard
│   │   │   ├── llm.json              # LLM service dashboard
│   │   │   ├── ingestion.json        # Ingestion pipeline dashboard
│   │   │   ├── cache.json            # Cache performance dashboard
│   │   │   ├── cost.json             # Cost tracking dashboard
│   │   │   └── slo.json              # SLO/Error budget dashboard
│   │   └── datasources/
│   │       ├── datasources.yaml
│   │       └── prometheus.yaml
│   ├── templates/
│   │   ├── base_dashboard.py         # Python dashboard generator
│   │   └── panels.py                 # Reusable panel templates
│   └── k8s/
│       ├── grafana.yaml              # Grafana deployment
│       └── configmaps.yaml           # Dashboard ConfigMaps
└── docs/
    └── dashboards.md                 # Dashboard documentation
```

### Dashboard Provisioning Configuration

```yaml
# provisioning/dashboards/dashboards.yaml
apiVersion: 1

providers:
  - name: 'RAG Pipeline'
    orgId: 1
    folder: 'RAG Pipeline'
    folderUid: 'rag-pipeline'
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: true
    options:
      path: /etc/grafana/provisioning/dashboards
      foldersFromFilesStructure: true
```

```yaml
# provisioning/datasources/datasources.yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    jsonData:
      timeInterval: "15s"
      httpMethod: POST
    editable: false
  
  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    jsonData:
      maxLines: 1000
    editable: false
  
  - name: Jaeger
    type: jaeger
    access: proxy
    url: http://jaeger:16686
    editable: false
  
  - name: Tempo
    type: tempo
    access: proxy
    url: http://tempo:3200
    jsonData:
      tracesToLogs:
        datasourceUid: loki
        filterByTraceID: true
        filterBySpanID: true
    editable: false
```

### Overview Dashboard

```json
{
  "uid": "rag-overview",
  "title": "RAG Pipeline Overview",
  "description": "High-level overview of RAG pipeline health and performance",
  "tags": ["rag", "overview"],
  "timezone": "browser",
  "refresh": "30s",
  "time": {
    "from": "now-1h",
    "to": "now"
  },
  "templating": {
    "list": [
      {
        "name": "service",
        "type": "query",
        "query": "label_values(rag_query_total, service)",
        "refresh": 2,
        "includeAll": true,
        "multi": true
      },
      {
        "name": "tenant_id",
        "type": "query",
        "query": "label_values(rag_query_total, tenant_id)",
        "refresh": 2,
        "includeAll": true,
        "multi": true
      }
    ]
  },
  "panels": [
    {
      "title": "Request Rate",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 0, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(rag_query_total{service=~\"$service\"}[5m]))",
          "legendFormat": "req/s"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "reqps",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": null}
            ]
          }
        }
      }
    },
    {
      "title": "Error Rate",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 4, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(rag_query_total{status=\"error\", service=~\"$service\"}[5m])) / sum(rate(rag_query_total{service=~\"$service\"}[5m])) * 100",
          "legendFormat": "Error %"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": null},
              {"color": "yellow", "value": 1},
              {"color": "red", "value": 5}
            ]
          }
        }
      }
    },
    {
      "title": "P95 Latency",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 8, "y": 0},
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum(rate(rag_query_duration_seconds_bucket{service=~\"$service\"}[5m])) by (le))",
          "legendFormat": "p95"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "s",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": null},
              {"color": "yellow", "value": 1},
              {"color": "red", "value": 2}
            ]
          }
        }
      }
    },
    {
      "title": "Active Queries",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 12, "y": 0},
      "targets": [
        {
          "expr": "sum(rag_query_active{service=~\"$service\"})",
          "legendFormat": "Active"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": null},
              {"color": "yellow", "value": 50},
              {"color": "red", "value": 100}
            ]
          }
        }
      }
    },
    {
      "title": "LLM Tokens (24h)",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 16, "y": 0},
      "targets": [
        {
          "expr": "sum(increase(rag_llm_tokens_total[24h]))",
          "legendFormat": "Tokens"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": null}
            ]
          }
        }
      }
    },
    {
      "title": "Cache Hit Rate",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 20, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(rag_cache_hits_total[5m])) / (sum(rate(rag_cache_hits_total[5m])) + sum(rate(rag_cache_misses_total[5m]))) * 100",
          "legendFormat": "Hit %"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "red", "value": null},
              {"color": "yellow", "value": 50},
              {"color": "green", "value": 80}
            ]
          }
        }
      }
    },
    {
      "title": "Request Rate Over Time",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 4},
      "targets": [
        {
          "expr": "sum(rate(rag_query_total{service=~\"$service\"}[5m])) by (service)",
          "legendFormat": "{{service}}"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "reqps",
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "smooth",
            "fillOpacity": 10
          }
        }
      }
    },
    {
      "title": "Latency Distribution",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 4},
      "targets": [
        {
          "expr": "histogram_quantile(0.50, sum(rate(rag_query_duration_seconds_bucket{service=~\"$service\"}[5m])) by (le))",
          "legendFormat": "p50"
        },
        {
          "expr": "histogram_quantile(0.95, sum(rate(rag_query_duration_seconds_bucket{service=~\"$service\"}[5m])) by (le))",
          "legendFormat": "p95"
        },
        {
          "expr": "histogram_quantile(0.99, sum(rate(rag_query_duration_seconds_bucket{service=~\"$service\"}[5m])) by (le))",
          "legendFormat": "p99"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "s",
          "custom": {
            "drawStyle": "line",
            "lineInterpolation": "smooth"
          }
        }
      }
    },
    {
      "title": "Error Rate by Service",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 12},
      "targets": [
        {
          "expr": "sum(rate(rag_query_total{status=\"error\", service=~\"$service\"}[5m])) by (service) / sum(rate(rag_query_total{service=~\"$service\"}[5m])) by (service) * 100",
          "legendFormat": "{{service}}"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "custom": {
            "drawStyle": "line",
            "fillOpacity": 10
          }
        }
      }
    },
    {
      "title": "Request Breakdown by Status",
      "type": "piechart",
      "gridPos": {"h": 8, "w": 6, "x": 12, "y": 12},
      "targets": [
        {
          "expr": "sum(increase(rag_query_total{service=~\"$service\"}[1h])) by (status)",
          "legendFormat": "{{status}}"
        }
      ]
    },
    {
      "title": "Top Tenants by Request Volume",
      "type": "bargauge",
      "gridPos": {"h": 8, "w": 6, "x": 18, "y": 12},
      "targets": [
        {
          "expr": "topk(10, sum(rate(rag_query_total[1h])) by (tenant_id))",
          "legendFormat": "{{tenant_id}}"
        }
      ],
      "options": {
        "orientation": "horizontal",
        "displayMode": "gradient"
      }
    }
  ]
}
```

### Retrieval Dashboard

```json
{
  "uid": "rag-retrieval",
  "title": "RAG Retrieval Service",
  "description": "Document retrieval performance and quality metrics",
  "tags": ["rag", "retrieval"],
  "timezone": "browser",
  "refresh": "30s",
  "templating": {
    "list": [
      {
        "name": "strategy",
        "type": "query",
        "query": "label_values(rag_retrieval_duration_seconds_bucket, strategy)",
        "refresh": 2,
        "includeAll": true,
        "multi": true
      },
      {
        "name": "index",
        "type": "query",
        "query": "label_values(rag_retrieval_duration_seconds_bucket, index)",
        "refresh": 2,
        "includeAll": true,
        "multi": true
      }
    ]
  },
  "panels": [
    {
      "title": "Retrieval Rate",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 0, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(rag_retrieval_duration_seconds_count{strategy=~\"$strategy\"}[5m]))",
          "legendFormat": "req/s"
        }
      ]
    },
    {
      "title": "P95 Retrieval Latency",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 4, "y": 0},
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum(rate(rag_retrieval_duration_seconds_bucket{strategy=~\"$strategy\"}[5m])) by (le))",
          "legendFormat": "p95"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "s",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": null},
              {"color": "yellow", "value": 0.3},
              {"color": "red", "value": 0.5}
            ]
          }
        }
      }
    },
    {
      "title": "Avg Results Per Query",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 8, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(rag_retrieval_result_count_sum[5m])) / sum(rate(rag_retrieval_result_count_count[5m]))",
          "legendFormat": "avg"
        }
      ]
    },
    {
      "title": "Zero Results Rate",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 12, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(rag_retrieval_result_count_bucket{le=\"0\"}[5m])) / sum(rate(rag_retrieval_result_count_count[5m])) * 100",
          "legendFormat": "%"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": null},
              {"color": "yellow", "value": 5},
              {"color": "red", "value": 10}
            ]
          }
        }
      }
    },
    {
      "title": "Retrieval Latency by Strategy",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 4},
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum(rate(rag_retrieval_duration_seconds_bucket{strategy=~\"$strategy\"}[5m])) by (le, strategy))",
          "legendFormat": "{{strategy}} p95"
        }
      ],
      "fieldConfig": {
        "defaults": {"unit": "s"}
      }
    },
    {
      "title": "Result Count Distribution",
      "type": "heatmap",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 4},
      "targets": [
        {
          "expr": "sum(increase(rag_retrieval_result_count_bucket{strategy=~\"$strategy\"}[5m])) by (le)",
          "format": "heatmap",
          "legendFormat": "{{le}}"
        }
      ],
      "options": {
        "calculate": false,
        "yAxis": {
          "unit": "short"
        }
      }
    },
    {
      "title": "Reranking Latency",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 12},
      "targets": [
        {
          "expr": "histogram_quantile(0.50, sum(rate(rag_reranking_duration_seconds_bucket[5m])) by (le, model))",
          "legendFormat": "{{model}} p50"
        },
        {
          "expr": "histogram_quantile(0.95, sum(rate(rag_reranking_duration_seconds_bucket[5m])) by (le, model))",
          "legendFormat": "{{model}} p95"
        }
      ],
      "fieldConfig": {
        "defaults": {"unit": "s"}
      }
    },
    {
      "title": "Vector DB Points",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 12},
      "targets": [
        {
          "expr": "rag_vector_db_points",
          "legendFormat": "{{collection}}"
        }
      ],
      "fieldConfig": {
        "defaults": {"unit": "short"}
      }
    }
  ]
}
```

### LLM Dashboard

```json
{
  "uid": "rag-llm",
  "title": "RAG LLM Service",
  "description": "LLM inference performance, token usage, and costs",
  "tags": ["rag", "llm"],
  "timezone": "browser",
  "refresh": "30s",
  "templating": {
    "list": [
      {
        "name": "model",
        "type": "query",
        "query": "label_values(rag_llm_duration_seconds_bucket, model)",
        "refresh": 2,
        "includeAll": true,
        "multi": true
      },
      {
        "name": "provider",
        "type": "query",
        "query": "label_values(rag_llm_duration_seconds_bucket, provider)",
        "refresh": 2,
        "includeAll": true,
        "multi": true
      }
    ]
  },
  "panels": [
    {
      "title": "LLM Request Rate",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 0, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(rag_llm_requests_total{model=~\"$model\"}[5m]))",
          "legendFormat": "req/s"
        }
      ]
    },
    {
      "title": "P95 Total Latency",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 4, "y": 0},
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum(rate(rag_llm_duration_seconds_bucket{model=~\"$model\"}[5m])) by (le))",
          "legendFormat": "p95"
        }
      ],
      "fieldConfig": {
        "defaults": {"unit": "s"}
      }
    },
    {
      "title": "P50 TTFT",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 8, "y": 0},
      "targets": [
        {
          "expr": "histogram_quantile(0.50, sum(rate(rag_llm_time_to_first_token_seconds_bucket{model=~\"$model\"}[5m])) by (le))",
          "legendFormat": "p50"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "s",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": null},
              {"color": "yellow", "value": 0.5},
              {"color": "red", "value": 1}
            ]
          }
        }
      }
    },
    {
      "title": "Tokens/sec",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 12, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(rag_llm_tokens_total{model=~\"$model\"}[5m]))",
          "legendFormat": "tokens/s"
        }
      ]
    },
    {
      "title": "Error Rate",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 16, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(rag_llm_requests_total{status=\"error\", model=~\"$model\"}[5m])) / sum(rate(rag_llm_requests_total{model=~\"$model\"}[5m])) * 100",
          "legendFormat": "Error %"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": null},
              {"color": "yellow", "value": 1},
              {"color": "red", "value": 5}
            ]
          }
        }
      }
    },
    {
      "title": "Estimated Cost (24h)",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 20, "y": 0},
      "targets": [
        {
          "expr": "sum(increase(rag_llm_tokens_total{token_type=\"input\"}[24h])) * 0.00001 + sum(increase(rag_llm_tokens_total{token_type=\"output\"}[24h])) * 0.00003",
          "legendFormat": "Cost"
        }
      ],
      "fieldConfig": {
        "defaults": {"unit": "currencyUSD"}
      }
    },
    {
      "title": "Latency by Model",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 4},
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum(rate(rag_llm_duration_seconds_bucket{model=~\"$model\"}[5m])) by (le, model))",
          "legendFormat": "{{model}} p95"
        }
      ],
      "fieldConfig": {
        "defaults": {"unit": "s"}
      }
    },
    {
      "title": "TTFT by Model",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 4},
      "targets": [
        {
          "expr": "histogram_quantile(0.50, sum(rate(rag_llm_time_to_first_token_seconds_bucket{model=~\"$model\"}[5m])) by (le, model))",
          "legendFormat": "{{model}} p50"
        },
        {
          "expr": "histogram_quantile(0.95, sum(rate(rag_llm_time_to_first_token_seconds_bucket{model=~\"$model\"}[5m])) by (le, model))",
          "legendFormat": "{{model}} p95"
        }
      ],
      "fieldConfig": {
        "defaults": {"unit": "s"}
      }
    },
    {
      "title": "Token Usage Over Time",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 12},
      "targets": [
        {
          "expr": "sum(rate(rag_llm_tokens_total{model=~\"$model\"}[5m])) by (model, token_type)",
          "legendFormat": "{{model}} {{token_type}}"
        }
      ],
      "fieldConfig": {
        "defaults": {"unit": "short"}
      }
    },
    {
      "title": "Prompt Token Distribution",
      "type": "heatmap",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 12},
      "targets": [
        {
          "expr": "sum(increase(rag_llm_prompt_tokens_bucket{model=~\"$model\"}[5m])) by (le)",
          "format": "heatmap",
          "legendFormat": "{{le}}"
        }
      ]
    }
  ]
}
```

### Ingestion Dashboard

```json
{
  "uid": "rag-ingestion",
  "title": "RAG Ingestion Pipeline",
  "description": "Document ingestion throughput, queue depth, and processing times",
  "tags": ["rag", "ingestion"],
  "timezone": "browser",
  "refresh": "30s",
  "templating": {
    "list": [
      {
        "name": "source_type",
        "type": "query",
        "query": "label_values(rag_documents_ingested_total, source_type)",
        "refresh": 2,
        "includeAll": true,
        "multi": true
      }
    ]
  },
  "panels": [
    {
      "title": "Documents Ingested (24h)",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 0, "y": 0},
      "targets": [
        {
          "expr": "sum(increase(rag_documents_ingested_total{status=\"success\", source_type=~\"$source_type\"}[24h]))",
          "legendFormat": "docs"
        }
      ]
    },
    {
      "title": "Ingestion Rate",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 4, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(rag_documents_ingested_total{status=\"success\", source_type=~\"$source_type\"}[5m]))",
          "legendFormat": "docs/s"
        }
      ]
    },
    {
      "title": "Queue Depth",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 8, "y": 0},
      "targets": [
        {
          "expr": "sum(rag_ingestion_queue_size)",
          "legendFormat": "queue"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": null},
              {"color": "yellow", "value": 100},
              {"color": "red", "value": 500}
            ]
          }
        }
      }
    },
    {
      "title": "Error Rate",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 12, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(rag_documents_ingested_total{status=\"error\"}[5m])) / sum(rate(rag_documents_ingested_total[5m])) * 100",
          "legendFormat": "Error %"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": null},
              {"color": "yellow", "value": 1},
              {"color": "red", "value": 5}
            ]
          }
        }
      }
    },
    {
      "title": "Data Throughput",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 16, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(rag_document_bytes_total[5m]))",
          "legendFormat": "throughput"
        }
      ],
      "fieldConfig": {
        "defaults": {"unit": "Bps"}
      }
    },
    {
      "title": "Chunks Created (24h)",
      "type": "stat",
      "gridPos": {"h": 4, "w": 4, "x": 20, "y": 0},
      "targets": [
        {
          "expr": "sum(increase(rag_chunks_created_total[24h]))",
          "legendFormat": "chunks"
        }
      ]
    },
    {
      "title": "Ingestion Rate by Source Type",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 4},
      "targets": [
        {
          "expr": "sum(rate(rag_documents_ingested_total{status=\"success\", source_type=~\"$source_type\"}[5m])) by (source_type)",
          "legendFormat": "{{source_type}}"
        }
      ],
      "fieldConfig": {
        "defaults": {"unit": "short"}
      }
    },
    {
      "title": "Queue Depth Over Time",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 4},
      "targets": [
        {
          "expr": "sum(rag_ingestion_queue_size) by (queue, priority)",
          "legendFormat": "{{queue}} ({{priority}})"
        }
      ]
    },
    {
      "title": "Processing Time by Stage",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 12},
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum(rate(rag_ingestion_duration_seconds_bucket[5m])) by (le, stage))",
          "legendFormat": "{{stage}} p95"
        }
      ],
      "fieldConfig": {
        "defaults": {"unit": "s"}
      }
    },
    {
      "title": "Documents by Status",
      "type": "piechart",
      "gridPos": {"h": 8, "w": 6, "x": 12, "y": 12},
      "targets": [
        {
          "expr": "sum(increase(rag_documents_ingested_total[24h])) by (status)",
          "legendFormat": "{{status}}"
        }
      ]
    },
    {
      "title": "Avg Chunks per Document",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 6, "x": 18, "y": 12},
      "targets": [
        {
          "expr": "sum(rate(rag_chunks_created_total[5m])) by (chunking_strategy) / sum(rate(rag_documents_ingested_total{status=\"success\"}[5m]))",
          "legendFormat": "{{chunking_strategy}}"
        }
      ]
    }
  ]
}
```

### SLO Dashboard

```json
{
  "uid": "rag-slo",
  "title": "RAG SLO Dashboard",
  "description": "SLO compliance, error budgets, and burn rates",
  "tags": ["rag", "slo"],
  "timezone": "browser",
  "refresh": "1m",
  "panels": [
    {
      "title": "Query Latency SLO (99% < 2s)",
      "type": "gauge",
      "gridPos": {"h": 6, "w": 6, "x": 0, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(rag_query_duration_seconds_bucket{le=\"2\"}[30d])) / sum(rate(rag_query_duration_seconds_count[30d])) * 100",
          "legendFormat": "Current"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 95,
          "max": 100,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "red", "value": 95},
              {"color": "yellow", "value": 99},
              {"color": "green", "value": 99.5}
            ]
          }
        }
      }
    },
    {
      "title": "Availability SLO (99.9%)",
      "type": "gauge",
      "gridPos": {"h": 6, "w": 6, "x": 6, "y": 0},
      "targets": [
        {
          "expr": "(1 - sum(rate(rag_query_total{status=\"error\"}[30d])) / sum(rate(rag_query_total[30d]))) * 100",
          "legendFormat": "Current"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 99,
          "max": 100,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "red", "value": 99},
              {"color": "yellow", "value": 99.9},
              {"color": "green", "value": 99.95}
            ]
          }
        }
      }
    },
    {
      "title": "LLM TTFT SLO (95% < 1s)",
      "type": "gauge",
      "gridPos": {"h": 6, "w": 6, "x": 12, "y": 0},
      "targets": [
        {
          "expr": "sum(rate(rag_llm_time_to_first_token_seconds_bucket{le=\"1\"}[7d])) / sum(rate(rag_llm_time_to_first_token_seconds_count[7d])) * 100",
          "legendFormat": "Current"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 90,
          "max": 100,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "red", "value": 90},
              {"color": "yellow", "value": 95},
              {"color": "green", "value": 97}
            ]
          }
        }
      }
    },
    {
      "title": "Error Budget (Latency)",
      "type": "gauge",
      "gridPos": {"h": 6, "w": 6, "x": 18, "y": 0},
      "targets": [
        {
          "expr": "(1 - ((1 - sum(rate(rag_query_duration_seconds_bucket{le=\"2\"}[30d])) / sum(rate(rag_query_duration_seconds_count[30d]))) / 0.01)) * 100",
          "legendFormat": "Remaining"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 0,
          "max": 100,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "red", "value": 0},
              {"color": "yellow", "value": 25},
              {"color": "green", "value": 50}
            ]
          }
        }
      }
    },
    {
      "title": "SLO Compliance Over Time",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 24, "x": 0, "y": 6},
      "targets": [
        {
          "expr": "sum(rate(rag_query_duration_seconds_bucket{le=\"2\"}[1h])) / sum(rate(rag_query_duration_seconds_count[1h])) * 100",
          "legendFormat": "Query Latency"
        },
        {
          "expr": "(1 - sum(rate(rag_query_total{status=\"error\"}[1h])) / sum(rate(rag_query_total[1h]))) * 100",
          "legendFormat": "Availability"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 95,
          "max": 100
        }
      }
    },
    {
      "title": "Error Budget Burn Rate",
      "type": "timeseries",
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 14},
      "targets": [
        {
          "expr": "(1 - sum(rate(rag_query_duration_seconds_bucket{le=\"2\"}[1h])) / sum(rate(rag_query_duration_seconds_count[1h]))) / 0.01",
          "legendFormat": "Latency Burn Rate"
        },
        {
          "expr": "sum(rate(rag_query_total{status=\"error\"}[1h])) / sum(rate(rag_query_total[1h])) / 0.001",
          "legendFormat": "Availability Burn Rate"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "custom": {
            "axisLabel": "Burn Rate (x)"
          }
        }
      }
    },
    {
      "title": "Error Budget Remaining",
      "type": "bargauge",
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 14},
      "targets": [
        {
          "expr": "(1 - ((1 - sum(rate(rag_query_duration_seconds_bucket{le=\"2\"}[30d])) / sum(rate(rag_query_duration_seconds_count[30d]))) / 0.01)) * 100",
          "legendFormat": "Query Latency"
        },
        {
          "expr": "(1 - (sum(rate(rag_query_total{status=\"error\"}[30d])) / sum(rate(rag_query_total[30d]))) / 0.001) * 100",
          "legendFormat": "Availability"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 0,
          "max": 100,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "red", "value": 0},
              {"color": "yellow", "value": 25},
              {"color": "green", "value": 50}
            ]
          }
        }
      },
      "options": {
        "orientation": "horizontal",
        "displayMode": "gradient"
      }
    }
  ]
}
```

### Dashboard Python Generator

```python
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json


@dataclass
class Panel:
    """Grafana panel definition."""
    title: str
    panel_type: str
    targets: List[Dict[str, Any]]
    grid_pos: Dict[str, int]
    field_config: Optional[Dict] = None
    options: Optional[Dict] = None


@dataclass
class Dashboard:
    """Grafana dashboard definition."""
    uid: str
    title: str
    description: str
    tags: List[str]
    panels: List[Panel] = field(default_factory=list)
    templating: List[Dict] = field(default_factory=list)
    refresh: str = "30s"
    timezone: str = "browser"
    
    def to_json(self) -> Dict:
        """Convert to Grafana JSON format."""
        return {
            "uid": self.uid,
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "timezone": self.timezone,
            "refresh": self.refresh,
            "time": {
                "from": "now-1h",
                "to": "now"
            },
            "templating": {
                "list": self.templating
            },
            "panels": [self._panel_to_json(p, i) for i, p in enumerate(self.panels)]
        }
    
    def _panel_to_json(self, panel: Panel, index: int) -> Dict:
        result = {
            "id": index + 1,
            "title": panel.title,
            "type": panel.panel_type,
            "gridPos": panel.grid_pos,
            "targets": panel.targets
        }
        
        if panel.field_config:
            result["fieldConfig"] = panel.field_config
        if panel.options:
            result["options"] = panel.options
        
        return result
    
    def save(self, path: str) -> None:
        """Save dashboard to JSON file."""
        with open(path, 'w') as f:
            json.dump(self.to_json(), f, indent=2)


def create_stat_panel(
    title: str,
    expr: str,
    unit: str = "short",
    grid_pos: Dict[str, int] = None,
    thresholds: List[Dict] = None,
) -> Panel:
    """Create a stat panel."""
    return Panel(
        title=title,
        panel_type="stat",
        grid_pos=grid_pos or {"h": 4, "w": 4, "x": 0, "y": 0},
        targets=[{"expr": expr, "legendFormat": title}],
        field_config={
            "defaults": {
                "unit": unit,
                "thresholds": {
                    "mode": "absolute",
                    "steps": thresholds or [{"color": "green", "value": None}]
                }
            }
        }
    )


def create_timeseries_panel(
    title: str,
    targets: List[Dict[str, str]],
    unit: str = "short",
    grid_pos: Dict[str, int] = None,
) -> Panel:
    """Create a timeseries panel."""
    return Panel(
        title=title,
        panel_type="timeseries",
        grid_pos=grid_pos or {"h": 8, "w": 12, "x": 0, "y": 0},
        targets=[{"expr": t["expr"], "legendFormat": t.get("legend", "")} for t in targets],
        field_config={
            "defaults": {
                "unit": unit,
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "smooth",
                    "fillOpacity": 10
                }
            }
        }
    )
```

### Kubernetes Deployment

```yaml
# grafana.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
  namespace: observability
spec:
  replicas: 1
  selector:
    matchLabels:
      app: grafana
  template:
    metadata:
      labels:
        app: grafana
    spec:
      containers:
        - name: grafana
          image: grafana/grafana:10.2.3
          ports:
            - containerPort: 3000
              name: http
          env:
            - name: GF_SECURITY_ADMIN_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: grafana-secrets
                  key: admin-password
            - name: GF_INSTALL_PLUGINS
              value: grafana-piechart-panel
          resources:
            requests:
              memory: 256Mi
              cpu: 100m
            limits:
              memory: 512Mi
              cpu: 500m
          volumeMounts:
            - name: grafana-storage
              mountPath: /var/lib/grafana
            - name: grafana-datasources
              mountPath: /etc/grafana/provisioning/datasources
            - name: grafana-dashboards-config
              mountPath: /etc/grafana/provisioning/dashboards
            - name: grafana-dashboards
              mountPath: /etc/grafana/provisioning/dashboards/rag
          livenessProbe:
            httpGet:
              path: /api/health
              port: 3000
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /api/health
              port: 3000
            initialDelaySeconds: 5
            periodSeconds: 5
      volumes:
        - name: grafana-storage
          persistentVolumeClaim:
            claimName: grafana-pvc
        - name: grafana-datasources
          configMap:
            name: grafana-datasources
        - name: grafana-dashboards-config
          configMap:
            name: grafana-dashboards-config
        - name: grafana-dashboards
          configMap:
            name: grafana-dashboards
---
apiVersion: v1
kind: Service
metadata:
  name: grafana
  namespace: observability
spec:
  selector:
    app: grafana
  ports:
    - name: http
      port: 3000
      targetPort: 3000
  type: ClusterIP
```

## Unit Tests

```python
import pytest
import json


def test_overview_dashboard_valid_json():
    """Test overview dashboard is valid JSON."""
    with open("grafana/provisioning/dashboards/overview.json") as f:
        dashboard = json.load(f)
    
    assert dashboard["uid"] == "rag-overview"
    assert "panels" in dashboard
    assert len(dashboard["panels"]) > 0


def test_all_dashboards_have_required_fields():
    """Test all dashboards have required fields."""
    import glob
    
    for path in glob.glob("grafana/provisioning/dashboards/*.json"):
        with open(path) as f:
            dashboard = json.load(f)
        
        assert "uid" in dashboard
        assert "title" in dashboard
        assert "panels" in dashboard
        assert "tags" in dashboard


def test_dashboard_panels_have_targets():
    """Test all panels have query targets."""
    with open("grafana/provisioning/dashboards/overview.json") as f:
        dashboard = json.load(f)
    
    for panel in dashboard["panels"]:
        assert "targets" in panel, f"Panel '{panel['title']}' missing targets"
        assert len(panel["targets"]) > 0


def test_dashboard_generator():
    """Test Python dashboard generator."""
    dashboard = Dashboard(
        uid="test-dashboard",
        title="Test Dashboard",
        description="Test description",
        tags=["test"],
    )
    
    dashboard.panels.append(create_stat_panel(
        title="Test Stat",
        expr="up",
        unit="short",
        grid_pos={"h": 4, "w": 4, "x": 0, "y": 0},
    ))
    
    json_output = dashboard.to_json()
    
    assert json_output["uid"] == "test-dashboard"
    assert len(json_output["panels"]) == 1


def test_templating_variables():
    """Test dashboard templating variables."""
    with open("grafana/provisioning/dashboards/overview.json") as f:
        dashboard = json.load(f)
    
    variables = dashboard.get("templating", {}).get("list", [])
    
    # Should have service and tenant_id variables
    var_names = [v["name"] for v in variables]
    assert "service" in var_names or "tenant_id" in var_names


def test_panel_thresholds():
    """Test panels have appropriate thresholds."""
    with open("grafana/provisioning/dashboards/overview.json") as f:
        dashboard = json.load(f)
    
    for panel in dashboard["panels"]:
        if panel["type"] == "stat":
            field_config = panel.get("fieldConfig", {})
            defaults = field_config.get("defaults", {})
            thresholds = defaults.get("thresholds", {})
            
            assert "steps" in thresholds, f"Panel '{panel['title']}' missing threshold steps"
```

## Dependencies

```
grafana>=10.0.0
```

## Definition of Done

- [ ] Overview dashboard with key metrics
- [ ] Retrieval service dashboard
- [ ] LLM service dashboard
- [ ] Ingestion pipeline dashboard
- [ ] Cache performance dashboard
- [ ] SLO/Error budget dashboard
- [ ] Dashboards use templating variables
- [ ] All panels have appropriate thresholds
- [ ] Datasource provisioning configured
- [ ] Dashboard provisioning configured
- [ ] Python dashboard generator implemented
- [ ] Kubernetes deployment manifests
- [ ] Grafana deployed with provisioning
- [ ] Dashboards version controlled as JSON
- [ ] >90% test coverage
- [ ] Documentation complete
