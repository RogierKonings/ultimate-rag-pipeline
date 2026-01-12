"""
Configuration manager for LLM Serving Layer.

Provides centralized configuration management with:
- YAML/ConfigMap loading
- Dynamic parameter updates
- Version tracking and rollback
- Change notifications
"""

import asyncio
import contextlib
import hashlib
import logging
from collections.abc import Callable
from pathlib import Path

import yaml

from .models import (
    ABTestConfig,
    ConfigVersion,
    LLMGenerationConfig,
    ModelConfigurationState,
    ModelEndpoint,
    ModelType,
)

logger = logging.getLogger(__name__)


class ConfigurationManager:
    """
    Centralized configuration management for LLM serving.

    Features:
    - Load configuration from YAML files or ConfigMaps
    - Dynamic updates without restart
    - Version tracking and rollback
    - A/B test routing
    - Change notifications
    """

    def __init__(
        self,
        config_path: Path | None = None,
        watch_interval: float = 5.0,
    ):
        """
        Initialize configuration manager.

        Args:
            config_path: Path to YAML configuration file
            watch_interval: Interval in seconds for file watching
        """
        self.config_path = config_path
        self.watch_interval = watch_interval

        self._state = ModelConfigurationState()
        self._callbacks: list[Callable[[ModelConfigurationState], None]] = []
        self._lock = asyncio.Lock()
        self._watcher_task: asyncio.Task | None = None
        self._last_config_hash: str | None = None

    async def load_from_file(self, path: Path) -> None:
        """Load configuration from YAML file."""
        logger.info(f"Loading configuration from {path}")

        async with self._lock:
            with Path(path).open() as f:
                data = yaml.safe_load(f)

            await self._apply_config(data)

    async def load_from_dict(self, data: dict) -> None:
        """Load configuration from dictionary."""
        async with self._lock:
            await self._apply_config(data)

    async def _apply_config(self, data: dict) -> None:
        """Apply configuration data to state."""
        # Parse endpoints
        endpoints = {}
        for name, endpoint_data in data.get("endpoints", {}).items():
            # Handle nested config objects
            if "llm_config" in endpoint_data and isinstance(
                endpoint_data["llm_config"],
                dict,
            ):
                endpoint_data["llm_config"] = LLMGenerationConfig(
                    **endpoint_data["llm_config"],
                )

            endpoint = ModelEndpoint(name=name, **endpoint_data)
            endpoints[name] = endpoint

        # Parse A/B tests
        ab_tests = []
        for test_data in data.get("ab_tests", []):
            test = ABTestConfig(**test_data)
            ab_tests.append(test)

        # Create new version
        new_version = ConfigVersion(
            version=self._state.current_version + 1,
            endpoints=endpoints,
            ab_tests=ab_tests,
            previous_version_id=(
                self._state.version_history[-1].id if self._state.version_history else None
            ),
        )

        # Update state
        self._state.endpoints = endpoints
        self._state.ab_tests = ab_tests
        self._state.current_version = new_version.version

        # Add to history (with limit)
        self._state.version_history.append(new_version)
        if len(self._state.version_history) > self._state.max_history_versions:
            self._state.version_history = self._state.version_history[
                -self._state.max_history_versions :
            ]

        logger.info(f"Configuration updated to version {new_version.version}")

        # Notify callbacks
        await self._notify_callbacks()

    async def update_endpoint(self, name: str, updates: dict) -> None:
        """Update a single endpoint's configuration."""
        async with self._lock:
            if name not in self._state.endpoints:
                raise ValueError(f"Endpoint {name} not found")

            endpoint = self._state.endpoints[name]

            # Apply updates
            for key, value in updates.items():
                if hasattr(endpoint, key):
                    setattr(endpoint, key, value)

            # Update LLM-specific config
            if "llm_config" in updates and endpoint.type == ModelType.LLM and endpoint.llm_config:
                for k, v in updates["llm_config"].items():
                    if hasattr(endpoint.llm_config, k):
                        setattr(endpoint.llm_config, k, v)

            logger.info(f"Updated endpoint {name}")
            await self._notify_callbacks()

    async def update_generation_params(
        self,
        endpoint_name: str,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> None:
        """Update LLM generation parameters dynamically."""
        async with self._lock:
            endpoint = self._state.endpoints.get(endpoint_name)
            if not endpoint:
                raise ValueError(f"Endpoint {endpoint_name} not found")

            if endpoint.type != ModelType.LLM:
                raise ValueError(f"Endpoint {endpoint_name} is not an LLM")

            if not endpoint.llm_config:
                endpoint.llm_config = LLMGenerationConfig()

            if temperature is not None:
                endpoint.llm_config.temperature = temperature
            if top_p is not None:
                endpoint.llm_config.top_p = top_p
            if max_tokens is not None:
                endpoint.llm_config.max_tokens = max_tokens

            for key, value in kwargs.items():
                if hasattr(endpoint.llm_config, key):
                    setattr(endpoint.llm_config, key, value)

            logger.info(f"Updated generation params for {endpoint_name}")

    async def create_ab_test(self, test: ABTestConfig) -> None:
        """Create a new A/B test."""
        async with self._lock:
            # Validate models exist
            if test.model_a not in self._state.endpoints:
                raise ValueError(f"Model A ({test.model_a}) not found")
            if test.model_b not in self._state.endpoints:
                raise ValueError(f"Model B ({test.model_b}) not found")

            self._state.ab_tests.append(test)
            logger.info(f"Created A/B test: {test.name}")
            await self._notify_callbacks()

    async def update_ab_test(self, test_id, updates: dict) -> None:
        """Update an existing A/B test."""
        async with self._lock:
            for test in self._state.ab_tests:
                if test.id == test_id:
                    for key, value in updates.items():
                        if hasattr(test, key):
                            setattr(test, key, value)
                    logger.info(f"Updated A/B test: {test.name}")
                    await self._notify_callbacks()
                    return

            raise ValueError(f"A/B test {test_id} not found")

    async def deactivate_ab_test(self, test_id) -> None:
        """Deactivate an A/B test."""
        await self.update_ab_test(test_id, {"active": False})

    async def rollback(self, version: int | None = None) -> None:
        """Rollback to a previous configuration version."""
        async with self._lock:
            if not self._state.version_history:
                raise ValueError("No version history available")

            if version is None:
                # Rollback to previous version
                if len(self._state.version_history) < 2:
                    raise ValueError("No previous version to rollback to")
                target = self._state.version_history[-2]
            else:
                # Find specific version
                target = None
                for v in self._state.version_history:
                    if v.version == version:
                        target = v
                        break

                if not target:
                    raise ValueError(f"Version {version} not found")

            # Apply rolled-back config
            self._state.endpoints = target.endpoints.copy()
            self._state.ab_tests = target.ab_tests.copy()
            self._state.current_version += 1

            logger.info(f"Rolled back to version {target.version}")
            await self._notify_callbacks()

    def get_state(self) -> ModelConfigurationState:
        """Get current configuration state."""
        return self._state

    def get_endpoint(self, name: str) -> ModelEndpoint | None:
        """Get endpoint configuration."""
        return self._state.get_endpoint(name)

    def get_all_endpoints(
        self,
        type_filter: ModelType | None = None,
    ) -> list[ModelEndpoint]:
        """Get all endpoints, optionally filtered by type."""
        endpoints = list(self._state.endpoints.values())
        if type_filter:
            endpoints = [e for e in endpoints if e.type == type_filter]
        return endpoints

    def get_active_ab_tests(self) -> list[ABTestConfig]:
        """Get active A/B tests."""
        return self._state.get_active_tests()

    def register_callback(
        self,
        callback: Callable[[ModelConfigurationState], None],
    ) -> None:
        """Register callback for configuration changes."""
        self._callbacks.append(callback)

    async def _notify_callbacks(self) -> None:
        """Notify all registered callbacks."""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(self._state)
                else:
                    callback(self._state)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    async def start_watching(self) -> None:
        """Start watching configuration file for changes."""
        if not self.config_path:
            logger.warning("No config path set, watching disabled")
            return

        self._watcher_task = asyncio.create_task(self._watch_loop())
        logger.info(f"Started watching {self.config_path}")

    async def stop_watching(self) -> None:
        """Stop watching configuration file."""
        if self._watcher_task:
            self._watcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watcher_task

    async def _watch_loop(self) -> None:
        """Watch loop for configuration changes."""
        while True:
            try:
                await asyncio.sleep(self.watch_interval)

                if self.config_path and self.config_path.exists():
                    with self.config_path.open() as f:
                        content = f.read()

                    content_hash = hashlib.md5(content.encode()).hexdigest()

                    if content_hash != self._last_config_hash:
                        logger.info("Configuration file changed, reloading...")
                        self._last_config_hash = content_hash
                        await self.load_from_file(self.config_path)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Watch loop error: {e}")

    def export_yaml(self) -> str:
        """Export current configuration as YAML."""
        data = {
            "version": self._state.current_version,
            "endpoints": {
                name: endpoint.model_dump(mode="json")
                for name, endpoint in self._state.endpoints.items()
            },
            "ab_tests": [test.model_dump(mode="json") for test in self._state.ab_tests],
        }
        return yaml.dump(data, default_flow_style=False, sort_keys=False)
