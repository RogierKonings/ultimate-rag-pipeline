# US-7.9: Security Scanning

> **Epic:** Security & Compliance  
> **Priority:** Medium  
> **Estimated Effort:** 1-2 days  
> **Dependencies:** None

## User Story

**As a** security engineer  
**I want** automated security scanning  
**So that** vulnerabilities are detected early in the development lifecycle

## Objective

Implement automated security scanning in CI/CD pipelines including dependency vulnerability scanning, container image scanning, static application security testing (SAST), secrets detection, and establish procedures for regular penetration testing.

## Architecture Reference

- **Dependency Scanning:** Snyk, Dependabot, Safety (Python)
- **Container Scanning:** Trivy, Clair
- **SAST:** Semgrep, Bandit (Python), ESLint security plugins
- **Secrets Detection:** GitLeaks, TruffleHog
- **DAST:** OWASP ZAP (for staging environments)
- **Integration:** GitHub Actions / GitLab CI

## Implementation Tasks

### 1. Configure Dependency Scanning

`pyproject.toml` (dependency groups):

```toml
[tool.poetry.group.security.dependencies]
safety = "^2.3.0"
bandit = "^1.7.5"
pip-audit = "^2.6.0"
```

`.github/workflows/security-dependency-scan.yml`:

```yaml
name: Dependency Security Scan

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]
  schedule:
    - cron: '0 6 * * 1'  # Weekly on Monday

jobs:
  python-dependency-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install safety pip-audit
          pip install -r requirements.txt
      
      - name: Run Safety check
        run: safety check --full-report
        continue-on-error: true
      
      - name: Run pip-audit
        run: pip-audit
        continue-on-error: true
      
      - name: Upload results
        uses: actions/upload-artifact@v4
        with:
          name: dependency-scan-results
          path: |
            safety-report.json
            pip-audit-report.json

  snyk-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Run Snyk to check for vulnerabilities
        uses: snyk/actions/python@master
        env:
          SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
        with:
          args: --severity-threshold=high --file=requirements.txt
      
      - name: Upload Snyk results to GitHub
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: snyk.sarif

  npm-audit:
    runs-on: ubuntu-latest
    if: hashFiles('package-lock.json') != ''
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      
      - name: Install dependencies
        run: npm ci
      
      - name: Run npm audit
        run: npm audit --audit-level=high
```

### 2. Configure Container Image Scanning

`.github/workflows/security-container-scan.yml`:

```yaml
name: Container Security Scan

on:
  push:
    branches: [main]
    paths:
      - 'services/**/Dockerfile'
      - '.github/workflows/security-container-scan.yml'
  pull_request:
    branches: [main]

jobs:
  trivy-scan:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        service:
          - api-gateway
          - ingestion
          - retrieval
          - query
    steps:
      - uses: actions/checkout@v4
      
      - name: Build Docker image
        run: |
          docker build -t rag-pipeline/${{ matrix.service }}:${{ github.sha }} \
            -f services/${{ matrix.service }}/Dockerfile \
            services/${{ matrix.service }}
      
      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: 'rag-pipeline/${{ matrix.service }}:${{ github.sha }}'
          format: 'sarif'
          output: 'trivy-results-${{ matrix.service }}.sarif'
          severity: 'CRITICAL,HIGH'
          exit-code: '1'  # Fail on critical/high
        continue-on-error: true
      
      - name: Upload Trivy scan results
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: 'trivy-results-${{ matrix.service }}.sarif'
      
      - name: Run Trivy for SBOM
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: 'rag-pipeline/${{ matrix.service }}:${{ github.sha }}'
          format: 'spdx-json'
          output: 'sbom-${{ matrix.service }}.json'
      
      - name: Upload SBOM
        uses: actions/upload-artifact@v4
        with:
          name: sbom-${{ matrix.service }}
          path: sbom-${{ matrix.service }}.json

  grype-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Build all images
        run: docker compose build
      
      - name: Run Grype scanner
        uses: anchore/scan-action@v3
        with:
          image: "rag-pipeline/api-gateway:latest"
          fail-build: true
          severity-cutoff: high
          output-format: sarif
      
      - name: Upload results
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: ${{ steps.scan.outputs.sarif }}
```

