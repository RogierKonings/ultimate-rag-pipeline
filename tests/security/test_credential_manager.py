"""
Tests for dynamic credential management module.

This module tests credential rotation, lease management,
and secret providers with caching.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.shared.security.secrets.credential_manager import (
    CredentialManagerConfig,
    DatabaseCredentials,
    DynamicCredentialManager,
)
from services.shared.security.secrets.provider import (
    CompositeSecretProvider,
    EnvironmentSecretProvider,
    FileSecretProvider,
    SecretProviderError,
    SecretValue,
    VaultSecretProvider,
    create_secret_provider,
)


class TestSecretValue:
    """Tests for SecretValue dataclass."""

    def test_create_secret_value(self):
        """Test creating a secret value with metadata."""
        secret = SecretValue(
            value="my_secret",
            version="1",
            expires_at=time.time() + 300,
            lease_id="lease-123",
        )

        assert secret.value == "my_secret"
        assert secret.version == "1"
        assert secret.lease_id == "lease-123"
        assert not secret.is_expired

    def test_expired_secret(self):
        """Test detecting expired secrets."""
        secret = SecretValue(
            value="expired",
            expires_at=time.time() - 10,  # Expired 10 seconds ago
        )

        assert secret.is_expired

    def test_no_expiry_secret(self):
        """Test secrets without expiration."""
        secret = SecretValue(value="no_expiry")

        assert not secret.is_expired
        assert secret.time_until_expiry is None

    def test_time_until_expiry(self):
        """Test calculating time until expiry."""
        expires_in = 300
        secret = SecretValue(
            value="expiring",
            expires_at=time.time() + expires_in,
        )

        # Should be close to 300 seconds
        assert 290 < secret.time_until_expiry < 310


class TestEnvironmentSecretProvider:
    """Tests for environment variable provider."""

    @pytest.fixture
    def provider(self):
        """Create provider with test prefix."""
        return EnvironmentSecretProvider(prefix="TEST_SECRET_")

    @pytest.mark.asyncio
    async def test_get_existing_secret(self, provider, monkeypatch):
        """Test getting an existing environment variable."""
        monkeypatch.setenv("TEST_SECRET_MY_KEY", "my_value")

        secret = await provider.get("my-key")

        assert secret.value == "my_value"

    @pytest.mark.asyncio
    async def test_get_missing_secret_raises(self, provider):
        """Test that missing secrets raise an error."""
        with pytest.raises(SecretProviderError) as exc_info:
            await provider.get("nonexistent-key")

        assert "Environment variable not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_or_default(self, provider):
        """Test getting secret with default value."""
        secret = await provider.get_or_default(
            "nonexistent",
            default="fallback",
        )

        assert secret.value == "fallback"

    def test_key_to_env_var_conversion(self, provider):
        """Test key to environment variable name conversion."""
        assert provider._key_to_env_var("database-password") == "TEST_SECRET_DATABASE_PASSWORD"
        assert provider._key_to_env_var("api/key") == "TEST_SECRET_API_KEY"


class TestFileSecretProvider:
    """Tests for file-based provider."""

    @pytest.fixture
    def temp_secrets_dir(self, tmp_path):
        """Create temporary secrets directory with test secrets."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()

        # Create test secrets
        (secrets_dir / "database_password").write_text("db_secret_123")
        (secrets_dir / "api_key").write_text("api_key_456")

        return secrets_dir

    @pytest.fixture
    def provider(self, temp_secrets_dir):
        """Create provider with temp directory."""
        return FileSecretProvider(
            secrets_dir=str(temp_secrets_dir),
            cache_ttl_seconds=60,
        )

    @pytest.mark.asyncio
    async def test_read_secret_from_file(self, provider):
        """Test reading secret from file."""
        secret = await provider.get("database_password")

        assert secret.value == "db_secret_123"
        assert secret.version is not None  # Should have file mtime

    @pytest.mark.asyncio
    async def test_missing_file_raises(self, provider):
        """Test that missing files raise an error."""
        with pytest.raises(SecretProviderError) as exc_info:
            await provider.get("nonexistent")

        assert "Secret file not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_caching(self, provider, temp_secrets_dir):
        """Test that secrets are cached."""
        # First read to populate cache
        await provider.get("api_key")

        # Modify file
        (temp_secrets_dir / "api_key").write_text("modified_value")

        # Should return cached value
        secret2 = await provider.get("api_key")
        assert secret2.value == "api_key_456"

    @pytest.mark.asyncio
    async def test_refresh_bypasses_cache(self, provider, temp_secrets_dir):
        """Test that refresh reads fresh value."""
        # First read
        await provider.get("api_key")

        # Modify file
        (temp_secrets_dir / "api_key").write_text("new_value")

        # Refresh should get new value
        secret = await provider.refresh("api_key")
        assert secret.value == "new_value"


