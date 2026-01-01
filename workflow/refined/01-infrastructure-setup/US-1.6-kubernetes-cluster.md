# US-1.6: Kubernetes Cluster

> **Epic:** Infrastructure Setup  
> **Priority:** Critical  
> **Estimated Effort:** 3-4 days  
> **Dependencies:** Cloud provider account or local K8s setup

## Objective

Configure Kubernetes cluster with GPU node pools, namespaces, ingress controller, and secrets management for running the RAG pipeline services.

## Architecture Reference

- **Namespace:** `rag-pipeline` (per `docs/architecture.md` Deployment section)
- **GPU Node Pool:** Required for vLLM serving
- **Ingress:** nginx or traefik
- **Secrets:** HashiCorp Vault or Kubernetes Secrets

## Implementation Tasks

### 1. Create Namespace and Resource Quotas

Create `k8s/base/namespace.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: rag-pipeline
  labels:
    name: rag-pipeline
    environment: production
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: rag-pipeline-quota
  namespace: rag-pipeline
spec:
  hard:
    requests.cpu: "20"
    requests.memory: "64Gi"
    limits.cpu: "40"
    limits.memory: "128Gi"
    persistentvolumeclaims: "20"
    pods: "50"
---
apiVersion: v1
kind: LimitRange
metadata:
  name: rag-pipeline-limits
  namespace: rag-pipeline
spec:
  limits:
  - default:
      cpu: "500m"
      memory: "512Mi"
    defaultRequest:
      cpu: "100m"
      memory: "128Mi"
    type: Container
```

### 2. Configure GPU Node Pool

Create `k8s/base/gpu-nodepool.yaml` (for reference - actual provisioning via cloud CLI):

```yaml
# Example for GKE - use appropriate provider commands
# gcloud container node-pools create gpu-pool \
#   --cluster=rag-cluster \
#   --machine-type=n1-standard-8 \
#   --accelerator=type=nvidia-tesla-t4,count=1 \
#   --num-nodes=1 \
#   --node-labels=gpu=true

# GPU Runtime Class
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: nvidia
handler: nvidia
---
# Node selector example for GPU workloads
# Use in pod spec:
# nodeSelector:
#   gpu: "true"
# tolerations:
# - key: "nvidia.com/gpu"
#   operator: "Exists"
#   effect: "NoSchedule"
```

### 3. Deploy NVIDIA GPU Operator (if using GPUs)

```bash
# Add NVIDIA Helm repo
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
helm repo update

# Install GPU operator
helm install --wait --generate-name \
  -n gpu-operator --create-namespace \
  nvidia/gpu-operator
```

### 4. Deploy Ingress Controller

Create `k8s/ingress/nginx-ingress.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: ingress-nginx
---
# Using Helm for nginx-ingress
# helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
# helm install ingress-nginx ingress-nginx/ingress-nginx \
#   --namespace ingress-nginx \
#   --set controller.service.type=LoadBalancer

# Manual ingress resource for RAG services
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: rag-pipeline-ingress
  namespace: rag-pipeline
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "100m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "300"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - api.rag-pipeline.example.com
    secretName: rag-pipeline-tls
  rules:
  - host: api.rag-pipeline.example.com
    http:
      paths:
      - path: /ingest
        pathType: Prefix
        backend:
          service:
            name: ingestion-service
            port:
              number: 8001
      - path: /retrieve
        pathType: Prefix
        backend:
          service:
            name: retrieval-service
            port:
              number: 8002
      - path: /query
        pathType: Prefix
        backend:
          service:
            name: orchestrator-service
            port:
              number: 8003
      - path: /
        pathType: Prefix
        backend:
          service:
            name: orchestrator-service
            port:
              number: 8003
```

### 5. Configure Secrets Management

Create `k8s/base/secrets.yaml`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: rag-secrets
  namespace: rag-pipeline
type: Opaque
stringData:
  database-url: "postgresql://raguser:ragpass@postgres:5432/ragpipeline"
  postgres-user: "raguser"
  postgres-password: "ragpass"
  redis-password: "ragredis"
  minio-access-key: "minioadmin"
  minio-secret-key: "minioadmin123"
  # Add more secrets as needed
