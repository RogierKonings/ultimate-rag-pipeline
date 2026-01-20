"""Tests for Celery application configuration."""

from ..celery_app import CeleryConfig, create_celery_app


class TestCeleryConfig:
    """Tests for CeleryConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = CeleryConfig()

        assert "redis" in config.broker_url
        assert "redis" in config.result_backend
        assert config.task_serializer == "json"
        assert config.task_track_started is True
        assert config.task_time_limit == 3600
        assert config.task_soft_time_limit == 3300
        assert config.worker_prefetch_multiplier == 1
        assert config.task_default_queue == "ingestion_normal"

    def test_custom_values(self):
        """Test custom configuration values."""
        config = CeleryConfig(
            broker_url="redis://custom:6379/0",
            worker_concurrency=8,
            task_max_retries=5,
        )

        assert config.broker_url == "redis://custom:6379/0"
        assert config.worker_concurrency == 8
        assert config.task_max_retries == 5


class TestCreateCeleryApp:
    """Tests for create_celery_app function."""

    def test_creates_app_with_defaults(self):
        """Test app creation with default config."""
        app = create_celery_app()

        assert app.main == "ingestion"
        assert app.conf.task_serializer == "json"
        assert app.conf.result_serializer == "json"
        assert app.conf.task_track_started is True

    def test_creates_app_with_custom_config(self):
        """Test app creation with custom config.

        Note: Celery reads from environment variables which may override
        config values for broker_url and result_backend. We test worker_concurrency
        which is not overridden by environment variables.
        """
        config = CeleryConfig(
            broker_url="memory://",
            result_backend="cache+memory://",
            worker_concurrency=2,
        )
        app = create_celery_app(config)

        # Note: Celery may use environment variables for broker/result_backend
        # Test that custom values that aren't in env vars work
        assert app.conf.worker_concurrency == 2

        # Verify the config object has the expected values
        assert config.broker_url == "memory://"
        assert config.result_backend == "cache+memory://"

    def test_queues_configured(self):
        """Test that queues are properly configured."""
        app = create_celery_app()
        queues = app.conf.task_queues

        queue_names = [q.name for q in queues]
        assert "ingestion" in queue_names
        assert "ingestion_normal" in queue_names
        assert "ingestion_high" in queue_names
        assert "ingestion_low" in queue_names
        assert "embedding" in queue_names
        assert "reembed" in queue_names
        assert "dlq" in queue_names

    def test_task_routes_configured(self):
        """Test that task routes are properly configured."""
        app = create_celery_app()
        routes = app.conf.task_routes

        assert "tasks.ingest.*" in routes
        assert "tasks.reembed.*" in routes
        assert "tasks.callbacks.*" in routes
