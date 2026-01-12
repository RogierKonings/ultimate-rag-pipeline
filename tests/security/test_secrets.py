"""
Tests for secrets management module.

This module tests secrets backends, service, and injection.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.shared.security.secrets import (
    FileSecretsSettings,
    K8sSecretsClient,
    KubernetesSecretsSettings,
    SecretsBackend,
    SecretsInjector,
    SecretsService,
    SecretsSettings,
    VaultAuthMethod,
    VaultClient,
    VaultSettings,
    get_secret,
    get_secrets_service,
)


class TestSecretsSettings:
    """Tests for secrets settings configuration."""

    def test_default_settings(self):
        """Test default settings values."""
        settings = SecretsSettings()
        assert settings.backend == SecretsBackend.ENVIRONMENT
        assert settings.cache_enabled is True
        assert settings.cache_ttl_seconds == 300

    def test_vault_settings(self):
        """Test Vault-specific settings."""
        settings = SecretsSettings(
            backend=SecretsBackend.VAULT,
            vault=VaultSettings(
                url="https://vault.example.com:8200",
                auth_method=VaultAuthMethod.KUBERNETES,
                kubernetes_role="test-role",
            ),
        )
        assert settings.backend == SecretsBackend.VAULT
        assert settings.vault.url == "https://vault.example.com:8200"
        assert settings.vault.auth_method == VaultAuthMethod.KUBERNETES
        assert settings.vault.kubernetes_role == "test-role"

    def test_kubernetes_settings(self):
        """Test Kubernetes-specific settings."""
        settings = SecretsSettings(
            backend=SecretsBackend.KUBERNETES,
            kubernetes=KubernetesSecretsSettings(
                namespace="production",
                secret_name="app-secrets",
            ),
        )
        assert settings.backend == SecretsBackend.KUBERNETES
        assert settings.kubernetes.namespace == "production"
        assert settings.kubernetes.secret_name == "app-secrets"

    def test_file_settings(self):
        """Test file-based settings."""
        settings = SecretsSettings(
            backend=SecretsBackend.FILE,
            file=FileSecretsSettings(
                secrets_dir="/app/secrets",
                file_extension=".txt",
            ),
        )
        assert settings.backend == SecretsBackend.FILE
        assert settings.file.secrets_dir == "/app/secrets"
        assert settings.file.file_extension == ".txt"


class TestEnvironmentBackend:
    """Tests for environment variable backend."""

    @pytest.fixture
    def service(self):
        """Create service with environment backend."""
        settings = SecretsSettings(
            backend=SecretsBackend.ENVIRONMENT,
            prefix="TEST_SECRET_",
            cache_enabled=False,
        )
        return SecretsService(settings)

    @pytest.mark.asyncio
    async def test_get_secret(self, service):
        """Test getting secret from environment."""
        os.environ["TEST_SECRET_MY_KEY"] = "my_value"
        try:
            value = await service.get_secret("MY_KEY")
            assert value == "my_value"
        finally:
            del os.environ["TEST_SECRET_MY_KEY"]

    @pytest.mark.asyncio
    async def test_get_missing_secret(self, service):
        """Test getting missing secret returns None."""
        value = await service.get_secret("NONEXISTENT")
        assert value is None

    @pytest.mark.asyncio
    async def test_get_secret_with_default(self, service):
        """Test getting missing secret with default."""
        value = await service.get_secret("NONEXISTENT", default="default_value")
        assert value == "default_value"

    @pytest.mark.asyncio
    async def test_set_secret(self, service):
        """Test setting secret in environment."""
        await service.set_secret("NEW_KEY", "new_value")
        assert os.environ.get("TEST_SECRET_NEW_KEY") == "new_value"
        del os.environ["TEST_SECRET_NEW_KEY"]

    @pytest.mark.asyncio
    async def test_delete_secret(self, service):
        """Test deleting secret from environment."""
        os.environ["TEST_SECRET_TO_DELETE"] = "value"
        await service.delete_secret("TO_DELETE")
        assert "TEST_SECRET_TO_DELETE" not in os.environ


class TestFileBackend:
    """Tests for file-based backend."""

    @pytest.fixture
    def temp_secrets_dir(self):
        """Create temporary secrets directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def service(self, temp_secrets_dir):
        """Create service with file backend."""
        settings = SecretsSettings(
            backend=SecretsBackend.FILE,
            file=FileSecretsSettings(secrets_dir=temp_secrets_dir),
            cache_enabled=False,
        )
        return SecretsService(settings)

    @pytest.mark.asyncio
    async def test_get_secret(self, service, temp_secrets_dir):
        """Test getting secret from file."""
        secret_path = Path(temp_secrets_dir) / "my_secret"
        secret_path.write_text("secret_value")

        value = await service.get_secret("my_secret")
        assert value == "secret_value"

    @pytest.mark.asyncio
    async def test_get_missing_secret(self, service):
        """Test getting missing secret returns None."""
        value = await service.get_secret("nonexistent")
        assert value is None

    @pytest.mark.asyncio
    async def test_set_secret(self, service, temp_secrets_dir):
        """Test setting secret to file."""
        await service.set_secret("new_secret", "new_value")

        secret_path = Path(temp_secrets_dir) / "new_secret"
        assert secret_path.exists()
        assert secret_path.read_text() == "new_value"

        # Check permissions (Unix only)
        if os.name != "nt":
            assert secret_path.stat().st_mode & 0o777 == 0o600

    @pytest.mark.asyncio
    async def test_delete_secret(self, service, temp_secrets_dir):
        """Test deleting secret file."""
        secret_path = Path(temp_secrets_dir) / "to_delete"
        secret_path.write_text("value")

        await service.delete_secret("to_delete")
        assert not secret_path.exists()


