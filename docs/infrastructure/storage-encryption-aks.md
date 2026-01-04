# AKS Storage Encryption

## Overview

Azure Kubernetes Service (AKS) uses Azure Managed Disks for persistent storage. All managed disks are encrypted at rest by default using platform-managed keys (PMK).

## Default Encryption

Azure encrypts all managed disks with AES-256 using platform-managed keys. No configuration required for basic encryption.

## Storage Classes

| Storage Class | Type | Encryption | Use Case |
|---------------|------|------------|----------|
| `default` | Standard HDD | AES-256 (PMK) | Development |
| `managed-csi` | Standard SSD | AES-256 (PMK) | General workloads |
| `managed-csi-premium` | Premium SSD | AES-256 (PMK) | Production databases |

## Customer-Managed Keys (CMK)

For enhanced security, use Azure Disk Encryption with customer-managed keys in Key Vault.

### 1. Create Key Vault and Key

```bash
# Create a Key Vault
az keyvault create \
  --name rag-pipeline-kv \
  --resource-group RESOURCE_GROUP \
  --location LOCATION \
  --enable-purge-protection true \
  --enable-soft-delete true

# Create a key
az keyvault key create \
  --vault-name rag-pipeline-kv \
  --name rag-disk-key \
  --protection software \
  --kty RSA \
  --size 4096
```

### 2. Create Disk Encryption Set

```bash
# Get Key ID
KEY_URL=$(az keyvault key show \
  --vault-name rag-pipeline-kv \
  --name rag-disk-key \
  --query "key.kid" -o tsv)

# Create Disk Encryption Set
az disk-encryption-set create \
  --name rag-pipeline-des \
  --resource-group RESOURCE_GROUP \
  --location LOCATION \
  --source-vault rag-pipeline-kv \
  --key-url "$KEY_URL"

# Get Disk Encryption Set ID
DES_ID=$(az disk-encryption-set show \
  --name rag-pipeline-des \
  --resource-group RESOURCE_GROUP \
  --query "id" -o tsv)

# Grant access to Key Vault
DES_PRINCIPAL=$(az disk-encryption-set show \
  --name rag-pipeline-des \
  --resource-group RESOURCE_GROUP \
  --query "identity.principalId" -o tsv)

az keyvault set-policy \
  --name rag-pipeline-kv \
  --object-id "$DES_PRINCIPAL" \
  --key-permissions wrapkey unwrapkey get
```

### 3. Create Encrypted Storage Class

```yaml
# k8s/storage/aks-encrypted-storageclass.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: encrypted-premium-cmk
provisioner: disk.csi.azure.com
parameters:
  skuName: Premium_LRS
  diskEncryptionSetID: /subscriptions/SUBSCRIPTION_ID/resourceGroups/RESOURCE_GROUP/providers/Microsoft.Compute/diskEncryptionSets/rag-pipeline-des
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Retain
```

## Server-Side Encryption with Platform-Managed Keys

For most use cases, the default encryption is sufficient:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: encrypted-premium
provisioner: disk.csi.azure.com
parameters:
  skuName: Premium_LRS
  # Azure encrypts by default with platform-managed keys
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Retain
```

## PVC Configuration

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
  storageClassName: managed-csi-premium  # Encrypted by default
  resources:
    requests:
      storage: 100Gi
```

## Verification

### Check Storage Classes

```bash
kubectl get storageclass -o wide
```

### Verify Disk Encryption

```bash
# List disks with encryption info
az disk list \
  --query "[?tags.\"kubernetes.io-created-for-pvc-namespace\"=='rag-pipeline'].{name:name,encryption:encryption.type,diskEncryptionSetId:encryption.diskEncryptionSetId}" \
  --output table

# Check specific disk
az disk show \
  --name DISK_NAME \
  --resource-group MC_RESOURCE_GROUP \
  --query "{encryption:encryption.type,diskEncryptionSetId:encryption.diskEncryptionSetId}"
```

### Verify Disk Encryption Set

```bash
az disk-encryption-set show \
  --name rag-pipeline-des \
  --resource-group RESOURCE_GROUP
```

## Host-Based Encryption

For encryption of temp disks and caches, enable host-based encryption:

```bash
# Enable on node pool
az aks nodepool update \
  --resource-group RESOURCE_GROUP \
  --cluster-name CLUSTER_NAME \
  --name nodepool1 \
  --enable-encryption-at-host
```

## Audit Compliance

For SOC 2/HIPAA audits, provide:

1. **Storage class configuration** showing encryption settings
2. **Disk encryption status** from `az disk list`
3. **Key Vault access policies** (if using CMK)
4. **Disk Encryption Set configuration**

## Troubleshooting

### Disk Creation Fails with Encryption Error

Check Disk Encryption Set permissions:

```bash
az disk-encryption-set show \
  --name rag-pipeline-des \
  --resource-group RESOURCE_GROUP \
  --query "identity"
```

Verify Key Vault access:

```bash
az keyvault show \
  --name rag-pipeline-kv \
  --query "properties.accessPolicies"
```

### CSI Driver Not Working

Verify the Azure Disk CSI driver:

```bash
kubectl get csidrivers disk.csi.azure.com
kubectl get pods -n kube-system -l app=csi-azuredisk-node
```
