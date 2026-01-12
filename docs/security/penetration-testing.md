# Penetration Testing Guide

This document outlines the penetration testing procedures for the RAG Pipeline system.

## Overview

Penetration testing is conducted to identify security vulnerabilities before they can be exploited. This guide covers the scope, methodology, tools, and procedures for security assessments.

## Testing Schedule

| Test Type | Frequency | Responsibility |
|-----------|-----------|----------------|
| Automated Scans | Daily (CI/CD) | DevOps |
| Internal Penetration Test | Quarterly | Security Team |
| External Penetration Test | Annually | Third-Party Vendor |
| Red Team Exercise | Annually | External Red Team |

## Scope Definition

### In-Scope Systems

1. **API Endpoints**
   - Ingestion Service (port 8001)
   - Retrieval Service (port 8002)
   - Orchestrator Service (port 8003)
   - LLM Gateway (port 8004)
   - Embedding Service (port 8080)

2. **Infrastructure**
   - Kubernetes cluster
   - PostgreSQL database
   - Qdrant vector database
   - OpenSearch cluster
   - Redis cache
   - MinIO object storage

3. **Authentication Systems**
   - JWT token handling
   - OAuth2 flows (if enabled)
   - API key management
   - Service-to-service authentication

### Out-of-Scope

- Third-party SaaS integrations (unless explicitly included)
- Physical security
- Social engineering (unless authorized)
- Denial of Service attacks against production
- Any testing against shared infrastructure

## Testing Areas

### 1. Authentication & Authorization

**Objectives:**
- Verify JWT token validation
- Test session management
- Identify privilege escalation paths
- Test RBAC enforcement

**Test Cases:**
```
AUTH-001: Test JWT token expiration enforcement
AUTH-002: Test token refresh mechanism
AUTH-003: Test invalid signature rejection
AUTH-004: Test role-based access control
AUTH-005: Test tenant isolation
AUTH-006: Test brute force protection
AUTH-007: Test account lockout mechanisms
AUTH-008: Test password policy enforcement
```

**Tools:**
- Burp Suite
- JWT.io for token analysis
- Custom Python scripts

### 2. Injection Vulnerabilities

**Objectives:**
- Identify SQL injection points
- Test for NoSQL injection
- Check for command injection
- Verify query parameter sanitization

**Test Cases:**
```
INJ-001: SQL injection in search queries
INJ-002: NoSQL injection in Qdrant filters
INJ-003: Command injection in file processing
INJ-004: LDAP injection (if applicable)
INJ-005: XPath injection (if applicable)
INJ-006: Server-side template injection
INJ-007: Log injection attacks
```

**Tools:**
- sqlmap
- Burp Suite Intruder
- Custom payloads

### 3. API Security

**Objectives:**
- Test rate limiting
- Verify input validation
- Check for information disclosure
- Test error handling

**Test Cases:**
```
API-001: Test rate limiting effectiveness
API-002: Test request size limits
API-003: Test malformed JSON handling
API-004: Test missing required fields
API-005: Test boundary value conditions
API-006: Test HTTP method restrictions
API-007: Test CORS configuration
API-008: Test API versioning security
```

**Tools:**
- Postman/Newman
- OWASP ZAP
- Custom scripts

### 4. Data Protection

**Objectives:**
- Verify encryption in transit
- Test encryption at rest
- Check for data leakage
- Verify PII handling

**Test Cases:**
```
DATA-001: Verify TLS configuration
DATA-002: Test for unencrypted data transmission
DATA-003: Check database encryption
DATA-004: Verify PII redaction in logs
DATA-005: Test data export controls
DATA-006: Verify backup encryption
DATA-007: Test key management
DATA-008: Check for sensitive data in errors
```

**Tools:**
- testssl.sh
- nmap with SSL scripts
- grep for sensitive patterns

### 5. Infrastructure Security

**Objectives:**
- Identify exposed services
- Test container security
- Verify network segmentation
- Check for misconfigurations

**Test Cases:**
```
INFRA-001: Port scanning for exposed services
INFRA-002: Container escape attempts
INFRA-003: Kubernetes RBAC verification
INFRA-004: Network policy testing
INFRA-005: Secrets management review
INFRA-006: Container image vulnerability scan
INFRA-007: Cloud configuration review
```

**Tools:**
- nmap
- Trivy
- kube-hunter
- Prowler (AWS/GCP)

## Testing Methodology

### Phase 1: Reconnaissance

1. Review architecture documentation
2. Identify all endpoints and services
3. Map authentication flows
4. Document API schemas
5. Identify data flows

### Phase 2: Scanning

1. Run automated vulnerability scanners
2. Perform port and service enumeration
3. Execute dependency vulnerability scans
4. Run SAST tools on codebase

```bash
# Run security scan script
./scripts/security-scan.sh --full

# Generate consolidated report
python scripts/generate_security_report.py --input-dir ./security-reports
```

### Phase 3: Manual Testing

1. Test each endpoint for common vulnerabilities
2. Attempt authentication bypass
3. Test authorization controls
4. Verify input validation
5. Check for business logic flaws

