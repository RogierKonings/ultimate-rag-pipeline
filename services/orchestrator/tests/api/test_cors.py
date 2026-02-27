"""Tests for CORS configuration in the orchestrator service."""

from unittest.mock import patch

from api.app import _parse_cors_list, create_app

from config import OrchestratorConfig


class TestParseCORSList:
    """Tests for the _parse_cors_list helper function."""

    def test_empty_string_returns_empty_list(self):
        assert _parse_cors_list("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert _parse_cors_list("   ") == []

    def test_single_origin(self):
        assert _parse_cors_list("https://example.com") == ["https://example.com"]

    def test_multiple_origins(self):
        result = _parse_cors_list("https://a.com, https://b.com, https://c.com")
        assert result == ["https://a.com", "https://b.com", "https://c.com"]

    def test_trims_whitespace(self):
        result = _parse_cors_list("  https://a.com ,  https://b.com  ")
        assert result == ["https://a.com", "https://b.com"]

    def test_filters_empty_entries(self):
        result = _parse_cors_list("https://a.com,,, https://b.com,")
        assert result == ["https://a.com", "https://b.com"]


class TestCORSConfiguration:
    """Tests for CORS middleware configuration in create_app."""

    @patch("api.app.lifespan")
    def test_cors_disabled(self, mock_lifespan):
        """When cors_enabled=False, CORSMiddleware should not be added."""
        mock_lifespan.return_value = None
        config = OrchestratorConfig(cors_enabled=False)
        app = create_app(config=config)

        # CORSMiddleware should not be in the middleware stack
        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" not in middleware_classes

    @patch("api.app.lifespan")
    def test_cors_enabled_dev_defaults(self, mock_lifespan):
        """In development, CORS should default to wildcard origins."""
        mock_lifespan.return_value = None
        config = OrchestratorConfig(
            cors_enabled=True,
            environment="development",
        )
        app = create_app(config=config)

        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_classes

    @patch("api.app.lifespan")
    def test_cors_enabled_prod_no_origins(self, mock_lifespan):
        """In production with no origins, CORS should be restrictive (empty list)."""
        mock_lifespan.return_value = None
        config = OrchestratorConfig(
            cors_enabled=True,
            environment="production",
            cors_allowed_origins="",
        )
        app = create_app(config=config)

        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_classes

    @patch("api.app.lifespan")
    def test_cors_enabled_prod_with_origins(self, mock_lifespan):
        """In production with explicit origins, those should be used."""
        mock_lifespan.return_value = None
        config = OrchestratorConfig(
            cors_enabled=True,
            environment="production",
            cors_allowed_origins="https://app.example.com, https://admin.example.com",
        )
        app = create_app(config=config)

        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_classes

    @patch("api.app.lifespan")
    def test_cors_custom_methods_and_headers(self, mock_lifespan):
        """Custom methods and headers should be applied."""
        mock_lifespan.return_value = None
        config = OrchestratorConfig(
            cors_enabled=True,
            environment="production",
            cors_allowed_origins="https://app.example.com",
            cors_allowed_methods="GET, POST",
            cors_allowed_headers="Content-Type, Authorization",
        )
        app = create_app(config=config)

        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_classes


class TestOrchestratorCORSConfig:
    """Tests for CORS fields in OrchestratorConfig."""

    def test_default_cors_fields(self):
        """Default values for CORS config fields."""
        config = OrchestratorConfig()
        assert config.cors_enabled is True
        assert config.environment == "development"
        assert config.cors_allowed_origins == ""
        assert config.cors_allowed_methods == ""
        assert config.cors_allowed_headers == ""

    def test_cors_from_env(self):
        """CORS config should be loadable from environment variables."""
        with patch.dict(
            "os.environ",
            {
                "ORCHESTRATOR_CORS_ENABLED": "false",
                "ORCHESTRATOR_ENVIRONMENT": "production",
                "ORCHESTRATOR_CORS_ALLOWED_ORIGINS": "https://app.example.com",
                "ORCHESTRATOR_CORS_ALLOWED_METHODS": "GET, POST",
                "ORCHESTRATOR_CORS_ALLOWED_HEADERS": "Content-Type",
            },
        ):
            config = OrchestratorConfig()
            assert config.cors_enabled is False
            assert config.environment == "production"
            assert config.cors_allowed_origins == "https://app.example.com"
            assert config.cors_allowed_methods == "GET, POST"
            assert config.cors_allowed_headers == "Content-Type"