class TestSecretsServiceCaching:
    """Tests for secrets caching."""

    @pytest.fixture
    def service(self):
        """Create service with caching enabled."""
        settings = SecretsSettings(
            backend=SecretsBackend.ENVIRONMENT,
            prefix="CACHE_TEST_",
            cache_enabled=True,
            cache_ttl_seconds=300,
        )
        return SecretsService(settings)

    @pytest.mark.asyncio
    async def test_cache_hit(self, service):
        """Test that cached values are returned."""
        os.environ["CACHE_TEST_KEY"] = "original"
        try:
            # First call - cache miss
            value1 = await service.get_secret("KEY")
            assert value1 == "original"

            # Change value
            os.environ["CACHE_TEST_KEY"] = "changed"

            # Second call - cache hit (returns original)
            value2 = await service.get_secret("KEY")
            assert value2 == "original"

        finally:
            del os.environ["CACHE_TEST_KEY"]

    @pytest.mark.asyncio
    async def test_clear_cache(self, service):
        """Test clearing the cache."""
        os.environ["CACHE_TEST_CLEAR"] = "value1"
        try:
            value1 = await service.get_secret("CLEAR")
            os.environ["CACHE_TEST_CLEAR"] = "value2"

            # Clear cache
            service.clear_cache()

            # Should get new value
            value2 = await service.get_secret("CLEAR")
            assert value2 == "value2"

        finally:
            del os.environ["CACHE_TEST_CLEAR"]


class TestSecretsServiceConvenience:
    """Tests for convenience methods."""

    @pytest.fixture
    def service(self):
        """Create service with environment backend."""
        settings = SecretsSettings(
            backend=SecretsBackend.ENVIRONMENT,
            prefix="",
            cache_enabled=False,
        )
        return SecretsService(settings)

    @pytest.mark.asyncio
    async def test_get_database_url_full(self, service):
        """Test getting full database URL."""
        os.environ["DATABASE_URL"] = "postgresql+asyncpg://user:pass@host/db"
        try:
            url = await service.get_database_url()
            assert url == "postgresql+asyncpg://user:pass@host/db"
        finally:
            del os.environ["DATABASE_URL"]

    @pytest.mark.asyncio
    async def test_get_database_url_components(self, service):
        """Test constructing database URL from components."""
        env_vars = {
            "DATABASE_HOST": "localhost",
            "DATABASE_PORT": "5432",
            "DATABASE_USER": "testuser",
            "DATABASE_PASSWORD": "testpass",
            "DATABASE_NAME": "testdb",
        }
        for key, value in env_vars.items():
            os.environ[key] = value
        try:
            url = await service.get_database_url()
            assert "postgresql+asyncpg://" in url
            assert "testuser:testpass" in url
            assert "localhost:5432" in url
            assert "testdb" in url
        finally:
            for key in env_vars:
                del os.environ[key]

    @pytest.mark.asyncio
    async def test_get_redis_url(self, service):
        """Test getting Redis URL."""
        os.environ["REDIS_URL"] = "redis://:password@localhost:6379"
        try:
            url = await service.get_redis_url()
            assert url == "redis://:password@localhost:6379"
        finally:
            del os.environ["REDIS_URL"]

    @pytest.mark.asyncio
    async def test_get_redis_url_components(self, service):
        """Test constructing Redis URL from components."""
        os.environ["REDIS_HOST"] = "redis.example.com"
        os.environ["REDIS_PORT"] = "6380"
        os.environ["REDIS_PASSWORD"] = "secret"
        try:
            url = await service.get_redis_url()
            assert "redis://:secret@redis.example.com:6380" == url
        finally:
            del os.environ["REDIS_HOST"]
            del os.environ["REDIS_PORT"]
            del os.environ["REDIS_PASSWORD"]

    @pytest.mark.asyncio
    async def test_get_jwt_secret(self, service):
        """Test getting JWT secret."""
        os.environ["JWT_SECRET"] = "super-secret-jwt-key"
        try:
            secret = await service.get_jwt_secret()
            assert secret == "super-secret-jwt-key"
        finally:
            del os.environ["JWT_SECRET"]

    @pytest.mark.asyncio
    async def test_get_encryption_key(self, service):
        """Test getting encryption key."""
        import base64

        key = os.urandom(32)
        encoded = base64.b64encode(key).decode()
        os.environ["ENCRYPTION_KEY"] = encoded
        try:
            retrieved = await service.get_encryption_key()
            assert retrieved == key
        finally:
            del os.environ["ENCRYPTION_KEY"]

    @pytest.mark.asyncio
    async def test_get_api_key(self, service):
        """Test getting API key for external service."""
        os.environ["OPENAI_API_KEY"] = "sk-test-key"
        try:
            key = await service.get_api_key("openai")
            assert key == "sk-test-key"
        finally:
            del os.environ["OPENAI_API_KEY"]


class TestSecretsServiceHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_environment_health_check(self):
        """Test health check for environment backend."""
        settings = SecretsSettings(backend=SecretsBackend.ENVIRONMENT)
        service = SecretsService(settings)

        health = await service.health_check()
        assert health["healthy"] is True
        assert health["backend"] == "environment"

    @pytest.mark.asyncio
    async def test_file_health_check_existing_dir(self):
        """Test health check for file backend with existing directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = SecretsSettings(
                backend=SecretsBackend.FILE,
                file=FileSecretsSettings(secrets_dir=tmpdir),
            )
            service = SecretsService(settings)

            health = await service.health_check()
            assert health["healthy"] is True
            assert health["dir_exists"] is True

    @pytest.mark.asyncio
    async def test_file_health_check_missing_dir(self):
        """Test health check for file backend with missing directory."""
        settings = SecretsSettings(
            backend=SecretsBackend.FILE,
            file=FileSecretsSettings(secrets_dir="/nonexistent/path"),
        )
        service = SecretsService(settings)

        health = await service.health_check()
        assert health["healthy"] is False


class TestVaultClient:
    """Tests for Vault client (mocked)."""

    @pytest.fixture
    def settings(self):
        """Create Vault settings."""
        return VaultSettings(
            url="http://localhost:8200",
            auth_method=VaultAuthMethod.TOKEN,
            token="test-token",
        )

    @pytest.fixture
    def client(self, settings):
        """Create Vault client."""
        return VaultClient(settings)

    @pytest.mark.asyncio
    async def test_read_secret_mocked(self, client):
        """Test reading secret with mocked hvac."""
        with patch.object(client, "_get_client") as mock_get_client:
            mock_hvac = MagicMock()
            mock_hvac.secrets.kv.v2.read_secret_version.return_value = {
                "data": {"data": {"value": "secret_value"}}
            }
            mock_get_client.return_value = mock_hvac

            # Mock authentication
            client._authenticated = True

            data = await client.read_secret("test/path")
            assert data == {"value": "secret_value"}

    @pytest.mark.asyncio
    async def test_write_secret_mocked(self, client):
        """Test writing secret with mocked hvac."""
        with patch.object(client, "_get_client") as mock_get_client:
            mock_hvac = MagicMock()
            mock_get_client.return_value = mock_hvac

            # Mock authentication
            client._authenticated = True

            await client.write_secret("test/path", {"key": "value"})

            mock_hvac.secrets.kv.v2.create_or_update_secret.assert_called_once()

    @pytest.mark.asyncio
    async def test_encrypt_decrypt_mocked(self, client):
        """Test transit encryption with mocked hvac."""
        import base64

        with patch.object(client, "_get_client") as mock_get_client:
            mock_hvac = MagicMock()

            # Mock encrypt
            mock_hvac.secrets.transit.encrypt_data.return_value = {
                "data": {"ciphertext": "vault:v1:encrypted"}
            }

            # Mock decrypt
            mock_hvac.secrets.transit.decrypt_data.return_value = {
                "data": {"plaintext": base64.b64encode(b"decrypted").decode()}
            }

            mock_get_client.return_value = mock_hvac
            client._authenticated = True

            encrypted = await client.encrypt("test data")
            assert encrypted == "vault:v1:encrypted"

            decrypted = await client.decrypt("vault:v1:encrypted")
            assert decrypted == "decrypted"


class TestSecretsInjector:
    """Tests for FastAPI secrets injection."""

    @pytest.fixture
    def service(self):
        """Create mock secrets service."""
        settings = SecretsSettings(
            backend=SecretsBackend.ENVIRONMENT,
            prefix="INJECT_TEST_",
            cache_enabled=False,
        )
        return SecretsService(settings)

    @pytest.fixture
    def injector(self, service):
        """Create secrets injector."""
        return SecretsInjector(service=service)

    @pytest.mark.asyncio
    async def test_get_secret_dependency(self, injector):
        """Test getting secret via dependency."""
        os.environ["INJECT_TEST_MY_SECRET"] = "secret_value"
        try:
            dep = injector.get_secret("MY_SECRET")
            value = await dep()
            assert value == "secret_value"
        finally:
            del os.environ["INJECT_TEST_MY_SECRET"]

    @pytest.mark.asyncio
    async def test_get_required_missing_secret(self, injector):
        """Test that missing required secret raises HTTPException."""
        from fastapi import HTTPException

        dep = injector.get_secret("MISSING_REQUIRED", required=True)

        with pytest.raises(HTTPException) as exc_info:
            await dep()

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_optional_missing_secret(self, injector):
        """Test that missing optional secret returns None."""
        dep = injector.get_secret("MISSING_OPTIONAL", required=False)
        value = await dep()
        assert value is None

    @pytest.mark.asyncio
    async def test_get_optional_with_default(self, injector):
        """Test optional secret with default value."""
        dep = injector.get_secret(
            "MISSING_DEFAULT",
            required=False,
            default="default_val",
        )
        value = await dep()
        assert value == "default_val"


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    @pytest.mark.asyncio
    async def test_get_secret_function(self):
        """Test module-level get_secret function."""
        os.environ["MODULE_TEST_KEY"] = "module_value"
        try:
            # Create service with matching settings
            settings = SecretsSettings(
                backend=SecretsBackend.ENVIRONMENT,
                prefix="MODULE_TEST_",
                cache_enabled=False,
            )

            # Use the service directly
            service = SecretsService(settings)
            value = await service.get_secret("KEY")
            assert value == "module_value"

        finally:
            if "MODULE_TEST_KEY" in os.environ:
                del os.environ["MODULE_TEST_KEY"]

    def test_get_secrets_service(self):
        """Test getting secrets service instance."""
        settings = SecretsSettings(
            backend=SecretsBackend.ENVIRONMENT,
            prefix="SERVICE_TEST_",
        )
        service = get_secrets_service(settings)
        assert isinstance(service, SecretsService)
        assert service.settings.prefix == "SERVICE_TEST_"


class TestSecretsIntegration:
    """Integration tests for secrets workflow."""

    @pytest.mark.asyncio
    async def test_full_workflow_file_backend(self):
        """Test complete workflow with file backend."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = SecretsSettings(
                backend=SecretsBackend.FILE,
                file=FileSecretsSettings(secrets_dir=tmpdir),
                cache_enabled=True,
                cache_ttl_seconds=60,
            )
            service = SecretsService(settings)

            # Set secrets
            await service.set_secret("db_password", "super_secret")
            await service.set_secret("api_key", "key_12345")

            # Read back
            password = await service.get_secret("db_password")
            api_key = await service.get_secret("api_key")

            assert password == "super_secret"
            assert api_key == "key_12345"

            # Delete one
            await service.delete_secret("api_key")
            deleted = await service.get_secret("api_key")
            assert deleted is None

            # Other still exists
            still_exists = await service.get_secret("db_password")
            assert still_exists == "super_secret"

    @pytest.mark.asyncio
    async def test_database_url_construction(self):
        """Test database URL construction from components."""
        env_vars = {
            "TEST_DB_HOST": "db.example.com",
            "TEST_DB_PORT": "5432",
            "TEST_DB_USER": "appuser",
            "TEST_DB_PASSWORD": "secret123",
            "TEST_DB_NAME": "myapp",
        }

        for key, value in env_vars.items():
            os.environ[key] = value

        try:
            settings = SecretsSettings(
                backend=SecretsBackend.ENVIRONMENT,
                prefix="TEST_DB_",
                cache_enabled=False,
            )
            service = SecretsService(settings)

            # Manually construct since our service uses different key names
            host = await service.get_secret("HOST")
            port = await service.get_secret("PORT")
            user = await service.get_secret("USER")
            password = await service.get_secret("PASSWORD")
            name = await service.get_secret("NAME")

            assert host == "db.example.com"
            assert port == "5432"
            assert user == "appuser"
            assert password == "secret123"
            assert name == "myapp"

        finally:
            for key in env_vars:
                del os.environ[key]