### 3. Configure SAST (Static Analysis)

`.github/workflows/security-sast.yml`:

```yaml
name: Static Application Security Testing

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  bandit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install Bandit
        run: pip install bandit[toml]
      
      - name: Run Bandit
        run: |
          bandit -r services/ \
            -f json \
            -o bandit-results.json \
            --severity-level medium \
            -c pyproject.toml
        continue-on-error: true
      
      - name: Upload Bandit results
        uses: actions/upload-artifact@v4
        with:
          name: bandit-results
          path: bandit-results.json
      
      - name: Convert to SARIF
        run: |
          pip install bandit-sarif-formatter
          bandit -r services/ -f sarif -o bandit.sarif
        continue-on-error: true
      
      - name: Upload SARIF
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: bandit.sarif

  semgrep:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Run Semgrep
        uses: returntocorp/semgrep-action@v1
        with:
          config: >-
            p/python
            p/security-audit
            p/secrets
            p/owasp-top-ten
          generateSarif: true
      
      - name: Upload SARIF
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: semgrep.sarif

  codeql:
    runs-on: ubuntu-latest
    permissions:
      actions: read
      contents: read
      security-events: write
    steps:
      - uses: actions/checkout@v4
      
      - name: Initialize CodeQL
        uses: github/codeql-action/init@v2
        with:
          languages: python
          queries: security-extended
      
      - name: Autobuild
        uses: github/codeql-action/autobuild@v2
      
      - name: Perform CodeQL Analysis
        uses: github/codeql-action/analyze@v2
```

### 4. Configure Secrets Detection

`.github/workflows/security-secrets.yml`:

```yaml
name: Secrets Detection

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  gitleaks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      
      - name: Run Gitleaks
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITLEAKS_LICENSE: ${{ secrets.GITLEAKS_LICENSE }}
      
      - name: Upload results
        uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: gitleaks-results
          path: gitleaks-report.json

  trufflehog:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      
      - name: TruffleHog OSS
        uses: trufflesecurity/trufflehog@main
        with:
          path: ./
          base: ${{ github.event.repository.default_branch }}
          head: HEAD
          extra_args: --only-verified
```

`.gitleaks.toml`:

```toml
[extend]
useDefault = true

[allowlist]
description = "Global allowlist"
paths = [
    '''\.env\.example$''',
    '''tests/.*test.*\.py$''',
    '''docs/.*\.md$''',
]

[[rules]]
id = "custom-api-key"
description = "Custom API Key pattern"
regex = '''(?i)api[_-]?key\s*[=:]\s*['"]?([a-zA-Z0-9]{32,})['"]?'''
secretGroup = 1
tags = ["api", "key"]

[[rules]]
id = "jwt-secret"
description = "JWT Secret"
regex = '''(?i)jwt[_-]?secret\s*[=:]\s*['"]?([a-zA-Z0-9+/=]{20,})['"]?'''
secretGroup = 1
tags = ["jwt", "secret"]
```

### 5. Configure Bandit Settings

`pyproject.toml`:

```toml
[tool.bandit]
exclude_dirs = ["tests", "venv", ".venv", "node_modules"]
skips = ["B101", "B601"]  # Skip assert and shell injection in tests

[tool.bandit.assert_used]
skips = ["*_test.py", "test_*.py"]

# Custom severity levels
[tool.bandit.any_other_function_with_shell_equals_true]
level = "MEDIUM"
```

### 6. Configure Semgrep Rules

`.semgrep.yml`:

```yaml
rules:
  # Custom rule for SQL injection in SQLAlchemy
  - id: sqlalchemy-raw-query
    patterns:
      - pattern: |
          $SESSION.execute(f"...")
      - pattern: |
          $SESSION.execute($QUERY.format(...))
    message: "Potential SQL injection with raw query"
    languages: [python]
    severity: ERROR

  # Insecure deserialization
  - id: pickle-unsafe
    patterns:
      - pattern: pickle.loads(...)
      - pattern: pickle.load(...)
    message: "Unsafe pickle usage - can lead to remote code execution"
    languages: [python]
    severity: ERROR

  # Hardcoded credentials
  - id: hardcoded-password
    patterns:
      - pattern: |
          password = "..."
      - pattern: |
          PASSWORD = "..."
    message: "Hardcoded password detected"
    languages: [python]
    severity: ERROR

  # JWT without expiration
  - id: jwt-no-expiration
    patterns:
      - pattern: |
          jwt.encode(..., ...)
      - pattern-not: |
          jwt.encode(..., exp=..., ...)
    message: "JWT token without expiration"
    languages: [python]
    severity: WARNING

  # Insecure random
  - id: insecure-random
    patterns:
      - pattern: random.random()
      - pattern: random.randint(...)
    message: "Use secrets module for security-sensitive random values"
    languages: [python]
    severity: WARNING
    metadata:
      category: security
```

### 7. Create Security Scanning Script

`scripts/security-scan.sh`:

```bash
#!/bin/bash
set -e

echo "=========================================="
echo "Running Security Scans"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

FAILED=0
WARNINGS=0

# 1. Dependency Scan
echo -e "\n${YELLOW}[1/6] Running dependency vulnerability scan...${NC}"
if pip-audit --strict 2>/dev/null; then
    echo -e "${GREEN}✓ No vulnerable dependencies found${NC}"
else
    echo -e "${RED}✗ Vulnerable dependencies detected${NC}"
    FAILED=$((FAILED + 1))
fi

# 2. Safety Check
echo -e "\n${YELLOW}[2/6] Running Safety check...${NC}"
if safety check --full-report 2>/dev/null; then
    echo -e "${GREEN}✓ Safety check passed${NC}"
else
    echo -e "${RED}✗ Safety check found issues${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

# 3. Bandit SAST
echo -e "\n${YELLOW}[3/6] Running Bandit SAST...${NC}"
if bandit -r services/ -c pyproject.toml -ll 2>/dev/null; then
    echo -e "${GREEN}✓ No high/critical issues found${NC}"
else
    echo -e "${RED}✗ Bandit found security issues${NC}"
    FAILED=$((FAILED + 1))
fi

# 4. Semgrep
echo -e "\n${YELLOW}[4/6] Running Semgrep...${NC}"
if semgrep --config=auto --config=.semgrep.yml services/ --error 2>/dev/null; then
    echo -e "${GREEN}✓ Semgrep scan passed${NC}"
else
    echo -e "${RED}✗ Semgrep found issues${NC}"
    FAILED=$((FAILED + 1))
fi

# 5. Secrets Detection
echo -e "\n${YELLOW}[5/6] Running Gitleaks...${NC}"
if gitleaks detect --source . --config .gitleaks.toml 2>/dev/null; then
    echo -e "${GREEN}✓ No secrets detected${NC}"
else
    echo -e "${RED}✗ Secrets detected in code${NC}"
    FAILED=$((FAILED + 1))
fi

# 6. Container Scan (if Docker available)
echo -e "\n${YELLOW}[6/6] Running Container scan...${NC}"
if command -v trivy &> /dev/null; then
    if docker images | grep -q "rag-pipeline"; then
        trivy image --severity HIGH,CRITICAL rag-pipeline/api-gateway:latest
    else
        echo "No container images to scan"
    fi
else
    echo "Trivy not installed, skipping container scan"
fi

# Summary
echo -e "\n=========================================="
echo "Security Scan Summary"
echo "=========================================="
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All critical scans passed!${NC}"
    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}$WARNINGS warnings to review${NC}"
    fi
    exit 0
else
    echo -e "${RED}$FAILED critical issues found${NC}"
    echo -e "${YELLOW}$WARNINGS warnings${NC}"
    exit 1
fi
```

### 8. Pre-commit Hooks

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: check-added-large-files
        args: ['--maxkb=500']
      - id: check-case-conflict
      - id: check-merge-conflict
      - id: check-yaml
      - id: detect-private-key
      - id: end-of-file-fixer
      - id: trailing-whitespace

  - repo: https://github.com/PyCQA/bandit
    rev: 1.7.5
    hooks:
      - id: bandit
        args: ["-c", "pyproject.toml", "-ll"]
        additional_dependencies: ["bandit[toml]"]

  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks

  - repo: https://github.com/returntocorp/semgrep
    rev: 'v1.48.0'
    hooks:
      - id: semgrep
        args: ['--config', 'auto', '--error']

  - repo: local
    hooks:
      - id: check-secrets-in-config
        name: Check for secrets in config files
        entry: python scripts/check_secrets.py
        language: python
        files: \.(yaml|yml|json|env|ini|conf)$