### Phase 4: Exploitation

1. Attempt to exploit identified vulnerabilities
2. Document proof-of-concept (PoC) evidence
3. Assess impact and severity
4. Chain vulnerabilities where possible

### Phase 5: Reporting

1. Document all findings
2. Assign severity ratings (CVSS)
3. Provide remediation guidance
4. Present to stakeholders

## OWASP ZAP Configuration

### Setup

```bash
# Pull ZAP Docker image
docker pull ghcr.io/zaproxy/zaproxy:stable

# Run ZAP in daemon mode
docker run -u zap -p 8080:8080 -p 8090:8090 \
  -v $(pwd)/zap-reports:/zap/wrk:rw \
  ghcr.io/zaproxy/zaproxy:stable \
  zap.sh -daemon -port 8080 -host 0.0.0.0 \
  -config api.addrs.addr.name=.* \
  -config api.addrs.addr.regex=true
```

### Baseline Scan

```bash
# Run baseline scan against API
docker run -v $(pwd)/zap-reports:/zap/wrk:rw \
  ghcr.io/zaproxy/zaproxy:stable \
  zap-baseline.py \
  -t http://host.docker.internal:8001 \
  -r api-baseline-report.html \
  -J api-baseline-report.json
```

### API Scan

```bash
# Run API scan with OpenAPI spec
docker run -v $(pwd)/zap-reports:/zap/wrk:rw \
  ghcr.io/zaproxy/zaproxy:stable \
  zap-api-scan.py \
  -t http://host.docker.internal:8001/openapi.json \
  -f openapi \
  -r api-scan-report.html
```

### Full Scan

```bash
# Run full active scan
docker run -v $(pwd)/zap-reports:/zap/wrk:rw \
  ghcr.io/zaproxy/zaproxy:stable \
  zap-full-scan.py \
  -t http://host.docker.internal:8001 \
  -r full-scan-report.html \
  -J full-scan-report.json
```

## Severity Rating

We use CVSS v3.1 for severity ratings:

| CVSS Score | Severity | Response SLA |
|------------|----------|--------------|
| 9.0 - 10.0 | Critical | 24 hours |
| 7.0 - 8.9 | High | 7 days |
| 4.0 - 6.9 | Medium | 30 days |
| 0.1 - 3.9 | Low | 90 days |
| 0.0 | Informational | Best effort |

## Remediation SLAs

### Critical Vulnerabilities (24 hours)
- Immediately notify security team
- Implement emergency mitigation
- Deploy fix within 24 hours
- Post-incident review required

### High Vulnerabilities (7 days)
- Prioritize in current sprint
- Test fix in staging
- Deploy within 7 calendar days
- Verify remediation

### Medium Vulnerabilities (30 days)
- Add to backlog
- Schedule in upcoming sprint
- Deploy within 30 days
- Document in security register

### Low Vulnerabilities (90 days)
- Track in issue tracker
- Include in regular maintenance
- Deploy within 90 days
- May defer with risk acceptance

## Reporting Template

### Executive Summary
- Overall security posture
- Critical/High findings count
- Key recommendations

### Technical Findings
For each finding:
1. **Title**: Descriptive name
2. **Severity**: CVSS score and rating
3. **Description**: What was found
4. **Impact**: Business and technical impact
5. **Evidence**: Screenshots, logs, PoC
6. **Remediation**: How to fix
7. **References**: CVE, CWE, OWASP

### Appendices
- Full scan results
- Testing methodology details
- Tool configurations

## Pre-Test Checklist

Before starting penetration testing:

- [ ] Obtain written authorization
- [ ] Define scope and rules of engagement
- [ ] Notify relevant stakeholders
- [ ] Set up isolated test environment
- [ ] Configure monitoring/alerting exclusions
- [ ] Verify backup and rollback procedures
- [ ] Document emergency contacts
- [ ] Schedule testing window

## Post-Test Checklist

After completing penetration testing:

- [ ] Remove all test accounts and data
- [ ] Reset any modified configurations
- [ ] Verify no tools left on systems
- [ ] Document all findings
- [ ] Schedule remediation reviews
- [ ] Update security baseline
- [ ] Archive test evidence securely

## Contact Information

| Role | Contact | Responsibility |
|------|---------|----------------|
| Security Lead | security@example.com | Overall coordination |
| DevOps Lead | devops@example.com | Infrastructure access |
| Development Lead | dev@example.com | Code-level fixes |
| Incident Response | incident@example.com | Emergency escalation |

## Compliance Considerations

Testing should align with:
- SOC 2 Type II requirements
- GDPR data protection standards
- Industry-specific regulations (HIPAA, PCI-DSS if applicable)
- Internal security policies

## References

- [OWASP Testing Guide](https://owasp.org/www-project-web-security-testing-guide/)
- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)
- [CWE - Common Weakness Enumeration](https://cwe.mitre.org/)
- [CVE - Common Vulnerabilities and Exposures](https://cve.mitre.org/)
