# EKS Storage Encryption

## Overview

Amazon EKS uses EBS volumes for persistent storage. EBS encryption can be enabled per-volume or as a default for all new volumes in a region.

## Default Encryption

Enable default EBS encryption for all new volumes:

```bash
# Enable default encryption in the region
aws ec2 enable-ebs-encryption-by-default --region REGION

# Verify
aws ec2 get-ebs-encryption-by-default --region REGION
```

## Storage Classes

| Storage Class | Type | Encryption | Use Case |
|---------------|------|------------|----------|
| `gp2` | General Purpose SSD | Optional (KMS) | Legacy |
| `gp3` | General Purpose SSD v3 | Optional (KMS) | Recommended |
| `io1`/`io2` | Provisioned IOPS SSD | Optional (KMS) | High performance |

## Encrypted Storage Class

### Using AWS Managed Key

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
  # Uses default AWS managed key (aws/ebs)
  iops: "3000"
  throughput: "125"
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Retain
```

### Using Customer Managed Key (CMK)

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: encrypted-gp3-cmk
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  encrypted: "true"
  kmsKeyId: arn:aws:kms:REGION:ACCOUNT_ID:key/KEY_ID
  iops: "3000"
  throughput: "125"
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Retain
```

## KMS Key Setup

### Create a CMK

```bash
# Create the key
aws kms create-key \
  --description "RAG Pipeline EBS encryption key" \
  --tags TagKey=Application,TagValue=rag-pipeline

# Create an alias
aws kms create-alias \
  --alias-name alias/rag-pipeline-ebs \
  --target-key-id KEY_ID
```

### IAM Policy for EBS CSI Driver

The EBS CSI driver service account needs KMS permissions:

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
      "Resource": "arn:aws:kms:REGION:ACCOUNT_ID:key/KEY_ID"
    },
    {
      "Effect": "Allow",
      "Action": [
        "kms:CreateGrant"
      ],
      "Resource": "arn:aws:kms:REGION:ACCOUNT_ID:key/KEY_ID",
      "Condition": {
        "Bool": {
          "kms:GrantIsForAWSResource": "true"
        }
      }
    }
  ]
}
```

Attach to the EBS CSI driver IAM role:

```bash
aws iam put-role-policy \
  --role-name AmazonEKS_EBS_CSI_DriverRole \
  --policy-name EBSEncryptionPolicy \
  --policy-document file://ebs-kms-policy.json
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
  storageClassName: encrypted-gp3
  resources:
    requests:
      storage: 100Gi
```

## Verification

### Check Storage Classes

```bash
kubectl get storageclass -o wide
```

### Verify Volume Encryption

```bash
# List all volumes for the namespace
aws ec2 describe-volumes \
  --filters "Name=tag:kubernetes.io/created-for/pvc/namespace,Values=rag-pipeline" \
  --query "Volumes[*].{ID:VolumeId,Encrypted:Encrypted,KmsKeyId:KmsKeyId}" \
  --output table

# Check specific volume
aws ec2 describe-volumes --volume-ids vol-XXXXX \
  --query "Volumes[0].{Encrypted:Encrypted,KmsKeyId:KmsKeyId}"
```

### Verify Default Encryption

```bash
aws ec2 get-ebs-encryption-by-default --region REGION
```

## Audit Compliance

For SOC 2/HIPAA/PCI-DSS audits, provide:

1. **Storage class manifests** showing `encrypted: "true"`
2. **Default encryption status** from `get-ebs-encryption-by-default`
3. **Volume encryption report** from `describe-volumes`
4. **KMS key policy** (if using CMK)
5. **IAM role policies** for EBS CSI driver

## Troubleshooting

### Volume Creation Fails with KMS Error

Check IAM permissions:

```bash
# Verify the EBS CSI driver role
aws iam get-role-policy \
  --role-name AmazonEKS_EBS_CSI_DriverRole \
  --policy-name EBSEncryptionPolicy
```

### EBS CSI Driver Not Working

Verify the addon is installed:

```bash
aws eks describe-addon \
  --cluster-name CLUSTER_NAME \
  --addon-name aws-ebs-csi-driver
```
