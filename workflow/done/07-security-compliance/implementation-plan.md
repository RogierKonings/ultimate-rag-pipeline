# Epic 7: Security & Compliance - Implementation Plan

> **Epic:** Security & Compliance
> **Total Estimated Effort:** 2-3 weeks
> **Dependencies:** Epic 1 (Infrastructure), Epic 2 (Ingestion Service)

## Executive Summary

This implementation plan details the deployment of a comprehensive Security & Compliance layer for the RAG pipeline. The plan covers authentication, authorization, encryption, PII handling, secrets management, audit logging, and security scanning. The implementation is structured in 4 waves with clear checkpoints and integration tests.

---

## Implementation Waves

### Wave 1: Authentication & Authorization Foundation

**Duration:** 5-6 days
**User Stories:** US-7.1, US-7.2, US-7.3 (can be partially parallelized)

#### Agent 1: JWT Authentication (US-7.1)

**Goal:** Implement JWT-based authentication with RS256 signing, token validation, and refresh token flows

**Tasks:**
1. Create JWT configuration module
   - Create `services/shared/security/jwt/config.py` with JWTSettings
   - Configure RS256 algorithm (production) and HS256 (development)
   - Set token expiration (30 min access, 7 days refresh)
   - Add IdP integration settings (Auth0, Keycloak, Azure AD)

2. Create token claims models
   - Create `services/shared/security/jwt/models.py`
   - Define TokenClaims with standard + custom claims (tenant_id, roles, groups)
   - Define TokenPair, TokenRequest models
   - Add TokenType enum (ACCESS, REFRESH)

3. Create JWT handler
   - Create `services/shared/security/jwt/handler.py`
   - Implement JWTHandler class with key loading
   - Add create_access_token, create_refresh_token methods
   - Add verify_token with JWKS support for external IdPs
   - Implement token refresh flow

4. Create FastAPI authentication middleware
   - Create `services/shared/security/jwt/middleware.py`
   - Implement JWTAuthMiddleware for route protection
   - Add get_current_user dependency
   - Add require_roles decorator
   - Configure excluded paths (health, docs, auth endpoints)

5. Create auth router
   - Create `services/api-gateway/routers/auth.py`
   - Implement POST /auth/token endpoint
   - Implement POST /auth/refresh endpoint
   - Implement POST /auth/logout endpoint

6. Generate RSA keys for production
   - Create `scripts/generate-jwt-keys.sh`
   - Generate 4096-bit RSA key pair
   - Document key storage in Vault/K8s Secrets

7. Create token blocklist (optional)
   - Create `services/shared/security/jwt/blocklist.py`
   - Implement Redis-based blocklist for logout/revocation
   - Add TTL based on token expiration

8. Write integration tests
   - Create `tests/security/test_jwt_authentication.py`
   - Test token creation and verification
   - Test refresh flow
   - Test expired/invalid token rejection

**Exit Criteria:**
- [ ] JWT validation middleware implemented
- [ ] Token claims extraction working correctly
- [ ] Access token expiration enforced (30 min default)
- [ ] Refresh token support with rotation
- [ ] RS256 signing for production
- [ ] /auth/token returns valid token pair
- [ ] /auth/refresh generates new tokens
- [ ] Unit tests passing

---

#### Agent 2: Authorization & RBAC (US-7.2)

**Goal:** Implement Role-Based Access Control with role definitions, permission mapping, and tenant isolation

**Tasks:**
1. Define permission and role models
   - Create `services/shared/security/rbac/permissions.py`
   - Define Permission enum (documents, query, ingestion, users, tenant, audit, system)
   - Define Role enum (super_admin, tenant_admin, tenant_user, tenant_viewer, data_engineer, analyst, developer, compliance_officer, service_account)
   - Create ROLE_PERMISSIONS mapping with inheritance

2. Create authorization service
   - Create `services/shared/security/rbac/service.py`
   - Implement AuthorizationService class
   - Add get_user_permissions with caching
   - Add has_permission, has_any_permission, has_all_permissions
   - Add check_permission with tenant isolation
   - Add filter_for_tenant for query filtering

3. Create authorization middleware
   - Create `services/shared/security/rbac/middleware.py`
   - Implement require_permission dependency
   - Implement require_role dependency
   - Implement require_tenant_access dependency
   - Create PermissionChecker class
   - Create @authorize decorator

