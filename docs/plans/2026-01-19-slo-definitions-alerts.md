# US-10.3.4: SLO Definitions & Alerts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement SLOs with per-tenant error budgets, Prometheus rules, Grafana dashboard, and runbooks.

**Architecture:** Extend existing SLI/SLO framework in `services/shared/observability/metrics/definitions/` with tenant-scoped SLIs. Generate Prometheus rules via CLI script. Provision Grafana dashboard via ConfigMap.

**Tech Stack:** Python 3.11+, Prometheus, Grafana, pytest, YAML

---

## Task 1: Add Tenant-Scoped SLI

**Files:**
- Modify: `services/shared/observability/metrics/definitions/sli.py:60-95`
- Test: `services/shared/observability/tests/test_metrics.py`

**Step 1: Write failing test for tenant_error_rate SLI**

Add to `services/shared/observability/tests/test_metrics.py` in the `TestSLI` class:

```python
def test_tenant_error_rate_sli_exists(self):
    """Test that tenant_error_rate SLI is registered."""
    from shared.observability.metrics.definitions import SLI_CATALOG

    assert "tenant_error_rate" in SLI_CATALOG
    sli = SLI_CATALOG["tenant_error_rate"]
    assert "tenant_id" in sli.query_good
    assert "tenant_id" in sli.query_total
    assert sli.category == "availability"
```

**Step 2: Run test to verify it fails**

Run: `cd services && python -m pytest shared/observability/tests/test_metrics.py::TestSLI::test_tenant_error_rate_sli_exists -v`

Expected: FAIL with `KeyError: 'tenant_error_rate'`

**Step 3: Add tenant_error_rate SLI**

Add to `services/shared/observability/metrics/definitions/sli.py` after line 82 (after `retrieval_availability` SLI):

```python
_register_sli(
    SLI(
        name="tenant_error_rate",
        description="Per-tenant success rate for RAG queries",
        query_good='sum(rate(rag_queries_total{status="success"}[{{window}}])) by (tenant_id)',
        query_total="sum(rate(rag_queries_total[{{window}}])) by (tenant_id)",
        category="availability",
    ),
)
```

**Step 4: Run test to verify it passes**

Run: `cd services && python -m pytest shared/observability/tests/test_metrics.py::TestSLI::test_tenant_error_rate_sli_exists -v`

Expected: PASS

**Step 5: Commit**

```bash
git add services/shared/observability/metrics/definitions/sli.py services/shared/observability/tests/test_metrics.py
git commit -m "feat(observability): add tenant_error_rate SLI for per-tenant tracking"
```

---

## Task 2: Add Latency Target SLIs

**Files:**
- Modify: `services/shared/observability/metrics/definitions/sli.py`
- Test: `services/shared/observability/tests/test_metrics.py`

**Step 1: Write failing tests for latency SLIs**

Add to `services/shared/observability/tests/test_metrics.py` in the `TestSLI` class:

```python
def test_retrieval_latency_target_sli_exists(self):
    """Test that retrieval_latency_p95_target SLI exists with 250ms threshold."""
    from shared.observability.metrics.definitions import SLI_CATALOG

    assert "retrieval_latency_p95_target" in SLI_CATALOG
    sli = SLI_CATALOG["retrieval_latency_p95_target"]
    assert 'le="0.25"' in sli.query_good  # 250ms
    assert sli.category == "latency"

def test_rag_e2e_latency_target_sli_exists(self):
    """Test that rag_e2e_latency_p95_target SLI exists with 2s threshold."""
    from shared.observability.metrics.definitions import SLI_CATALOG

    assert "rag_e2e_latency_p95_target" in SLI_CATALOG
    sli = SLI_CATALOG["rag_e2e_latency_p95_target"]
    assert 'le="2.0"' in sli.query_good  # 2000ms
    assert sli.category == "latency"
```

**Step 2: Run tests to verify they fail**

Run: `cd services && python -m pytest shared/observability/tests/test_metrics.py::TestSLI::test_retrieval_latency_target_sli_exists shared/observability/tests/test_metrics.py::TestSLI::test_rag_e2e_latency_target_sli_exists -v`

Expected: FAIL with `KeyError`

**Step 3: Add latency target SLIs**

Add to `services/shared/observability/metrics/definitions/sli.py` after the `llm_ttft_p95` SLI (around line 156):

```python
_register_sli(
    SLI(
        name="retrieval_latency_p95_target",
        description="Percentage of retrieval requests completing under 250ms",
        query_good='sum(rate(retrieval_service_search_duration_seconds_bucket{le="0.25"}[{{window}}]))',
        query_total="sum(rate(retrieval_service_search_duration_seconds_count[{{window}}]))",
        category="latency",
    ),
)

_register_sli(
    SLI(
        name="rag_e2e_latency_p95_target",
        description="Percentage of RAG queries completing under 2000ms",
        query_good='sum(rate(rag_e2e_latency_seconds_bucket{le="2.0"}[{{window}}]))',
        query_total="sum(rate(rag_e2e_latency_seconds_count[{{window}}]))",
        category="latency",
    ),
)
```

**Step 4: Run tests to verify they pass**

Run: `cd services && python -m pytest shared/observability/tests/test_metrics.py::TestSLI::test_retrieval_latency_target_sli_exists shared/observability/tests/test_metrics.py::TestSLI::test_rag_e2e_latency_target_sli_exists -v`

Expected: PASS

**Step 5: Commit**

```bash
git add services/shared/observability/metrics/definitions/sli.py services/shared/observability/tests/test_metrics.py
git commit -m "feat(observability): add latency target SLIs (250ms retrieval, 2s E2E)"
```

---

## Task 3: Add tenant_scoped Flag to SLO Dataclass

**Files:**
- Modify: `services/shared/observability/metrics/definitions/slo.py:37-62`
- Test: `services/shared/observability/tests/test_metrics.py`

**Step 1: Write failing test for tenant_scoped flag**