```

### 9. Security Report Generator

`scripts/generate_security_report.py`:

```python
#!/usr/bin/env python3
"""Generate consolidated security report from scan results."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any


def load_json_report(path: str) -> Dict[str, Any]:
    """Load JSON report file."""
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def parse_bandit_results(path: str) -> List[Dict]:
    """Parse Bandit scan results."""
    data = load_json_report(path)
    issues = []
    
    for result in data.get("results", []):
        issues.append({
            "tool": "bandit",
            "severity": result.get("issue_severity", "UNKNOWN"),
            "confidence": result.get("issue_confidence", "UNKNOWN"),
            "file": result.get("filename"),
            "line": result.get("line_number"),
            "issue": result.get("issue_text"),
            "cwe": result.get("issue_cwe", {}).get("id"),
        })
    
    return issues


def parse_trivy_results(path: str) -> List[Dict]:
    """Parse Trivy scan results."""
    data = load_json_report(path)
    issues = []
    
    for result in data.get("Results", []):
        for vuln in result.get("Vulnerabilities", []):
            issues.append({
                "tool": "trivy",
                "severity": vuln.get("Severity"),
                "package": vuln.get("PkgName"),
                "version": vuln.get("InstalledVersion"),
                "fixed_version": vuln.get("FixedVersion"),
                "vulnerability_id": vuln.get("VulnerabilityID"),
                "title": vuln.get("Title"),
                "description": vuln.get("Description"),
            })
    
    return issues


def parse_gitleaks_results(path: str) -> List[Dict]:
    """Parse Gitleaks scan results."""
    data = load_json_report(path)
    issues = []
    
    for finding in data:
        issues.append({
            "tool": "gitleaks",
            "severity": "HIGH",
            "file": finding.get("File"),
            "line": finding.get("StartLine"),
            "rule": finding.get("RuleID"),
            "secret_type": finding.get("Description"),
            "commit": finding.get("Commit"),
        })
    
    return issues


def generate_report(output_dir: str) -> Dict[str, Any]:
    """Generate consolidated security report."""
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "summary": {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        },
        "by_tool": {},
        "issues": [],
    }
    
    # Parse all available reports
    scan_files = {
        "bandit": f"{output_dir}/bandit-results.json",
        "trivy": f"{output_dir}/trivy-results.json",
        "gitleaks": f"{output_dir}/gitleaks-report.json",
    }
    
    for tool, path in scan_files.items():
        if os.path.exists(path):
            if tool == "bandit":
                issues = parse_bandit_results(path)
            elif tool == "trivy":
                issues = parse_trivy_results(path)
            elif tool == "gitleaks":
                issues = parse_gitleaks_results(path)
            else:
                issues = []
            
            report["by_tool"][tool] = len(issues)
            report["issues"].extend(issues)
    
    # Count by severity
    for issue in report["issues"]:
        severity = issue.get("severity", "").upper()
        if severity in report["summary"]:
            report["summary"][severity] += 1
    
    return report


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate security report")
    parser.add_argument("--output-dir", default="./security-reports")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args()
    
    report = generate_report(args.output_dir)
    
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        # Markdown format
        print(f"# Security Scan Report")
        print(f"\nGenerated: {report['generated_at']}")
        print(f"\n## Summary")
        print(f"- Critical: {report['summary']['critical']}")
        print(f"- High: {report['summary']['high']}")
        print(f"- Medium: {report['summary']['medium']}")
        print(f"- Low: {report['summary']['low']}")
        print(f"\n## Issues by Tool")
        for tool, count in report['by_tool'].items():
            print(f"- {tool}: {count}")


if __name__ == "__main__":
    main()
```

### 10. Penetration Testing Procedure

`docs/security/penetration-testing.md`:

```markdown
# Penetration Testing Procedure

## Schedule

- **Frequency:** Quarterly for staging, annually for production
- **Scope:** All external APIs, authentication flows, authorization logic
- **Type:** Black-box and gray-box testing

## Pre-Testing Checklist

- [ ] Define scope and objectives
- [ ] Get written authorization
- [ ] Set up isolated test environment
- [ ] Provide test accounts and credentials
- [ ] Document known issues (out of scope)
- [ ] Establish communication channels

## Testing Areas

### 1. Authentication Testing
- [ ] Brute force protection
- [ ] Password policy enforcement
- [ ] Session management
- [ ] JWT token security
- [ ] OAuth flow vulnerabilities

### 2. Authorization Testing
- [ ] Privilege escalation
- [ ] IDOR (Insecure Direct Object Reference)
- [ ] Tenant isolation
- [ ] RBAC bypass attempts

### 3. Injection Testing
- [ ] SQL injection (SQLAlchemy)
- [ ] NoSQL injection (Qdrant, OpenSearch)
- [ ] Command injection
- [ ] LDAP injection

### 4. API Security
- [ ] Rate limiting effectiveness
- [ ] Input validation
- [ ] Error handling (no info leakage)
- [ ] API versioning security

### 5. Data Security
- [ ] Encryption verification
- [ ] PII handling
- [ ] Data exfiltration attempts
- [ ] Backup security

## OWASP ZAP Automated Scan

```bash
# Run ZAP baseline scan against staging
docker run -t owasp/zap2docker-stable zap-baseline.py \
  -t https://staging-api.rag-pipeline.example.com \
  -r zap-report.html

# Run full scan
docker run -t owasp/zap2docker-stable zap-full-scan.py \
  -t https://staging-api.rag-pipeline.example.com \
  -r zap-full-report.html
```

## Post-Testing

1. Receive detailed report from pentest team
2. Triage findings by severity
3. Create remediation tickets
4. Set remediation deadlines:
   - Critical: 24 hours
   - High: 7 days
   - Medium: 30 days
   - Low: 90 days
5. Verify fixes
6. Request retest if needed
7. Document lessons learned
```

## Acceptance Criteria

- [ ] Dependency scanning in CI/CD pipeline
- [ ] Container image scanning with Trivy
- [ ] SAST with Bandit and Semgrep
- [ ] Secrets detection with Gitleaks
- [ ] Pre-commit hooks configured
- [ ] Security report generation
- [ ] Penetration testing procedure documented
- [ ] All scans integrated in GitHub Actions
- [ ] Build fails on critical/high vulnerabilities

## Verification Commands

```bash
# Run local security scan
./scripts/security-scan.sh

# Run Bandit
bandit -r services/ -c pyproject.toml

# Run Semgrep
semgrep --config=auto services/

# Run Gitleaks
gitleaks detect --source . --verbose

# Scan container image
trivy image rag-pipeline/api-gateway:latest

# Generate security report
python scripts/generate_security_report.py --format markdown

# Check for outdated dependencies
pip-audit

# Install pre-commit hooks
pre-commit install
pre-commit run --all-files
```

## Environment Variables

```bash
# Snyk
SNYK_TOKEN=your-snyk-token

# Gitleaks
GITLEAKS_LICENSE=your-license-key

# GitHub
GITHUB_TOKEN=your-token
```

## Files to Create

1. `.github/workflows/security-dependency-scan.yml`
2. `.github/workflows/security-container-scan.yml`
3. `.github/workflows/security-sast.yml`
4. `.github/workflows/security-secrets.yml`
5. `.gitleaks.toml`
6. `.semgrep.yml`
7. `.pre-commit-config.yaml`
8. `scripts/security-scan.sh`
9. `scripts/generate_security_report.py`
10. `docs/security/penetration-testing.md`

## Security Considerations

- **Fail fast** - Block merges on critical vulnerabilities
- **Regular updates** - Keep scanning tools updated
- **False positive management** - Maintain allowlists carefully
- **Baseline scans** - Run on main branch regularly
- **SBOM generation** - Maintain software bill of materials
- **Remediation SLAs** - Define and enforce fix timelines