4. Create tenant context manager
   - Create `services/shared/security/rbac/tenant.py`
   - Implement TenantContext dataclass
   - Add context variable for current tenant
   - Add set_tenant_context, get_tenant_context functions

5. Update database models for RBAC
   - Create `services/shared/database/models/user.py`
   - Add User model with roles, groups relationships
   - Add RoleModel and GroupModel
   - Create user_roles and user_groups association tables

6. Create database migration
   - Create migration for users, roles, groups tables
   - Add indexes for tenant_id, username, email

7. Write integration tests
   - Create `tests/security/test_authorization.py`
   - Test role permissions mapping
   - Test permission checking
   - Test tenant isolation

**Exit Criteria:**
- [ ] Role definitions implemented (super_admin, tenant_admin, etc.)
- [ ] Permission mapping to all API endpoints
- [ ] Tenant isolation enforced on all operations
- [ ] Group-based access support implemented
- [ ] Authorization middleware for FastAPI routes
- [ ] Permission inheritance from roles working
- [ ] Unit tests passing

---

#### Agent 3: Document ACL (US-7.3)

**Goal:** Implement fine-grained Access Control Lists for documents with visibility levels and filter integration

**Tasks:**
1. Define ACL data models
   - Create `services/shared/security/acl/models.py`
   - Define Visibility enum (public, private, group, restricted)
   - Define ACLEntry model
   - Define DocumentACL model with can_access method
   - Add to_filter_payload for vector store integration

2. Create ACL service
   - Create `services/shared/security/acl/service.py`
   - Implement ACLService class
   - Add get_document_acl, create_acl, update_acl methods
   - Add check_access method
   - Add filter_accessible_documents method
   - Add get_acl_filter_for_user for Qdrant/OpenSearch
   - Add share_document, make_public, make_private helpers

3. Create ACL query filters for vector stores
   - Create `services/shared/security/acl/filters.py`
   - Implement QdrantACLFilter.build_access_filter
   - Implement OpenSearchACLFilter.build_access_filter
   - Add build_chunk_acl_payload function

4. Update Qdrant service with ACL
   - Update `services/retrieval/vector_store.py`
   - Add ACL metadata to chunk payloads
   - Implement search_with_acl method
   - Add update_document_acl for ACL propagation

5. Create ACL management API
   - Create `services/api-gateway/routers/acl.py`
   - GET /documents/{id}/acl - Get ACL
   - PUT /documents/{id}/acl - Update ACL
   - POST /documents/{id}/acl/share - Share document
   - POST /documents/{id}/acl/make-public - Make public
   - POST /documents/{id}/acl/make-private - Make private
   - POST /documents/acl/bulk - Bulk update

6. Create database migration
   - Create migration for document_acls table
   - Add GIN indexes for allowed_users, allowed_groups arrays

7. Write integration tests
   - Create `tests/security/test_document_acl.py`
   - Test visibility levels
   - Test owner access
   - Test group access
   - Test denied overrides allowed
   - Test Qdrant filter generation

**Exit Criteria:**
- [ ] ACL metadata stored with documents
- [ ] Visibility levels working (public, private, group, restricted)
- [ ] ACL filter applied in Qdrant vector searches
- [ ] ACL filter applied in OpenSearch keyword searches
- [ ] ACL inheritance to chunks implemented
- [ ] ACL management API endpoints working
- [ ] Super admin bypass working correctly
- [ ] Unit tests passing

---

### Wave 1 Checkpoint

**Integration Test:** `tests/integration/test_wave1_auth_authz.py`

```python
# Verify authentication flow
# - Test JWT token generation and validation
# - Test refresh token flow
# Test authorization
# - Verify role-based permission checking
# - Verify tenant isolation
# Test document ACL
# - Verify document visibility filtering
# - Verify search results respect ACL
```

---

### Wave 2: Data Protection

**Duration:** 3-4 days
**User Stories:** US-7.4, US-7.5, US-7.10 (can be done in parallel)
**Dependencies:** Wave 1 completed

#### Agent 4: Encryption at Rest (US-7.4)

**Goal:** Configure AES-256 encryption for all data stores with key management

**Tasks:**
1. Create field encryption module
   - Create `services/shared/security/encryption/field_encryption.py`
   - Implement FieldEncryption class with AES-256-GCM
   - Add encrypt, decrypt methods
   - Add encrypt_dict, decrypt_dict for batch operations
   - Create EncryptionKeyManager with Vault support

2. Create SQLAlchemy encrypted types
   - Create `services/shared/database/types/encrypted.py`
   - Implement EncryptedString type
   - Implement EncryptedJSON type

