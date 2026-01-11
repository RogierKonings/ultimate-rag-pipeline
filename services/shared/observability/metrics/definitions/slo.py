"""
Service Level Objective (SLO) Definitions.

Provides SLO dataclasses with targets, error budgets, and
Prometheus recording/alerting rule generation.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from .sli import SLI, SLI_CATALOG


@dataclass
class BurnRate:
    """
    Burn rate alert configuration.

    Defines how fast the error budget is being consumed.

    Attributes:
        rate: Burn rate multiplier (e.g., 14.4x means budget consumed in 1/14.4 of window)
        short_window: Short alerting window
        long_window: Long alerting window
        severity: Alert severity
        action: Recommended action
    """
    rate: float
    short_window: str
    long_window: str
    severity: str
    action: str


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
    """
    name: str
    sli_name: str
    target: float
    window: str
    description: str
    burn_rates: List[BurnRate] = field(default_factory=list)
    owner: str = ""
    consequences: str = ""

    def __post_init__(self):
        """Set default burn rates if not provided."""
        if not self.burn_rates:
            self.burn_rates = [
                # Fast burn: exhausts budget in 1h if sustained
                BurnRate(
                    rate=14.4,
                    short_window="5m",
                    long_window="1h",
                    severity="critical",
                    action="Page immediately",
                ),
                # Medium burn: exhausts budget in 6h if sustained
                BurnRate(
                    rate=6.0,
                    short_window="30m",
                    long_window="6h",
                    severity="critical",
                    action="Page",
                ),
                # Slow burn: exhausts budget in 3d if sustained
                BurnRate(
                    rate=1.0,
                    short_window="6h",
                    long_window="3d",
                    severity="warning",
                    action="Create ticket",
                ),
            ]

    @property
    def error_budget(self) -> float:
        """Calculate error budget as 1 - target."""
        return 1.0 - self.target

    @property
    def error_budget_percent(self) -> float:
        """Error budget as percentage."""
        return self.error_budget * 100

    def get_sli(self) -> Optional[SLI]:
        """Get the associated SLI."""
        return SLI_CATALOG.get(self.sli_name)


# =============================================================================
# SLO Catalog
# =============================================================================

SLO_CATALOG: Dict[str, SLO] = {}


def _register_slo(slo: SLO) -> SLO:
    """Register an SLO in the catalog."""
    SLO_CATALOG[slo.name] = slo
    return slo


# -----------------------------------------------------------------------------
# Availability SLOs
# -----------------------------------------------------------------------------

_register_slo(SLO(
    name="query_availability",
    sli_name="query_availability",
    target=0.999,  # 99.9%
    window="30d",
    description="99.9% of queries should complete successfully",
    owner="platform-team",
    consequences="User-facing errors, degraded experience",
))

_register_slo(SLO(
    name="llm_availability",
    sli_name="llm_availability",
    target=0.995,  # 99.5%
    window="30d",
    description="99.5% of LLM requests should complete successfully",
    owner="ml-team",
    consequences="Fallback to cached responses or simpler models",
))

# -----------------------------------------------------------------------------
# Latency SLOs
# -----------------------------------------------------------------------------

_register_slo(SLO(
    name="query_latency",
    sli_name="query_latency_p99",
    target=0.99,  # 99% of requests under threshold
    window="30d",
    description="99% of queries should complete in under 2 seconds",
    owner="platform-team",
    consequences="Poor user experience, timeouts",
))

_register_slo(SLO(
    name="retrieval_latency",
    sli_name="retrieval_latency_p99",
    target=0.99,  # 99% of requests under threshold
    window="30d",
    description="99% of retrieval operations should complete in under 500ms",
    owner="platform-team",
    consequences="Slow queries, degraded throughput",
))

_register_slo(SLO(
    name="llm_ttft",
    sli_name="llm_ttft_p95",
    target=0.95,  # 95% of requests under threshold
    window="7d",
    description="95% of streaming responses should start within 1 second",
    owner="ml-team",
    consequences="Poor perceived responsiveness",
))

# -----------------------------------------------------------------------------
# Quality SLOs
# -----------------------------------------------------------------------------

_register_slo(SLO(
    name="retrieval_quality",
    sli_name="retrieval_zero_results_rate",
    target=0.80,  # 80% of queries return results
    window="7d",
    description="At least 80% of queries should return relevant results",
    owner="search-team",
    consequences="Users not finding information, poor RAG quality",
))

_register_slo(SLO(
    name="cache_effectiveness",
    sli_name="cache_hit_rate",
    target=0.50,  # 50% cache hit rate
    window="7d",
    description="Cache hit rate should be at least 50%",
    owner="platform-team",
    consequences="Higher latency, increased costs",
))


# =============================================================================
# Rule Generation
# =============================================================================

