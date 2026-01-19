# US-10.3.4: SLO Definitions & Alerts - Design Document

**Date:** 2026-01-19
**Status:** Approved
**Reference:** workflow/refined/10-architectural-improvements/US-10.3.4-slo-definitions-alerts.md

## Overview

Define Service Level Objectives (SLOs) for the RAG pipeline with automated alerting based on error budgets and burn rates. This builds on the existing SLI/SLO framework in `services/shared/observability/metrics/definitions/`.

## Design Decisions

1. **Per-tenant SLOs** - Implement true per-tenant error budgets (not just global aggregations)
2. **Dashboard** - Full JSON dashboard provisioned via ConfigMap with error budget gauges, burn rate stats, SLI time series
3. **Runbooks** - Stored in `docs/runbooks/slo/` as markdown files versioned with code
4. **Rule generation** - CLI script outputs YAML to `config/prometheus/` for manual review before deployment

## SLO Targets (per US-10.3.4)

| SLO | Target | Window |
|-----|--------|--------|
| Retrieval p95 latency | < 250ms | 30d |
| RAG E2E p95 latency | < 2000ms | 30d |
| Error rate per tenant | < 1% | 30d |
| Service availability | > 99.9% | 30d |

## New/Modified Files

### New Files

| File | Purpose |
|------|---------|
| `scripts/generate_slo_rules.py` | CLI to generate Prometheus rules from SLI/SLO definitions |
| `config/prometheus/slo_recording_rules.yaml` | Generated recording rules |
| `config/prometheus/slo_alerting_rules.yaml` | Generated alerting rules |
| `config/grafana/dashboards/slo-overview.json` | SLO dashboard for Grafana |
| `docs/runbooks/slo/rag-error-budget-burn.md` | Runbook for error budget alerts |
| `docs/runbooks/slo/retrieval-latency.md` | Runbook for retrieval latency alerts |
| `docs/runbooks/slo/rag-e2e-latency.md` | Runbook for E2E latency alerts |
| `docs/runbooks/slo/service-availability.md` | Runbook for availability alerts |

### Modified Files

| File | Changes |
|------|---------|
| `services/shared/observability/metrics/definitions/sli.py` | Add tenant-scoped and latency SLIs |
| `services/shared/observability/metrics/definitions/slo.py` | Add new SLOs, tenant_scoped flag, update targets |
| `k8s/base/observability/prometheus.yaml` | Reference generated rule files |
| `k8s/base/observability/grafana.yaml` | Add dashboard ConfigMap |

## Technical Design

### 1. SLI Definitions

New SLIs to add to `sli.py`:

```python
# Tenant-scoped error rate
_register_sli(
    SLI(
        name="tenant_error_rate",
        description="Per-tenant error rate for RAG queries",
        query_good='sum(rate(rag_queries_total{status="success"}[{{window}}])) by (tenant_id)',
        query_total='sum(rate(rag_queries_total[{{window}}])) by (tenant_id)',
        category="availability",
    ),
)

# Retrieval latency p95 (250ms target)
_register_sli(
    SLI(
        name="retrieval_latency_p95_target",
        description="Percentage of retrieval requests under 250ms",
        query_good='sum(rate(retrieval_service_search_duration_seconds_bucket{le="0.25"}[{{window}}]))',
        query_total='sum(rate(retrieval_service_search_duration_seconds_count[{{window}}]))',
        category="latency",
    ),
)

# RAG E2E latency p95 (2000ms target)
_register_sli(
    SLI(
        name="rag_e2e_latency_p95_target",
        description="Percentage of RAG queries under 2000ms",
        query_good='sum(rate(rag_e2e_latency_seconds_bucket{le="2.0"}[{{window}}]))',
        query_total='sum(rate(rag_e2e_latency_seconds_count[{{window}}]))',
        category="latency",
    ),
)
```

### 2. SLO Definitions

Updates to `slo.py`:

```python
@dataclass
class SLO:
    # ... existing fields ...
    tenant_scoped: bool = False  # NEW: enables per-tenant tracking

# New SLOs
_register_slo(
    SLO(
        name="retrieval_latency_p95",
        sli_name="retrieval_latency_p95_target",
        target=0.95,
        window="30d",
        description="95% of retrieval requests complete in under 250ms",
        owner="platform-team",
    ),
)

_register_slo(
    SLO(
        name="rag_e2e_latency_p95",
        sli_name="rag_e2e_latency_p95_target",
        target=0.95,
        window="30d",
        description="95% of RAG queries complete in under 2 seconds",
        owner="platform-team",
    ),
)

_register_slo(
    SLO(
        name="tenant_error_rate",
        sli_name="tenant_error_rate",
        target=0.99,
        window="30d",
        description="Per-tenant error rate below 1%",
        owner="platform-team",
        tenant_scoped=True,
    ),
)
```

### 3. Rule Generation Script

`scripts/generate_slo_rules.py`:

```python
#!/usr/bin/env python3
"""Generate Prometheus SLO recording and alerting rules."""

import argparse
import yaml
from pathlib import Path

# Add services/shared to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "services"))

from shared.observability.metrics.definitions.slo import (
    SLO_CATALOG,
    generate_all_slo_rules,
)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="config/prometheus/")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rules = generate_all_slo_rules()

    # Split into recording and alerting
    recording = {"groups": [rules["groups"][0]]}
    alerting = {"groups": [rules["groups"][1]]}

    with open(output_dir / "slo_recording_rules.yaml", "w") as f:
        yaml.dump(recording, f, default_flow_style=False)

    with open(output_dir / "slo_alerting_rules.yaml", "w") as f:
        yaml.dump(alerting, f, default_flow_style=False)

    print(f"Generated rules in {output_dir}")

if __name__ == "__main__":
    main()
```

### 4. Grafana Dashboard

`config/grafana/dashboards/slo-overview.json`:

**Row 1 - Overview Gauges:**
- Error Budget Remaining (Gauge)
- Retrieval Latency SLO (Gauge)
- E2E Latency SLO (Gauge)
- Service Availability (Gauge)

**Row 2 - Burn Rate Stats:**
- Burn Rate 1h (Stat)
- Burn Rate 6h (Stat)
- Time Until Budget Exhaustion (Stat)

**Row 3 - SLI Time Series:**
- Error Rate by Tenant (Time series with tenant_id grouping)
- Retrieval Latency p95 (Time series with 250ms target line)
- RAG E2E Latency p95 (Time series with 2s target line)

**Row 4 - Error Budget:**
- Error Budget Burn Over Time (Time series)
- 30-Day SLO Compliance Table (Table)

### 5. Runbook Structure

Each runbook in `docs/runbooks/slo/` follows this template:

```markdown
# Runbook: [Alert Name]

## Alert
- Name: [AlertName]
- Severity: [critical/warning]
- SLO: [slo_name]

## Impact
[User-facing impact description]

## Investigation Steps
1. Check service health
2. Identify error/latency source
3. Check dependencies
4. Review recent deployments

## Mitigation
[Specific mitigation steps with commands]

## Escalation
- Warning >30min: Page on-call SRE
- Critical >10min: Declare incident

## Recovery Verification
[How to confirm the issue is resolved]
```

## Implementation Order

1. Update SLI definitions
2. Update SLO definitions (add tenant_scoped support)
3. Create rule generation script
4. Generate rules
5. Create Grafana dashboard
6. Write runbooks
7. Update Kubernetes manifests
8. Add tests

## Testing

- Unit tests for rule generation
- Validate generated YAML is valid Prometheus syntax
- Test dashboard JSON is valid
- Integration test: deploy to dev and verify alerts fire on simulated data
