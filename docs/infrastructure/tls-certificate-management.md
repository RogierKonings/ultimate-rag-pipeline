# TLS Certificate Management

> **Version:** 1.0  
> **Status:** Production Ready  
> **Last Updated:** January 2026  
> **Related:** US-1.9, US-7.10

## Overview

This document describes the TLS certificate management strategy for the RAG Pipeline, including:
- Certificate issuance via cert-manager and Let's Encrypt
- TLS 1.3 enforcement on ingress
- Automatic certificate renewal
- mTLS readiness for internal services
- Network policies for namespace isolation

---

## Table of Contents

1. [Architecture](#architecture)
2. [Certificate Lifecycle](#certificate-lifecycle)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Certificate Renewal](#certificate-renewal)
6. [Verification](#verification)
7. [Troubleshooting](#troubleshooting)
8. [mTLS Readiness](#mtls-readiness)
9. [Security Considerations](#security-considerations)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Internet                                 │
└─────────────────────────┬───────────────────────────────────────┘
                          │ HTTPS (TLS 1.3)
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Ingress Controller                            │
│                    (nginx + TLS termination)                     │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Certificate: rag-pipeline-tls                           │    │
│  │  Issuer: letsencrypt-prod                               │    │
│  │  Auto-Renewal: Yes (30 days before expiry)              │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────┬───────────────────────────────────────┘
                          │ HTTP (internal)
                          │ NetworkPolicy enforced
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    rag-pipeline namespace                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Ingestion   │  │  Retrieval   │  │ Orchestrator │          │
│  │  Service     │  │  Service     │  │   Service    │          │
│  │  :8001       │  │  :8002       │  │   :8003      │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  PostgreSQL  │  │   Qdrant     │  │  OpenSearch  │          │
│  │  :5432       │  │  :6333/6334  │  │  :9200/9300  │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐                             │
│  │    Redis     │  │    MinIO     │                             │
│  │  :6379       │  │  :9000       │                             │
│  └──────────────┘  └──────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Certificate Lifecycle

### Let's Encrypt Certificates

| Property | Value |
|----------|-------|
| **Duration** | 90 days |
| **Renewal Window** | 30 days before expiry |
| **Algorithm** | RSA 2048-bit |
| **Challenge Type** | HTTP-01 |
| **Automation** | Fully automatic via cert-manager |

### Internal CA Certificates (mTLS)

| Property | Value |
|----------|-------|
| **CA Duration** | 10 years |
| **Service Cert Duration** | 30 days |
| **Renewal Window** | 7 days before expiry |
| **Algorithm** | ECDSA P-256 |
| **Automation** | Fully automatic via cert-manager |

---

## Installation

### Prerequisites

1. **Kubernetes Cluster** with admin access
2. **kubectl** configured with cluster access
3. **DNS** configured to point to ingress controller

### Install cert-manager

#### Option 1: Using kubectl (recommended)

```bash
# Install cert-manager with all CRDs (single command)
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.0/cert-manager.yaml

# Wait for cert-manager pods to be ready
kubectl wait --for=condition=Available deployment --all -n cert-manager --timeout=300s

# Verify installation
kubectl get pods -n cert-manager
kubectl get crd | grep cert-manager

# Expected CRDs:
# certificaterequests.cert-manager.io
# certificates.cert-manager.io
# challenges.acme.cert-manager.io
# clusterissuers.cert-manager.io
# issuers.cert-manager.io
# orders.acme.cert-manager.io
```

#### Option 2: Using Helm (alternative)

```bash
# Add Jetstack Helm repository
helm repo add jetstack https://charts.jetstack.io
helm repo update

# Install cert-manager with CRDs
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.14.0 \
  --set crds.enabled=true

# Verify installation
kubectl get pods -n cert-manager
```

### Apply ClusterIssuers

```bash
# Apply cluster issuers
kubectl apply -f k8s/cert-manager/cluster-issuers.yaml

# Verify issuers are ready
kubectl get clusterissuers
```

### Install nginx-ingress with TLS 1.3

#### Option 1: Using kubectl (recommended)

```bash
# Install nginx-ingress controller
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.0/deploy/static/provider/cloud/deploy.yaml

# Wait for ingress controller to be ready
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=300s

# Apply TLS 1.3 ConfigMap from this repository (includes all security settings)
kubectl apply -f k8s/ingress/nginx-ingress.yaml
```

#### Option 2: Using Helm (alternative)

```bash
# Add ingress-nginx Helm repository
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

# Install with TLS 1.3 configuration
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.service.type=LoadBalancer \
  --set controller.config.ssl-protocols="TLSv1.3" \
  --set controller.config.ssl-ciphers="TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256" \
  --set controller.config.ssl-prefer-server-ciphers="true" \
  --set controller.config.hsts="true" \
  --set controller.config.hsts-max-age="31536000" \
  --set controller.config.hsts-include-subdomains="true"
```

---

## Configuration

### Update Email Address

Before deploying to production, update the email address in the ClusterIssuer:

```bash
# Edit k8s/cert-manager/cluster-issuers.yaml
# Replace: email: admin@example.com
# With: email: your-team@your-domain.com
```

### Update Domain Names

Update the domain names in:
- `k8s/cert-manager/certificates.yaml`
- `k8s/ingress/nginx-ingress.yaml`

```bash
# Replace: api.rag-pipeline.example.com
# With: your-actual-domain.com
```

### Deploy Resources

```bash
# Apply cert-manager resources
kubectl apply -f k8s/cert-manager/cluster-issuers.yaml
kubectl apply -f k8s/cert-manager/certificates.yaml

# Apply ingress configuration
kubectl apply -f k8s/ingress/nginx-ingress.yaml

# Apply network policies
kubectl apply -f k8s/network-policies/network-policies.yaml
```

---

## Certificate Renewal

### Automatic Renewal

cert-manager automatically renews certificates. No manual intervention is required under normal operation.

**Renewal Timeline:**
1. Certificate issued → 90 days validity
2. At 60 days remaining → cert-manager starts monitoring
3. At 30 days remaining → automatic renewal triggered
4. New certificate issued → seamlessly replaces old certificate
5. Ingress controller picks up new certificate → zero downtime

### Monitor Renewal Status

```bash
# Check certificate status
kubectl get certificates -n rag-pipeline

# Expected output:
# NAME                  READY   SECRET               AGE
# rag-pipeline-api-tls  True    rag-pipeline-tls     30d

# Check certificate details
kubectl describe certificate rag-pipeline-api-tls -n rag-pipeline

# Check certificate expiry
kubectl get secret rag-pipeline-tls -n rag-pipeline -o jsonpath='{.data.tls\.crt}' | \
  base64 -d | openssl x509 -noout -dates
```

### Manual Renewal (if needed)

```bash
# Delete the certificate secret to force renewal
kubectl delete secret rag-pipeline-tls -n rag-pipeline

# cert-manager will automatically create a new certificate
# Monitor progress
kubectl get certificaterequest -n rag-pipeline
kubectl get order -n rag-pipeline
kubectl get challenge -n rag-pipeline
```

### Certificate Events

```bash
# Watch for certificate events
kubectl get events -n rag-pipeline --field-selector involvedObject.kind=Certificate

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager -f
```

---

## Verification

### Verify TLS 1.3 Enforcement

```bash
# Test TLS 1.3 connection (should succeed)
curl -v https://api.rag-pipeline.example.com/health 2>&1 | grep "TLSv1.3"

# Test TLS 1.2 connection (should fail)
openssl s_client -connect api.rag-pipeline.example.com:443 -tls1_2
# Expected: no peer certificate available / handshake failure

# Test TLS 1.3 connection
openssl s_client -connect api.rag-pipeline.example.com:443 -tls1_3
# Expected: Certificate chain and TLSv1.3 in output
```

### Verify Certificate Details

```bash
# Check certificate chain
echo | openssl s_client -connect api.rag-pipeline.example.com:443 2>/dev/null | \
  openssl x509 -noout -text | head -30

# Verify certificate issuer (should be Let's Encrypt)
echo | openssl s_client -connect api.rag-pipeline.example.com:443 2>/dev/null | \
  openssl x509 -noout -issuer

# Check SSL Labs rating (external)
# https://www.ssllabs.com/ssltest/analyze.html?d=api.rag-pipeline.example.com
```

### Verify Network Policies

```bash
# Create a test pod
kubectl run test-pod --image=nicolaka/netshoot -n rag-pipeline --rm -it -- /bin/bash

# Test allowed connections (should succeed)
nc -zv postgres 5432        # PostgreSQL
nc -zv qdrant 6333          # Qdrant
nc -zv opensearch 9200      # OpenSearch
nc -zv redis 6379           # Redis
nc -zv minio 9000           # MinIO

# Test denied connections (should fail due to network policy)
nc -zv google.com 443       # External egress should be denied for most pods

# Exit test pod
exit
```

### Verify Ingress

```bash
# Check ingress status
kubectl get ingress -n rag-pipeline

# Describe ingress for details
kubectl describe ingress rag-pipeline-ingress -n rag-pipeline

# Check TLS secret exists
kubectl get secret rag-pipeline-tls -n rag-pipeline -o yaml
```

---

## Troubleshooting

### Certificate Not Ready

```bash
# Check certificate status
kubectl describe certificate rag-pipeline-api-tls -n rag-pipeline

# Check certificate requests
kubectl get certificaterequest -n rag-pipeline
kubectl describe certificaterequest <name> -n rag-pipeline

# Check orders
kubectl get order -n rag-pipeline
kubectl describe order <name> -n rag-pipeline

# Check challenges
kubectl get challenge -n rag-pipeline
kubectl describe challenge <name> -n rag-pipeline
```

### Common Issues

#### 1. DNS Not Resolving

```bash
# Verify DNS
nslookup api.rag-pipeline.example.com
dig api.rag-pipeline.example.com

# Fix: Update DNS records to point to ingress controller external IP
kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
```

#### 2. HTTP-01 Challenge Failing

```bash
# Check if challenge path is accessible
curl http://api.rag-pipeline.example.com/.well-known/acme-challenge/test

# Common fixes:
# - Ensure ingress controller is accessible on port 80
# - Check firewall rules allow HTTP traffic
# - Verify DNS is correct
```

#### 3. Rate Limiting

```bash
# If hitting Let's Encrypt rate limits:
# 1. Switch to staging issuer for testing
kubectl patch certificate rag-pipeline-api-tls -n rag-pipeline \
  --type='json' -p='[{"op": "replace", "path": "/spec/issuerRef/name", "value": "letsencrypt-staging"}]'

# 2. Wait for rate limit reset (usually 1 hour)
# 3. Switch back to production issuer
```

#### 4. TLS 1.2 Connection Succeeding

```bash
# Verify ConfigMap is applied
kubectl get configmap ingress-nginx-controller -n ingress-nginx -o yaml

# Restart ingress controller to apply changes
kubectl rollout restart deployment ingress-nginx-controller -n ingress-nginx

# Verify nginx configuration
kubectl exec -n ingress-nginx deployment/ingress-nginx-controller -- cat /etc/nginx/nginx.conf | grep ssl_protocols
```

---

## mTLS Readiness

### Current State

The RAG Pipeline is prepared for mTLS adoption with:

1. **Internal CA**: `rag-pipeline-ca-issuer` ClusterIssuer for signing internal certificates
2. **Internal Certificates**: `rag-pipeline-internal-tls` certificate for service-to-service communication
3. **Annotations**: mTLS-ready annotations on ingress resources

### Adopting mTLS

When ready to enable mTLS (e.g., with Istio or Linkerd):

#### Option 1: Istio Service Mesh

```yaml
# Enable Istio injection for namespace
kubectl label namespace rag-pipeline istio-injection=enabled

# Apply PeerAuthentication policy
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: rag-pipeline
spec:
  mtls:
    mode: STRICT
```

#### Option 2: Linkerd Service Mesh

```bash
# Inject Linkerd proxy
kubectl get deploy -n rag-pipeline -o yaml | linkerd inject - | kubectl apply -f -

# Verify mTLS
linkerd viz -n rag-pipeline top deploy
```

#### Option 3: Manual cert-manager mTLS

Use the `rag-pipeline-internal-tls` certificate in service configurations:

```yaml
# Mount certificate in deployment
volumes:
  - name: tls-certs
    secret:
      secretName: rag-pipeline-internal-tls
containers:
  - name: app
    volumeMounts:
      - name: tls-certs
        mountPath: /etc/tls
        readOnly: true
```

---

## Security Considerations

### TLS Best Practices

| Practice | Status |
|----------|--------|
| TLS 1.3 only | ✅ Enforced |
| Strong cipher suites | ✅ AES-GCM, ChaCha20 only |
| HSTS enabled | ✅ 1 year max-age |
| HSTS preload | ✅ Enabled |
| Certificate auto-renewal | ✅ 30 days before expiry |
| OCSP stapling | ✅ Enabled |

### Network Isolation

| Rule | Status |
|------|--------|
| Default deny all | ✅ Implemented |
| DNS egress allowed | ✅ kube-system only |
| Ingress from nginx only | ✅ API services |
| Service-to-service restricted | ✅ Only necessary ports |
| Cross-namespace denied | ✅ Except monitoring |

### Audit

```bash
# Regular certificate audit
kubectl get certificates -A -o wide
kubectl get clusterissuers -o wide

# Check expiring certificates
kubectl get certificates -A -o json | jq '.items[] | select(.status.notAfter | fromdateiso8601 < (now + 30*24*60*60)) | {name: .metadata.name, namespace: .metadata.namespace, expires: .status.notAfter}'
```

---

## Related Documentation

- [US-7.10: TLS/mTLS Certificates](../../workflow/refined/07-security-compliance/US-7.10-tls-mtls-certificates.md)
- [Kubernetes Setup](./kubernetes-setup.md)
- [Security Architecture](../../docs/architecture.md#security--compliance)

---

## References

- [cert-manager Documentation](https://cert-manager.io/docs/)
- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [nginx-ingress TLS Configuration](https://kubernetes.github.io/ingress-nginx/user-guide/tls/)
- [Kubernetes NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