```

For HashiCorp Vault integration, create `k8s/vault/vault-agent.yaml`:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: rag-pipeline-sa
  namespace: rag-pipeline
---
# Vault Agent Injector annotation example for pods:
# annotations:
#   vault.hashicorp.com/agent-inject: "true"
#   vault.hashicorp.com/role: "rag-pipeline"
#   vault.hashicorp.com/agent-inject-secret-database: "secret/data/rag-pipeline/database"
#   vault.hashicorp.com/agent-inject-template-database: |
#     {{- with secret "secret/data/rag-pipeline/database" -}}
#     export DATABASE_URL="{{ .Data.data.url }}"
#     {{- end }}
```

### 6. Create Service Accounts and RBAC

Create `k8s/base/rbac.yaml`:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ingestion-service
  namespace: rag-pipeline
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: retrieval-service
  namespace: rag-pipeline
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: orchestrator-service
  namespace: rag-pipeline
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: rag-pipeline-role
  namespace: rag-pipeline
rules:
- apiGroups: [""]
  resources: ["configmaps", "secrets"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: rag-pipeline-binding
  namespace: rag-pipeline
subjects:
- kind: ServiceAccount
  name: ingestion-service
- kind: ServiceAccount
  name: retrieval-service
- kind: ServiceAccount
  name: orchestrator-service
roleRef:
  kind: Role
  name: rag-pipeline-role
  apiGroup: rbac.authorization.k8s.io
```

### 7. Create Kustomization Base

Create `k8s/base/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: rag-pipeline

resources:
  - namespace.yaml
  - secrets.yaml
  - rbac.yaml

commonLabels:
  app.kubernetes.io/part-of: rag-pipeline
  app.kubernetes.io/managed-by: kustomize
```

Create `k8s/overlays/dev/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

bases:
  - ../../base

namespace: rag-pipeline

patchesStrategicMerge:
  - resource-limits-patch.yaml

configMapGenerator:
  - name: rag-config
    literals:
      - ENVIRONMENT=development
      - LOG_LEVEL=DEBUG
```

Create `k8s/overlays/prod/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

bases:
  - ../../base

namespace: rag-pipeline

patchesStrategicMerge:
  - resource-limits-patch.yaml
  - replicas-patch.yaml

configMapGenerator:
  - name: rag-config
    literals:
      - ENVIRONMENT=production
      - LOG_LEVEL=INFO
```

## Acceptance Criteria

- [ ] Namespace `rag-pipeline` created with resource quotas
- [ ] GPU node pool provisioned (if using vLLM on-prem)
- [ ] Ingress controller (nginx/traefik) deployed
- [ ] TLS certificate configured for ingress
- [ ] Secrets management configured (K8s Secrets or Vault)
- [ ] Service accounts created for each service
- [ ] RBAC roles configured
- [ ] Kustomize overlays for dev/prod environments

## Verification Commands

```bash
# Verify namespace
kubectl get namespace rag-pipeline
kubectl describe resourcequota -n rag-pipeline

# Check GPU nodes (if applicable)
kubectl get nodes -l gpu=true
kubectl describe node <gpu-node-name> | grep -A5 "Allocatable"

# Check ingress controller
kubectl get pods -n ingress-nginx
kubectl get ingress -n rag-pipeline

# Check secrets
kubectl get secrets -n rag-pipeline

# Apply with kustomize
kubectl apply -k k8s/overlays/dev/
```

## Files to Create

1. `k8s/base/namespace.yaml`
2. `k8s/base/secrets.yaml`
3. `k8s/base/rbac.yaml`
4. `k8s/base/kustomization.yaml`
5. `k8s/ingress/nginx-ingress.yaml`
6. `k8s/overlays/dev/kustomization.yaml`
7. `k8s/overlays/dev/resource-limits-patch.yaml`
8. `k8s/overlays/prod/kustomization.yaml`
9. `k8s/overlays/prod/replicas-patch.yaml`
10. `docs/infrastructure/kubernetes-setup.md`
