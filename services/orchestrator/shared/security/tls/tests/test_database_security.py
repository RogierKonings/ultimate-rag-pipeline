"""
Unit tests for database security configuration.

Tests SSL/TLS context creation for PostgreSQL, Redis, and OpenSearch
as specified in US-10.7.2.
"""

import ssl
from unittest.mock import patch


class TestPostgresSSL:
    """Tests for PostgreSQL SSL configuration."""

    @patch.dict(
        "os.environ",
        {
            "POSTGRES_SSL_MODE": "verify-full",
            "POSTGRES_SSL_CA": "/path/to/ca.crt",
        },
    )
    def test_creates_ssl_context_verify_full(self):
        """Should create SSL context with full verification."""
        # Patch Path.exists to return True for the CA cert
        with patch("pathlib.Path.exists", return_value=True):
            from shared.database.connection import create_ssl_context

            ctx = create_ssl_context()

            assert ctx is not None
            assert ctx.check_hostname is True
            assert ctx.verify_mode == ssl.CERT_REQUIRED
            assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2

    @patch.dict(
        "os.environ",
        {
            "POSTGRES_SSL_MODE": "require",
        },
    )
    def test_creates_ssl_context_require_mode(self):
        """Should create SSL context without certificate verification in require mode."""
        from shared.database.connection import create_ssl_context

        ctx = create_ssl_context()

        assert ctx is not None
        assert ctx.check_hostname is False
        assert ctx.verify_mode == ssl.CERT_NONE

    @patch.dict(
        "os.environ",
        {
            "POSTGRES_SSL_MODE": "verify-ca",
            "POSTGRES_SSL_CA": "/path/to/ca.crt",
        },
    )
    def test_creates_ssl_context_verify_ca_mode(self):
        """Should create SSL context with CA verification but no hostname check."""
        with patch("pathlib.Path.exists", return_value=True):
            from shared.database.connection import create_ssl_context

            ctx = create_ssl_context()

            assert ctx is not None
            assert ctx.check_hostname is False
            assert ctx.verify_mode == ssl.CERT_REQUIRED

    @patch.dict(
        "os.environ",
        {
            "POSTGRES_SSL_MODE": "disable",
        },
    )
    def test_ssl_disabled(self):
        """Should return None when SSL disabled."""
        from shared.database.connection import create_ssl_context

        ctx = create_ssl_context()

        assert ctx is None

    @patch.dict(
        "os.environ",
        {
            "POSTGRES_SSL_MODE": "verify-full",
            "POSTGRES_SSL_CA": "/path/to/ca.crt",
            "POSTGRES_SSL_CERT": "/path/to/client.crt",
            "POSTGRES_SSL_KEY": "/path/to/client.key",
        },
    )
    def test_loads_client_certificate_for_mtls(self):
        """Should load client certificate for mutual TLS."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch.object(ssl.SSLContext, "load_cert_chain") as mock_load,
        ):
            from shared.database.connection import create_ssl_context

            ctx = create_ssl_context()

            assert ctx is not None
            mock_load.assert_called_once_with(
                "/path/to/client.crt",
                "/path/to/client.key",
            )

    @patch.dict(
        "os.environ",
        {
            "POSTGRES_HOST": "db.example.com",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "testdb",
            "POSTGRES_USER": "testuser",
        },
    )
    def test_get_database_url_without_password(self):
        """Should build database URL without password for logging safety."""
        from shared.database.connection import get_database_url_without_password

        url = get_database_url_without_password()

        assert url == "postgresql+asyncpg://testuser@db.example.com:5432/testdb"
        assert "password" not in url.lower()


class TestRedisTLS:
    """Tests for Redis TLS configuration."""

    @patch.dict(
        "os.environ",
        {
            "REDIS_TLS_ENABLED": "true",
            "ENVIRONMENT": "production",
        },
    )
    def test_creates_tls_context_production(self):
        """Should create TLS context with verification in production."""
        with patch("pathlib.Path.exists", return_value=False):
            from shared.cache.redis_client import get_ssl_context

            ctx = get_ssl_context()

            assert ctx is not None
            assert ctx.check_hostname is True
            assert ctx.verify_mode == ssl.CERT_REQUIRED
            assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2

    @patch.dict(
        "os.environ",
        {
            "REDIS_TLS_ENABLED": "true",
            "ENVIRONMENT": "development",
        },
    )
    def test_creates_tls_context_development(self):
        """Should create TLS context with relaxed verification in development."""
        with patch("pathlib.Path.exists", return_value=False):
            from shared.cache.redis_client import get_ssl_context

            ctx = get_ssl_context()

            assert ctx is not None
            assert ctx.check_hostname is False
            assert ctx.verify_mode == ssl.CERT_NONE

    @patch.dict(
        "os.environ",
        {
            "REDIS_TLS_ENABLED": "false",
        },
    )
    def test_returns_none_when_tls_disabled(self):
        """Should return None when TLS is disabled."""
        from shared.cache.redis_client import get_ssl_context

        ctx = get_ssl_context()

        assert ctx is None

    @patch.dict(
        "os.environ",
        {
            "REDIS_TLS_ENABLED": "true",
            "REDIS_TLS_CA_CERT": "/path/to/ca.crt",
            "REDIS_TLS_CERT": "/path/to/client.crt",
            "REDIS_TLS_KEY": "/path/to/client.key",
            "ENVIRONMENT": "production",
        },
    )
    def test_loads_client_certificate_for_mtls(self):
        """Should load client certificate for mutual TLS."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch.object(ssl.SSLContext, "load_cert_chain") as mock_load,
            patch.object(ssl.SSLContext, "load_verify_locations"),
        ):
            from shared.cache.redis_client import get_ssl_context

            ctx = get_ssl_context()

            assert ctx is not None
            mock_load.assert_called_once_with(
                certfile="/path/to/client.crt",
                keyfile="/path/to/client.key",
            )


