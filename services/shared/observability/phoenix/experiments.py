"""
Experiment Tracking.

Provides experiment tracking for LLM/RAG pipeline changes.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .config import PhoenixConfig

logger = logging.getLogger(__name__)


@dataclass
class ExperimentRun:
    """A single run within an experiment."""

    id: str = field(default_factory=lambda: str(uuid4()))
    experiment_id: str = ""
    name: str = ""

    # Configuration
    config: dict[str, Any] = field(default_factory=dict)

    # Metrics
    metrics: dict[str, float] = field(default_factory=dict)

    # Timing
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    # Status
    status: str = "running"  # running, completed, failed
    error: str | None = None

    # Artifacts
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "experiment_id": self.experiment_id,
            "name": self.name,
            "config": self.config,
            "metrics": self.metrics,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "error": self.error,
            "artifacts": self.artifacts,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentRun":
        """Create from dictionary."""
        started_at = data.get("started_at")
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)

        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)

        return cls(
            id=data.get("id", str(uuid4())),
            experiment_id=data.get("experiment_id", ""),
            name=data.get("name", ""),
            config=data.get("config", {}),
            metrics=data.get("metrics", {}),
            started_at=started_at or datetime.now(tz=UTC),
            completed_at=completed_at,
            status=data.get("status", "running"),
            error=data.get("error"),
            artifacts=data.get("artifacts", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Experiment:
    """An experiment comparing different configurations."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""

    # What we're testing
    hypothesis: str = ""
    experiment_type: str = ""  # prompt, model, retrieval, etc.

    # Runs
    runs: list[ExperimentRun] = field(default_factory=list)

    # Baseline
    baseline_run_id: str | None = None

    # Timing
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    # Status
    status: str = "active"  # active, completed, archived

    # Results
    conclusion: str | None = None
    winning_run_id: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "hypothesis": self.hypothesis,
            "experiment_type": self.experiment_type,
            "runs": [r.to_dict() for r in self.runs],
            "baseline_run_id": self.baseline_run_id,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "conclusion": self.conclusion,
            "winning_run_id": self.winning_run_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Experiment":
        """Create from dictionary."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)

        return cls(
            id=data.get("id", str(uuid4())),
            name=data.get("name", ""),
            description=data.get("description", ""),
            hypothesis=data.get("hypothesis", ""),
            experiment_type=data.get("experiment_type", ""),
            runs=[ExperimentRun.from_dict(r) for r in data.get("runs", [])],
            baseline_run_id=data.get("baseline_run_id"),
            created_at=created_at or datetime.now(tz=UTC),
            completed_at=completed_at,
            status=data.get("status", "active"),
            conclusion=data.get("conclusion"),
            winning_run_id=data.get("winning_run_id"),
            metadata=data.get("metadata", {}),
        )


class ExperimentTracker:
    """
    Tracks experiments comparing different RAG configurations.

    Supports:
    - Prompt experiments
    - Model comparisons
    - Retrieval strategy experiments
    - Chunking experiments
    """

    def __init__(self, config: PhoenixConfig | None = None):
        """
        Initialize experiment tracker.

        Args:
            config: Phoenix configuration
        """
        self.config = config or PhoenixConfig.from_env()
        self._pool = None
        self._active_experiments: dict[str, Experiment] = {}

    async def _get_pool(self):
        """Get or create database connection pool."""
        if self._pool is None:
            if not self.config.postgres_url:
                raise ValueError("PostgreSQL URL required for experiment storage")

            import asyncpg

            self._pool = await asyncpg.create_pool(self.config.postgres_url)
        return self._pool

    async def create_experiment(
        self,
        name: str,
        description: str = "",
        hypothesis: str = "",
        experiment_type: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Experiment:
        """
        Create a new experiment.

        Args:
            name: Experiment name
            description: Description
            hypothesis: What we expect to find
            experiment_type: Type of experiment
            metadata: Additional metadata

        Returns:
            The created Experiment
        """
        experiment = Experiment(
            name=name,
            description=description,
            hypothesis=hypothesis,
            experiment_type=experiment_type,
            metadata=metadata or {},
        )

        await self._store_experiment(experiment)
        self._active_experiments[experiment.id] = experiment

        logger.info(f"Created experiment {experiment.id}: {name}")
        return experiment

    async def start_run(
        self,
        experiment_id: str,
        name: str,
        config: dict[str, Any],
        is_baseline: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> ExperimentRun:
        """
        Start a new run within an experiment.

        Args:
            experiment_id: Parent experiment ID
            name: Run name
            config: Configuration for this run
            is_baseline: Whether this is the baseline run
            metadata: Additional metadata

        Returns:
            The created ExperimentRun
        """
        run = ExperimentRun(
            experiment_id=experiment_id,
            name=name,
            config=config,
            metadata=metadata or {},
        )

        # Get experiment
        experiment = self._active_experiments.get(experiment_id)
        if not experiment:
            experiment = await self.get_experiment(experiment_id)
            self._active_experiments[experiment_id] = experiment

        experiment.runs.append(run)
        if is_baseline:
            experiment.baseline_run_id = run.id

        await self._store_run(run)

        logger.info(f"Started run {run.id} for experiment {experiment_id}")
        return run

    async def log_metric(
        self,
        run_id: str,
        name: str,
        value: float,
    ) -> None:
        """
        Log a metric for a run.

        Args:
            run_id: Run ID
            name: Metric name
            value: Metric value
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE experiment_runs
                SET metrics = metrics || $1::jsonb
                WHERE id = $2
                """,
                json.dumps({name: value}),
                run_id,
            )

        logger.debug(f"Logged metric {name}={value} for run {run_id}")

    async def log_metrics(
        self,
        run_id: str,
        metrics: dict[str, float],
    ) -> None:
        """
        Log multiple metrics for a run.

        Args:
            run_id: Run ID
            metrics: Dictionary of metric name to value
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE experiment_runs
                SET metrics = metrics || $1::jsonb
                WHERE id = $2
                """,
                json.dumps(metrics),
                run_id,
            )

        logger.debug(f"Logged {len(metrics)} metrics for run {run_id}")

    async def log_artifact(
        self,
        run_id: str,
        name: str,
        artifact_type: str,
        path: str | None = None,
        data: Any | None = None,
    ) -> None:
        """
        Log an artifact for a run.

        Args:
            run_id: Run ID
            name: Artifact name
            artifact_type: Type (e.g., "model", "dataset", "config")
            path: Path to artifact
            data: Artifact data (will be JSON serialized)
        """
        artifact = {
            "name": name,
            "type": artifact_type,
            "path": path,
            "data": data,
            "logged_at": datetime.now(tz=UTC).isoformat(),
        }

        pool = await self._get_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE experiment_runs
                SET artifacts = artifacts || $1::jsonb
                WHERE id = $2
                """,
                json.dumps([artifact]),
                run_id,
            )

    async def complete_run(
        self,
        run_id: str,
        metrics: dict[str, float] | None = None,
        error: str | None = None,
    ) -> ExperimentRun:
        """
        Mark a run as complete.

        Args:
            run_id: Run ID
            metrics: Final metrics
            error: Error message if failed

        Returns:
            The completed run
        """
        status = "failed" if error else "completed"

        pool = await self._get_pool()

        async with pool.acquire() as conn:
            if metrics:
                await conn.execute(
                    """
                    UPDATE experiment_runs
                    SET metrics = metrics || $1::jsonb,
                        status = $2,
                        completed_at = $3,
                        error = $4
                    WHERE id = $5
                    """,
                    json.dumps(metrics),
                    status,
                    datetime.now(tz=UTC),
                    error,
                    run_id,
                )
            else:
                await conn.execute(
                    """
                    UPDATE experiment_runs
                    SET status = $1,
                        completed_at = $2,
                        error = $3
                    WHERE id = $4
                    """,
                    status,
                    datetime.now(tz=UTC),
                    error,
                    run_id,
                )

            row = await conn.fetchrow(
                "SELECT * FROM experiment_runs WHERE id = $1",
                run_id,
            )

        logger.info(f"Completed run {run_id} with status {status}")
        return ExperimentRun.from_dict(dict(row))

    async def complete_experiment(
        self,
        experiment_id: str,
        conclusion: str,
        winning_run_id: str | None = None,
    ) -> Experiment:
        """
        Mark an experiment as complete.

        Args:
            experiment_id: Experiment ID
            conclusion: Conclusion/findings
            winning_run_id: ID of the best run

        Returns:
            The completed experiment
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE experiments
                SET status = 'completed',
                    completed_at = $1,
                    conclusion = $2,
                    winning_run_id = $3
                WHERE id = $4
                """,
                datetime.now(tz=UTC),
                conclusion,
                winning_run_id,
                experiment_id,
            )

        # Remove from active
        self._active_experiments.pop(experiment_id, None)

        logger.info(f"Completed experiment {experiment_id}")
        return await self.get_experiment(experiment_id)

    async def get_experiment(self, experiment_id: str) -> Experiment:
        """
        Get an experiment by ID.

        Args:
            experiment_id: Experiment ID

        Returns:
            The Experiment
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM experiments WHERE id = $1",
                experiment_id,
            )
            if not row:
                raise ValueError(f"Experiment {experiment_id} not found")

            runs = await conn.fetch(
                "SELECT * FROM experiment_runs WHERE experiment_id = $1",
                experiment_id,
            )

        experiment = Experiment.from_dict(dict(row))
        experiment.runs = [ExperimentRun.from_dict(dict(r)) for r in runs]

        return experiment

    async def compare_runs(
        self,
        experiment_id: str,
        metric_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Compare runs within an experiment.

        Args:
            experiment_id: Experiment ID
            metric_names: Metrics to compare (None = all)

        Returns:
            Comparison results
        """
        experiment = await self.get_experiment(experiment_id)

        if not experiment.runs:
            return {"error": "No runs in experiment"}

        # Get baseline
        baseline = None
        if experiment.baseline_run_id:
            baseline = next(
                (r for r in experiment.runs if r.id == experiment.baseline_run_id),
                None,
            )

        comparison = {
            "experiment_id": experiment_id,
            "experiment_name": experiment.name,
            "baseline_run_id": experiment.baseline_run_id,
            "runs": [],
        }

        for run in experiment.runs:
            run_data = {
                "id": run.id,
                "name": run.name,
                "config": run.config,
                "metrics": run.metrics,
                "status": run.status,
            }

            # Compare to baseline if available
            if baseline and run.id != baseline.id:
                run_data["vs_baseline"] = {}
                for metric, value in run.metrics.items():
                    if metric_names and metric not in metric_names:
                        continue
                    if metric in baseline.metrics:
                        baseline_value = baseline.metrics[metric]
                        delta = value - baseline_value
                        pct_change = (
                            (delta / baseline_value * 100)
                            if baseline_value != 0
                            else 0
                        )
                        run_data["vs_baseline"][metric] = {
                            "delta": delta,
                            "percent_change": pct_change,
                            "improved": delta > 0,
                        }

            comparison["runs"].append(run_data)

        return comparison

    async def _store_experiment(self, experiment: Experiment) -> None:
        """Store experiment in database."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO experiments
                (id, name, description, hypothesis, experiment_type,
                 baseline_run_id, created_at, status, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                experiment.id,
                experiment.name,
                experiment.description,
                experiment.hypothesis,
                experiment.experiment_type,
                experiment.baseline_run_id,
                experiment.created_at,
                experiment.status,
                json.dumps(experiment.metadata),
            )

    async def _store_run(self, run: ExperimentRun) -> None:
        """Store run in database."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO experiment_runs
                (id, experiment_id, name, config, metrics,
                 started_at, status, artifacts, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                run.id,
                run.experiment_id,
                run.name,
                json.dumps(run.config),
                json.dumps(run.metrics),
                run.started_at,
                run.status,
                json.dumps(run.artifacts),
                json.dumps(run.metadata),
            )

    async def list_experiments(
        self,
        status: str | None = None,
        experiment_type: str | None = None,
        limit: int = 50,
    ) -> list[Experiment]:
        """
        List experiments.

        Args:
            status: Filter by status
            experiment_type: Filter by type
            limit: Maximum results

        Returns:
            List of experiments
        """
        pool = await self._get_pool()

        query = "SELECT * FROM experiments WHERE 1=1"
        params = []

        if status:
            params.append(status)
            query += f" AND status = ${len(params)}"

        if experiment_type:
            params.append(experiment_type)
            query += f" AND experiment_type = ${len(params)}"

        params.append(limit)
        query += f" ORDER BY created_at DESC LIMIT ${len(params)}"

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [Experiment.from_dict(dict(row)) for row in rows]