3. Configure Kubernetes encrypted storage
   - Create `infrastructure/k8s/storage-classes/encrypted-gp3.yaml`
   - Configure KMS key for EBS encryption (AWS)
   - Update PostgreSQL PVC to use encrypted storage class
   - Update Qdrant StatefulSet to use encrypted storage
   - Update OpenSearch StatefulSet to use encrypted storage

4. Configure MinIO/S3 server-side encryption
   - Create `services/shared/storage/s3_client.py` (EncryptedS3Client)
   - Enable SSE-S3 or SSE-KMS
   - Add set_bucket_encryption method
   - Update MinIO deployment with KMS secret

5. Create key rotation script
   - Create `scripts/rotate-encryption-keys.sh`
   - Store current key as previous for migration
   - Document re-encryption procedure

6. Write integration tests
   - Create `tests/security/test_encryption.py`
   - Test field encryption/decryption
   - Test different ciphertext for same plaintext (nonce)
   - Test wrong key rejection
   - Test Unicode content

**Exit Criteria:**
- [ ] PostgreSQL volumes use encrypted storage class
- [ ] Field-level encryption available for sensitive columns
- [ ] Qdrant uses encrypted persistent volumes
- [ ] OpenSearch uses encrypted persistent volumes
- [ ] MinIO/S3 has server-side encryption enabled
- [ ] Encryption keys stored in Vault/KMS
- [ ] Key rotation procedure documented and tested
- [ ] All encryption uses AES-256
- [ ] Unit tests passing

---

#### Agent 5: Encryption in Transit (US-7.5)

**Goal:** Configure TLS 1.3 for external endpoints and mTLS readiness for internal services

**Tasks:**
1. Install and configure cert-manager
   - Create `infrastructure/k8s/cert-manager/cert-manager.yaml`
   - Install via Helm or manifests

2. Create certificate issuers
   - Create `infrastructure/k8s/certificates/cluster-issuer.yaml`
   - Configure Let's Encrypt Production issuer
   - Configure Let's Encrypt Staging issuer
   - Configure internal CA issuer for mTLS

3. Create internal CA
   - Create `infrastructure/k8s/certificates/internal-ca.yaml`
   - Generate root CA certificate (10 years)
   - Create Issuer that uses internal CA

4. Configure Ingress with TLS
   - Create `infrastructure/k8s/ingress/ingress-tls.yaml`
   - Enable TLS 1.3 only
   - Configure strong cipher suites
   - Add HSTS headers
   - Add security headers (X-Content-Type-Options, X-Frame-Options)

5. Create service certificates for mTLS
   - Create `infrastructure/k8s/certificates/service-certs.yaml`
   - Generate certificates for api-gateway, ingestion, retrieval, query services
   - Configure DNS names for internal resolution

6. Configure FastAPI for TLS/mTLS
   - Create `services/shared/security/tls/config.py`
   - Implement create_server_ssl_context
   - Implement create_client_ssl_context
   - Add TLSSettings configuration

7. Configure database TLS connections
   - Update `services/shared/database/connection.py`
   - Add create_postgres_ssl_context
   - Add SSL parameters to connection URL

8. Configure Redis TLS
   - Update `services/shared/cache/redis_client.py`
   - Add create_redis_ssl_context
   - Add TLS support to Redis client

9. Create TLS health check endpoint
   - Add /health/tls endpoint
   - Return TLS status, protocol, cipher info

10. Write integration tests
    - Create `tests/security/test_tls.py`
    - Test SSL context creation
    - Test TLS 1.3 enforcement

**Exit Criteria:**
- [ ] TLS 1.3 enforced for all external API endpoints
- [ ] Valid certificates from Let's Encrypt
- [ ] cert-manager configured for automatic renewal
- [ ] Internal CA created for service certificates
- [ ] mTLS configured between services (optional)
- [ ] Database connections use TLS
- [ ] Redis connections use TLS
- [ ] HSTS headers configured on ingress

---

#### Agent 6: TLS/mTLS & Certificate Management (US-7.10)

**Goal:** Ensure certificate rotation, mTLS testing, and runbook documentation

**Tasks:**
1. Verify cert-manager renewal configuration
   - Set renewBefore to 30 days
   - Configure certificate duration (1 year)
   - Test renewal workflow

2. Test mTLS between services
   - Deploy test with mTLS enabled
   - Verify connection fails without client cert
   - Verify connection succeeds with valid cert

