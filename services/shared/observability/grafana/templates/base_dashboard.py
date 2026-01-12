"""
Grafana Dashboard Generator.

Provides Python classes for programmatically generating Grafana dashboards.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PanelType(Enum):
    """Grafana panel types."""
    STAT = "stat"
    GAUGE = "gauge"
    TIMESERIES = "timeseries"
    BARGAUGE = "bargauge"
    PIECHART = "piechart"
    TABLE = "table"
    HEATMAP = "heatmap"
    LOGS = "logs"
    TEXT = "text"


class ThresholdMode(Enum):
    """Threshold evaluation modes."""
    ABSOLUTE = "absolute"
    PERCENTAGE = "percentage"


@dataclass
class Threshold:
    """Grafana threshold definition."""
    value: float
    color: str


@dataclass
class Target:
    """Prometheus query target."""
    expr: str
    legendFormat: str = ""
    refId: str = "A"
    instant: bool = False
    range: bool = True
    datasource: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to Grafana target dict."""
        result = {
            "expr": self.expr,
            "legendFormat": self.legendFormat,
            "refId": self.refId,
            "instant": self.instant,
            "range": self.range,
        }
        if self.datasource:
            result["datasource"] = {"type": "prometheus", "uid": self.datasource}
        return result


@dataclass
class Panel:
    """Grafana panel definition."""
    title: str
    panel_type: PanelType
    targets: list[Target]
    gridPos: dict[str, int]
    id: int = 0
    description: str = ""
    unit: str = ""
    decimals: int | None = None
    thresholds: list[Threshold] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)
    fieldConfig: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to Grafana panel dict."""
        result: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "type": self.panel_type.value,
            "gridPos": self.gridPos,
            "targets": [t.to_dict() for t in self.targets],
        }

        if self.description:
            result["description"] = self.description

        # Build field config
        field_defaults: dict[str, Any] = {}
        if self.unit:
            field_defaults["unit"] = self.unit
        if self.decimals is not None:
            field_defaults["decimals"] = self.decimals
        if self.thresholds:
            field_defaults["thresholds"] = {
                "mode": ThresholdMode.ABSOLUTE.value,
                "steps": [{"value": t.value, "color": t.color} for t in self.thresholds],
            }

        if field_defaults or self.fieldConfig:
            result["fieldConfig"] = {
                "defaults": {**field_defaults, **self.fieldConfig.get("defaults", {})},
                "overrides": self.fieldConfig.get("overrides", []),
            }

        if self.options:
            result["options"] = self.options

        return result


@dataclass
class Row:
    """Grafana row (collapsible section)."""
    title: str
    panels: list[Panel]
    collapsed: bool = False
    gridPos: dict[str, int] = field(default_factory=lambda: {"h": 1, "w": 24, "x": 0, "y": 0})

    def to_dict(self) -> dict[str, Any]:
        """Convert to Grafana row dict."""
        return {
            "type": "row",
            "title": self.title,
            "collapsed": self.collapsed,
            "gridPos": self.gridPos,
            "panels": [p.to_dict() for p in self.panels] if self.collapsed else [],
        }


@dataclass
class Variable:
    """Grafana template variable."""
    name: str
    label: str
    query: str
    datasource: str = "Prometheus"
    type: str = "query"
    includeAll: bool = True
    allValue: str | None = ".*"
    multi: bool = True
    refresh: int = 2  # On time range change

    def to_dict(self) -> dict[str, Any]:
        """Convert to Grafana variable dict."""
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "datasource": {"type": "prometheus", "uid": "${datasource}"},
            "query": self.query,
            "includeAll": self.includeAll,
            "allValue": self.allValue,
            "multi": self.multi,
            "refresh": self.refresh,
        }


@dataclass
class Dashboard:
    """Grafana dashboard definition."""
    title: str
    uid: str
    panels: list[Panel]
    tags: list[str] = field(default_factory=lambda: ["rag-pipeline"])
    variables: list[Variable] = field(default_factory=list)
    refresh: str = "30s"
    time_from: str = "now-1h"
    time_to: str = "now"
    description: str = ""
    editable: bool = True

    def _assign_panel_ids(self) -> None:
        """Assign unique IDs to all panels."""
        for i, panel in enumerate(self.panels, start=1):
            panel.id = i

    def to_dict(self) -> dict[str, Any]:
        """Convert to Grafana dashboard dict."""
        self._assign_panel_ids()

        templating = {"list": [v.to_dict() for v in self.variables]}

        # Add datasource variable
        templating["list"].insert(0, {
            "name": "datasource",
            "label": "Datasource",
            "type": "datasource",
            "query": "prometheus",
            "current": {"text": "Prometheus", "value": "Prometheus"},
        })

        return {
            "uid": self.uid,
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "editable": self.editable,
            "refresh": self.refresh,
            "time": {
                "from": self.time_from,
                "to": self.time_to,
            },
            "templating": templating,
            "panels": [p.to_dict() for p in self.panels],
            "schemaVersion": 38,
            "version": 1,
        }

    def to_json(self, indent: int = 2) -> str:
        """Export dashboard as JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, filepath: str) -> None:
        """Save dashboard to file."""
        with open(filepath, "w") as f:
            f.write(self.to_json())


