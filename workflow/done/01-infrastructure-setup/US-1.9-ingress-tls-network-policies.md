# US-1.9: Ingress, TLS 1.3, and Network Policies

## Goal
Provide secure ingress with TLS 1.3/cert-manager and baseline namespace/network isolation to support mTLS readiness for internal services.

## Requirements
- Deploy cert-manager (or use existing) and configure ClusterIssuer (e.g., Let’s Encrypt/Staging + Prod).
- Configure ingress controller (nginx/traefik) with TLS 1.3 enforced; set minimum TLS version and strong ciphers.
- Issue certificates for public endpoints; document renewal/rotation.
- Define NetworkPolicies for `rag-pipeline` namespace: restrict ingress/egress to necessary service ports (Postgres, Qdrant, OpenSearch, Redis, MinIO, OTEL, Prometheus).
- Provide placeholders/annotations for mTLS between services if mesh is adopted.

## Acceptance Criteria
- Ingress resources terminate TLS 1.3 with valid cert-manager issued certs; `curl -v https://…` shows TLSv1.3.
- NetworkPolicies applied; unauthorized cross-namespace traffic blocked (verified via test pod).
- Renewal/rotation documented; certs auto-renew before expiry.
- Security epic ready hook: ingress/mTLS docs referenced for US-7.10.

## Verification
- `kubectl get certificate -A` shows Ready certificates; `openssl s_client -connect host:443 -tls1_2` fails when TLS1.2 is disabled.
- `kubectl exec test-pod -- nc -zv <service> <port>` succeeds for allowed paths and fails for denied paths.