Add to `services/shared/observability/tests/test_metrics.py` in the `TestSLO` class:

```python
def test_slo_tenant_scoped_flag(self):
    """Test that SLO supports tenant_scoped flag."""
    from shared.observability.metrics.definitions.slo import SLO

    slo = SLO(
        name="test_tenant_slo",
        sli_name="tenant_error_rate",
        target=0.99,
        window="30d",
        description="Test tenant-scoped SLO",
        tenant_scoped=True,
    )

    assert slo.tenant_scoped is True

    # Default should be False
    slo_default = SLO(
        name="test_global_slo",
        sli_name="query_availability",
        target=0.999,
        window="30d",
        description="Test global SLO",
    )
    assert slo_default.tenant_scoped is False
```

**Step 2: Run test to verify it fails**

Run: `cd services && python -m pytest shared/observability/tests/test_metrics.py::TestSLO::test_slo_tenant_scoped_flag -v`

Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'tenant_scoped'`

**Step 3: Add tenant_scoped field to SLO dataclass**

Modify `services/shared/observability/metrics/definitions/slo.py`, update the SLO dataclass (around line 37-62):

```python
@dataclass
class SLO:
    """
    Service Level Objective definition.

    An SLO defines a target for an SLI over a compliance window,
    along with error budget calculations and alerting configuration.

    Attributes:
        name: Human-readable SLO name
        sli_name: Name of the SLI this SLO measures
        target: Target percentage (0-1, e.g., 0.999 for 99.9%)
        window: Compliance window (e.g., "30d")
        description: Human-readable description
        burn_rates: Burn rate alert configurations
        owner: Team or individual responsible
        consequences: What happens when SLO is violated
        tenant_scoped: If True, SLO is tracked per-tenant with separate error budgets
    """

    name: str
    sli_name: str
    target: float
    window: str
    description: str
    burn_rates: list[BurnRate] = field(default_factory=list)
    owner: str = ""
    consequences: str = ""
    tenant_scoped: bool = False
```

**Step 4: Run test to verify it passes**

Run: `cd services && python -m pytest shared/observability/tests/test_metrics.py::TestSLO::test_slo_tenant_scoped_flag -v`

Expected: PASS

**Step 5: Commit**

```bash
git add services/shared/observability/metrics/definitions/slo.py services/shared/observability/tests/test_metrics.py
git commit -m "feat(observability): add tenant_scoped flag to SLO dataclass"
```

---

## Task 4: Register New SLOs

**Files:**
- Modify: `services/shared/observability/metrics/definitions/slo.py:125-220`
- Test: `services/shared/observability/tests/test_metrics.py`

**Step 1: Write failing tests for new SLOs**

Add to `services/shared/observability/tests/test_metrics.py` in the `TestSLO` class:

```python
def test_new_slos_registered(self):
    """Test that US-10.3.4 SLOs are registered."""
    from shared.observability.metrics.definitions import SLO_CATALOG

    # Retrieval latency SLO
    assert "retrieval_latency_p95" in SLO_CATALOG
    retrieval_slo = SLO_CATALOG["retrieval_latency_p95"]
    assert retrieval_slo.target == 0.95
    assert retrieval_slo.sli_name == "retrieval_latency_p95_target"

    # E2E latency SLO
    assert "rag_e2e_latency_p95" in SLO_CATALOG
    e2e_slo = SLO_CATALOG["rag_e2e_latency_p95"]
    assert e2e_slo.target == 0.95
    assert e2e_slo.sli_name == "rag_e2e_latency_p95_target"

    # Tenant error rate SLO
    assert "tenant_error_rate" in SLO_CATALOG
    tenant_slo = SLO_CATALOG["tenant_error_rate"]
    assert tenant_slo.target == 0.99
    assert tenant_slo.tenant_scoped is True
```

**Step 2: Run test to verify it fails**

Run: `cd services && python -m pytest shared/observability/tests/test_metrics.py::TestSLO::test_new_slos_registered -v`

Expected: FAIL with `KeyError`

**Step 3: Register new SLOs**

Add to `services/shared/observability/metrics/definitions/slo.py` after the existing SLOs (after `cache_effectiveness` around line 216):

```python
# -----------------------------------------------------------------------------
# US-10.3.4 SLOs
# -----------------------------------------------------------------------------

_register_slo(
    SLO(
        name="retrieval_latency_p95",
        sli_name="retrieval_latency_p95_target",
        target=0.95,  # 95% of requests < 250ms
        window="30d",
        description="95% of retrieval requests complete in under 250ms",
        owner="platform-team",
        consequences="Slow queries, degraded user experience",
    ),
)

_register_slo(
    SLO(
        name="rag_e2e_latency_p95",
        sli_name="rag_e2e_latency_p95_target",
        target=0.95,  # 95% of requests < 2s
        window="30d",
        description="95% of RAG queries complete in under 2 seconds",
        owner="platform-team",
        consequences="Poor user experience, timeouts",
    ),
)

_register_slo(
    SLO(
        name="tenant_error_rate",
        sli_name="tenant_error_rate",
        target=0.99,  # <1% error rate per tenant
        window="30d",
        description="Per-tenant error rate below 1%",
        owner="platform-team",
        consequences="User-facing errors, tenant SLA violations",
        tenant_scoped=True,
    ),
)
```

**Step 4: Run test to verify it passes**

Run: `cd services && python -m pytest shared/observability/tests/test_metrics.py::TestSLO::test_new_slos_registered -v`

Expected: PASS

**Step 5: Commit**

```bash
git add services/shared/observability/metrics/definitions/slo.py services/shared/observability/tests/test_metrics.py
git commit -m "feat(observability): register US-10.3.4 SLOs (latency, tenant error rate)"
```

---

## Task 5: Update Rule Generation for Tenant-Scoped SLOs

**Files:**
- Modify: `services/shared/observability/metrics/definitions/slo.py:224-310`
- Test: `services/shared/observability/tests/test_metrics.py`

**Step 1: Write failing test for tenant-scoped rule generation**

Add to `services/shared/observability/tests/test_metrics.py` in the `TestSLO` class:

```python
def test_tenant_scoped_recording_rules_preserve_label(self):
    """Test that tenant-scoped SLOs generate rules preserving tenant_id label."""
    from shared.observability.metrics.definitions import SLO_CATALOG
    from shared.observability.metrics.definitions.slo import generate_slo_recording_rules

    slo = SLO_CATALOG["tenant_error_rate"]
    rules = generate_slo_recording_rules(slo)

    # Find the error_budget_remaining rule
    budget_rule = next(
        (r for r in rules if "error_budget_remaining" in r["record"]),
        None,
    )
    assert budget_rule is not None
    # Should preserve tenant_id grouping from SLI
    assert "tenant_id" in budget_rule["expr"] or "by (tenant_id)" in budget_rule.get("labels", {}).get("__preserve__", "")
