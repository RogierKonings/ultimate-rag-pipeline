# GKE Storage Encryption

## Overview

Google Kubernetes Engine (GKE) automatically encrypts all data at rest using Google-managed encryption keys. This document describes how to configure and verify storage encryption for the RAG Pipeline on GKE.

## Default Encryption

All GKE persistent disks are encrypted by default with AES-256 using Google-managed keys. No additional configuration is required for basic encryption.

## Storage Classes

| Storage Class | Type | Encryption | Use Case |
|---------------|------|------------|----------|
| `standard` | pd-standard | AES-256 (Google-managed) | Development |
| `standard-rwo` | pd-balanced | AES-256 (Google-managed) | General workloads |
| `premium-rwo` | pd-ssd | AES-256 (Google-managed) | Production databases |

## Using Customer-Managed Encryption Keys (CMEK)

For enhanced security and compliance, use CMEK with Cloud KMS:

### 1. Create a KMS Key

```bash
# Create a key ring
gcloud kms keyrings create rag-pipeline-keyring \
  --location=REGION \
  --project=PROJECT_ID

# Create a key
gcloud kms keys create rag-storage-key \
  --location=REGION \
  --keyring=rag-pipeline-keyring \
  --purpose=encryption \
  --project=PROJECT_ID

# Grant the GKE service account access
gcloud kms keys add-iam-policy-binding rag-storage-key \
  --location=REGION \
  --keyring=rag-pipeline-keyring \
  --member="serviceAccount:service-PROJECT_NUMBER@compute-system.iam.gserviceaccount.com" \
  --role="roles/cloudkms.cryptoKeyEncrypterDecrypter" \
  --project=PROJECT_ID
```

### 2. Create Encrypted Storage Class

```yaml
# k8s/storage/gke-encrypted-storageclass.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: encrypted-premium
provisioner: pd.csi.storage.gke.io
parameters:
  type: pd-ssd
  disk-encryption-kms-key: projects/PROJECT_ID/locations/REGION/keyRings/rag-pipeline-keyring/cryptoKeys/rag-storage-key
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Retain
```

## PVC Configuration

All PVCs in the RAG Pipeline should use encrypted storage:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-pvc
  namespace: rag-pipeline
  labels:
    encryption: required
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: premium-rwo  # Encrypted by default
  resources:
    requests:
      storage: 100Gi
```

## Verification

### Check Storage Class

```bash
kubectl get storageclass -o wide
```

### Verify Disk Encryption

```bash
# List disks with encryption info
gcloud compute disks list \
  --filter="labels.kubernetes_io_created-for_pvc_namespace:rag-pipeline" \
  --format="table(name,diskEncryptionKey.sha256,diskEncryptionKey.kmsKeyName)"

# Check specific disk
gcloud compute disks describe DISK_NAME --zone=ZONE \
  --format="yaml(diskEncryptionKey)"
```

### Verify CMEK is Applied

```bash
# For CMEK-encrypted disks, this shows the KMS key
gcloud compute disks describe DISK_NAME --zone=ZONE \
  --format="value(diskEncryptionKey.kmsKeyName)"
```

## Audit Compliance

For SOC 2/HIPAA audits, provide:

1. **Storage class configuration** showing encryption parameters
2. **KMS key policies** (if using CMEK)
3. **Disk encryption status** from `gcloud compute disks list`
4. **IAM bindings** for KMS access

## Troubleshooting

### Disk Creation Fails with KMS Error

Ensure the compute service account has `cloudkms.cryptoKeyEncrypterDecrypter` role:

```bash
gcloud kms keys get-iam-policy rag-storage-key \
  --location=REGION \
  --keyring=rag-pipeline-keyring
```

### Storage Class Not Found

Verify the CSI driver is installed:

```bash
kubectl get csidrivers
# Should show pd.csi.storage.gke.io
```
