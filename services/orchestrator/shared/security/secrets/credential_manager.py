"""
Dynamic credential manager for automatic credential rotation.

This module provides automatic credential renewal for database connections
without requiring service restarts. It handles lease management, renewal
scheduling, and notifies connection pools of credential changes.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from .vault import VaultClient, VaultError

logger = structlog.get_logger(__name__)


@dataclass
class DatabaseCredentials:
    """Dynamic database credentials with lease information."""

    username: str
    password: str
    lease_id: str
    lease_duration: int
    expires_at: float


class CredentialManagerError(Exception):
    """Base exception for credential manager errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


@dataclass
class CredentialManagerConfig:
    """Configuration for DynamicCredentialManager."""

    database: str = "database"
    role: str = "rag-pipeline"
    renewal_buffer_seconds: int = 300  # Renew 5 minutes before expiry
    max_renewal_retries: int = 3
    retry_backoff_base: float = 1.0  # Base backoff in seconds


class DynamicCredentialManager:
    """
    Manages dynamic database credentials with automatic renewal.

    Handles credential rotation without service restart by:
    1. Getting initial credentials from Vault
    2. Scheduling renewal before expiry
    3. Notifying connection pools of credential changes

    Example:
        ```python
        from shared.security.secrets import (
            DynamicCredentialManager,
            CredentialManagerConfig,
            VaultClient,
        )

        vault = VaultClient(settings)
        await vault.authenticate()

        config = CredentialManagerConfig(
            database="database",
            role="rag-pipeline-db",
            renewal_buffer_seconds=300,
        )

        manager = DynamicCredentialManager(vault, config)

        # Register callback for connection pool updates
        manager.on_credential_change(update_connection_pool)

        # Start credential management
        await manager.start()

        # Get current credentials
        username, password = await manager.get_credentials()

        # Gracefully stop (revokes lease)
        await manager.stop()
        ```
    """

    def __init__(
        self,
        vault_client: VaultClient,
        config: CredentialManagerConfig | None = None,
    ):
        """
        Initialize credential manager.

        Args:
            vault_client: Authenticated Vault client.
            config: Manager configuration.
        """
        self.vault = vault_client
        self.config = config or CredentialManagerConfig()
        self._credentials: DatabaseCredentials | None = None
        self._renewal_task: asyncio.Task | None = None
        self._on_credential_change: list[Callable[[str, str], Any]] = []
        self._running = False
        self._lock = asyncio.Lock()

    def on_credential_change(
        self,
        callback: Callable[[str, str], Any],
    ) -> None:
        """
        Register callback for credential changes.

        Callback is called with (username, password) when credentials
        are rotated. Use this to update connection pools.

        Args:
            callback: Function to call on credential change.
        """
        self._on_credential_change.append(callback)

    async def start(self) -> None:
        """
        Start credential management.

        Fetches initial credentials and schedules automatic renewal.

        Raises:
            CredentialManagerError: If initial credential fetch fails.
        """
        if self._running:
            logger.warning("Credential manager already running")
            return

        logger.info(
            "Starting credential manager",
            extra={
                "database": self.config.database,
                "role": self.config.role,
            },
        )

        await self._fetch_credentials()
        self._running = True
        self._schedule_renewal()

    async def stop(self) -> None:
        """
        Stop credential management and revoke lease.

        Gracefully stops renewal and revokes the current lease.
        """
        if not self._running:
            return

        logger.info("Stopping credential manager")
        self._running = False

        if self._renewal_task:
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                pass
            self._renewal_task = None

        if self._credentials:
            try:
                await self._revoke_lease()
            except Exception as e:
                logger.error(
                    "Failed to revoke lease on shutdown",
                    extra={"error": str(e)},
                )

    async def get_credentials(self) -> tuple[str, str]:
        """
        Get current database credentials.

        Returns:
            Tuple of (username, password).

        Raises:
            CredentialManagerError: If credentials not available.
        """
        if not self._credentials:
            async with self._lock:
                if not self._credentials:
                    await self._fetch_credentials()

        return self._credentials.username, self._credentials.password

    async def _fetch_credentials(self) -> None:
        """Fetch new credentials from Vault."""
        try:
            creds = await self.vault.get_database_credentials(
                role=self.config.role,
            )

            loop = asyncio.get_event_loop()
            self._credentials = DatabaseCredentials(
                username=creds["username"],
                password=creds["password"],
                lease_id=creds["lease_id"],
                lease_duration=creds["lease_duration"],
                expires_at=loop.time() + creds["lease_duration"],
            )

            logger.info(
                "Fetched database credentials",
                extra={
                    "database": self.config.database,
                    "role": self.config.role,
                    "lease_duration": creds["lease_duration"],
                    "username": creds["username"],  # Safe to log username
                },
            )

            # Notify listeners
            await self._notify_credential_change()

        except VaultError as e:
            raise CredentialManagerError(
                f"Failed to fetch database credentials: {str(e)}",
                {
                    "database": self.config.database,
                    "role": self.config.role,
                },
            ) from e

    async def _notify_credential_change(self) -> None:
        """Notify all registered callbacks of credential change."""
        if not self._credentials:
            return

        for callback in self._on_credential_change:
            try:
                result = callback(
                    self._credentials.username,
                    self._credentials.password,
                )
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(
                    "Credential change callback failed",
                    extra={"error": str(e)},
                )

    def _schedule_renewal(self) -> None:
        """Schedule credential renewal before expiry."""
        if not self._credentials or not self._running:
            return

        loop = asyncio.get_event_loop()
        delay = self._credentials.expires_at - loop.time() - self.config.renewal_buffer_seconds

        if delay > 0:
            self._renewal_task = asyncio.create_task(
                self._renewal_loop(delay),
            )
            logger.debug(
                "Scheduled credential renewal",
                extra={"delay_seconds": delay},
            )
        else:
            # Already past renewal time, renew immediately
            self._renewal_task = asyncio.create_task(
                self._renewal_loop(0),
            )

    async def _renewal_loop(self, initial_delay: float) -> None:
        """Loop to renew credentials periodically."""
        await asyncio.sleep(initial_delay)

        while self._running:
            success = await self._try_renew_with_retry()

            if not success:
                # Renewal failed after retries, fetch new credentials
                logger.warning(
                    "Lease renewal failed, fetching new credentials",
                )
                try:
                    await self._fetch_credentials()
                    self._schedule_renewal()
                except Exception as e:
                    logger.error(
                        "Failed to fetch new credentials",
                        extra={"error": str(e)},
                    )
                break

            # Calculate next renewal time
            if self._credentials:
                loop = asyncio.get_event_loop()
                next_delay = (
                    self._credentials.expires_at - loop.time() - self.config.renewal_buffer_seconds
                )
                if next_delay > 0:
                    await asyncio.sleep(next_delay)
                else:
                    # Immediate renewal needed
                    continue

    async def _try_renew_with_retry(self) -> bool:
        """Try to renew lease with retries."""
        for attempt in range(self.config.max_renewal_retries):
            try:
                await self._renew_lease()
                return True
            except Exception as e:
                logger.warning(
                    "Lease renewal attempt failed",
                    extra={
                        "attempt": attempt + 1,
                        "max_retries": self.config.max_renewal_retries,
                        "error": str(e),
                    },
                )
                if attempt < self.config.max_renewal_retries - 1:
                    backoff = self.config.retry_backoff_base * (2**attempt)
                    await asyncio.sleep(backoff)

        return False

    async def _renew_lease(self) -> None:
        """Renew the current lease."""
        if not self._credentials:
            raise CredentialManagerError("No credentials to renew")

        try:
            # Vault client doesn't have renew_lease exposed, we need to add it
            # For now, we'll use the hvac client directly
            client = self.vault._get_client()
            response = client.sys.renew_lease(
                lease_id=self._credentials.lease_id,
            )

            new_duration = response["lease_duration"]
            loop = asyncio.get_event_loop()
            self._credentials.lease_duration = new_duration
            self._credentials.expires_at = loop.time() + new_duration

            logger.info(
                "Renewed database credential lease",
                extra={
                    "lease_id": self._credentials.lease_id,
                    "new_duration": new_duration,
                },
            )

        except Exception as e:
            raise CredentialManagerError(
                f"Failed to renew lease: {str(e)}",
                {"lease_id": self._credentials.lease_id},
            ) from e

    async def _revoke_lease(self) -> None:
        """Revoke the current lease."""
        if not self._credentials:
            return

        try:
            client = self.vault._get_client()
            client.sys.revoke_lease(lease_id=self._credentials.lease_id)

            logger.info(
                "Revoked database credential lease",
                extra={"lease_id": self._credentials.lease_id},
            )

            self._credentials = None

        except Exception as e:
            logger.error(
                "Failed to revoke lease",
                extra={
                    "lease_id": self._credentials.lease_id if self._credentials else None,
                    "error": str(e),
                },
            )

    @property
    def credentials(self) -> DatabaseCredentials | None:
        """Get current credentials object (for inspection)."""
        return self._credentials

    @property
    def is_running(self) -> bool:
        """Check if credential manager is running."""
        return self._running

    async def health_check(self) -> dict[str, Any]:
        """
        Check credential manager health.

        Returns:
            Health status dict.
        """
        if not self._running:
            return {
                "healthy": False,
                "running": False,
                "error": "Credential manager not running",
            }

        if not self._credentials:
            return {
                "healthy": False,
                "running": True,
                "error": "No credentials available",
            }

        loop = asyncio.get_event_loop()
        time_until_expiry = self._credentials.expires_at - loop.time()

        return {
            "healthy": time_until_expiry > 0,
            "running": True,
            "database": self.config.database,
            "role": self.config.role,
            "username": self._credentials.username,
            "lease_duration": self._credentials.lease_duration,
            "time_until_expiry_seconds": max(0, time_until_expiry),
            "renewal_buffer_seconds": self.config.renewal_buffer_seconds,
        }
