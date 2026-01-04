# US-1A.4: Storage Encryption Documentation

> **Epic:** Infrastructure Gaps & Hardening  
> **Priority:** High  
> **Estimated Effort:** 0.5 day  
> **Dependencies:** None  
> **Status:** ✅ Complete

## User Story

**As a** compliance officer  
**I want** all persistent data encrypted at rest with verified storage classes  
**So that** the platform meets data protection requirements and can pass security audits

## Problem Statement

### Current State

- PVCs created without explicit encrypted `storageClassName`
- Transparent Data Encryption (TDE) requirement not verifiably met
- No documentation for cloud-provider specific encryption setup
- Audit cannot verify encryption status

### Impact

- Non-compliance with SOC 2, HIPAA, PCI-DSS requirements
- Potential data exposure if storage is compromised
- Failed security audits
- Risk of regulatory fines

## Architecture Reference

From `docs/architecture.md`:

> **Security:** Encryption at rest for all persistent data

All stateful services require encrypted storage:
- PostgreSQL (document metadata)
- Qdrant (vector embeddings)
- OpenSearch (search indices)
- Redis (cache with persistence)
- MinIO (raw documents)

## Solution Design

### Encryption Matrix

| Service | Data Type | Sensitivity | Encryption Requirement |
|---------|-----------|-------------|----------------------|
| PostgreSQL | Metadata, PII | High | Required |
| Qdrant | Vector embeddings | Medium | Required |
| OpenSearch | Search indices | Medium | Required |
| Redis | Cache, sessions | Medium | Required (if persistent) |
| MinIO | Raw documents | High | Required |

### Cloud Provider Storage Classes

```
┌──────────────────────────────────────────────────────────────────┐
│                    Encrypted Storage by Provider                  │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │    GKE      │  │    EKS      │  │    AKS      │              │
│  │             │  │             │  │             │              │
│  │ premium-rwo │  │   gp3       │  │  managed-   │              │
│  │ (default)   │  │ + KMS       │  │  premium    │              │
│  │             │  │             │  │ + ADE       │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

## Implementation Tasks

### 1. Document GKE Storage Classes

Create `docs/infrastructure/storage-encryption-gke.md`:

```markdown
# GKE Storage Encryption

## Default Encryption

GKE automatically encrypts all data at rest using Google-managed encryption keys.

### Storage Classes

| Storage Class | Type | Encryption | Use Case |
|--------------|------|------------|----------|
| `standard` | pd-standard | AES-256 (Google-managed) | Development |
| `standard-rwo` | pd-balanced | AES-256 (Google-managed) | General workloads |
| `premium-rwo` | pd-ssd | AES-256 (Google-managed) | Production databases |

### Using Customer-Managed Encryption Keys (CMEK)

For enhanced security, use CMEK with Cloud KMS:

```yaml
# k8s/storage/gke-encrypted-storageclass.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: encrypted-premium
provisioner: pd.csi.storage.gke.io
parameters:
  type: pd-ssd
  disk-encryption-kms-key: projects/PROJECT/locations/REGION/keyRings/KEYRING/cryptoKeys/KEY
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Retain
```

### Verification

```bash
# Check disk encryption
gcloud compute disks describe DISK_NAME --zone=ZONE \
  --format="value(diskEncryptionKey.sha256)"

# List storage classes
kubectl get storageclass -o wide
```

## PVC Configuration

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-pvc
  namespace: rag-pipeline
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: premium-rwo  # Encrypted by default
  resources:
    requests:
      storage: 100Gi
```
```

### 2. Document EKS Storage Classes

Create `docs/infrastructure/storage-encryption-eks.md`:

```markdown
# EKS Storage Encryption

## AWS EBS Encryption

EBS volumes can be encrypted with AWS KMS.

### Storage Classes

| Storage Class | Type | Encryption | Use Case |
|--------------|------|------------|----------|
| `gp2` | General Purpose SSD | Optional (KMS) | Legacy |
| `gp3` | General Purpose SSD v3 | Optional (KMS) | Recommended |
| `io1`/`io2` | Provisioned IOPS SSD | Optional (KMS) | High performance |

### Encrypted Storage Class

```yaml
# k8s/storage/eks-encrypted-storageclass.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: encrypted-gp3
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  encrypted: "true"
  kmsKeyId: arn:aws:kms:REGION:ACCOUNT:key/KEY_ID  # Optional: use default if omitted
  iops: "3000"
  throughput: "125"
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Retain
```

### Default Encryption

Enable default encryption for all new EBS volumes:

```bash
# Enable default encryption in the region
aws ec2 enable-ebs-encryption-by-default --region REGION

