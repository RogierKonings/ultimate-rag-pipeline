# Kubernetes Setup Guide

This guide covers the Kubernetes infrastructure setup for the RAG Pipeline.

## Prerequisites

- Kubernetes cluster (1.27+)
- `kubectl` configured with cluster access
- `helm` (for installing ingress controller and GPU operator)
- `kustomize` (or `kubectl` with kustomize support)

## Directory Structure

```
k8s/
├── base/                    # Base resources
│   ├── namespace.yaml       # Namespace and quotas
│   ├── secrets.yaml         # Centralized secrets
│   ├── rbac.yaml           # Service accounts and roles
│   ├── gpu-nodepool.yaml   # GPU configuration reference
│   └── kustomization.yaml   # Base kustomization
├── ingress/
│   └── nginx-ingress.yaml   # Ingress controller and routes
├── vault/
│   └── vault-agent.yaml     # HashiCorp Vault integration
└── overlays/
    ├── dev/                 # Development overlay
    │   ├── kustomization.yaml
    │   └── resource-limits-patch.yaml
    └── prod/                # Production overlay
        ├── kustomization.yaml
        ├── resource-limits-patch.yaml
        └── replicas-patch.yaml
```

## Quick Start

### 1. Deploy to Development

```bash
# Preview the resources
kubectl kustomize k8s/overlays/dev/

# Apply to cluster
kubectl apply -k k8s/overlays/dev/
```

### 2. Deploy to Production

```bash
# Preview the resources
kubectl kustomize k8s/overlays/prod/

# Apply to cluster
kubectl apply -k k8s/overlays/prod/
```

## Component Setup

### Ingress Controller

Install nginx-ingress using Helm:

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.service.type=LoadBalancer
```

Apply the ingress resource:

```bash
kubectl apply -f k8s/ingress/nginx-ingress.yaml
```

### GPU Node Pool (Optional)

If running vLLM or other GPU workloads, provision GPU nodes:

**GKE:**
```bash
gcloud container node-pools create gpu-pool \
  --cluster=rag-cluster \
  --machine-type=n1-standard-8 \
  --accelerator=type=nvidia-tesla-t4,count=1 \
  --num-nodes=1 \
  --node-labels=gpu=true
```

**EKS:**
```bash
eksctl create nodegroup \
  --cluster=rag-cluster \
  --name=gpu-workers \
  --node-type=g4dn.xlarge \
  --nodes=1 \
  --node-labels=gpu=true
```

Install NVIDIA GPU Operator:

```bash
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
helm repo update

helm install gpu-operator nvidia/gpu-operator \
  --namespace gpu-operator \
  --create-namespace \
  --wait
```

### HashiCorp Vault Integration (Optional)

For production secrets management, set up Vault:

1. Enable Kubernetes auth in Vault:
```bash
vault auth enable kubernetes

vault write auth/kubernetes/config \
  token_reviewer_jwt="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)" \
  kubernetes_host="https://$KUBERNETES_PORT_443_TCP_ADDR:443" \
  kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
```

2. Create policy and role:
```bash
vault policy write rag-pipeline - <<EOF
path "secret/data/rag-pipeline/*" {
  capabilities = ["read"]
}
EOF

vault write auth/kubernetes/role/rag-pipeline \
  bound_service_account_names=rag-pipeline-sa \
  bound_service_account_namespaces=rag-pipeline \
  policies=rag-pipeline \
  ttl=24h
```

3. Add Vault annotations to pods (see `k8s/vault/vault-agent.yaml` for examples).

## TLS Certificate Setup

Create a TLS secret for the ingress:

```bash
# Using cert-manager (recommended)
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml

# Or manually create secret
kubectl create secret tls rag-pipeline-tls \
  --namespace rag-pipeline \
  --cert=path/to/tls.crt \
  --key=path/to/tls.key
```

## Verification

Check namespace and quotas:
```bash
kubectl get namespace rag-pipeline
kubectl describe resourcequota -n rag-pipeline
kubectl describe limitrange -n rag-pipeline
```

Check secrets and service accounts:
```bash
kubectl get secrets -n rag-pipeline
kubectl get serviceaccounts -n rag-pipeline
```

Check ingress:
```bash
kubectl get pods -n ingress-nginx
kubectl get ingress -n rag-pipeline
```

Check GPU nodes (if applicable):
```bash
kubectl get nodes -l gpu=true
kubectl describe node <gpu-node-name> | grep -A5 "Allocatable"
```

## Resource Quotas

| Environment | CPU Requests | Memory Requests | CPU Limits | Memory Limits | Pods |
|-------------|--------------|-----------------|------------|---------------|------|
| Development | 4 | 8Gi | 8 | 16Gi | 20 |
| Production | 20 | 64Gi | 40 | 128Gi | 50 |