```

**Step 2: Run test to verify it fails**

Run: `cd services && python -m pytest shared/observability/tests/test_metrics.py::TestSLO::test_tenant_scoped_recording_rules_preserve_label -v`

Expected: FAIL (the current implementation doesn't handle tenant_scoped specially)

**Step 3: Update generate_slo_recording_rules to handle tenant_scoped**

Modify `services/shared/observability/metrics/definitions/slo.py`, update the `generate_slo_recording_rules` function:

```python
def generate_slo_recording_rules(slo: SLO) -> list[dict[str, Any]]:
    """
    Generate Prometheus recording rules for an SLO.

    Creates rules for:
    - SLI ratio over various windows
    - Error budget remaining
    - Burn rate calculations

    For tenant_scoped SLOs, rules preserve the tenant_id label.

    Args:
        slo: SLO to generate rules for

    Returns:
        List of Prometheus recording rule definitions
    """
    sli = slo.get_sli()
    if sli is None:
        return []

    rules = []
    base_name = slo.name.replace("-", "_")

    # Recording rule for SLI ratio
    for window in ["5m", "30m", "1h", "6h", "1d", "3d", "7d", "30d"]:
        ratio_query = sli.query_ratio.replace("{{window}}", window)
        rule = {
            "record": f"slo:{base_name}:ratio_{window}",
            "expr": ratio_query,
            "labels": {
                "slo": slo.name,
                "window": window,
            },
        }
        rules.append(rule)

    # Error budget remaining (over compliance window)
    # For tenant_scoped, the query already includes "by (tenant_id)" from the SLI
    ratio_query = sli.query_ratio.replace("{{window}}", slo.window)
    budget_query = f"""
    1 - (
        (1 - ({ratio_query}))
        / {slo.error_budget}
    )
    """.strip()
    rules.append(
        {
            "record": f"slo:{base_name}:error_budget_remaining",
            "expr": budget_query,
            "labels": {
                "slo": slo.name,
            },
        },
    )

    # Burn rate for each window
    for burn_rate in slo.burn_rates:
        short_ratio = sli.query_ratio.replace("{{window}}", burn_rate.short_window)
        long_ratio = sli.query_ratio.replace("{{window}}", burn_rate.long_window)

        short_burn = f"(1 - ({short_ratio})) / {slo.error_budget}"
        long_burn = f"(1 - ({long_ratio})) / {slo.error_budget}"

        rules.append(
            {
                "record": f"slo:{base_name}:burn_rate_{burn_rate.short_window}",
                "expr": short_burn,
                "labels": {
                    "slo": slo.name,
                    "window": burn_rate.short_window,
                },
            },
        )

        rules.append(
            {
                "record": f"slo:{base_name}:burn_rate_{burn_rate.long_window}",
                "expr": long_burn,
                "labels": {
                    "slo": slo.name,
                    "window": burn_rate.long_window,
                },
            },
        )

    return rules
```

**Step 4: Run test to verify it passes**

Run: `cd services && python -m pytest shared/observability/tests/test_metrics.py::TestSLO::test_tenant_scoped_recording_rules_preserve_label -v`

Expected: PASS

**Step 5: Commit**

```bash
git add services/shared/observability/metrics/definitions/slo.py services/shared/observability/tests/test_metrics.py
git commit -m "feat(observability): preserve tenant_id label in tenant-scoped SLO rules"
```

---

## Task 6: Create Rule Generation CLI Script

**Files:**
- Create: `scripts/generate_slo_rules.py`
- Test: Run script and validate output

**Step 1: Create scripts directory if needed**

Run: `mkdir -p scripts config/prometheus`

**Step 2: Create the CLI script**

Create `scripts/generate_slo_rules.py`:

```python
#!/usr/bin/env python3
"""Generate Prometheus SLO recording and alerting rules from Python definitions.

Usage:
    python scripts/generate_slo_rules.py --output-dir config/prometheus/

This script reads the SLI/SLO definitions from the shared observability module
and generates Prometheus-compatible YAML rule files.
"""

import argparse
import sys
from pathlib import Path

# Add services directory to path for imports
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "services"))

import yaml


