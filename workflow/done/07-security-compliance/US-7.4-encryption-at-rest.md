# US-7.4: Encryption at Rest

> **Epic:** Security & Compliance  
> **Priority:** High  
> **Estimated Effort:** 1-2 days  
> **Dependencies:** Epic 1 (Infrastructure)

## User Story

**As a** security engineer  
**I want** data encrypted at rest  
**So that** data is protected from unauthorized access even if storage is compromised

## Objective

Configure encryption at rest for all data stores (PostgreSQL, Qdrant, OpenSearch, MinIO/S3) using industry-standard encryption (AES-256), implement key management with HashiCorp Vault or AWS KMS, and establish key rotation procedures.

## Architecture Reference

- **Algorithm:** AES-256-GCM for all encryption
- **Key Management:** HashiCorp Vault or AWS KMS
- **PostgreSQL:** Transparent Data Encryption (TDE) via pgcrypto
- **Qdrant:** Disk-level encryption
- **OpenSearch:** Node-level encryption
- **MinIO/S3:** Server-Side Encryption (SSE)

## Implementation Tasks

### 1. Configure PostgreSQL Encryption

#### Option A: Volume-Level Encryption (Recommended for Kubernetes)

`infrastructure/k8s/postgres/pvc-encrypted.yaml`:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-pvc-encrypted
  namespace: rag-pipeline
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: encrypted-gp3  # Use encrypted storage class
  resources:
    requests:
      storage: 100Gi
---
# Storage class with encryption (AWS EKS example)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: encrypted-gp3
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  encrypted: "true"
  kmsKeyId: "alias/rag-pipeline-encryption"  # KMS key alias
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
```

#### Option B: Application-Level Field Encryption

`services/shared/security/encryption/field_encryption.py`:

```python
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import base64
import os
from typing import Optional, Union
import structlog

logger = structlog.get_logger(__name__)


class FieldEncryption:
    """AES-256-GCM encryption for sensitive database fields."""
    
    def __init__(self, key: bytes):
        """
        Initialize with encryption key.
        
        Args:
            key: 32-byte (256-bit) encryption key
        """
        if len(key) != 32:
            raise ValueError("Key must be 32 bytes for AES-256")
        self.aesgcm = AESGCM(key)
    
    @classmethod
    def from_password(cls, password: str, salt: bytes = None) -> "FieldEncryption":
        """Derive encryption key from password."""
        if salt is None:
            salt = os.urandom(16)
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        key = kdf.derive(password.encode())
        return cls(key)
    
    @classmethod
    def from_base64_key(cls, key_b64: str) -> "FieldEncryption":
        """Initialize from base64-encoded key."""
        key = base64.b64decode(key_b64)
        return cls(key)
    
    def encrypt(self, plaintext: Union[str, bytes]) -> str:
        """
        Encrypt data and return base64-encoded ciphertext.
        
        Format: base64(nonce || ciphertext || tag)
        """
        if isinstance(plaintext, str):
            plaintext = plaintext.encode('utf-8')
        
        nonce = os.urandom(12)  # 96-bit nonce for GCM
        ciphertext = self.aesgcm.encrypt(nonce, plaintext, None)
        
        # Combine nonce + ciphertext (tag is appended by AESGCM)
        encrypted = nonce + ciphertext
        return base64.b64encode(encrypted).decode('utf-8')
    
    def decrypt(self, encrypted_b64: str) -> str:
        """Decrypt base64-encoded ciphertext."""
        encrypted = base64.b64decode(encrypted_b64)
        
        # Extract nonce and ciphertext
        nonce = encrypted[:12]
        ciphertext = encrypted[12:]
        
        plaintext = self.aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode('utf-8')
    
    def encrypt_dict(self, data: dict, fields: list[str]) -> dict:
        """Encrypt specific fields in a dictionary."""
        result = data.copy()
        for field in fields:
            if field in result and result[field] is not None:
                result[field] = self.encrypt(str(result[field]))
        return result
    
    def decrypt_dict(self, data: dict, fields: list[str]) -> dict:
        """Decrypt specific fields in a dictionary."""
        result = data.copy()
        for field in fields:
            if field in result and result[field] is not None:
                try:
                    result[field] = self.decrypt(result[field])
                except Exception as e:
                    logger.error("field_decryption_failed", field=field, error=str(e))
                    result[field] = None
        return result