class TestVaultSecretProvider:
    """Tests for Vault-backed provider."""

    @pytest.fixture
    def mock_vault_client(self):
        """Create mock Vault client."""
        client = AsyncMock()
        client.read_secret = AsyncMock(
            return_value={"username": "user", "password": "pass"},
        )
        return client

    @pytest.fixture
    def provider(self, mock_vault_client):
        """Create provider with mock client."""
        return VaultSecretProvider(
            vault_client=mock_vault_client,
            base_path="rag-pipeline",
            cache_ttl_seconds=300,
        )

    @pytest.mark.asyncio
    async def test_get_secret(self, provider, mock_vault_client):
        """Test getting secret from Vault."""
        secret = await provider.get("database")

        mock_vault_client.read_secret.assert_called_once_with(
            "rag-pipeline/database",
        )
        assert secret.value == {"username": "user", "password": "pass"}

    @pytest.mark.asyncio
    async def test_caching(self, provider, mock_vault_client):
        """Test that secrets are cached."""
        # First call
        await provider.get("database")
        # Second call should use cache
        await provider.get("database")

        assert mock_vault_client.read_secret.call_count == 1

    @pytest.mark.asyncio
    async def test_invalidate_cache(self, provider, mock_vault_client):
        """Test cache invalidation."""
        await provider.get("database")
        provider.invalidate("database")
        await provider.get("database")

        assert mock_vault_client.read_secret.call_count == 2


class TestCompositeSecretProvider:
    """Tests for composite provider with fallback."""

    @pytest.mark.asyncio
    async def test_tries_providers_in_order(self):
        """Test that providers are tried in order."""
        provider1 = AsyncMock()
        provider1.get = AsyncMock(
            side_effect=SecretProviderError("Not found"),
        )

        provider2 = AsyncMock()
        provider2.get = AsyncMock(
            return_value=SecretValue(value="from_provider2"),
        )

        composite = CompositeSecretProvider([provider1, provider2])

        secret = await composite.get("test_key")

        assert secret.value == "from_provider2"
        provider1.get.assert_called_once_with("test_key")
        provider2.get.assert_called_once_with("test_key")

    @pytest.mark.asyncio
    async def test_all_providers_fail(self):
        """Test error when all providers fail."""
        provider1 = AsyncMock()
        provider1.get = AsyncMock(
            side_effect=SecretProviderError("Error 1"),
        )

        provider2 = AsyncMock()
        provider2.get = AsyncMock(
            side_effect=SecretProviderError("Error 2"),
        )

        composite = CompositeSecretProvider([provider1, provider2])

        with pytest.raises(SecretProviderError) as exc_info:
            await composite.get("test_key")

        assert "All providers failed" in str(exc_info.value)

    def test_requires_at_least_one_provider(self):
        """Test that at least one provider is required."""
        with pytest.raises(ValueError):
            CompositeSecretProvider([])


class TestDynamicCredentialManager:
    """Tests for dynamic database credential manager."""

    @pytest.fixture
    def mock_vault_client(self):
        """Create mock Vault client."""
        client = MagicMock()
        client.get_database_credentials = AsyncMock(
            return_value={
                "username": "v-rag-db-user",
                "password": "dynamic_password",
                "lease_id": "database/creds/rag/lease-123",
                "lease_duration": 3600,
            },
        )

        # Mock the internal client for lease operations
        mock_hvac = MagicMock()
        mock_hvac.sys.renew_lease.return_value = {"lease_duration": 3600}
        mock_hvac.sys.revoke_lease.return_value = None
        client._get_client = MagicMock(return_value=mock_hvac)

        return client

    @pytest.fixture
    def config(self):
        """Create credential manager config."""
        return CredentialManagerConfig(
            database="database",
            role="rag-pipeline-db",
            renewal_buffer_seconds=60,
            max_renewal_retries=3,
        )

    @pytest.fixture
    def manager(self, mock_vault_client, config):
        """Create credential manager."""
        return DynamicCredentialManager(mock_vault_client, config)

    @pytest.mark.asyncio
    async def test_start_fetches_credentials(self, manager, mock_vault_client):
        """Test that start fetches initial credentials."""
        await manager.start()

        try:
            mock_vault_client.get_database_credentials.assert_called_once_with(
                role="rag-pipeline-db",
            )
            assert manager._credentials is not None
            assert manager._credentials.username == "v-rag-db-user"
        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_get_credentials(self, manager):
        """Test getting current credentials."""
        await manager.start()

        try:
            username, password = await manager.get_credentials()

            assert username == "v-rag-db-user"
            assert password == "dynamic_password"
        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_credential_change_callback(self, manager):
        """Test that credential change callbacks are called."""
        callback = MagicMock()
        manager.on_credential_change(callback)

        await manager.start()

        try:
            callback.assert_called_once_with("v-rag-db-user", "dynamic_password")
        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_async_callback(self, manager):
        """Test async credential change callback."""
        async_callback = AsyncMock()
        manager.on_credential_change(async_callback)

        await manager.start()

        try:
            async_callback.assert_called_once_with("v-rag-db-user", "dynamic_password")
        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_stop_revokes_lease(self, manager, mock_vault_client):
        """Test that stop revokes the lease."""
        await manager.start()
        await manager.stop()

        mock_hvac = mock_vault_client._get_client()
        mock_hvac.sys.revoke_lease.assert_called_once_with(
            lease_id="database/creds/rag/lease-123",
        )

    @pytest.mark.asyncio
    async def test_health_check_running(self, manager):
        """Test health check when running."""
        await manager.start()

        try:
            health = await manager.health_check()

            assert health["healthy"] is True
            assert health["running"] is True
            assert health["username"] == "v-rag-db-user"
            assert health["time_until_expiry_seconds"] > 0
        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_health_check_not_running(self, manager):
        """Test health check when not running."""
        health = await manager.health_check()

        assert health["healthy"] is False
        assert health["running"] is False

    @pytest.mark.asyncio
    async def test_double_start_warning(self, manager, caplog):
        """Test that double start logs a warning."""
        import logging

        await manager.start()

        try:
            with caplog.at_level(logging.WARNING):
                await manager.start()

            assert "already running" in caplog.text.lower()
        finally:
            await manager.stop()


