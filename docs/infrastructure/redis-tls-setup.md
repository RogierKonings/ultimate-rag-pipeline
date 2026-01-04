# Redis TLS Setup for Production

This guide explains how to enable TLS encryption for Redis and Redis Sentinel in the RAG pipeline production environment.

## Prerequisites

1. **cert-manager** installed in the cluster
2. A **ClusterIssuer** named `rag-ca-issuer` configured
3. Redis and Sentinel already deployed (US-1A.1)

## Step 1: Install cert-manager (if not installed)

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.0/cert-manager.yaml

# Wait for cert-manager to be ready
kubectl wait --for=condition=available --timeout=300s deployment/cert-manager -n cert-manager
kubectl wait --for=condition=available --timeout=300s deployment/cert-manager-webhook -n cert-manager
```

## Step 2: Create ClusterIssuer

Create a self-signed CA for internal services:

```yaml
# k8s/cert-manager/cluster-issuer.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: rag-selfsigned-issuer
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: rag-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: rag-pipeline-ca
  secretName: rag-ca-secret
  privateKey:
    algorithm: ECDSA
    size: 256
  issuerRef:
    name: rag-selfsigned-issuer
    kind: ClusterIssuer
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: rag-ca-issuer
spec:
  ca:
    secretName: rag-ca-secret
```

Apply it:

```bash
kubectl apply -f k8s/cert-manager/cluster-issuer.yaml
```

## Step 3: Deploy Redis TLS Certificates

Apply the certificate resources:

```bash
kubectl apply -f k8s/redis/certificate.yaml
```

Verify certificates are issued:

```bash
kubectl get certificates -n rag-pipeline

# Expected output:
# NAME                 READY   SECRET                      AGE
# redis-tls            True    redis-tls-secret            1m
# redis-sentinel-tls   True    redis-sentinel-tls-secret   1m
```

## Step 4: Update Redis StatefulSet for TLS

Edit `k8s/redis/statefulset.yaml` to enable TLS:

```yaml
spec:
  template:
    spec:
      containers:
        - name: redis
          env:
            - name: TLS_ENABLED
              value: "true"  # Enable TLS
          volumeMounts:
            - name: tls
              mountPath: /tls
              readOnly: true
      volumes:
        - name: tls
          secret:
            secretName: redis-tls-secret
```

## Step 5: Update Sentinel StatefulSet for TLS

Edit `k8s/redis/sentinel-statefulset.yaml`:

```yaml
spec:
  template:
    spec:
      containers:
        - name: sentinel
          env:
            - name: TLS_ENABLED
              value: "true"  # Enable TLS
          volumeMounts:
            - name: tls
              mountPath: /tls
              readOnly: true
      volumes:
        - name: tls
          secret:
            secretName: redis-sentinel-tls-secret
```

## Step 6: Apply Changes

```bash
# Apply updated configs
kubectl apply -f k8s/redis/configmap.yaml
kubectl apply -f k8s/redis/statefulset.yaml
kubectl apply -f k8s/redis/sentinel-statefulset.yaml

# Rolling restart to pick up new configs
kubectl rollout restart statefulset/redis -n rag-pipeline
kubectl rollout restart statefulset/redis-sentinel -n rag-pipeline

# Wait for rollout
kubectl rollout status statefulset/redis -n rag-pipeline
kubectl rollout status statefulset/redis-sentinel -n rag-pipeline
```

## Step 7: Update Application Configuration

Set environment variables for application services:

```bash
# Update deployments with TLS config
kubectl set env deployment/retrieval-service -n rag-pipeline \
  REDIS_TLS_ENABLED=true \
  REDIS_TLS_CA_CERT=/tls/ca.crt \
  REDIS_TLS_CERT=/tls/tls.crt \
  REDIS_TLS_KEY=/tls/tls.key

kubectl set env deployment/ingestion-service -n rag-pipeline \
  REDIS_TLS_ENABLED=true \
  REDIS_TLS_CA_CERT=/tls/ca.crt \
  REDIS_TLS_CERT=/tls/tls.crt \
  REDIS_TLS_KEY=/tls/tls.key
```

Mount the TLS secrets in application pods (add to deployment specs):

```yaml
volumeMounts:
  - name: redis-tls
    mountPath: /tls
    readOnly: true
volumes:
  - name: redis-tls
    secret:
      secretName: redis-tls-secret
```

## Step 8: Verify TLS Connectivity

```bash
# Check Redis TLS is working
kubectl exec -it redis-0 -n rag-pipeline -- \
  redis-cli --tls \
    --cert /tls/tls.crt \
    --key /tls/tls.key \
    --cacert /tls/ca.crt \
    -a $REDIS_PASSWORD \
    PING

# Check TLS certificate details
kubectl exec -it redis-0 -n rag-pipeline -- \
  openssl x509 -in /tls/tls.crt -text -noout | head -20

# Test from application pod
kubectl exec -it deployment/retrieval-service -n rag-pipeline -- \
  python -c "
from cache.redis_client import get_redis_client
r = get_redis_client()
print('TLS connection successful:', r.ping())
"
```

## Rollback Procedure

If TLS causes issues, revert to plaintext:

```bash
# Disable TLS on Redis
kubectl set env statefulset/redis -n rag-pipeline TLS_ENABLED=false
kubectl set env statefulset/redis-sentinel -n rag-pipeline TLS_ENABLED=false

# Disable TLS on applications
kubectl set env deployment/retrieval-service -n rag-pipeline REDIS_TLS_ENABLED=false
kubectl set env deployment/ingestion-service -n rag-pipeline REDIS_TLS_ENABLED=false

# Restart
kubectl rollout restart statefulset/redis -n rag-pipeline
kubectl rollout restart statefulset/redis-sentinel -n rag-pipeline
kubectl rollout restart deployment -n rag-pipeline
```

## Certificate Renewal

cert-manager automatically renews certificates before expiry (30 days before by default). Monitor certificate status:

```bash
# Check certificate expiry
kubectl get certificates -n rag-pipeline -o wide

# View certificate events
kubectl describe certificate redis-tls -n rag-pipeline
```

## Troubleshooting

### Connection Refused

Check that TLS port is enabled:

```bash
kubectl exec -it redis-0 -n rag-pipeline -- redis-cli INFO server | grep tcp_port
# Should show: tcp_port:0 (plaintext disabled)
# And: tls_port:6379
```

### Certificate Errors

Verify certificate chain:

```bash
kubectl exec -it redis-0 -n rag-pipeline -- \
  openssl verify -CAfile /tls/ca.crt /tls/tls.crt
```

### Sentinel Can't Connect to Redis

Ensure Sentinel uses the same CA:

```bash
kubectl exec -it redis-sentinel-0 -n rag-pipeline -- \
  redis-cli -p 26379 --tls \
    --cert /tls/tls.crt \
    --key /tls/tls.key \
    --cacert /tls/ca.crt \
    SENTINEL master mymaster
```

## Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_TLS_ENABLED` | Enable TLS for Redis connections | `false` |
| `REDIS_TLS_CA_CERT` | Path to CA certificate | `/tls/ca.crt` |
| `REDIS_TLS_CERT` | Path to client certificate | `/tls/tls.crt` |
| `REDIS_TLS_KEY` | Path to client private key | `/tls/tls.key` |

## Related Documentation

- [Redis Sentinel HA](./redis-sentinel-ha.md)
- [Architecture Overview](../architecture.md)