class EncryptionKeyManager:
    """Manage encryption keys with rotation support."""
    
    def __init__(self, vault_client=None, key_id: str = "rag-encryption-key"):
        self.vault_client = vault_client
        self.key_id = key_id
        self._current_key: Optional[bytes] = None
        self._key_version: int = 0
    
    async def get_current_key(self) -> tuple[bytes, int]:
        """Get current encryption key and version."""
        if self._current_key is None:
            await self._load_key()
        return self._current_key, self._key_version
    
    async def _load_key(self):
        """Load key from Vault or environment."""
        if self.vault_client:
            # Load from Vault
            secret = await self.vault_client.read_secret(f"secret/data/{self.key_id}")
            self._current_key = base64.b64decode(secret["key"])
            self._key_version = secret.get("version", 1)
        else:
            # Load from environment
            key_b64 = os.environ.get("ENCRYPTION_KEY")
            if not key_b64:
                raise ValueError("ENCRYPTION_KEY environment variable not set")
            self._current_key = base64.b64decode(key_b64)
            self._key_version = int(os.environ.get("ENCRYPTION_KEY_VERSION", "1"))
    
    async def rotate_key(self) -> tuple[bytes, int]:
        """Generate new key and store in Vault."""
        new_key = os.urandom(32)
        new_version = self._key_version + 1
        
        if self.vault_client:
            await self.vault_client.write_secret(
                f"secret/data/{self.key_id}",
                {
                    "key": base64.b64encode(new_key).decode(),
                    "version": new_version,
                    "previous_version": self._key_version,
                }
            )
        
        self._current_key = new_key
        self._key_version = new_version
        
        logger.info("encryption_key_rotated", new_version=new_version)
        return new_key, new_version


# Generate new encryption key
def generate_encryption_key() -> str:
    """Generate a new 256-bit encryption key."""
    key = os.urandom(32)
    return base64.b64encode(key).decode('utf-8')
```

### 2. Create SQLAlchemy Encrypted Type

`services/shared/database/types/encrypted.py`:

```python
from sqlalchemy import TypeDecorator, String
from typing import Optional
import os

from shared.security.encryption.field_encryption import FieldEncryption


class EncryptedString(TypeDecorator):
    """SQLAlchemy type for encrypted string fields."""
    
    impl = String
    cache_ok = True
    
    def __init__(self, length: int = 4096):
        super().__init__(length)
        key_b64 = os.environ.get("FIELD_ENCRYPTION_KEY")
        if key_b64:
            self._encryptor = FieldEncryption.from_base64_key(key_b64)
        else:
            self._encryptor = None
    
    def process_bind_param(self, value: Optional[str], dialect) -> Optional[str]:
        """Encrypt value before storing."""
        if value is None or self._encryptor is None:
            return value
        return self._encryptor.encrypt(value)
    
    def process_result_value(self, value: Optional[str], dialect) -> Optional[str]:
        """Decrypt value after loading."""
        if value is None or self._encryptor is None:
            return value
        try:
            return self._encryptor.decrypt(value)
        except Exception:
            return value  # Return as-is if decryption fails


class EncryptedJSON(TypeDecorator):
    """SQLAlchemy type for encrypted JSON fields."""
    
    impl = String
    cache_ok = True
    
    def __init__(self, length: int = 65536):
        super().__init__(length)
        key_b64 = os.environ.get("FIELD_ENCRYPTION_KEY")
        if key_b64:
            self._encryptor = FieldEncryption.from_base64_key(key_b64)
        else:
            self._encryptor = None
    
    def process_bind_param(self, value, dialect) -> Optional[str]:
        if value is None or self._encryptor is None:
            return value
        import json
        json_str = json.dumps(value)
        return self._encryptor.encrypt(json_str)
    
    def process_result_value(self, value: Optional[str], dialect):
        if value is None or self._encryptor is None:
            return value
        try:
            import json
            decrypted = self._encryptor.decrypt(value)
            return json.loads(decrypted)
        except Exception:
            return value
```

### 3. Configure Qdrant Disk Encryption

`infrastructure/k8s/qdrant/statefulset-encrypted.yaml`:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: qdrant
  namespace: rag-pipeline
spec:
  serviceName: qdrant
  replicas: 3
  selector:
    matchLabels:
      app: qdrant
  template:
    metadata:
      labels:
        app: qdrant
    spec:
      containers:
      - name: qdrant
        image: qdrant/qdrant:v1.7.0
        ports:
        - containerPort: 6333
        - containerPort: 6334
        env:
        - name: QDRANT__STORAGE__STORAGE_PATH
          value: /qdrant/storage
        volumeMounts:
        - name: qdrant-storage
          mountPath: /qdrant/storage
  volumeClaimTemplates:
  - metadata:
      name: qdrant-storage
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: encrypted-gp3  # Encrypted storage class
      resources:
        requests:
          storage: 50Gi
```