3. Create certificate runbooks
   - Document bootstrap procedure
   - Document renewal/rotation procedure
   - Document emergency certificate replacement
   - Create monitoring alerts for expiring certificates

4. Integrate with NetworkPolicies
   - Update NetworkPolicies to allow TLS ports
   - Document firewall requirements

**Exit Criteria:**
- [ ] Ingress endpoints negotiate TLS 1.3
- [ ] TLS 1.2 and lower disabled
- [ ] Internal service mTLS tested
- [ ] Certificates auto-renew before expiry
- [ ] Rotation does not cause downtime
- [ ] Runbooks documented with operator commands

---

### Wave 2 Checkpoint

**Integration Test:** `tests/integration/test_wave2_encryption.py`

```python
# Verify encryption at rest
# - Test field encryption with EncryptedString type
# - Verify storage volumes are encrypted
# Test encryption in transit
# - Verify TLS 1.3 negotiation
# - Test mTLS between services
# - Verify database SSL connections
```

---

### Wave 3: Privacy & Compliance

**Duration:** 3-4 days
**User Stories:** US-7.6, US-7.7 (can be done in parallel)
**Dependencies:** Wave 1, 2 completed

#### Agent 7: PII Detection & Handling (US-7.6)

**Goal:** Integrate Microsoft Presidio for PII detection during document ingestion

**Tasks:**
1. Configure PII detection settings
   - Create `services/shared/security/pii/config.py`
   - Define PIIHandlingMode enum (redact, mask, flag, reject, encrypt, passthrough)
   - Define PIISettings with entity types, confidence threshold
   - Configure entity-specific handling overrides

2. Create PII detector with Presidio
   - Create `services/shared/security/pii/detector.py`
   - Initialize AnalyzerEngine with spaCy NLP
   - Implement PIIDetector.analyze method
   - Add _redact_text, _mask_text helper methods
   - Support custom recognizers loading

3. Create custom recognizers configuration
   - Create `services/shared/security/pii/custom_recognizers.yaml`
   - Add EMPLOYEE_ID pattern
   - Add PROJECT_CODE pattern
   - Add API_KEY pattern
   - Add AWS_ACCESS_KEY pattern
   - Add PRIVATE_KEY pattern

4. Integrate PII detection in ingestion pipeline
   - Create `services/ingestion/processors/pii_processor.py`
   - Implement PIIProcessor.process_chunk
   - Implement PIIProcessor.process_chunks
   - Create PIIPipelineStep for workflow integration
   - Handle document rejection on PII detection (if configured)

5. Create PII filtering for query responses
   - Create `services/shared/security/pii/response_filter.py`
   - Implement PIIResponseFilter.filter_response
   - Implement filter_search_results for chunks

6. Create PII API endpoints
   - Create `services/api-gateway/routers/pii.py`
   - POST /pii/analyze - Analyze text for PII
   - GET /pii/config - Get PII configuration
   - GET /pii/entities - List supported entity types

7. Write integration tests
   - Create `tests/security/test_pii_detection.py`
   - Test email, phone, SSN, person detection
   - Test redaction output
   - Test confidence threshold filtering
   - Test disabled detection passthrough

**Exit Criteria:**
- [ ] Presidio integration working for PII detection
- [ ] Detection of names, emails, SSN, phone numbers
- [ ] Configurable handling modes (redact, flag, reject)
- [ ] PII metadata stored with chunks
- [ ] PII filtering in query responses
- [ ] Custom recognizers support
- [ ] PII analysis API endpoint
- [ ] Unit tests passing

---

#### Agent 8: Secrets Management (US-7.7)

**Goal:** Implement centralized secrets management with Vault and Kubernetes Secrets fallback

**Tasks:**
1. Deploy HashiCorp Vault (development)
   - Create `infrastructure/k8s/vault/deployment.yaml`
   - Configure ServiceAccount and RBAC
   - Create PVC for Vault data
   - Set up health/readiness probes

2. Configure Vault policies
   - Create `infrastructure/vault/policies/rag-pipeline-policy.hcl`
   - Grant read access to application secrets
   - Grant database credential generation
   - Grant transit encrypt/decrypt
   - Create admin policy for secret management

3. Create Vault client
   - Create `services/shared/security/secrets/vault.py`
   - Implement VaultClient class
   - Add Kubernetes authentication
   - Add read_secret, write_secret, delete_secret methods
   - Add get_database_credentials for dynamic creds
   - Add encrypt, decrypt using Transit engine

