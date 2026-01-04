# RAG Pipeline Deployment Runbook

## Overview

This runbook provides step-by-step instructions for deploying the RAG Pipeline to Kubernetes clusters on GKE, EKS, and AKS.

## Pre-Deployment Checklist

### General Requirements

- [ ] Kubernetes cluster is running (1.27+)
- [ ] `kubectl` configured and connected to cluster
- [ ] Helm 3.x installed
- [ ] Container images pushed to registry
- [ ] Secrets created in cluster

### Storage Encryption

- [ ] Encrypted storage class exists in cluster
- [ ] KMS keys created (if using CMEK)
- [ ] IAM permissions for KMS access configured
- [ ] Run storage validation script

### Network Security

- [ ] Network policies applied
- [ ] TLS certificates created/renewed
- [ ] Ingress controller configured

## Deployment Steps

### 1. Create Namespace

```bash
kubectl apply -f k8s/base/namespace.yaml
```

### 2. Apply Secrets

```bash
# Create secrets from template
kubectl apply -f k8s/base/secrets.yaml

# Or use external secrets operator
kubectl apply -f k8s/secrets/external-secrets.yaml
```

### 3. Deploy Using Kustomize

Choose the appropriate overlay for your cloud provider:

```bash
# GKE
kubectl apply -k k8s/overlays/gke

# EKS
kubectl apply -k k8s/overlays/eks

# AKS
kubectl apply -k k8s/overlays/aks

# Production (generic)
kubectl apply -k k8s/overlays/prod

# Development
kubectl apply -k k8s/overlays/dev
```

### 4. Verify Deployment

```bash
# Check all pods are running
kubectl get pods -n rag-pipeline

# Check services
kubectl get svc -n rag-pipeline

# Check PVCs are bound
kubectl get pvc -n rag-pipeline
```

## Storage Encryption Verification

### Pre-Deployment Validation

```bash
# Run encryption validation script
./scripts/validate-storage-encryption.sh rag-pipeline
```

### Check Storage Classes

```bash
kubectl get storageclass -o wide
```

### Provider-Specific Verification

#### GKE

```bash
# List disks with encryption info
gcloud compute disks list \
  --filter="labels.kubernetes_io_created-for_pvc_namespace:rag-pipeline" \
  --format="table(name,diskEncryptionKey.sha256,diskEncryptionKey.kmsKeyName)"
```

#### EKS

```bash
# Check volume encryption status
aws ec2 describe-volumes \
  --filters "Name=tag:kubernetes.io/created-for/pvc/namespace,Values=rag-pipeline" \
  --query "Volumes[*].{ID:VolumeId,Encrypted:Encrypted,KmsKeyId:KmsKeyId}" \
  --output table
```

#### AKS

```bash
# Check disk encryption
az disk list \
  --query "[?tags.\"kubernetes.io-created-for-pvc-namespace\"=='rag-pipeline'].{name:name,encryption:encryption.type}" \
  --output table
```

## Health Checks

### Service Health

```bash
# Check all deployments
kubectl get deployments -n rag-pipeline

# Check pod health
kubectl get pods -n rag-pipeline -o wide

# View pod logs
kubectl logs -n rag-pipeline deployment/ingestion-service --tail=100
```

### Database Connectivity

```bash
# PostgreSQL
kubectl exec -it -n rag-pipeline deployment/postgres -- psql -U raguser -c "SELECT 1;"

# OpenSearch
kubectl exec -it -n rag-pipeline deployment/opensearch -- curl -s localhost:9200/_cluster/health

# Qdrant
kubectl exec -it -n rag-pipeline deployment/qdrant -- curl -s localhost:6333/collections

# Redis
kubectl exec -it -n rag-pipeline deployment/redis -- redis-cli ping
```

## Rollback Procedures

### Quick Rollback

```bash
# Rollback a deployment
kubectl rollout undo deployment/ingestion-service -n rag-pipeline

# Rollback to specific revision
kubectl rollout undo deployment/ingestion-service -n rag-pipeline --to-revision=2

# Check rollout history
kubectl rollout history deployment/ingestion-service -n rag-pipeline
```

### Full Rollback

```bash
# Delete current deployment
kubectl delete -k k8s/overlays/prod

# Apply previous version
git checkout <previous-tag>
kubectl apply -k k8s/overlays/prod
```

## Troubleshooting

### Pod Not Starting

```bash
# Check pod events
kubectl describe pod <pod-name> -n rag-pipeline

# Check logs
kubectl logs <pod-name> -n rag-pipeline --previous
```

### PVC Not Binding

```bash
# Check PVC status
kubectl describe pvc <pvc-name> -n rag-pipeline

# Check storage class
kubectl get storageclass

# Check PV availability
kubectl get pv
```

### Network Issues

```bash
# Check service endpoints
kubectl get endpoints -n rag-pipeline

# Test service connectivity
kubectl run debug --rm -it --image=busybox -n rag-pipeline -- wget -qO- http://ingestion-service:8001/health
```

## Audit Compliance

### Evidence Collection

For SOC 2, HIPAA, PCI-DSS audits, collect:

1. **Storage Encryption**
   - Storage class configurations
   - Encryption validation script output
   - KMS key policies (if using CMEK)

2. **Network Security**
   - Network policy manifests
   - TLS certificate details
   - Ingress configurations

3. **Access Control**
   - RBAC configurations
   - Service account bindings
   - Namespace isolation

### Generate Audit Report

```bash
# Storage encryption status
./scripts/validate-storage-encryption.sh rag-pipeline > audit/storage-encryption.txt

# Resource inventory
kubectl get all -n rag-pipeline -o yaml > audit/resource-inventory.yaml

# Network policies
kubectl get networkpolicy -n rag-pipeline -o yaml > audit/network-policies.yaml

# RBAC
kubectl get rolebindings,clusterrolebindings -n rag-pipeline -o yaml > audit/rbac.yaml
```

## Maintenance

### Certificate Renewal

Certificates are auto-renewed by cert-manager. To manually trigger:

```bash
kubectl delete certificate <cert-name> -n rag-pipeline
# cert-manager will recreate it
```

### Database Backups

```bash
# PostgreSQL backup
kubectl exec -it -n rag-pipeline deployment/postgres -- pg_dump -U raguser ragpipeline > backup.sql

# Restore
kubectl exec -i -n rag-pipeline deployment/postgres -- psql -U raguser ragpipeline < backup.sql
```

### Scaling

```bash
# Scale deployment
kubectl scale deployment ingestion-service --replicas=3 -n rag-pipeline

# Enable HPA
kubectl apply -f k8s/base/hpa.yaml
```

## Contacts

| Role | Contact |
|------|---------|
| On-Call Engineer | oncall@example.com |
| Platform Team | platform@example.com |
| Security Team | security@example.com |