### 4. Configure OpenSearch Encryption

`infrastructure/k8s/opensearch/configmap-security.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: opensearch-config
  namespace: rag-pipeline
data:
  opensearch.yml: |
    cluster.name: rag-opensearch
    node.name: ${HOSTNAME}
    network.host: 0.0.0.0
    
    # Security settings
    plugins.security.disabled: false
    plugins.security.ssl.http.enabled: true
    plugins.security.ssl.transport.enabled: true
    
    # Encryption at rest (requires OpenSearch 2.x+)
    # Note: Actual encryption is handled at storage level
    plugins.security.audit.type: internal_opensearch
    plugins.security.audit.config.index: .opendistro-audit-log
```

`infrastructure/k8s/opensearch/statefulset-encrypted.yaml`:

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
        image: opensearchproject/opensearch:2.11.0
        ports:
        - containerPort: 9200
        - containerPort: 9300
        env:
        - name: cluster.name
          value: rag-opensearch
        - name: OPENSEARCH_JAVA_OPTS
          value: "-Xms2g -Xmx2g"
        volumeMounts:
        - name: opensearch-data
          mountPath: /usr/share/opensearch/data
        - name: opensearch-config
          mountPath: /usr/share/opensearch/config/opensearch.yml
          subPath: opensearch.yml
      volumes:
      - name: opensearch-config
        configMap:
          name: opensearch-config
  volumeClaimTemplates:
  - metadata:
      name: opensearch-data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: encrypted-gp3
      resources:
        requests:
          storage: 100Gi
```

### 5. Configure MinIO/S3 Server-Side Encryption

`infrastructure/k8s/minio/deployment-sse.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: minio
  namespace: rag-pipeline
spec:
  replicas: 1
  selector:
    matchLabels:
      app: minio
  template:
    metadata:
      labels:
        app: minio
    spec:
      containers:
      - name: minio
        image: minio/minio:RELEASE.2024-01-01T00-00-00Z
        args:
        - server
        - /data
        - --console-address
        - ":9001"
        env:
        - name: MINIO_ROOT_USER
          valueFrom:
            secretKeyRef:
              name: minio-credentials
              key: root-user
        - name: MINIO_ROOT_PASSWORD
          valueFrom:
            secretKeyRef:
              name: minio-credentials
              key: root-password
        # Enable SSE-S3 (server-side encryption)
        - name: MINIO_KMS_SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: minio-kms
              key: secret-key
        ports:
        - containerPort: 9000
        - containerPort: 9001
        volumeMounts:
        - name: minio-data
          mountPath: /data
      volumes:
      - name: minio-data
        persistentVolumeClaim:
          claimName: minio-pvc
```

`services/shared/storage/s3_client.py`:

```python
import aioboto3
from typing import BinaryIO, Optional
import structlog

logger = structlog.get_logger(__name__)