# Verify
aws ec2 get-ebs-encryption-by-default --region REGION
```

### IAM Policy for KMS

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "kms:Encrypt",
        "kms:Decrypt",
        "kms:ReEncrypt*",
        "kms:GenerateDataKey*",
        "kms:DescribeKey"
      ],
      "Resource": "arn:aws:kms:REGION:ACCOUNT:key/KEY_ID"
    },
    {
      "Effect": "Allow",
      "Action": [
        "kms:CreateGrant"
      ],
      "Resource": "arn:aws:kms:REGION:ACCOUNT:key/KEY_ID",
      "Condition": {
        "Bool": {
          "kms:GrantIsForAWSResource": "true"
        }
      }
    }
  ]
}
```

### Verification

```bash
# Check volume encryption
aws ec2 describe-volumes --volume-ids VOL_ID \
  --query "Volumes[*].{ID:VolumeId,Encrypted:Encrypted,KmsKeyId:KmsKeyId}"

# List storage classes
kubectl get storageclass -o wide
```
```

### 3. Document AKS Storage Classes

Create `docs/infrastructure/storage-encryption-aks.md`:

```markdown
# AKS Storage Encryption

## Azure Disk Encryption

Azure managed disks are encrypted by default with platform-managed keys.

### Storage Classes

| Storage Class | Type | Encryption | Use Case |
|--------------|------|------------|----------|
| `default` | Standard LRS | AES-256 (Platform-managed) | Development |
| `managed-premium` | Premium SSD LRS | AES-256 (Platform-managed) | Production |
| `managed-csi-premium` | Premium SSD v2 | AES-256 (CMK optional) | High performance |

### Customer-Managed Keys (CMK)

```yaml
# k8s/storage/aks-encrypted-storageclass.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: encrypted-premium
provisioner: disk.csi.azure.com
parameters:
  skuName: Premium_LRS
  diskEncryptionSetID: /subscriptions/SUB/resourceGroups/RG/providers/Microsoft.Compute/diskEncryptionSets/DES_NAME
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Retain
```

### Create Disk Encryption Set

```bash
# Create key vault
az keyvault create --name rag-keyvault \
  --resource-group RAG_RG \
  --enable-purge-protection true \
  --enable-soft-delete true

# Create key
az keyvault key create --vault-name rag-keyvault \
  --name rag-disk-key \
  --kty RSA \
  --size 4096

# Get key ID
KEY_URL=$(az keyvault key show --vault-name rag-keyvault \
  --name rag-disk-key \
  --query "key.kid" -o tsv)

# Create disk encryption set
az disk-encryption-set create --name rag-des \
  --resource-group RAG_RG \
  --key-url $KEY_URL \
  --source-vault rag-keyvault
```

### Verification

```bash
# Check disk encryption
az disk show --resource-group MC_RG --name DISK_NAME \
  --query "encryption.type"

# List storage classes
kubectl get storageclass -o wide
```
```

### 4. Update PVC Specifications

Create standardized PVC templates with explicit storage class:

```yaml
# k8s/base/pvc-templates.yaml

# PostgreSQL PVC
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-pvc
  namespace: rag-pipeline
  labels:
    app: postgres
    encryption: required
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: "${ENCRYPTED_STORAGE_CLASS}"
  resources:
    requests:
      storage: 100Gi

# Qdrant PVC
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: qdrant-pvc
  namespace: rag-pipeline
  labels:
    app: qdrant
    encryption: required
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: "${ENCRYPTED_STORAGE_CLASS}"
  resources:
    requests:
      storage: 50Gi

# OpenSearch PVC
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: opensearch-pvc
  namespace: rag-pipeline
  labels:
    app: opensearch
    encryption: required
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: "${ENCRYPTED_STORAGE_CLASS}"
  resources:
    requests:
      storage: 100Gi

# MinIO PVC
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: minio-pvc
  namespace: rag-pipeline
  labels:
    app: minio
    encryption: required
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: "${ENCRYPTED_STORAGE_CLASS}"
  resources:
    requests:
      storage: 500Gi
```

### 5. Create Kustomize Overlays

```yaml
# k8s/overlays/gke/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

bases:
- ../../base

patches:
- target:
    kind: PersistentVolumeClaim
  patch: |
    - op: replace
      path: /spec/storageClassName
      value: premium-rwo

# k8s/overlays/eks/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

bases:
- ../../base

patches:
- target:
    kind: PersistentVolumeClaim
  patch: |
    - op: replace
      path: /spec/storageClassName
      value: encrypted-gp3

# k8s/overlays/aks/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

bases:
- ../../base

patches:
- target:
    kind: PersistentVolumeClaim
  patch: |
    - op: replace
      path: /spec/storageClassName
      value: managed-csi-premium
```

### 6. Create Validation Script

Create `scripts/validate-storage-encryption.sh`:

```bash
#!/bin/bash
# Validate all PVCs use encrypted storage classes

set -e