def main() -> int:
    """Generate SLO rules and write to output directory."""
    parser = argparse.ArgumentParser(
        description="Generate Prometheus SLO recording and alerting rules"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("config/prometheus"),
        help="Output directory for generated YAML files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print rules to stdout instead of writing files",
    )
    args = parser.parse_args()

    # Import after path setup
    from shared.observability.metrics.definitions.slo import (
        SLO_CATALOG,
        generate_all_slo_rules,
    )

    print(f"Generating rules for {len(SLO_CATALOG)} SLOs...")

    rules = generate_all_slo_rules()

    # Split into recording and alerting groups
    recording_group = next(
        (g for g in rules["groups"] if g["name"] == "slo_recording_rules"),
        {"name": "slo_recording_rules", "interval": "30s", "rules": []},
    )
    alerting_group = next(
        (g for g in rules["groups"] if g["name"] == "slo_alerting_rules"),
        {"name": "slo_alerting_rules", "rules": []},
    )

    recording_rules = {"groups": [recording_group]}
    alerting_rules = {"groups": [alerting_group]}

    if args.dry_run:
        print("\n=== Recording Rules ===")
        print(yaml.dump(recording_rules, default_flow_style=False, sort_keys=False))
        print("\n=== Alerting Rules ===")
        print(yaml.dump(alerting_rules, default_flow_style=False, sort_keys=False))
        return 0

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Write recording rules
    recording_path = args.output_dir / "slo_recording_rules.yaml"
    with open(recording_path, "w") as f:
        f.write("# Auto-generated by scripts/generate_slo_rules.py\n")
        f.write("# DO NOT EDIT MANUALLY - changes will be overwritten\n\n")
        yaml.dump(recording_rules, f, default_flow_style=False, sort_keys=False)
    print(f"Wrote recording rules to {recording_path}")

    # Write alerting rules
    alerting_path = args.output_dir / "slo_alerting_rules.yaml"
    with open(alerting_path, "w") as f:
        f.write("# Auto-generated by scripts/generate_slo_rules.py\n")
        f.write("# DO NOT EDIT MANUALLY - changes will be overwritten\n\n")
        yaml.dump(alerting_rules, f, default_flow_style=False, sort_keys=False)
    print(f"Wrote alerting rules to {alerting_path}")

    print(f"\nGenerated {len(recording_group['rules'])} recording rules")
    print(f"Generated {len(alerting_group['rules'])} alerting rules")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Step 3: Make script executable**

Run: `chmod +x scripts/generate_slo_rules.py`

**Step 4: Run script to generate rules**

Run: `python scripts/generate_slo_rules.py --output-dir config/prometheus/`

Expected: Success message with rule counts

**Step 5: Verify generated files**

Run: `ls -la config/prometheus/ && head -50 config/prometheus/slo_recording_rules.yaml`

Expected: Two YAML files with valid Prometheus rules

**Step 6: Commit**

```bash
git add scripts/generate_slo_rules.py config/prometheus/
git commit -m "feat(observability): add SLO rule generation script and generated rules"
```

---

## Task 7: Create Grafana SLO Dashboard

**Files:**
- Create: `config/grafana/dashboards/slo-overview.json`

**Step 1: Create directory structure**

Run: `mkdir -p config/grafana/dashboards`

**Step 2: Create dashboard JSON**

Create `config/grafana/dashboards/slo-overview.json`:

```json
{
  "annotations": {
    "list": []
  },
  "editable": true,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 1,
  "id": null,
  "links": [],
  "liveNow": false,
  "panels": [
    {
      "collapsed": false,
      "gridPos": { "h": 1, "w": 24, "x": 0, "y": 0 },
      "id": 1,
      "panels": [],
      "title": "SLO Overview",
      "type": "row"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "thresholds" },
          "mappings": [],
          "max": 100,
          "min": 0,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "red", "value": null },
              { "color": "yellow", "value": 25 },
              { "color": "green", "value": 50 }
            ]
          },
          "unit": "percent"
        },
        "overrides": []
      },
      "gridPos": { "h": 6, "w": 6, "x": 0, "y": 1 },
      "id": 2,
      "options": {
        "orientation": "auto",
        "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false },
        "showThresholdLabels": false,
        "showThresholdMarkers": true
      },
      "pluginVersion": "10.2.3",
      "targets": [
        {
          "datasource": { "type": "prometheus", "uid": "${datasource}" },
          "expr": "slo:tenant_error_rate:error_budget_remaining * 100",
          "legendFormat": "Error Budget %",
          "refId": "A"
        }
      ],
      "title": "Error Budget Remaining (Tenant Avg)",
      "type": "gauge"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "thresholds" },
          "mappings": [],
          "max": 100,
          "min": 0,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "red", "value": null },
              { "color": "yellow", "value": 90 },
              { "color": "green", "value": 95 }
            ]
          },
          "unit": "percent"
        },
        "overrides": []
      },
      "gridPos": { "h": 6, "w": 6, "x": 6, "y": 1 },
      "id": 3,
      "options": {
        "orientation": "auto",
        "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false },
        "showThresholdLabels": false,
        "showThresholdMarkers": true
      },
      "targets": [
        {
          "expr": "slo:retrieval_latency_p95:ratio_5m * 100",
          "legendFormat": "% under 250ms",
          "refId": "A"
        }
      ],
      "title": "Retrieval Latency SLO",
      "type": "gauge"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "thresholds" },
          "mappings": [],
          "max": 100,
          "min": 0,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "red", "value": null },
              { "color": "yellow", "value": 90 },
              { "color": "green", "value": 95 }
            ]
          },
          "unit": "percent"
        },
        "overrides": []
      },
      "gridPos": { "h": 6, "w": 6, "x": 12, "y": 1 },
      "id": 4,
      "options": {
        "orientation": "auto",
        "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false },
        "showThresholdLabels": false,
        "showThresholdMarkers": true
      },
      "targets": [
        {
          "expr": "slo:rag_e2e_latency_p95:ratio_5m * 100",
          "legendFormat": "% under 2s",
          "refId": "A"
        }
      ],
      "title": "RAG E2E Latency SLO",
      "type": "gauge"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "thresholds" },
          "mappings": [],
          "max": 100,
          "min": 0,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "red", "value": null },
              { "color": "yellow", "value": 99 },
              { "color": "green", "value": 99.9 }
            ]
          },
          "unit": "percent"
        },
        "overrides": []
      },
      "gridPos": { "h": 6, "w": 6, "x": 18, "y": 1 },
      "id": 5,
      "options": {
        "orientation": "auto",
        "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false },
        "showThresholdLabels": false,
        "showThresholdMarkers": true
      },
      "targets": [
        {
          "expr": "slo:query_availability:ratio_5m * 100",
          "legendFormat": "Availability %",
          "refId": "A"
        }
      ],
      "title": "Service Availability",
      "type": "gauge"
    },
    {
      "collapsed": false,
      "gridPos": { "h": 1, "w": 24, "x": 0, "y": 7 },
      "id": 6,
      "panels": [],
      "title": "Burn Rate",
      "type": "row"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "thresholds" },
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "yellow", "value": 2 },
              { "color": "red", "value": 10 }
            ]
          },
          "unit": "x"
        },
        "overrides": []
      },
      "gridPos": { "h": 4, "w": 8, "x": 0, "y": 8 },
      "id": 7,
      "options": {
        "colorMode": "value",
        "graphMode": "area",
        "justifyMode": "auto",
        "orientation": "auto",
        "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false },
        "textMode": "auto"
      },
      "targets": [
        {
          "expr": "avg(slo:tenant_error_rate:burn_rate_1h)",
          "legendFormat": "1h Burn Rate",
          "refId": "A"
        }
      ],
      "title": "Error Rate Burn (1h)",
      "description": "1x = sustainable, >2x = warning, >10x = critical",
      "type": "stat"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "thresholds" },
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "yellow", "value": 2 },
              { "color": "red", "value": 6 }
            ]
          },
          "unit": "x"
        },
        "overrides": []
      },
      "gridPos": { "h": 4, "w": 8, "x": 8, "y": 8 },
      "id": 8,
      "options": {
        "colorMode": "value",
        "graphMode": "area",
        "justifyMode": "auto",
        "orientation": "auto",
        "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false },
        "textMode": "auto"
      },
      "targets": [
        {
          "expr": "avg(slo:tenant_error_rate:burn_rate_6h)",
          "legendFormat": "6h Burn Rate",
          "refId": "A"
        }
      ],
      "title": "Error Rate Burn (6h)",
      "type": "stat"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "thresholds" },
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "red", "value": null },
              { "color": "yellow", "value": 168 },
              { "color": "green", "value": 720 }
            ]
          },
          "unit": "h"
        },
        "overrides": []
      },
      "gridPos": { "h": 4, "w": 8, "x": 16, "y": 8 },
      "id": 9,
      "options": {
        "colorMode": "value",
        "graphMode": "none",
        "justifyMode": "auto",
        "orientation": "auto",
        "reduceOptions": { "calcs": ["lastNotNull"], "fields": "", "values": false },
        "textMode": "auto"
      },
      "targets": [
        {
          "expr": "720 / clamp_min(avg(slo:tenant_error_rate:burn_rate_1h), 0.001)",
          "legendFormat": "Hours until exhaustion",
          "refId": "A"
        }
      ],
      "title": "Time Until Budget Exhaustion",
      "type": "stat"
    },
    {
      "collapsed": false,
      "gridPos": { "h": 1, "w": 24, "x": 0, "y": 12 },
      "id": 10,
      "panels": [],
      "title": "SLI Time Series",
      "type": "row"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "palette-classic" },
          "custom": {
            "axisCenteredZero": false,
            "axisColorMode": "text",
            "axisLabel": "",
            "axisPlacement": "auto",
            "barAlignment": 0,
            "drawStyle": "line",
            "fillOpacity": 10,
            "gradientMode": "none",
            "hideFrom": { "legend": false, "tooltip": false, "viz": false },
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "pointSize": 5,
            "scaleDistribution": { "type": "linear" },
            "showPoints": "never",
            "spanNulls": false,
            "stacking": { "group": "A", "mode": "none" },
            "thresholdsStyle": { "mode": "line" }
          },
          "mappings": [],
          "max": 5,
          "min": 0,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "red", "value": 1 }
            ]
          },
          "unit": "percent"
        },
        "overrides": []
      },
      "gridPos": { "h": 8, "w": 8, "x": 0, "y": 13 },
      "id": 11,
      "options": {
        "legend": { "calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": true },
        "tooltip": { "mode": "multi", "sort": "none" }
      },
      "targets": [
        {
          "expr": "(1 - slo:tenant_error_rate:ratio_5m) * 100",
          "legendFormat": "{{tenant_id}}",
          "refId": "A"
        },
        {
          "expr": "1",
          "legendFormat": "SLO Target (1%)",
          "refId": "B"
        }
      ],
      "title": "Error Rate by Tenant",
      "type": "timeseries"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "palette-classic" },
          "custom": {
            "axisCenteredZero": false,
            "axisColorMode": "text",
            "axisLabel": "",
            "axisPlacement": "auto",
            "barAlignment": 0,
            "drawStyle": "line",
            "fillOpacity": 10,
            "gradientMode": "none",
            "hideFrom": { "legend": false, "tooltip": false, "viz": false },
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "pointSize": 5,
            "scaleDistribution": { "type": "linear" },
            "showPoints": "never",
            "spanNulls": false,
            "stacking": { "group": "A", "mode": "none" },
            "thresholdsStyle": { "mode": "line" }
          },
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "red", "value": 0.25 }
            ]
          },
          "unit": "s"
        },
        "overrides": []
      },
      "gridPos": { "h": 8, "w": 8, "x": 8, "y": 13 },
      "id": 12,
      "options": {
        "legend": { "calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": true },
        "tooltip": { "mode": "multi", "sort": "none" }
      },
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum(rate(retrieval_service_search_duration_seconds_bucket[5m])) by (le))",
          "legendFormat": "p95 Latency",
          "refId": "A"
        },
        {
          "expr": "0.25",
          "legendFormat": "Target (250ms)",
          "refId": "B"
        }
      ],
      "title": "Retrieval Latency p95",
      "type": "timeseries"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "palette-classic" },
          "custom": {
            "axisCenteredZero": false,
            "axisColorMode": "text",
            "axisLabel": "",
            "axisPlacement": "auto",
            "barAlignment": 0,
            "drawStyle": "line",
            "fillOpacity": 10,
            "gradientMode": "none",
            "hideFrom": { "legend": false, "tooltip": false, "viz": false },
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "pointSize": 5,
            "scaleDistribution": { "type": "linear" },
            "showPoints": "never",
            "spanNulls": false,
            "stacking": { "group": "A", "mode": "none" },
            "thresholdsStyle": { "mode": "line" }
          },
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "red", "value": 2 }
            ]
          },
          "unit": "s"
        },
        "overrides": []
      },
      "gridPos": { "h": 8, "w": 8, "x": 16, "y": 13 },
      "id": 13,
      "options": {
        "legend": { "calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": true },
        "tooltip": { "mode": "multi", "sort": "none" }
      },
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum(rate(rag_e2e_latency_seconds_bucket[5m])) by (le))",
          "legendFormat": "p95 Latency",
          "refId": "A"
        },
        {
          "expr": "2",
          "legendFormat": "Target (2s)",
          "refId": "B"
        }
      ],
      "title": "RAG E2E Latency p95",
      "type": "timeseries"
    },
    {
      "collapsed": false,
      "gridPos": { "h": 1, "w": 24, "x": 0, "y": 21 },
      "id": 14,
      "panels": [],
      "title": "Error Budget",
      "type": "row"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "palette-classic" },
          "custom": {
            "axisCenteredZero": false,
            "axisColorMode": "text",
            "axisLabel": "",
            "axisPlacement": "auto",
            "barAlignment": 0,
            "drawStyle": "line",
            "fillOpacity": 20,
            "gradientMode": "none",
            "hideFrom": { "legend": false, "tooltip": false, "viz": false },
            "lineInterpolation": "linear",
            "lineWidth": 2,
            "pointSize": 5,
            "scaleDistribution": { "type": "linear" },
            "showPoints": "never",
            "spanNulls": false,
            "stacking": { "group": "A", "mode": "none" },
            "thresholdsStyle": { "mode": "off" }
          },
          "mappings": [],
          "max": 100,
          "min": 0,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null }
            ]
          },
          "unit": "percent"
        },
        "overrides": []
      },
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 22 },
      "id": 15,
      "options": {
        "legend": { "calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": true },
        "tooltip": { "mode": "multi", "sort": "none" }
      },
      "targets": [
        {
          "expr": "slo:tenant_error_rate:error_budget_remaining * 100",
          "legendFormat": "{{tenant_id}}",
          "refId": "A"
        }
      ],
      "title": "Error Budget Remaining Over Time",
      "type": "timeseries"
    },
    {
      "datasource": { "type": "prometheus", "uid": "${datasource}" },
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "thresholds" },
          "custom": {
            "align": "auto",
            "cellOptions": { "type": "auto" },
            "inspect": false
          },
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null }
            ]
          }
        },
        "overrides": [
          {
            "matcher": { "id": "byName", "options": "Current" },
            "properties": [
              { "id": "unit", "value": "percent" },
              { "id": "decimals", "value": 2 }
            ]
          },
          {
            "matcher": { "id": "byName", "options": "Target" },
            "properties": [
              { "id": "unit", "value": "percent" },
              { "id": "decimals", "value": 1 }
            ]
          },
          {
            "matcher": { "id": "byName", "options": "Status" },
            "properties": [
              {
                "id": "mappings",
                "value": [
                  { "options": { "Met": { "color": "green", "index": 0, "text": "Met" }, "Violated": { "color": "red", "index": 1, "text": "Violated" } }, "type": "value" }
                ]
              }
            ]
          }
        ]
      },
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 22 },
      "id": 16,
      "options": {
        "cellHeight": "sm",
        "footer": { "countRows": false, "fields": "", "reducer": ["sum"], "show": false },
        "showHeader": true
      },
      "targets": [
        {
          "expr": "slo:query_availability:ratio_30d * 100",
          "format": "table",
          "instant": true,
          "legendFormat": "",
          "refId": "A"
        },
        {
          "expr": "slo:retrieval_latency_p95:ratio_30d * 100",
          "format": "table",
          "instant": true,
          "legendFormat": "",
          "refId": "B"
        },
        {
          "expr": "slo:rag_e2e_latency_p95:ratio_30d * 100",
          "format": "table",
          "instant": true,
          "legendFormat": "",
          "refId": "C"
        }
      ],
      "title": "30-Day SLO Compliance",
      "transformations": [
        {
          "id": "merge",
          "options": {}
        }
      ],
      "type": "table"
    }
  ],
  "refresh": "30s",
  "schemaVersion": 38,
  "style": "dark",
  "tags": ["slo", "rag-pipeline", "observability"],
  "templating": {
    "list": [
      {
        "current": { "selected": false, "text": "Prometheus", "value": "Prometheus" },
        "hide": 0,
        "includeAll": false,
        "label": "Datasource",
        "multi": false,
        "name": "datasource",
        "options": [],
        "query": "prometheus",
        "refresh": 1,
        "regex": "",
        "skipUrlSync": false,
        "type": "datasource"
      }
    ]
  },
  "time": { "from": "now-24h", "to": "now" },
  "timepicker": {},
  "timezone": "browser",
  "title": "SLO Overview",
  "uid": "slo-overview",
  "version": 1,
  "weekStart": ""
}
```