class EncryptedS3Client:
    """S3 client with server-side encryption enabled."""
    
    def __init__(
        self,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
        sse_algorithm: str = "AES256",  # or "aws:kms"
        kms_key_id: Optional[str] = None,
    ):
        self.endpoint_url = endpoint_url
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.region = region
        self.sse_algorithm = sse_algorithm
        self.kms_key_id = kms_key_id
        self.session = aioboto3.Session()
    
    def _get_sse_params(self) -> dict:
        """Get SSE parameters for upload."""
        if self.sse_algorithm == "aws:kms" and self.kms_key_id:
            return {
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": self.kms_key_id,
            }
        return {
            "ServerSideEncryption": "AES256",
        }
    
    async def upload_file(
        self,
        key: str,
        data: BinaryIO,
        content_type: str = "application/octet-stream",
        metadata: dict = None,
    ) -> str:
        """Upload file with server-side encryption."""
        async with self.session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        ) as s3:
            extra_args = {
                "ContentType": content_type,
                **self._get_sse_params(),
            }
            if metadata:
                extra_args["Metadata"] = metadata
            
            await s3.upload_fileobj(
                data,
                self.bucket,
                key,
                ExtraArgs=extra_args,
            )
            
            logger.info(
                "file_uploaded_encrypted",
                bucket=self.bucket,
                key=key,
                sse=self.sse_algorithm,
            )
            
            return f"s3://{self.bucket}/{key}"
    
    async def download_file(self, key: str) -> bytes:
        """Download and decrypt file."""
        async with self.session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        ) as s3:
            response = await s3.get_object(Bucket=self.bucket, Key=key)
            data = await response["Body"].read()
            return data
    
    async def set_bucket_encryption(self) -> None:
        """Enable default encryption on bucket."""
        async with self.session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        ) as s3:
            encryption_config = {
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": self.sse_algorithm,
                        },
                        "BucketKeyEnabled": True,
                    }
                ]
            }
            
            if self.sse_algorithm == "aws:kms" and self.kms_key_id:
                encryption_config["Rules"][0]["ApplyServerSideEncryptionByDefault"]["KMSMasterKeyID"] = self.kms_key_id
            
            await s3.put_bucket_encryption(
                Bucket=self.bucket,
                ServerSideEncryptionConfiguration=encryption_config,
            )
            
            logger.info(
                "bucket_encryption_enabled",
                bucket=self.bucket,
                algorithm=self.sse_algorithm,
            )
```

### 6. Key Rotation Script

`scripts/rotate-encryption-keys.sh`:

```bash
#!/bin/bash
set -e

# Rotate encryption keys in Vault
# Usage: ./rotate-encryption-keys.sh [key-name]

KEY_NAME="${1:-rag-encryption-key}"
VAULT_ADDR="${VAULT_ADDR:-https://vault.rag-pipeline.svc:8200}"

echo "Rotating encryption key: $KEY_NAME"

# Generate new key
NEW_KEY=$(openssl rand -base64 32)
CURRENT_VERSION=$(vault kv get -field=version secret/$KEY_NAME 2>/dev/null || echo "0")
NEW_VERSION=$((CURRENT_VERSION + 1))

# Store current key as previous (for decryption during migration)
CURRENT_KEY=$(vault kv get -field=key secret/$KEY_NAME 2>/dev/null || echo "")

# Write new key to Vault
vault kv put secret/$KEY_NAME \
  key="$NEW_KEY" \
  version="$NEW_VERSION" \
  previous_key="$CURRENT_KEY" \
  previous_version="$CURRENT_VERSION" \
  rotated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "Key rotated successfully. New version: $NEW_VERSION"
echo ""
echo "Next steps:"
echo "1. Update application deployments to use new key version"
echo "2. Run re-encryption job for existing data"
echo "3. Remove previous_key after migration is complete"
```

### 7. Create Tests

`tests/security/test_encryption.py`:

```python
import pytest
import base64
import os

from shared.security.encryption.field_encryption import (
    FieldEncryption,
    generate_encryption_key,
)


@pytest.fixture
def encryption_key():
    return os.urandom(32)


@pytest.fixture
def encryptor(encryption_key):
    return FieldEncryption(encryption_key)


class TestFieldEncryption:
    def test_encrypt_decrypt_string(self, encryptor):
        plaintext = "Hello, World! This is sensitive data."
        
        encrypted = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(encrypted)
        
        assert encrypted != plaintext
        assert decrypted == plaintext
    
    def test_encrypt_produces_different_ciphertext(self, encryptor):
        plaintext = "Same message"
        
        encrypted1 = encryptor.encrypt(plaintext)
        encrypted2 = encryptor.encrypt(plaintext)
        
        # Due to random nonce, ciphertext should differ
        assert encrypted1 != encrypted2
    
    def test_decrypt_with_wrong_key_fails(self, encryptor):
        plaintext = "Secret message"
        encrypted = encryptor.encrypt(plaintext)
        
        wrong_key = os.urandom(32)
        wrong_encryptor = FieldEncryption(wrong_key)
        
        with pytest.raises(Exception):
            wrong_encryptor.decrypt(encrypted)
    
    def test_encrypt_dict_fields(self, encryptor):
        data = {
            "id": "123",
            "email": "user@example.com",
            "ssn": "123-45-6789",
            "name": "John Doe",
        }
        
        encrypted = encryptor.encrypt_dict(data, ["email", "ssn"])
        
        assert encrypted["id"] == "123"  # Not encrypted
        assert encrypted["name"] == "John Doe"  # Not encrypted
        assert encrypted["email"] != "user@example.com"  # Encrypted
        assert encrypted["ssn"] != "123-45-6789"  # Encrypted
    
    def test_decrypt_dict_fields(self, encryptor):
        data = {
            "email": "user@example.com",
            "ssn": "123-45-6789",
        }
        
        encrypted = encryptor.encrypt_dict(data, ["email", "ssn"])
        decrypted = encryptor.decrypt_dict(encrypted, ["email", "ssn"])
        
        assert decrypted == data
    
    def test_from_password(self):
        password = "my-secure-password"
        salt = b"fixed-salt-1234"
        
        encryptor1 = FieldEncryption.from_password(password, salt)
        encryptor2 = FieldEncryption.from_password(password, salt)
        
        plaintext = "Test message"
        encrypted = encryptor1.encrypt(plaintext)
        decrypted = encryptor2.decrypt(encrypted)
        
        assert decrypted == plaintext
    
    def test_generate_key(self):
        key = generate_encryption_key()
        
        # Should be base64-encoded 32-byte key
        decoded = base64.b64decode(key)
        assert len(decoded) == 32
    
    def test_empty_string(self, encryptor):
        plaintext = ""
        encrypted = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(encrypted)
        
        assert decrypted == plaintext
    
    def test_unicode_content(self, encryptor):
        plaintext = "日本語テスト 🔐 émojis"
        encrypted = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(encrypted)
        
        assert decrypted == plaintext