NAMESPACE=${1:-rag-pipeline}
ENCRYPTED_CLASSES=("premium-rwo" "encrypted-gp3" "managed-csi-premium" "encrypted-premium")

echo "Validating storage encryption for namespace: $NAMESPACE"
echo "=================================================="

# Get all PVCs
PVCS=$(kubectl get pvc -n $NAMESPACE -o jsonpath='{range .items[*]}{.metadata.name}:{.spec.storageClassName}{"\n"}{end}')

FAILURES=0

while IFS=: read -r pvc_name storage_class; do
    if [ -z "$pvc_name" ]; then
        continue
    fi
    
    ENCRYPTED=false
    for enc_class in "${ENCRYPTED_CLASSES[@]}"; do
        if [ "$storage_class" == "$enc_class" ]; then
            ENCRYPTED=true
            break
        fi
    done
    
    if [ "$ENCRYPTED" = true ]; then
        echo "✅ $pvc_name: $storage_class (encrypted)"
    else
        echo "❌ $pvc_name: $storage_class (NOT encrypted)"
        FAILURES=$((FAILURES + 1))
    fi
done <<< "$PVCS"

echo ""
echo "=================================================="
if [ $FAILURES -gt 0 ]; then
    echo "❌ FAILED: $FAILURES PVCs are not using encrypted storage classes"
    exit 1
else
    echo "✅ PASSED: All PVCs use encrypted storage classes"
    exit 0
fi
```

### 7. Add to Deployment Runbook

Create `docs/infrastructure/deployment-runbook.md` (encryption section):

```markdown
## Storage Encryption Verification

### Pre-Deployment Checklist

- [ ] Verify encrypted storage class exists in cluster
- [ ] Confirm KMS keys are created (if using CMEK)
- [ ] IAM permissions for KMS access configured
- [ ] Run validation script

### Verification Steps

1. **Check storage classes:**
   ```bash
   kubectl get storageclass -o wide
   ```

2. **Run encryption validation:**
   ```bash
   ./scripts/validate-storage-encryption.sh rag-pipeline
   ```

3. **Verify individual volumes:**

   **GKE:**
   ```bash
   gcloud compute disks list --filter="labels.kubernetes_io_created-for_pvc_namespace:rag-pipeline" \
     --format="table(name,diskEncryptionKey.sha256)"
   ```

   **EKS:**
   ```bash
   aws ec2 describe-volumes \
     --filters "Name=tag:kubernetes.io/created-for/pvc/namespace,Values=rag-pipeline" \
     --query "Volumes[*].{ID:VolumeId,Encrypted:Encrypted}"
   ```

   **AKS:**
   ```bash
   az disk list --query "[?tags.\"kubernetes.io-created-for-pvc-namespace\"=='rag-pipeline'].{name:name,encryption:encryption.type}"
   ```

### Audit Requirements

For compliance audits, provide:
1. Storage class configuration showing encryption settings
2. KMS key policies (if using CMEK)
3. Volume encryption status report
4. This runbook as evidence of encryption procedures
```

## Acceptance Criteria

- [ ] Storage encryption documented for GKE, EKS, and AKS
- [ ] Encrypted storage classes defined in overlays
- [ ] All PVC specs reference encrypted storage classes
- [ ] Validation script created and tested
- [ ] Deployment runbook includes encryption verification
- [ ] Evidence collection procedure documented for audits

## Verification Commands

```bash
# List storage classes
kubectl get storageclass

# Check PVC storage classes
kubectl get pvc -n rag-pipeline -o custom-columns='NAME:.metadata.name,STORAGE_CLASS:.spec.storageClassName'

# Run validation
./scripts/validate-storage-encryption.sh rag-pipeline
```

## Files Created

| File | Description |
|------|-------------|
| `docs/infrastructure/storage-encryption-gke.md` | GKE encryption guide |
| `docs/infrastructure/storage-encryption-eks.md` | EKS encryption guide |
| `docs/infrastructure/storage-encryption-aks.md` | AKS encryption guide |
| `k8s/base/pvc-templates.yaml` | Standardized PVC templates |
| `k8s/overlays/gke/kustomization.yaml` | GKE storage class overlay |
| `k8s/overlays/eks/kustomization.yaml` | EKS storage class overlay |
| `k8s/overlays/aks/kustomization.yaml` | AKS storage class overlay |
| `scripts/validate-storage-encryption.sh` | Encryption validation script |
| `docs/infrastructure/deployment-runbook.md` | Updated runbook |

## Related Stories

- **US-1.1:** PostgreSQL Setup (uses encrypted storage)
- **US-1.2:** Qdrant Vector Database (uses encrypted storage)
- **US-1.3:** OpenSearch Cluster (uses encrypted storage)
- **US-1.5:** Object Storage (uses encrypted storage)