**Step 3: Validate JSON syntax**

Run: `python -m json.tool config/grafana/dashboards/slo-overview.json > /dev/null && echo "Valid JSON"`

Expected: "Valid JSON"

**Step 4: Commit**

```bash
git add config/grafana/dashboards/slo-overview.json
git commit -m "feat(observability): add Grafana SLO overview dashboard"
```

---

## Task 8: Create Runbooks

**Files:**
- Create: `docs/runbooks/slo/rag-error-budget-burn.md`
- Create: `docs/runbooks/slo/retrieval-latency.md`
- Create: `docs/runbooks/slo/rag-e2e-latency.md`
- Create: `docs/runbooks/slo/service-availability.md`

**Step 1: Create runbooks directory**

Run: `mkdir -p docs/runbooks/slo`

**Step 2: Create error budget runbook**

Create `docs/runbooks/slo/rag-error-budget-burn.md`:

```markdown
# Runbook: RAG Error Budget Burn

## Alert

- **Name:** `SLOTenant_error_rateBurnRateTooHigh`
- **Severity:** critical / warning
- **SLO:** tenant_error_rate
- **Target:** 99% success rate per tenant

## Impact

Users are experiencing elevated error rates. The monthly error budget is being consumed faster than sustainable. At current rate, the 30-day error budget will be exhausted before the window ends.

## Investigation Steps

### 1. Check Service Health

```bash
kubectl get pods -n rag-pipeline
curl -s http://orchestrator:8003/health | jq
curl -s http://retrieval:8002/health | jq
```

### 2. Identify Error Source

Check Grafana dashboard: [RAG Errors](http://grafana:3000/d/rag-errors)

Query specific error types:
```promql
sum by (error_type, tenant_id) (rate(rag_queries_total{status="error"}[5m]))
```

### 3. Check Dependencies

```bash
# Qdrant
curl http://qdrant:6333/health