def generate_slo_recording_rules(slo: SLO) -> List[Dict[str, Any]]:
    """
    Generate Prometheus recording rules for an SLO.

    Creates rules for:
    - SLI ratio over various windows
    - Error budget remaining
    - Burn rate calculations

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
        rules.append({
            "record": f"slo:{base_name}:ratio_{window.replace('d', 'd').replace('h', 'h').replace('m', 'm')}",
            "expr": ratio_query,
            "labels": {
                "slo": slo.name,
                "window": window,
            },
        })

    # Error budget remaining (over compliance window)
    budget_query = f"""
    1 - (
        (1 - {sli.query_ratio.replace("{{window}}", slo.window)})
        / {slo.error_budget}
    )
    """.strip()
    rules.append({
        "record": f"slo:{base_name}:error_budget_remaining",
        "expr": budget_query,
        "labels": {
            "slo": slo.name,
        },
    })

    # Burn rate for each window
    for burn_rate in slo.burn_rates:
        short_ratio = sli.query_ratio.replace("{{window}}", burn_rate.short_window)
        long_ratio = sli.query_ratio.replace("{{window}}", burn_rate.long_window)

        short_burn = f"(1 - ({short_ratio})) / {slo.error_budget}"
        long_burn = f"(1 - ({long_ratio})) / {slo.error_budget}"

        rules.append({
            "record": f"slo:{base_name}:burn_rate_{burn_rate.short_window}",
            "expr": short_burn,
            "labels": {
                "slo": slo.name,
                "window": burn_rate.short_window,
            },
        })

        rules.append({
            "record": f"slo:{base_name}:burn_rate_{burn_rate.long_window}",
            "expr": long_burn,
            "labels": {
                "slo": slo.name,
                "window": burn_rate.long_window,
            },
        })

    return rules


def generate_slo_burn_rate_alerts(slo: SLO) -> List[Dict[str, Any]]:
    """
    Generate Prometheus alerting rules for SLO burn rates.

    Creates multi-window burn rate alerts that fire when
    the error budget is being consumed too quickly.

    Args:
        slo: SLO to generate alerts for

    Returns:
        List of Prometheus alerting rule definitions
    """
    sli = slo.get_sli()
    if sli is None:
        return []

    alerts = []
    base_name = slo.name.replace("-", "_")

    for burn_rate in slo.burn_rates:
        short_window = burn_rate.short_window
        long_window = burn_rate.long_window

        # Multi-window burn rate alert
        # Fires when both short and long window exceed threshold
        short_ratio = sli.query_ratio.replace("{{window}}", short_window)
        long_ratio = sli.query_ratio.replace("{{window}}", long_window)

        # Error rate must exceed burn_rate * error_budget for both windows
        threshold = burn_rate.rate * slo.error_budget

        alert_expr = f"""
        (
            (1 - ({short_ratio})) > {threshold}
            and
            (1 - ({long_ratio})) > {threshold}
        )
        """.strip()

        alerts.append({
            "alert": f"SLO{base_name.title()}BurnRateTooHigh",
            "expr": alert_expr,
            "for": "2m",
            "labels": {
                "severity": burn_rate.severity,
                "slo": slo.name,
                "burn_rate": str(burn_rate.rate),
            },
            "annotations": {
                "summary": f"SLO {slo.name} burn rate is {burn_rate.rate}x",
                "description": f"Error budget for {slo.name} is being consumed {burn_rate.rate}x faster than sustainable. "
                               f"Short window ({short_window}) and long window ({long_window}) both exceed threshold. "
                               f"Action: {burn_rate.action}",
                "runbook_url": f"https://runbooks.example.com/slo/{slo.name}",
            },
        })

    # Error budget exhausted alert
    budget_query = f"""
    (
        1 - (
            (1 - {sli.query_ratio.replace("{{window}}", slo.window)})
            / {slo.error_budget}
        )
    ) <= 0
    """.strip()

    alerts.append({
        "alert": f"SLO{base_name.title()}ErrorBudgetExhausted",
        "expr": budget_query,
        "for": "5m",
        "labels": {
            "severity": "critical",
            "slo": slo.name,
        },
        "annotations": {
            "summary": f"SLO {slo.name} error budget exhausted",
            "description": f"The error budget for {slo.name} has been completely consumed. "
                           f"Target: {slo.target*100}% over {slo.window}. "
                           f"Immediate action required.",
            "runbook_url": f"https://runbooks.example.com/slo/{slo.name}",
        },
    })

    return alerts


def generate_all_slo_rules() -> Dict[str, Any]:
    """
    Generate all SLO recording and alerting rules.

    Returns:
        Prometheus rule file structure
    """
    recording_rules = []
    alerting_rules = []

    for slo in SLO_CATALOG.values():
        recording_rules.extend(generate_slo_recording_rules(slo))
        alerting_rules.extend(generate_slo_burn_rate_alerts(slo))

    return {
        "groups": [
            {
                "name": "slo_recording_rules",
                "interval": "30s",
                "rules": recording_rules,
            },
            {
                "name": "slo_alerting_rules",
                "rules": alerting_rules,
            },
        ],
    }


def get_slo(name: str) -> Optional[SLO]:
    """
    Get an SLO by name.

    Args:
        name: SLO name

    Returns:
        SLO or None if not found
    """
    return SLO_CATALOG.get(name)
