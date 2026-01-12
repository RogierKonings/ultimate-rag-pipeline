"""
Evaluation Result Reporters.

Provides various reporters for evaluation results:
- JSON file storage
- PostgreSQL database storage
- Grafana annotations
- Slack notifications
"""

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from .pipeline import EvaluationRun

logger = logging.getLogger(__name__)


class BaseReporter(ABC):
    """Base class for evaluation reporters."""

    @abstractmethod
    async def report(self, run: "EvaluationRun") -> None:
        """
        Report evaluation results.

        Args:
            run: The evaluation run to report
        """


class JSONFileReporter(BaseReporter):
    """Reporter that saves results to JSON files."""

    def __init__(
        self,
        output_dir: str = "./eval_results",
        include_individual: bool = True,
    ):
        """
        Initialize JSON file reporter.

        Args:
            output_dir: Directory for output files
            include_individual: Whether to include individual results
        """
        self.output_dir = Path(output_dir)
        self.include_individual = include_individual

    async def report(self, run: "EvaluationRun") -> None:
        """Save evaluation results to JSON file."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Create filename with timestamp
        timestamp = run.started_at.strftime("%Y%m%d_%H%M%S")
        filename = f"{run.name}_{timestamp}.json"
        filepath = self.output_dir / filename

        # Prepare data
        data = run.to_dict()

        # Optionally exclude individual results to reduce file size
        if not self.include_individual and data.get("results"):
            data["results"]["individual_results"] = []

        with filepath.open("w") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info(f"Saved evaluation results to {filepath}")

        # Also save a summary file
        summary_file = self.output_dir / f"{run.name}_{timestamp}_summary.json"
        summary = self._create_summary(run)
        with summary_file.open("w") as f:
            json.dump(summary, f, indent=2)

        logger.info(f"Saved evaluation summary to {summary_file}")

    def _create_summary(self, run: "EvaluationRun") -> dict[str, Any]:
        """Create a summary of the evaluation run."""
        summary = {
            "run_id": run.id,
            "run_name": run.name,
            "dataset": run.dataset_name,
            "status": run.status,
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

        if run.results:
            summary["metrics"] = {
                metric: stats["mean"] for metric, stats in run.results.aggregated_metrics.items()
            }
            summary["total_samples"] = run.results.total_samples
            summary["successful_samples"] = run.results.successful_samples
            summary["failed_samples"] = run.results.failed_samples

        if run.error:
            summary["error"] = run.error

        return summary


class PostgreSQLReporter(BaseReporter):
    """Reporter that saves results to PostgreSQL."""

    def __init__(
        self,
        connection_url: str,
        table_prefix: str = "eval_",
    ):
        """
        Initialize PostgreSQL reporter.

        Args:
            connection_url: PostgreSQL connection URL
            table_prefix: Prefix for table names
        """
        self.connection_url = connection_url
        self.table_prefix = table_prefix
        self._pool = None

    async def _get_pool(self):
        """Get or create connection pool."""
        if self._pool is None:
            import asyncpg

            self._pool = await asyncpg.create_pool(self.connection_url)
        return self._pool

    async def report(self, run: "EvaluationRun") -> None:
        """Save evaluation results to PostgreSQL."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            # Insert run record
            await conn.execute(
                f"""
                INSERT INTO {self.table_prefix}runs
                (id, name, dataset_name, status, started_at, completed_at,
                 total_samples, successful_samples, failed_samples, error, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    completed_at = EXCLUDED.completed_at,
                    total_samples = EXCLUDED.total_samples,
                    successful_samples = EXCLUDED.successful_samples,
                    failed_samples = EXCLUDED.failed_samples,
                    error = EXCLUDED.error
                """,
                run.id,
                run.name,
                run.dataset_name,
                run.status,
                run.started_at,
                run.completed_at,
                run.results.total_samples if run.results else 0,
                run.results.successful_samples if run.results else 0,
                run.results.failed_samples if run.results else 0,
                run.error,
                json.dumps(run.metadata),
            )

            # Insert aggregated metrics
            if run.results:
                for metric_name, stats in run.results.aggregated_metrics.items():
                    await conn.execute(
                        f"""
                        INSERT INTO {self.table_prefix}metrics
                        (run_id, metric_name, mean, std, min, max, median)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (run_id, metric_name) DO UPDATE SET
                            mean = EXCLUDED.mean,
                            std = EXCLUDED.std,
                            min = EXCLUDED.min,
                            max = EXCLUDED.max,
                            median = EXCLUDED.median
                        """,
                        run.id,
                        metric_name,
                        stats["mean"],
                        stats["std"],
                        stats["min"],
                        stats["max"],
                        stats["median"],
                    )

        logger.info(f"Saved evaluation run {run.id} to PostgreSQL")

    async def get_recent_runs(
        self,
        limit: int = 10,
        dataset_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get recent evaluation runs.

        Args:
            limit: Maximum number of runs
            dataset_name: Filter by dataset name

        Returns:
            List of run records
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            if dataset_name:
                rows = await conn.fetch(
                    f"""
                    SELECT * FROM {self.table_prefix}runs
                    WHERE dataset_name = $1
                    ORDER BY started_at DESC
                    LIMIT $2
                    """,
                    dataset_name,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT * FROM {self.table_prefix}runs
                    ORDER BY started_at DESC
                    LIMIT $1
                    """,
                    limit,
                )

            return [dict(row) for row in rows]

    async def get_metrics_trend(
        self,
        metric_name: str,
        dataset_name: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """
        Get metric trend over time.

        Args:
            metric_name: Name of the metric
            dataset_name: Filter by dataset
            limit: Number of data points

        Returns:
            List of metric values over time
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            query = f"""
                SELECT r.started_at, m.mean, m.std
                FROM {self.table_prefix}metrics m
                JOIN {self.table_prefix}runs r ON m.run_id = r.id
                WHERE m.metric_name = $1
                AND r.status = 'completed'
            """
            params = [metric_name]

            if dataset_name:
                query += " AND r.dataset_name = $2"
                params.append(dataset_name)

            query += f" ORDER BY r.started_at DESC LIMIT ${len(params) + 1}"
            params.append(limit)

            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]


class GrafanaAnnotationReporter(BaseReporter):
    """Reporter that creates Grafana annotations."""

    def __init__(
        self,
        grafana_url: str,
        api_key: str,
        dashboard_uid: str | None = None,
        panel_id: int | None = None,
    ):
        """
        Initialize Grafana annotation reporter.

        Args:
            grafana_url: Grafana base URL
            api_key: Grafana API key
            dashboard_uid: Target dashboard UID
            panel_id: Target panel ID
        """
        self.grafana_url = grafana_url.rstrip("/")
        self.api_key = api_key
        self.dashboard_uid = dashboard_uid
        self.panel_id = panel_id

    async def report(self, run: "EvaluationRun") -> None:
        """Create Grafana annotation for evaluation run."""
        # Prepare annotation
        tags = ["evaluation", run.dataset_name, run.status]

        # Build annotation text
        text_parts = [
            f"**Evaluation Run: {run.name}**",
            f"Dataset: {run.dataset_name}",
            f"Status: {run.status}",
        ]

        if run.results:
            text_parts.append(
                f"Samples: {run.results.successful_samples}/{run.results.total_samples}",
            )
            # Add key metrics
            for metric, stats in run.results.aggregated_metrics.items():
                text_parts.append(f"{metric}: {stats['mean']:.3f}")

        if run.error:
            text_parts.append(f"Error: {run.error}")
            tags.append("error")

        annotation = {
            "time": int(run.started_at.timestamp() * 1000),
            "timeEnd": int(run.completed_at.timestamp() * 1000) if run.completed_at else None,
            "tags": tags,
            "text": "\n".join(text_parts),
        }

        if self.dashboard_uid:
            annotation["dashboardUID"] = self.dashboard_uid
        if self.panel_id:
            annotation["panelId"] = self.panel_id

        # Send to Grafana
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.grafana_url}/api/annotations",
                json=annotation,
                headers=headers,
            )
            response.raise_for_status()

        logger.info(f"Created Grafana annotation for run {run.id}")