```

## Acceptance Criteria

- [ ] PostgreSQL volumes use encrypted storage class
- [ ] Field-level encryption available for sensitive columns
- [ ] Qdrant uses encrypted persistent volumes
- [ ] OpenSearch uses encrypted persistent volumes
- [ ] MinIO/S3 has server-side encryption enabled
- [ ] Encryption keys stored in Vault/KMS
- [ ] Key rotation procedure documented and tested
- [ ] All encryption uses AES-256
- [ ] Unit tests for encryption utilities passing

## Verification Commands

```bash
# Verify PostgreSQL PVC is encrypted (AWS)
kubectl get pvc postgres-pvc -n rag-pipeline -o yaml | grep storageClassName
# Should show: encrypted-gp3

# Verify S3 bucket encryption
aws s3api get-bucket-encryption --bucket rag-documents
# Should show SSEAlgorithm: AES256 or aws:kms

# Test field encryption
python -c "
from shared.security.encryption.field_encryption import FieldEncryption, generate_encryption_key
import base64

key = base64.b64decode(generate_encryption_key())
enc = FieldEncryption(key)
encrypted = enc.encrypt('test-data')
print(f'Encrypted: {encrypted}')
print(f'Decrypted: {enc.decrypt(encrypted)}')
"

# Run encryption tests
pytest tests/security/test_encryption.py -v

# Check Vault key
vault kv get secret/rag-encryption-key
```

## Environment Variables

```bash
# Field-level encryption key (base64-encoded 32 bytes)
FIELD_ENCRYPTION_KEY=base64-encoded-32-byte-key

# Key version for rotation tracking
ENCRYPTION_KEY_VERSION=1

# Vault configuration for key management
VAULT_ADDR=https://vault.rag-pipeline.svc:8200
VAULT_TOKEN=s.xxxxx

# S3/MinIO SSE configuration
S3_SSE_ALGORITHM=AES256
S3_KMS_KEY_ID=alias/rag-pipeline-encryption
```

## Files to Create

1. `services/shared/security/encryption/__init__.py`
2. `services/shared/security/encryption/field_encryption.py`
3. `services/shared/database/types/encrypted.py`
4. `services/shared/storage/s3_client.py`
5. `infrastructure/k8s/storage-classes/encrypted-gp3.yaml`
6. `infrastructure/k8s/postgres/pvc-encrypted.yaml`
7. `infrastructure/k8s/qdrant/statefulset-encrypted.yaml`
8. `infrastructure/k8s/opensearch/statefulset-encrypted.yaml`
9. `infrastructure/k8s/minio/deployment-sse.yaml`
10. `scripts/rotate-encryption-keys.sh`
11. `tests/security/test_encryption.py`

## Security Considerations

- **Key separation** - Use different keys for different data classifications
- **Key rotation** - Rotate keys at least annually
- **Key backup** - Ensure key recovery procedures exist
- **Hardware security** - Consider HSM for production key storage
- **Never log keys** - Encryption keys must never appear in logs
- **Encrypt backups** - Backup data should also be encrypted