# OpenSearch
curl http://opensearch:9200/_cluster/health

# LLM Gateway
curl http://llm-gateway:8004/health
```

### 4. Review Recent Deployments

```bash
kubectl rollout history deployment/orchestrator -n rag-pipeline
kubectl rollout history deployment/retrieval -n rag-pipeline
```

## Mitigation

### If Qdrant/OpenSearch Unhealthy

Circuit breaker should activate degraded mode. Verify:
```promql
retrieval_service_degradation_mode{mode!="hybrid_full"} == 1
```

### If LLM Gateway Issues

- Check rate limits
- Verify model availability
- Consider switching to fallback model

### If Recent Deployment

```bash
kubectl rollout undo deployment/orchestrator -n rag-pipeline
```

### If Unknown Cause

- Enable debug logging temporarily
- Collect traces for failed requests via Jaeger

## Escalation

| Condition | Action |
|-----------|--------|
| Warning persists > 30 min | Page on-call SRE |
| Critical persists > 10 min | Declare incident |
| Budget exhausted | Immediate incident |

## Recovery Verification

- [ ] Error rate returns to < 1% per tenant
- [ ] Burn rate drops below 1x
- [ ] No new alerts for 15 min
- [ ] Error budget remaining stabilizes
```

**Step 3: Create retrieval latency runbook**

Create `docs/runbooks/slo/retrieval-latency.md`:

```markdown
# Runbook: Retrieval Latency SLO

## Alert

- **Name:** `SLORetrieval_latency_p95BurnRateTooHigh`
- **Severity:** critical / warning
- **SLO:** retrieval_latency_p95
- **Target:** 95% of requests < 250ms

## Impact

Retrieval operations are taking longer than expected. This directly impacts end-to-end query latency and user experience.

## Investigation Steps

### 1. Check Component Latencies

```promql
histogram_quantile(0.95, sum(rate(retrieval_service_search_duration_seconds_bucket[5m])) by (le, search_type))
```

### 2. Check Backend Health

```bash
# Qdrant performance
curl http://qdrant:6333/metrics | grep qdrant_search

# OpenSearch performance
curl http://opensearch:9200/_cat/nodes?v&h=name,heap.percent,cpu,load_1m
```

### 3. Check Reranker Performance

```promql
histogram_quantile(0.95, sum(rate(retrieval_service_rerank_duration_seconds_bucket[5m])) by (le))
```

### 4. Check Query Complexity

Look for increased top_k values or complex queries:
```promql
avg(retrieval_service_retrieval_top_k_used) by (tier, query_type)
```

## Mitigation

### If Qdrant Slow

- Check memory usage and consider scaling
- Verify HNSW index is built
- Review segment count

### If OpenSearch Slow

- Check cluster health
- Review shard allocation
- Consider adding nodes

### If Reranker Bottleneck

Temporarily disable reranker:
```bash
kubectl set env deployment/retrieval -n rag-pipeline RERANKER_ENABLED=false
```

### Scale Resources

```bash
kubectl scale deployment/retrieval -n rag-pipeline --replicas=3
```

## Escalation

| Condition | Action |
|-----------|--------|
| Warning persists > 30 min | Page on-call SRE |
| Critical persists > 10 min | Declare incident |
| p95 > 1s | Immediate investigation |

## Recovery Verification

- [ ] p95 latency < 250ms
- [ ] Burn rate < 1x
- [ ] No degraded mode active
- [ ] Backend health checks passing
```

**Step 4: Create E2E latency runbook**

Create `docs/runbooks/slo/rag-e2e-latency.md`:

```markdown
# Runbook: RAG E2E Latency SLO

## Alert

- **Name:** `SLORag_e2e_latency_p95BurnRateTooHigh`
- **Severity:** critical / warning
- **SLO:** rag_e2e_latency_p95
- **Target:** 95% of requests < 2000ms

## Impact

End-to-end RAG query latency is exceeding targets. Users experience slow responses and potential timeouts.

## Investigation Steps

### 1. Identify Bottleneck Component

```promql
histogram_quantile(0.95, sum(rate(rag_component_latency_seconds_bucket[5m])) by (le, component))
```

Components: routing, retrieval, prompt, generation, validation

### 2. Check LLM Latency

```promql
histogram_quantile(0.95, sum(rate(rag_llm_duration_seconds_bucket[5m])) by (le, model))
```

### 3. Check Retrieval Latency

See [retrieval-latency.md](./retrieval-latency.md)

### 4. Check Context Size

Large contexts increase LLM generation time:
```promql
avg(rag_llm_input_tokens_total) by (model)
```

## Mitigation

### If LLM Slow

- Check vLLM/Ollama health
- Review batch sizes
- Consider switching to faster model

### If Retrieval Slow

Follow [retrieval-latency.md](./retrieval-latency.md)

### If Context Too Large

- Reduce top_k results
- Enable context truncation
- Use summarization

### Enable Caching

```bash
kubectl set env deployment/orchestrator -n rag-pipeline RESPONSE_CACHE_ENABLED=true
```

## Escalation

| Condition | Action |
|-----------|--------|
| Warning persists > 30 min | Page on-call SRE |
| Critical persists > 10 min | Declare incident |
| p95 > 5s | Immediate investigation |

## Recovery Verification

- [ ] p95 E2E latency < 2s
- [ ] All component latencies within budget
- [ ] Burn rate < 1x
- [ ] No timeouts in logs
```