4. Create Kubernetes Secrets alternative
   - Create `services/shared/security/secrets/k8s_secrets.py`
   - Implement K8sSecretsClient class
   - Add read_secret, write_secret, delete_secret methods

5. Create unified secrets service
   - Create `services/shared/security/secrets/service.py`
   - Define SecretsBackend enum (vault, kubernetes, environment)
   - Implement SecretsService with backend selection
   - Add get_database_url, get_redis_url helpers
   - Add get_jwt_keys, get_encryption_key helpers

6. Create secrets injection for FastAPI
   - Create `services/shared/security/secrets/injection.py`
   - Implement SecretsInjector class
   - Add caching support
   - Create get_secret dependency

7. Configure External Secrets Operator (optional)
   - Create `infrastructure/k8s/external-secrets/secret-store.yaml`
   - Configure Vault backend sync
   - Create ExternalSecret for rag-pipeline-secrets

8. Create secret rotation script
   - Create `scripts/rotate-secrets.sh`
   - Add database password rotation
   - Add JWT keys rotation
   - Add encryption key rotation

9. Write integration tests
   - Create `tests/security/test_secrets.py`
   - Test environment backend
   - Test Vault integration (if available)
   - Test secrets injection caching

**Exit Criteria:**
- [ ] HashiCorp Vault deployed and accessible
- [ ] Vault policies configured for service access
- [ ] Kubernetes Secrets alternative available
- [ ] No secrets in code or config files
- [ ] Secret rotation scripts working
- [ ] Audit logging of secret access enabled
- [ ] Environment-based fallback for development
- [ ] Unit tests passing

---

### Wave 3 Checkpoint

**Integration Test:** `tests/integration/test_wave3_privacy.py`

```python
# Verify PII detection
# - Test document ingestion with PII
# - Verify redaction in stored chunks
# - Test PII filtering in responses
# Verify secrets management
# - Test secret retrieval from Vault
# - Test database URL construction
# - Test secret injection
```

---

### Wave 4: Observability & Hardening

**Duration:** 4-5 days
**User Stories:** US-7.8, US-7.9, US-7.11
**Dependencies:** Wave 1, 2, 3 completed

#### Agent 9: Audit Logging (US-7.8)

**Goal:** Implement comprehensive audit logging for all API operations

**Tasks:**
1. Create audit log models
   - Create `services/shared/security/audit/models.py`
   - Define AuditAction enum (auth, document, query, acl, admin, config, data)
   - Define AuditOutcome enum (success, failure, denied, error)
   - Define AuditSeverity enum (info, warning, error, critical)
   - Define AuditLogEntry model with all required fields
   - Define AuditQuery model for searching

2. Create audit logger
   - Create `services/shared/security/audit/logger.py`
   - Implement AuditLogger class
   - Add log method with structured output
   - Add convenience methods (log_login, log_document_access, log_query, log_access_denied)
   - Output to stdout for log aggregation

3. Create audit middleware
   - Create `services/shared/security/audit/middleware.py`
   - Implement AuditMiddleware for automatic request logging
   - Extract client IP (handle proxies)
   - Map HTTP methods to audit actions
   - Extract resource type/ID from path

4. Create audit database model
   - Create `services/shared/database/models/audit_log.py`
   - Define AuditLog table with all fields
   - Add composite indexes for efficient queries

5. Create audit repository
   - Create `services/shared/database/repositories/audit.py`
   - Implement AuditRepository class
   - Add create, search methods
   - Add get_user_activity, get_resource_history
   - Add count_by_action for statistics

6. Create audit API endpoints
   - Create `services/api-gateway/routers/audit.py`
   - GET /audit/logs - Search logs with filters
   - GET /audit/logs/user/{id} - User activity
   - GET /audit/logs/resource/{type}/{id} - Resource history
   - GET /audit/stats - Statistics
   - POST /audit/export - Export for compliance

7. Create database migration
   - Create migration for audit_logs table
   - Add indexes for timestamp, user_id, tenant_id, action

8. Write integration tests
   - Create `tests/security/test_audit_logging.py`
   - Test audit entry creation
   - Test login logging (success/failure)
   - Test query logging

**Exit Criteria:**
- [ ] All API calls logged with user identity
- [ ] Action and resource type/ID logged
- [ ] Timestamp and IP address logged
- [ ] Structured JSON log format for aggregation
- [ ] Database persistence for audit queries
- [ ] Audit log search API implemented
- [ ] Export functionality for compliance
- [ ] Unit tests passing