class SlackReporter(BaseReporter):
    """Reporter that sends Slack notifications."""

    def __init__(
        self,
        webhook_url: str,
        channel: str | None = None,
        mention_on_failure: str | None = None,
    ):
        """
        Initialize Slack reporter.

        Args:
            webhook_url: Slack webhook URL
            channel: Override channel
            mention_on_failure: User/group to mention on failure
        """
        self.webhook_url = webhook_url
        self.channel = channel
        self.mention_on_failure = mention_on_failure

    async def report(self, run: "EvaluationRun") -> None:
        """Send Slack notification for evaluation run."""
        # Determine message color based on status
        if run.status == "completed":
            color = "good"  # green
        elif run.status == "failed":
            color = "danger"  # red
        else:
            color = "warning"  # yellow

        # Build fields
        fields = [
            {"title": "Dataset", "value": run.dataset_name, "short": True},
            {"title": "Status", "value": run.status.upper(), "short": True},
        ]

        if run.results:
            fields.append(
                {
                    "title": "Samples",
                    "value": f"{run.results.successful_samples}/{run.results.total_samples}",
                    "short": True,
                },
            )

            # Add key metrics
            for metric, stats in run.results.aggregated_metrics.items():
                fields.append(
                    {
                        "title": metric.replace("_", " ").title(),
                        "value": f"{stats['mean']:.3f} (±{stats['std']:.3f})",
                        "short": True,
                    },
                )

        # Build message
        text = f"Evaluation Run: *{run.name}*"
        if run.status == "failed" and self.mention_on_failure:
            text = f"{self.mention_on_failure} {text}"

        attachment = {
            "color": color,
            "title": run.name,
            "fields": fields,
            "footer": f"Run ID: {run.id}",
            "ts": int(run.started_at.timestamp()),
        }

        if run.error:
            attachment["text"] = f"Error: {run.error}"

        payload = {
            "text": text,
            "attachments": [attachment],
        }

        if self.channel:
            payload["channel"] = self.channel

        # Send to Slack
        async with httpx.AsyncClient() as client:
            response = await client.post(self.webhook_url, json=payload)
            response.raise_for_status()

        logger.info(f"Sent Slack notification for run {run.id}")


class CompositeReporter(BaseReporter):
    """Reporter that delegates to multiple reporters."""

    def __init__(self, reporters: list[BaseReporter]):
        """
        Initialize composite reporter.

        Args:
            reporters: List of reporters to delegate to
        """
        self.reporters = reporters

    async def report(self, run: "EvaluationRun") -> None:
        """Report to all configured reporters."""
        for reporter in self.reporters:
            try:
                await reporter.report(run)
            except Exception as e:
                logger.error(
                    f"Reporter {reporter.__class__.__name__} failed: {e}",
                    exc_info=True,
                )
