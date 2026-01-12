# US-7.10: TLS 1.3/mTLS & Certificate Management

## Goal
Implement TLS 1.3 for external endpoints and mTLS readiness for internal services using cert-manager/Vault issued certificates.

## Requirements
- Configure cert-manager (or Vault agent) issuers; manage certificate rotation.
- Enforce TLS 1.3 on ingress; set strong cipher suites.
- Provide mTLS configuration for service-to-service traffic (ingress annotations or mesh policy); distribute client certs via Vault/Secrets.
- Document bootstrap/renewal/rotation runbooks; integrate with infra NetworkPolicies.

## Acceptance Criteria
- Ingress endpoints negotiate TLS 1.3; lower versions disabled.
- Internal service mTLS tested between at least two services; failure without client cert confirmed.
- Certificates auto-renew before expiry; rotation does not cause downtime.
- Runbooks stored with commands/steps for operators.

## Verification
- `openssl s_client -connect host:443 -tls1_2` fails; `-tls1_3` succeeds.
- Mutual TLS curl test between services succeeds only with valid client cert.
- `kubectl get certificate -A` shows Ready with renewal windows.