---

#### Agent 10: Security Scanning (US-7.9)

**Goal:** Implement automated security scanning in CI/CD pipelines

**Tasks:**
1. Configure dependency scanning
   - Create `.github/workflows/security-dependency-scan.yml`
   - Add Safety check for Python packages
   - Add pip-audit for vulnerability detection
   - Add Snyk scan with SARIF upload
   - Add npm audit for JavaScript (if applicable)

2. Configure container image scanning
   - Create `.github/workflows/security-container-scan.yml`
   - Add Trivy scan for all service images
   - Configure SBOM generation
   - Add Grype scan as alternative
   - Fail on CRITICAL/HIGH vulnerabilities

3. Configure SAST (static analysis)
   - Create `.github/workflows/security-sast.yml`
   - Add Bandit for Python security analysis
   - Add Semgrep with OWASP rules
   - Add CodeQL analysis
   - Upload SARIF results to GitHub

4. Configure secrets detection
   - Create `.github/workflows/security-secrets.yml`
   - Add Gitleaks for secret scanning
   - Add TruffleHog as alternative
   - Create `.gitleaks.toml` configuration

5. Configure Bandit settings
   - Add [tool.bandit] section to pyproject.toml
   - Exclude test directories
   - Configure severity levels

6. Configure Semgrep rules
   - Create `.semgrep.yml` with custom rules
   - Add SQL injection detection for SQLAlchemy
   - Add insecure deserialization detection
   - Add hardcoded password detection
   - Add JWT without expiration detection

7. Create security scanning script
   - Create `scripts/security-scan.sh`
   - Run all scans locally
   - Generate summary report

8. Configure pre-commit hooks
   - Create `.pre-commit-config.yaml`
   - Add Bandit hook
   - Add Gitleaks hook
   - Add Semgrep hook
   - Add detect-private-key hook

9. Create security report generator
   - Create `scripts/generate_security_report.py`
   - Parse Bandit, Trivy, Gitleaks results
   - Generate consolidated report (JSON/Markdown)

10. Document penetration testing procedure
    - Create `docs/security/penetration-testing.md`
    - Define scope and schedule
    - List testing areas (auth, injection, API, data)
    - Document OWASP ZAP usage
    - Define remediation SLAs

**Exit Criteria:**
- [ ] Dependency scanning in CI/CD pipeline
- [ ] Container image scanning with Trivy
- [ ] SAST with Bandit and Semgrep
- [ ] Secrets detection with Gitleaks
- [ ] Pre-commit hooks configured
- [ ] Security report generation
- [ ] Penetration testing procedure documented
- [ ] All scans integrated in GitHub Actions
- [ ] Build fails on critical/high vulnerabilities

---

#### Agent 11: Audit Log Persistence & Tamper-evidence (US-7.11)

**Goal:** Persist audit logs to Loki and Postgres with tamper-evident guarantees

**Tasks:**
1. Implement audit middleware enhancements
   - Capture additional context (user, tenant, action, resource, IP, trace_id, status)
   - Ensure trace_id correlation across services

2. Implement hash chaining for tamper-evidence
   - Update AuditLog model with previous_hash field
   - Compute SHA-256 hash of record + previous_hash
   - Store hash chain in database
   - Add validation method for chain integrity

3. Configure Loki log shipping
   - Update log format to include trace_id and audit_id
   - Configure structured JSON output
   - Add hash references to log entries

4. Create export script
   - Create `scripts/export-audit-logs.py`
   - Support date range filtering
   - Export to JSON/CSV formats
   - Validate hash chain on export
   - Enforce access control (audit:export permission)

5. Define retention policy
   - Configure database retention (default 1 year)
   - Configure Loki retention
   - Create cleanup job for expired logs

6. Create tampering detection test
   - Test hash chain validation
   - Test detection of modified records
   - Test detection of deleted records

**Exit Criteria:**
- [ ] Audit entries stored in DB with valid hash chain
- [ ] Tampering detection test passes
- [ ] Logs visible in Loki with matching trace_id
- [ ] 401/403/5xx actions also logged with reason
- [ ] Export script works and enforces access control

---

### Wave 4 Checkpoint

**Integration Test:** `tests/integration/test_wave4_observability.py`