# Helper functions for common panel types

def create_stat_panel(
    title: str,
    expr: str,
    gridPos: dict[str, int],
    unit: str = "",
    description: str = "",
    thresholds: list[Threshold] | None = None,
    color_mode: str = "value",
) -> Panel:
    """Create a stat panel."""
    return Panel(
        title=title,
        panel_type=PanelType.STAT,
        targets=[Target(expr=expr, instant=True, range=False)],
        gridPos=gridPos,
        unit=unit,
        description=description,
        thresholds=thresholds or [],
        options={
            "colorMode": color_mode,
            "graphMode": "none",
            "justifyMode": "auto",
            "textMode": "auto",
            "reduceOptions": {
                "calcs": ["lastNotNull"],
                "fields": "",
                "values": False,
            },
        },
    )


def create_timeseries_panel(
    title: str,
    targets: list[Target],
    gridPos: dict[str, int],
    unit: str = "",
    description: str = "",
    fill_opacity: int = 10,
    line_width: int = 1,
) -> Panel:
    """Create a time series panel."""
    return Panel(
        title=title,
        panel_type=PanelType.TIMESERIES,
        targets=targets,
        gridPos=gridPos,
        unit=unit,
        description=description,
        options={
            "legend": {"displayMode": "list", "placement": "bottom"},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
        fieldConfig={
            "defaults": {
                "custom": {
                    "fillOpacity": fill_opacity,
                    "lineWidth": line_width,
                    "spanNulls": True,
                },
            },
        },
    )


def create_gauge_panel(
    title: str,
    expr: str,
    gridPos: dict[str, int],
    unit: str = "percentunit",
    min_val: float = 0,
    max_val: float = 1,
    thresholds: list[Threshold] | None = None,
) -> Panel:
    """Create a gauge panel."""
    default_thresholds = [
        Threshold(value=0, color="red"),
        Threshold(value=0.9, color="yellow"),
        Threshold(value=0.99, color="green"),
    ]
    return Panel(
        title=title,
        panel_type=PanelType.GAUGE,
        targets=[Target(expr=expr, instant=True, range=False)],
        gridPos=gridPos,
        unit=unit,
        thresholds=thresholds or default_thresholds,
        fieldConfig={
            "defaults": {
                "min": min_val,
                "max": max_val,
            },
        },
        options={
            "showThresholdLabels": False,
            "showThresholdMarkers": True,
        },
    )


def create_bar_gauge_panel(
    title: str,
    expr: str,
    gridPos: dict[str, int],
    unit: str = "",
    orientation: str = "horizontal",
) -> Panel:
    """Create a bar gauge panel."""
    return Panel(
        title=title,
        panel_type=PanelType.BARGAUGE,
        targets=[Target(expr=expr, instant=True, range=False)],
        gridPos=gridPos,
        unit=unit,
        options={
            "orientation": orientation,
            "displayMode": "gradient",
            "showUnfilled": True,
        },
    )


def create_table_panel(
    title: str,
    targets: list[Target],
    gridPos: dict[str, int],
) -> Panel:
    """Create a table panel."""
    return Panel(
        title=title,
        panel_type=PanelType.TABLE,
        targets=targets,
        gridPos=gridPos,
        options={
            "showHeader": True,
            "sortBy": [],
        },
    )


def create_logs_panel(
    title: str,
    expr: str,
    gridPos: dict[str, int],
    datasource: str = "Loki",
) -> Panel:
    """Create a logs panel."""
    return Panel(
        title=title,
        panel_type=PanelType.LOGS,
        targets=[Target(expr=expr, datasource=datasource)],
        gridPos=gridPos,
        options={
            "showTime": True,
            "showLabels": True,
            "showCommonLabels": False,
            "wrapLogMessage": True,
            "prettifyLogMessage": True,
            "enableLogDetails": True,
            "dedupStrategy": "none",
            "sortOrder": "Descending",
        },
    )