class TestOpenSearchSSL:
    """Tests for OpenSearch SSL configuration."""

    @patch.dict(
        "os.environ",
        {
            "OPENSEARCH_USE_SSL": "true",
            "OPENSEARCH_VERIFY_CERTS": "true",
            "ENVIRONMENT": "production",
        },
    )
    def test_creates_ssl_context_production(self):
        """Should create SSL context with strict verification in production."""
        from shared.search.opensearch_client import OpenSearchClient

        client = OpenSearchClient(use_ssl=True, verify_certs=True)
        ctx = client._create_ssl_context()

        assert ctx is not None
        assert ctx.check_hostname is True
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2

    @patch.dict(
        "os.environ",
        {
            "OPENSEARCH_USE_SSL": "true",
            "OPENSEARCH_VERIFY_CERTS": "false",
        },
    )
    def test_creates_ssl_context_without_verification(self):
        """Should create SSL context without verification when disabled."""
        from shared.search.opensearch_client import OpenSearchClient

        client = OpenSearchClient(use_ssl=True, verify_certs=False)
        ctx = client._create_ssl_context()

        assert ctx is not None
        assert ctx.check_hostname is False
        assert ctx.verify_mode == ssl.CERT_NONE

    @patch.dict(
        "os.environ",
        {
            "OPENSEARCH_USE_SSL": "false",
        },
    )
    def test_returns_none_when_ssl_disabled(self):
        """Should return None when SSL is disabled."""
        from shared.search.opensearch_client import OpenSearchClient

        client = OpenSearchClient(use_ssl=False)
        ctx = client._create_ssl_context()

        assert ctx is None

    @patch.dict(
        "os.environ",
        {
            "OPENSEARCH_USE_SSL": "true",
            "OPENSEARCH_VERIFY_CERTS": "true",
            "OPENSEARCH_CA_CERT": "/path/to/ca.crt",
            "OPENSEARCH_CLIENT_CERT": "/path/to/client.crt",
            "OPENSEARCH_CLIENT_KEY": "/path/to/client.key",
        },
    )
    def test_loads_client_certificate_for_mtls(self):
        """Should load client certificate for mutual TLS."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch.object(ssl.SSLContext, "load_cert_chain") as mock_load,
            patch.object(ssl.SSLContext, "load_verify_locations"),
        ):
            from shared.search.opensearch_client import (
                OpenSearchClient,
            )

            client = OpenSearchClient(
                use_ssl=True,
                verify_certs=True,
                ca_cert_path="/path/to/ca.crt",
                client_cert_path="/path/to/client.crt",
                client_key_path="/path/to/client.key",
            )
            ctx = client._create_ssl_context()

            assert ctx is not None
            mock_load.assert_called_once_with(
                certfile="/path/to/client.crt",
                keyfile="/path/to/client.key",
            )


class TestLogSanitizer:
    """Tests for log sanitization."""

    def test_sanitizes_password_in_url(self):
        """Should mask password in connection URLs."""
        from shared.observability.logging.sanitizer import sanitize_value

        url = "postgresql://user:secret123@localhost/db"
        result = sanitize_value(url)

        assert "secret123" not in result
        assert "://***:***@" in result

    def test_sanitizes_redis_url(self):
        """Should mask password in Redis URLs."""
        from shared.observability.logging.sanitizer import sanitize_value

        url = "redis://:mypassword@localhost:6379/0"
        result = sanitize_value(url)

        assert "mypassword" not in result
        assert "redis://***:***@" in result

    def test_sanitizes_bearer_token(self):
        """Should mask bearer tokens."""
        from shared.observability.logging.sanitizer import sanitize_value

        auth = "Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature"
        result = sanitize_value(auth)

        assert "eyJ" not in result
        assert "Bearer ***" in result

    def test_sanitizes_basic_auth(self):
        """Should mask basic auth headers."""
        from shared.observability.logging.sanitizer import sanitize_value

        auth = "Basic dXNlcjpwYXNz"
        result = sanitize_value(auth)

        assert "dXNlcjpwYXNz" not in result
        assert "Basic ***" in result

    def test_sanitizes_password_param(self):
        """Should mask password parameters."""
        from shared.observability.logging.sanitizer import sanitize_value

        text = "connection string: host=localhost password=secret123 dbname=test"
        result = sanitize_value(text)

        assert "secret123" not in result
        assert "password=***" in result

    def test_sanitizes_sensitive_dict_keys(self):
        """Should mask values for sensitive keys."""
        from shared.observability.logging.sanitizer import sanitize_dict

        data = {
            "username": "admin",
            "password": "secret",
            "api_key": "key123",
            "data": "visible",
            "database_url": "postgresql://user:pass@localhost/db",
        }
        result = sanitize_dict(data)

        assert result["username"] == "admin"
        assert result["password"] == "***"
        assert result["api_key"] == "***"
        assert result["data"] == "visible"
        assert result["database_url"] == "***"

    def test_sanitizes_nested_dict(self):
        """Should recursively sanitize nested dictionaries."""
        from shared.observability.logging.sanitizer import sanitize_dict

        data = {
            "config": {
                "database": {
                    "host": "localhost",
                    "password": "nested_secret",
                },
            },
        }
        result = sanitize_dict(data)

        assert result["config"]["database"]["host"] == "localhost"
        assert result["config"]["database"]["password"] == "***"

    def test_sanitizes_list_in_dict(self):
        """Should sanitize lists containing sensitive data."""
        from shared.observability.logging.sanitizer import sanitize_dict

        data = {
            "urls": [
                "postgresql://user:pass1@host1/db",
                "postgresql://user:pass2@host2/db",
            ],
        }
        result = sanitize_dict(data)

        assert "pass1" not in str(result)
        assert "pass2" not in str(result)

    def test_sanitize_connection_string(self):
        """Should sanitize database connection strings."""
        from shared.observability.logging.sanitizer import (
            sanitize_connection_string,
        )

        conn = "postgresql://admin:supersecret@db.example.com:5432/mydb"
        result = sanitize_connection_string(conn)

        assert "supersecret" not in result
        assert "admin:" in result  # Username preserved
        assert "***@db.example.com" in result

    def test_structlog_processor(self):
        """Should work as a structlog processor."""
        from shared.observability.logging.sanitizer import SanitizingProcessor

        processor = SanitizingProcessor()

        event_dict = {
            "event": "database_connect",
            "connection_url": "postgresql://user:secret@localhost/db",
            "password": "should_be_masked",
        }

        result = processor(None, "info", event_dict)

        assert result["password"] == "***"
        assert result["connection_url"] == "***"


class TestSensitiveDataFilter:
    """Tests for the logging filter that masks sensitive data."""

    def test_masks_jwt_tokens(self):
        """Should mask JWT tokens in log messages."""
        from shared.observability.logging.filters import SensitiveDataFilter

        filter = SensitiveDataFilter()
        text = "Token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.abc123"
        result = filter._mask_string(text)

        assert "eyJ" not in result

    def test_masks_database_url_credentials(self):
        """Should mask credentials in database URLs."""
        from shared.observability.logging.filters import SensitiveDataFilter

        filter = SensitiveDataFilter()
        text = "Connecting to postgresql://admin:password123@localhost/db"
        result = filter._mask_string(text)

        assert "password123" not in result
        assert "://***:***@" in result

    def test_masks_aws_keys(self):
        """Should mask AWS access keys."""
        from shared.observability.logging.filters import SensitiveDataFilter

        filter = SensitiveDataFilter()
        text = "AWS Key: AKIAIOSFODNN7EXAMPLE"
        result = filter._mask_string(text)

        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_preserves_non_sensitive_data(self):
        """Should preserve non-sensitive data."""
        from shared.observability.logging.filters import SensitiveDataFilter

        filter = SensitiveDataFilter()
        text = "User john.doe logged in from 192.168.1.1"
        result = filter._mask_string(text)

        assert result == text