```python
# Verify audit logging
# - Test API calls generate audit entries
# - Verify log search API
# - Test export functionality
# Verify security scanning
# - Run security-scan.sh locally
# - Verify CI/CD workflows syntax
# Verify tamper-evidence
# - Test hash chain validation
# - Query Loki for trace_id correlation
```

---

## Final Integration & Validation

### End-to-End Test Suite

**File:** `tests/e2e/test_security_compliance.py`

```python
# Full E2E test covering:
# 1. User authentication (login, token refresh, logout)
# 2. Authorization checks (permission denied, tenant isolation)
# 3. Document ACL enforcement (visibility, sharing)
# 4. Encrypted data storage (field encryption)
# 5. TLS connection verification
# 6. PII detection in ingestion
# 7. PII redaction in responses
# 8. Audit log generation
# 9. Audit log search
# 10. Hash chain validation
```

### Security Validation

| Test | Method | Expected Result |
|------|--------|-----------------|
| JWT Validation | `curl` with expired token | 401 Unauthorized |
| RBAC Enforcement | Request admin endpoint as user | 403 Forbidden |
| Tenant Isolation | Access other tenant's document | 403 Forbidden |
| ACL Filtering | Search query | Only permitted documents returned |
| TLS Version | `openssl s_client -tls1_2` | Connection refused |
| TLS Version | `openssl s_client -tls1_3` | Connection successful |
| PII Detection | Ingest document with email | PII redacted in storage |
| Audit Trail | Perform action | Audit entry created |
| Tamper Detection | Modify audit record | Validation fails |

### Compliance Verification

```bash
# Run compliance checks
pytest tests/e2e/test_security_compliance.py -v

# Verify TLS configuration
openssl s_client -connect api.rag-pipeline.example.com:443 -tls1_3

# Verify audit logs
curl -X GET "http://localhost:8000/audit/logs?action=auth.login&limit=10" \
  -H "Authorization: Bearer $TOKEN"

# Export audit logs for review
curl -X POST "http://localhost:8000/audit/export" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"start_time": "2024-01-01T00:00:00Z", "end_time": "2024-12-31T23:59:59Z"}'

# Run security scans
./scripts/security-scan.sh
```

---

## Deployment Checklist

### Pre-deployment

- [ ] Generate RSA keys for JWT signing
- [ ] Configure Vault or K8s Secrets with required secrets
- [ ] cert-manager installed in cluster
- [ ] Let's Encrypt account configured
- [ ] Encrypted storage class available
- [ ] Prometheus/Grafana stack deployed
- [ ] Loki deployed for log aggregation
- [ ] Redis available for token blocklist

### Wave 1 Deployment

- [ ] `kubectl apply -f services/shared/database/migrations/` (RBAC tables)
- [ ] Deploy auth configuration ConfigMaps
- [ ] Deploy JWT secrets
- [ ] Verify /auth/token endpoint works
- [ ] Run Wave 1 integration tests

### Wave 2 Deployment

- [ ] Apply encrypted storage class
- [ ] Update PVCs to use encrypted storage
- [ ] Apply cert-manager issuers
- [ ] Apply service certificates
- [ ] Update Ingress with TLS
- [ ] Verify TLS 1.3 negotiation
- [ ] Run Wave 2 integration tests

### Wave 3 Deployment

- [ ] Deploy Vault (or configure External Secrets)
- [ ] Apply Vault policies
- [ ] Deploy PII detection dependencies (spaCy model)
- [ ] Configure PII settings
- [ ] Verify secrets injection
- [ ] Run Wave 3 integration tests

### Wave 4 Deployment

- [ ] Apply audit_logs migration
- [ ] Configure log shipping to Loki
- [ ] Enable audit middleware
- [ ] Configure GitHub Actions workflows
- [ ] Install pre-commit hooks
- [ ] Run Wave 4 integration tests

### Post-deployment

- [ ] Run full E2E test suite
- [ ] Run security scans
- [ ] Verify all alerts not firing
- [ ] Document any deviations
- [ ] Schedule penetration test

---

## Rollback Plan

### Per-Component Rollback

```bash
# Rollback JWT/Auth changes
kubectl rollout undo deployment/api-gateway -n rag-pipeline

# Rollback database migrations
cd services/shared/database/migrations
alembic downgrade -1

# Rollback Vault deployment
kubectl delete -f infrastructure/k8s/vault/

# Rollback certificate changes
kubectl delete certificate -n rag-pipeline --all
kubectl apply -f infrastructure/k8s/certificates/backup/
```

### Configuration Rollback