**Step 5: Create service availability runbook**

Create `docs/runbooks/slo/service-availability.md`:

```markdown
# Runbook: Service Availability SLO

## Alert

- **Name:** `SLOQuery_availabilityBurnRateTooHigh` / `SLOQuery_availabilityErrorBudgetExhausted`
- **Severity:** critical
- **SLO:** query_availability
- **Target:** 99.9% availability

## Impact

The RAG service is experiencing elevated failure rates or complete unavailability. Users cannot complete queries.

## Investigation Steps

### 1. Check Pod Status

```bash
kubectl get pods -n rag-pipeline -o wide
kubectl describe pods -n rag-pipeline -l app=orchestrator
```

### 2. Check Recent Events

```bash
kubectl get events -n rag-pipeline --sort-by='.lastTimestamp' | tail -20
```

### 3. Check Service Endpoints

```bash
kubectl get endpoints -n rag-pipeline
```

### 4. Check Resource Usage

```bash
kubectl top pods -n rag-pipeline
```

### 5. Review Logs

```bash
kubectl logs -n rag-pipeline -l app=orchestrator --tail=100
kubectl logs -n rag-pipeline -l app=retrieval --tail=100
```

## Mitigation

### If Pods CrashLooping

```bash
kubectl describe pod <pod-name> -n rag-pipeline
kubectl logs <pod-name> -n rag-pipeline --previous
```

### If OOMKilled

Increase memory limits:
```bash
kubectl set resources deployment/orchestrator -n rag-pipeline --limits=memory=4Gi
```

### If Recent Deployment

```bash
kubectl rollout undo deployment/orchestrator -n rag-pipeline
kubectl rollout undo deployment/retrieval -n rag-pipeline
```

### Scale Up

```bash
kubectl scale deployment/orchestrator -n rag-pipeline --replicas=3
kubectl scale deployment/retrieval -n rag-pipeline --replicas=3
```

### If Infrastructure Issue

- Check Kubernetes node health
- Verify network policies
- Check ingress controller

## Escalation

| Condition | Action |
|-----------|--------|
| Availability < 99% for 5 min | Declare incident immediately |
| Error budget exhausted | Freeze deployments, incident |
| Multiple services affected | Major incident |

## Recovery Verification

- [ ] All pods Running and Ready
- [ ] Health endpoints returning 200
- [ ] Success rate > 99.9%
- [ ] Burn rate < 1x
- [ ] No error spikes in last 15 min
```

**Step 6: Commit**

```bash
git add docs/runbooks/slo/
git commit -m "docs(observability): add SLO runbooks for error budget, latency, availability"
```

---

## Task 9: Update Kubernetes Manifests

**Files:**
- Modify: `k8s/base/observability/prometheus.yaml`
- Modify: `k8s/base/observability/grafana.yaml`

**Step 1: Update prometheus-rules ConfigMap**

Read the generated rules and update `k8s/base/observability/prometheus.yaml`. Replace the existing `prometheus-rules` ConfigMap (around line 313-329) with the content from the generated files.

The data section should include both `slo_recording_rules.yaml` and `slo_alerting_rules.yaml` from `config/prometheus/`.

**Step 2: Add grafana-dashboards ConfigMap**

Add a new ConfigMap to `k8s/base/observability/grafana.yaml` for the dashboard:

```yaml
---
# Grafana Dashboards ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboards
  namespace: rag-pipeline
  labels:
    app.kubernetes.io/name: grafana
data:
  slo-overview.json: |
    # Content from config/grafana/dashboards/slo-overview.json
```

**Step 3: Commit**

```bash
git add k8s/base/observability/prometheus.yaml k8s/base/observability/grafana.yaml
git commit -m "feat(k8s): integrate SLO rules and dashboard into observability stack"
```

---

## Task 10: Run All Tests

**Step 1: Run the full test suite for observability**

Run: `cd services && python -m pytest shared/observability/tests/test_metrics.py -v`

Expected: All tests pass

**Step 2: Verify rule generation**

Run: `python scripts/generate_slo_rules.py --dry-run`

Expected: Valid YAML output for recording and alerting rules

**Step 3: Final commit**

```bash
git add -A
git commit -m "test(observability): verify SLO implementation (US-10.3.4)"
```

---

## Task 11: Move User Story to Done

**Step 1: Move the user story file**

```bash
mkdir -p workflow/done/10-architectural-improvements
mv workflow/refined/10-architectural-improvements/US-10.3.4-slo-definitions-alerts.md workflow/done/10-architectural-improvements/
```

**Step 2: Final commit**

```bash
git add workflow/
git commit -m "docs: mark US-10.3.4 SLO definitions & alerts as done"
```

---

## Summary

This plan implements US-10.3.4 with:

- **3 new SLIs**: tenant_error_rate, retrieval_latency_p95_target, rag_e2e_latency_p95_target
- **3 new SLOs**: retrieval_latency_p95, rag_e2e_latency_p95, tenant_error_rate (tenant-scoped)
- **CLI script**: `scripts/generate_slo_rules.py` for rule generation
- **Grafana dashboard**: SLO overview with gauges, burn rates, time series
- **4 runbooks**: Error budget, retrieval latency, E2E latency, availability
- **Kubernetes integration**: Updated ConfigMaps for Prometheus rules and Grafana dashboards