class TestDatabaseCredentialsDataclass:
    """Tests for DatabaseCredentials dataclass."""

    def test_create_credentials(self):
        """Test creating database credentials."""
        creds = DatabaseCredentials(
            username="user",
            password="pass",
            lease_id="lease-123",
            lease_duration=3600,
            expires_at=time.time() + 3600,
        )

        assert creds.username == "user"
        assert creds.password == "pass"
        assert creds.lease_id == "lease-123"


class TestCreateSecretProviderFactory:
    """Tests for secret provider factory function."""

    def test_create_environment_provider(self, monkeypatch):
        """Test creating environment provider."""
        # Ensure no VAULT_ADDR is set
        monkeypatch.delenv("VAULT_ADDR", raising=False)

        from services.shared.security.secrets.config import SecretsBackend

        provider = create_secret_provider(
            backend=SecretsBackend.ENVIRONMENT,
            prefix="TEST_",
        )

        assert isinstance(provider, EnvironmentSecretProvider)
        assert provider.prefix == "TEST_"

    def test_create_file_provider(self, tmp_path):
        """Test creating file provider."""
        from services.shared.security.secrets.config import SecretsBackend

        provider = create_secret_provider(
            backend=SecretsBackend.FILE,
            secrets_dir=str(tmp_path),
        )

        assert isinstance(provider, FileSecretProvider)
        assert str(provider.secrets_dir) == str(tmp_path)

    def test_auto_detect_environment(self, monkeypatch, tmp_path):
        """Test auto-detection defaults to environment."""
        monkeypatch.delenv("VAULT_ADDR", raising=False)

        # Ensure /run/secrets doesn't exist in test
        with patch("os.path.exists", return_value=False):
            provider = create_secret_provider()

        assert isinstance(provider, EnvironmentSecretProvider)


class TestCredentialManagerIntegration:
    """Integration tests for credential manager."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """Test full credential manager lifecycle."""
        mock_client = MagicMock()
        mock_client.get_database_credentials = AsyncMock(
            return_value={
                "username": "test_user",
                "password": "test_pass",
                "lease_id": "lease-abc",
                "lease_duration": 3600,
            },
        )

        mock_hvac = MagicMock()
        mock_hvac.sys.renew_lease.return_value = {"lease_duration": 3600}
        mock_hvac.sys.revoke_lease.return_value = None
        mock_client._get_client = MagicMock(return_value=mock_hvac)

        config = CredentialManagerConfig(
            database="database",
            role="test-role",
            renewal_buffer_seconds=60,
        )

        manager = DynamicCredentialManager(mock_client, config)

        # Track credential changes
        changes = []
        manager.on_credential_change(lambda u, p: changes.append((u, p)))

        # Start
        await manager.start()
        assert manager.is_running
        assert len(changes) == 1

        # Get credentials
        user, password = await manager.get_credentials()
        assert user == "test_user"
        assert password == "test_pass"

        # Health check
        health = await manager.health_check()
        assert health["healthy"] is True

        # Stop
        await manager.stop()
        assert not manager.is_running