```bash
# Restore previous ConfigMaps
kubectl apply -f backup/configmaps/

# Restore previous Secrets
kubectl apply -f backup/secrets/
```

### Full Epic Rollback

```bash
# Delete security-related resources
kubectl delete -n rag-pipeline \
  secret/jwt-keys \
  secret/encryption-keys \
  configmap/security-config

# Re-apply from previous known-good state
kubectl apply -k k8s/overlays/prod-previous/

# Restore database from backup
pg_restore -d ragpipeline backup.dump
```

---

## Definition of Done (Epic Level)

- [ ] JWT authentication implemented and tested
- [ ] RBAC authorization enforcing permissions
- [ ] Document ACL filtering in searches
- [ ] Encryption at rest for all data stores
- [ ] TLS 1.3 for external endpoints
- [ ] mTLS configured for internal services
- [ ] PII detection in ingestion pipeline
- [ ] PII redaction in query responses
- [ ] Secrets managed in Vault/K8s Secrets
- [ ] No secrets in code or config files
- [ ] Comprehensive audit logging
- [ ] Audit logs stored with tamper-evidence
- [ ] Security scanning in CI/CD
- [ ] Pre-commit hooks configured
- [ ] All tests passing
- [ ] Documentation complete
- [ ] Penetration testing scheduled

---

## Appendix: Service Ports

| Service | Internal Port | External Port | Protocol |
|---------|--------------|---------------|----------|
| API Gateway | 8000 | 443 | HTTPS |
| Ingestion Service | 8001 | - | HTTP/mTLS |
| Retrieval Service | 8002 | - | HTTP/mTLS |
| Query Service | 8003 | - | HTTP/mTLS |
| Vault | 8200 | - | HTTP |
| Redis | 6379 | - | TLS |
| PostgreSQL | 5432 | - | TLS |

## Appendix: Environment Variables

### JWT Configuration
- `JWT_SECRET_KEY` - Path to private key or key content
- `JWT_PUBLIC_KEY` - Path to public key or key content
- `JWT_ALGORITHM` - RS256 (production) or HS256 (development)
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` - 30
- `JWT_REFRESH_TOKEN_EXPIRE_DAYS` - 7
- `JWT_ISSUER` - rag-pipeline
- `JWT_AUDIENCE` - rag-api

### Secrets Management
- `SECRETS_BACKEND` - vault, kubernetes, or environment
- `VAULT_ADDR` - Vault server URL
- `VAULT_TOKEN` - Vault authentication token
- `VAULT_NAMESPACE` - Vault namespace (if used)

### PII Detection
- `PII_DETECTION_ENABLED` - true/false
- `PII_CONFIDENCE_THRESHOLD` - 0.8
- `PII_HANDLING_MODE` - redact, flag, reject, passthrough
- `PII_LANGUAGES` - en

### Encryption
- `FIELD_ENCRYPTION_KEY` - Base64-encoded 32-byte key
- `ENCRYPTION_KEY_VERSION` - Key version for rotation

### TLS
- `TLS_ENABLED` - true/false
- `TLS_CERT_FILE` - Path to certificate
- `TLS_KEY_FILE` - Path to private key
- `MTLS_ENABLED` - true/false
- `MTLS_CA_FILE` - Path to CA certificate

### Audit
- `AUDIT_LOG_LEVEL` - INFO
- `AUDIT_RETENTION_DAYS` - 365
- `AUDIT_STORAGE_BACKEND` - postgresql

## Appendix: File Structure

```
services/shared/security/
├── jwt/
│   ├── __init__.py
│   ├── config.py
│   ├── models.py
│   ├── handler.py
│   ├── middleware.py
│   └── blocklist.py
├── rbac/
│   ├── __init__.py
│   ├── permissions.py
│   ├── service.py
│   ├── middleware.py
│   └── tenant.py
├── acl/
│   ├── __init__.py
│   ├── models.py
│   ├── service.py
│   └── filters.py
├── encryption/
│   ├── __init__.py
│   └── field_encryption.py
├── tls/
│   ├── __init__.py
│   └── config.py
├── pii/
│   ├── __init__.py
│   ├── config.py
│   ├── detector.py
│   ├── custom_recognizers.yaml
│   └── response_filter.py
├── secrets/
│   ├── __init__.py
│   ├── vault.py
│   ├── k8s_secrets.py
│   ├── service.py
│   └── injection.py
└── audit/
    ├── __init__.py
    ├── models.py
    ├── logger.py
    └── middleware.py
```
