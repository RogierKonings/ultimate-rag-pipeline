# US-5.4: Model Configuration

> **Story ID:** US-5.4  
> **Epic:** LLM Serving Layer  
> **Priority:** High  
> **Estimated Effort:** 2 days  
> **Dependencies:** US-5.1 (vLLM Deployment), US-5.2 (Embedding Service), US-5.3 (Reranker Service)

## User Story

**As a** ML engineer  
**I want** configurable model settings  
**So that** I can tune inference parameters and switch models without restart

## Context

The Model Configuration system provides centralized management of model settings across all LLM serving components. It enables dynamic parameter tuning (temperature, top_p, max_tokens), hot-swapping models without service restart, A/B testing between model versions, and versioned configuration management. This allows ML engineers to experiment with different models and parameters without infrastructure changes.

Key features:
- Centralized configuration management
- Dynamic parameter updates via API
- A/B model routing for experiments
- Configuration versioning and rollback
- YAML-based configuration files
- Kubernetes ConfigMap integration

## Technical Requirements

### Directory Structure

```
llm-serving/
└── config/
    ├── __init__.py
    ├── manager.py               # Configuration manager
    ├── models.py                # Configuration data models
    ├── storage.py               # Configuration storage backends
    ├── router.py                # A/B routing logic
    ├── watcher.py               # ConfigMap/file watcher
    ├── api/
    │   ├── __init__.py
    │   ├── main.py              # FastAPI config API
    │   └── routes.py            # API routes
    ├── defaults/
    │   ├── llm.yaml             # Default LLM configs
    │   ├── embedding.yaml       # Default embedding configs
    │   └── reranker.yaml        # Default reranker configs
    └── k8s/
        └── configmap.yaml       # Kubernetes ConfigMap
```

### Data Models

```python
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal, Any
from enum import Enum
from datetime import datetime
from uuid import UUID, uuid4
import yaml

class ModelType(str, Enum):
    LLM = "llm"
    EMBEDDING = "embedding"
    RERANKER = "reranker"

class RoutingStrategy(str, Enum):
    SINGLE = "single"          # Always use primary model
    RANDOM = "random"          # Random selection with weights
    ROUND_ROBIN = "round_robin"  # Alternate between models
    HEADER_BASED = "header_based"  # Based on request header
    USER_BASED = "user_based"  # Based on user ID hash

class LLMGenerationConfig(BaseModel):
    """Generation parameters for LLM inference."""
    
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    top_k: int = Field(default=50, ge=1)
    max_tokens: int = Field(default=1024, ge=1, le=32768)
    
    # Penalty settings
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    repetition_penalty: float = Field(default=1.0, ge=0.0, le=2.0)
    
    # Stop sequences
    stop_sequences: list[str] = []
    
    # Streaming
    stream: bool = True
    
    def to_vllm_params(self) -> dict:
        """Convert to vLLM SamplingParams format."""
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "max_tokens": self.max_tokens,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "repetition_penalty": self.repetition_penalty,
            "stop": self.stop_sequences if self.stop_sequences else None
        }

class EmbeddingConfig(BaseModel):
    """Configuration for embedding model."""
    
    normalize: bool = True
    batch_size: int = Field(default=32, ge=1, le=256)
    max_sequence_length: int = Field(default=512, ge=1, le=8192)
    use_fp16: bool = True
    prefix_query: str = "query: "
    prefix_passage: str = "passage: "

class RerankerConfig(BaseModel):
    """Configuration for reranker model."""
    
    max_pairs_per_request: int = Field(default=100, ge=1, le=1000)
    max_sequence_length: int = Field(default=512, ge=1, le=2048)
    batch_size: int = Field(default=32, ge=1, le=128)
    normalize_scores: bool = False
    use_fp16: bool = True

class ModelEndpoint(BaseModel):
    """Configuration for a model endpoint."""
    
    name: str
    type: ModelType
    model_id: str  # HuggingFace model ID or path
    endpoint_url: str
    
    # Version tracking
    version: str = "1.0.0"
    revision: Optional[str] = None  # Git commit or model revision
    
    # Enabled state
    enabled: bool = True
    
    # Type-specific configuration
    llm_config: Optional[LLMGenerationConfig] = None
    embedding_config: Optional[EmbeddingConfig] = None
    reranker_config: Optional[RerankerConfig] = None
    
    # Performance settings
    timeout_seconds: float = 60.0
    max_retries: int = 3
    
    # Metadata
    description: Optional[str] = None
    tags: list[str] = []

class ABTestConfig(BaseModel):
    """A/B test configuration for model experiments."""
    
    id: UUID = Field(default_factory=uuid4)
    name: str
    description: Optional[str] = None
    
    # Models in the test
    model_a: str  # Model endpoint name
    model_b: str  # Model endpoint name
    
    # Traffic split (0.0 to 1.0 for model_a, rest goes to model_b)
    traffic_split: float = Field(default=0.5, ge=0.0, le=1.0)
    
    # Routing strategy
    strategy: RoutingStrategy = RoutingStrategy.RANDOM
    
    # User segments for USER_BASED strategy
    model_a_user_segments: list[str] = []
    
    # Header name for HEADER_BASED strategy
    routing_header: str = "X-Model-Version"
    
    # Time bounds
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    # Status
    active: bool = True
    
    def is_active(self) -> bool:
        """Check if test is currently active."""
        if not self.active:
            return False
        
        now = datetime.utcnow()
        if self.start_time and now < self.start_time:
            return False
        if self.end_time and now > self.end_time:
            return False
        
        return True

class ConfigVersion(BaseModel):
    """Versioned configuration snapshot."""
    
    id: UUID = Field(default_factory=uuid4)
    version: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Configuration content
    endpoints: dict[str, ModelEndpoint]
    ab_tests: list[ABTestConfig] = []
    
    # Metadata
    description: Optional[str] = None
    created_by: Optional[str] = None
    
    # Rollback reference
    previous_version_id: Optional[UUID] = None

class ModelConfigurationState(BaseModel):
    """Current state of model configuration."""
    
    # Current version
    current_version: int = 1
    
    # Model endpoints
    endpoints: dict[str, ModelEndpoint] = {}
    
    # Active A/B tests
    ab_tests: list[ABTestConfig] = []
    
    # Version history
    version_history: list[ConfigVersion] = []
    max_history_versions: int = 10
    
    def get_endpoint(self, name: str) -> Optional[ModelEndpoint]:
        """Get endpoint by name."""
        return self.endpoints.get(name)
    
    def get_active_tests(self) -> list[ABTestConfig]:
        """Get currently active A/B tests."""
        return [t for t in self.ab_tests if t.is_active()]
```

### Configuration Manager

```python
import asyncio
import yaml
import json
from pathlib import Path
from typing import Optional, Callable
import hashlib
from datetime import datetime
import logging

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
        config_path: Optional[Path] = None,
        watch_interval: float = 5.0
    ):
        self.config_path = config_path
        self.watch_interval = watch_interval
        
        self._state = ModelConfigurationState()
        self._callbacks: list[Callable[[ModelConfigurationState], None]] = []
        self._lock = asyncio.Lock()
        self._watcher_task: Optional[asyncio.Task] = None
        self._last_config_hash: Optional[str] = None
    
    async def load_from_file(self, path: Path):
        """Load configuration from YAML file."""
        logger.info(f"Loading configuration from {path}")
        
        async with self._lock:
            with open(path, "r") as f:
                data = yaml.safe_load(f)
            
            await self._apply_config(data)
    
    async def load_from_dict(self, data: dict):
        """Load configuration from dictionary."""
        async with self._lock:
            await self._apply_config(data)
    
    async def _apply_config(self, data: dict):
        """Apply configuration data to state."""
        # Parse endpoints
        endpoints = {}
        for name, endpoint_data in data.get("endpoints", {}).items():
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
                self._state.version_history[-1].id
                if self._state.version_history else None
            )
        )
        
        # Update state
        self._state.endpoints = endpoints
        self._state.ab_tests = ab_tests
        self._state.current_version = new_version.version
        
        # Add to history (with limit)
        self._state.version_history.append(new_version)
        if len(self._state.version_history) > self._state.max_history_versions:
            self._state.version_history = self._state.version_history[-self._state.max_history_versions:]
        
        logger.info(f"Configuration updated to version {new_version.version}")
        
        # Notify callbacks
        await self._notify_callbacks()
    
    async def update_endpoint(self, name: str, updates: dict):
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
            if "llm_config" in updates and endpoint.type == ModelType.LLM:
                if endpoint.llm_config:
                    for k, v in updates["llm_config"].items():
                        if hasattr(endpoint.llm_config, k):
                            setattr(endpoint.llm_config, k, v)
            
            logger.info(f"Updated endpoint {name}")
            await self._notify_callbacks()
    
    async def update_generation_params(
        self,
        endpoint_name: str,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ):
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
    
    async def create_ab_test(self, test: ABTestConfig):
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
    
    async def update_ab_test(self, test_id: UUID, updates: dict):
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
    
    async def deactivate_ab_test(self, test_id: UUID):
        """Deactivate an A/B test."""
        await self.update_ab_test(test_id, {"active": False})
    
    async def rollback(self, version: Optional[int] = None):
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
    
    def get_endpoint(self, name: str) -> Optional[ModelEndpoint]:
        """Get endpoint configuration."""
        return self._state.get_endpoint(name)
    
    def get_all_endpoints(self, type_filter: Optional[ModelType] = None) -> list[ModelEndpoint]:
        """Get all endpoints, optionally filtered by type."""
        endpoints = list(self._state.endpoints.values())
        if type_filter:
            endpoints = [e for e in endpoints if e.type == type_filter]
        return endpoints
    
    def get_active_ab_tests(self) -> list[ABTestConfig]:
        """Get active A/B tests."""
        return self._state.get_active_tests()
    
    def register_callback(self, callback: Callable[[ModelConfigurationState], None]):
        """Register callback for configuration changes."""
        self._callbacks.append(callback)
    
    async def _notify_callbacks(self):
        """Notify all registered callbacks."""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(self._state)
                else:
                    callback(self._state)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    async def start_watching(self):
        """Start watching configuration file for changes."""
        if not self.config_path:
            logger.warning("No config path set, watching disabled")
            return
        
        self._watcher_task = asyncio.create_task(self._watch_loop())
        logger.info(f"Started watching {self.config_path}")
    
    async def stop_watching(self):
        """Stop watching configuration file."""
        if self._watcher_task:
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass
    
    async def _watch_loop(self):
        """Watch loop for configuration changes."""
        while True:
            try:
                await asyncio.sleep(self.watch_interval)
                
                if self.config_path and self.config_path.exists():
                    with open(self.config_path, "r") as f:
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
                name: endpoint.model_dump()
                for name, endpoint in self._state.endpoints.items()
            },
            "ab_tests": [
                test.model_dump() for test in self._state.ab_tests
            ]
        }
        return yaml.dump(data, default_flow_style=False)
```

### A/B Test Router

```python
import random
import hashlib
from typing import Optional
from fastapi import Request

class ABRouter:
    """
    Routes requests to different models based on A/B test configuration.
    """
    
    def __init__(self, config_manager: ConfigurationManager):
        self.config_manager = config_manager
    
    def route(
        self,
        model_type: ModelType,
        request: Optional[Request] = None,
        user_id: Optional[str] = None
    ) -> str:
        """
        Determine which model endpoint to use.
        
        Args:
            model_type: Type of model (LLM, embedding, reranker)
            request: Optional FastAPI request for header-based routing
            user_id: Optional user ID for user-based routing
        
        Returns:
            Name of the model endpoint to use
        """
        # Get active tests for this model type
        active_tests = self._get_tests_for_type(model_type)
        
        if not active_tests:
            # No active tests, return default endpoint
            return self._get_default_endpoint(model_type)
        
        # Use first active test (could be extended to support multiple)
        test = active_tests[0]
        
        return self._select_model(test, request, user_id)
    
    def _get_tests_for_type(self, model_type: ModelType) -> list[ABTestConfig]:
        """Get active A/B tests that apply to the given model type."""
        tests = []
        
        for test in self.config_manager.get_active_ab_tests():
            endpoint_a = self.config_manager.get_endpoint(test.model_a)
            endpoint_b = self.config_manager.get_endpoint(test.model_b)
            
            if endpoint_a and endpoint_a.type == model_type:
                tests.append(test)
            elif endpoint_b and endpoint_b.type == model_type:
                tests.append(test)
        
        return tests
    
    def _get_default_endpoint(self, model_type: ModelType) -> str:
        """Get default endpoint for a model type."""
        endpoints = self.config_manager.get_all_endpoints(model_type)
        enabled_endpoints = [e for e in endpoints if e.enabled]
        
        if not enabled_endpoints:
            raise ValueError(f"No enabled {model_type.value} endpoints found")
        
        return enabled_endpoints[0].name
    
    def _select_model(
        self,
        test: ABTestConfig,
        request: Optional[Request],
        user_id: Optional[str]
    ) -> str:
        """Select model based on test strategy."""
        
        if test.strategy == RoutingStrategy.SINGLE:
            return test.model_a
        
        elif test.strategy == RoutingStrategy.RANDOM:
            return test.model_a if random.random() < test.traffic_split else test.model_b
        
        elif test.strategy == RoutingStrategy.ROUND_ROBIN:
            # Simple implementation using timestamp
            import time
            return test.model_a if int(time.time()) % 2 == 0 else test.model_b
        
        elif test.strategy == RoutingStrategy.HEADER_BASED:
            if request:
                header_value = request.headers.get(test.routing_header, "a")
                return test.model_a if header_value.lower() == "a" else test.model_b
            return test.model_a
        
        elif test.strategy == RoutingStrategy.USER_BASED:
            if user_id:
                # Hash user ID for consistent routing
                user_hash = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
                return test.model_a if (user_hash % 100) < (test.traffic_split * 100) else test.model_b
            
            # Check user segments
            # (simplified - would need user context in production)
            return test.model_a
        
        return test.model_a
    
    def get_selected_model_info(
        self,
        model_type: ModelType,
        request: Optional[Request] = None,
        user_id: Optional[str] = None
    ) -> dict:
        """Get information about which model was selected and why."""
        model_name = self.route(model_type, request, user_id)
        endpoint = self.config_manager.get_endpoint(model_name)
        
        # Find applicable test
        active_tests = self._get_tests_for_type(model_type)
        test_info = None
        if active_tests:
            test = active_tests[0]
            test_info = {
                "test_id": str(test.id),
                "test_name": test.name,
                "strategy": test.strategy.value,
                "traffic_split": test.traffic_split
            }
        
        return {
            "model_name": model_name,
            "model_id": endpoint.model_id if endpoint else None,
            "endpoint_url": endpoint.endpoint_url if endpoint else None,
            "ab_test": test_info
        }
```

### FastAPI Configuration API

```python
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

class UpdateEndpointRequest(BaseModel):
    enabled: Optional[bool] = None
    timeout_seconds: Optional[float] = None
    max_retries: Optional[int] = None
    llm_config: Optional[dict] = None
    embedding_config: Optional[dict] = None
    reranker_config: Optional[dict] = None

class UpdateGenerationParamsRequest(BaseModel):
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    max_tokens: Optional[int] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    stop_sequences: Optional[list[str]] = None

class CreateABTestRequest(BaseModel):
    name: str
    description: Optional[str] = None
    model_a: str
    model_b: str
    traffic_split: float = 0.5
    strategy: RoutingStrategy = RoutingStrategy.RANDOM
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

class UpdateABTestRequest(BaseModel):
    traffic_split: Optional[float] = None
    active: Optional[bool] = None
    end_time: Optional[datetime] = None

# Global config manager
config_manager: Optional[ConfigurationManager] = None

def get_config_manager() -> ConfigurationManager:
    if config_manager is None:
        raise HTTPException(status_code=503, detail="Configuration manager not initialized")
    return config_manager

app = FastAPI(title="Model Configuration API", version="1.0.0")

@app.get("/config")
async def get_configuration(
    manager: ConfigurationManager = Depends(get_config_manager)
):
    """Get current configuration state."""
    state = manager.get_state()
    return {
        "version": state.current_version,
        "endpoints": {
            name: endpoint.model_dump()
            for name, endpoint in state.endpoints.items()
        },
        "ab_tests": [test.model_dump() for test in state.ab_tests],
        "active_ab_tests": [test.model_dump() for test in state.get_active_tests()]
    }

@app.get("/config/endpoints")
async def list_endpoints(
    type: Optional[ModelType] = None,
    manager: ConfigurationManager = Depends(get_config_manager)
):
    """List all model endpoints."""
    endpoints = manager.get_all_endpoints(type)
    return {
        "endpoints": [e.model_dump() for e in endpoints]
    }

@app.get("/config/endpoints/{name}")
async def get_endpoint(
    name: str,
    manager: ConfigurationManager = Depends(get_config_manager)
):
    """Get a specific endpoint configuration."""
    endpoint = manager.get_endpoint(name)
    if not endpoint:
        raise HTTPException(status_code=404, detail=f"Endpoint {name} not found")
    return endpoint.model_dump()

@app.patch("/config/endpoints/{name}")
async def update_endpoint(
    name: str,
    request: UpdateEndpointRequest,
    manager: ConfigurationManager = Depends(get_config_manager)
):
    """Update an endpoint's configuration."""
    try:
        await manager.update_endpoint(name, request.model_dump(exclude_unset=True))
        return {"status": "updated", "endpoint": name}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.patch("/config/endpoints/{name}/generation")
async def update_generation_params(
    name: str,
    request: UpdateGenerationParamsRequest,
    manager: ConfigurationManager = Depends(get_config_manager)
):
    """Update LLM generation parameters."""
    try:
        await manager.update_generation_params(
            name,
            **request.model_dump(exclude_unset=True)
        )
        return {"status": "updated", "endpoint": name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/config/ab-tests")
async def list_ab_tests(
    active_only: bool = False,
    manager: ConfigurationManager = Depends(get_config_manager)
):
    """List A/B tests."""
    if active_only:
        tests = manager.get_active_ab_tests()
    else:
        tests = manager.get_state().ab_tests
    
    return {"ab_tests": [t.model_dump() for t in tests]}

@app.post("/config/ab-tests")
async def create_ab_test(
    request: CreateABTestRequest,
    manager: ConfigurationManager = Depends(get_config_manager)
):
    """Create a new A/B test."""
    try:
        test = ABTestConfig(**request.model_dump())
        await manager.create_ab_test(test)
        return {"status": "created", "test_id": str(test.id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.patch("/config/ab-tests/{test_id}")
async def update_ab_test(
    test_id: UUID,
    request: UpdateABTestRequest,
    manager: ConfigurationManager = Depends(get_config_manager)
):
    """Update an A/B test."""
    try:
        await manager.update_ab_test(test_id, request.model_dump(exclude_unset=True))
        return {"status": "updated", "test_id": str(test_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.delete("/config/ab-tests/{test_id}")
async def deactivate_ab_test_endpoint(
    test_id: UUID,
    manager: ConfigurationManager = Depends(get_config_manager)
):
    """Deactivate an A/B test."""
    try:
        await manager.deactivate_ab_test(test_id)
        return {"status": "deactivated", "test_id": str(test_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/config/rollback")
async def rollback_configuration(
    version: Optional[int] = None,
    manager: ConfigurationManager = Depends(get_config_manager)
):
    """Rollback to a previous configuration version."""
    try:
        await manager.rollback(version)
        return {
            "status": "rolled_back",
            "current_version": manager.get_state().current_version
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/config/versions")
async def list_versions(
    manager: ConfigurationManager = Depends(get_config_manager)
):
    """List configuration version history."""
    state = manager.get_state()
    return {
        "current_version": state.current_version,
        "versions": [
            {
                "version": v.version,
                "timestamp": v.timestamp.isoformat(),
                "id": str(v.id),
                "description": v.description
            }
            for v in state.version_history
        ]
    }

@app.get("/config/export")
async def export_configuration(
    manager: ConfigurationManager = Depends(get_config_manager)
):
    """Export current configuration as YAML."""
    yaml_content = manager.export_yaml()
    return Response(
        content=yaml_content,
        media_type="text/yaml",
        headers={"Content-Disposition": "attachment; filename=config.yaml"}
    )
```

### Default Configuration YAML

```yaml
# defaults/llm.yaml
endpoints:
  llama-8b-primary:
    type: llm
    model_id: meta-llama/Llama-3.1-8B-Instruct
    endpoint_url: http://vllm-llama.llm-serving.svc.cluster.local:8000
    version: "1.0.0"
    enabled: true
    description: "Primary Llama 3.1 8B model"
    llm_config:
      temperature: 0.7
      top_p: 1.0
      top_k: 50
      max_tokens: 1024
      frequency_penalty: 0.0
      presence_penalty: 0.0
      stop_sequences: []
      stream: true
    timeout_seconds: 60.0
    max_retries: 3
    tags:
      - production
      - primary

  bge-large-embedding:
    type: embedding
    model_id: BAAI/bge-large-en-v1.5
    endpoint_url: http://embedding-service.llm-serving.svc.cluster.local:8001
    version: "1.0.0"
    enabled: true
    description: "BGE Large embedding model"
    embedding_config:
      normalize: true
      batch_size: 32
      max_sequence_length: 512
      use_fp16: true
      prefix_query: "query: "
      prefix_passage: "passage: "
    timeout_seconds: 30.0
    max_retries: 3
    tags:
      - production

  bge-reranker:
    type: reranker
    model_id: BAAI/bge-reranker-v2-m3
    endpoint_url: http://reranker-service.llm-serving.svc.cluster.local:8002
    version: "1.0.0"
    enabled: true
    description: "BGE Reranker model"
    reranker_config:
      max_pairs_per_request: 100
      max_sequence_length: 512
      batch_size: 32
      normalize_scores: false
      use_fp16: true
    timeout_seconds: 30.0
    max_retries: 3
    tags:
      - production

ab_tests: []
```

## Acceptance Criteria

- [ ] Configuration loaded from YAML files
- [ ] ConfigurationManager with version tracking
- [ ] Dynamic parameter updates via API
- [ ] Temperature, top_p, max_tokens configurable
- [ ] Model endpoints switchable without restart
- [ ] A/B test creation and management
- [ ] Multiple routing strategies supported
- [ ] Configuration rollback functionality
- [ ] YAML export of current configuration
- [ ] File watching for auto-reload
- [ ] Kubernetes ConfigMap integration
- [ ] Prometheus metrics for routing decisions

## Testing Requirements

```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from pathlib import Path
import tempfile
import yaml

@pytest.fixture
def config_manager():
    return ConfigurationManager()

@pytest.fixture
def sample_config():
    return {
        "endpoints": {
            "test-llm": {
                "type": "llm",
                "model_id": "test-model",
                "endpoint_url": "http://localhost:8000",
                "llm_config": {
                    "temperature": 0.5,
                    "max_tokens": 512
                }
            }
        }
    }

@pytest.mark.asyncio
async def test_load_from_dict(config_manager, sample_config):
    """Test loading configuration from dictionary."""
    await config_manager.load_from_dict(sample_config)
    
    state = config_manager.get_state()
    assert "test-llm" in state.endpoints
    assert state.endpoints["test-llm"].llm_config.temperature == 0.5

@pytest.mark.asyncio
async def test_load_from_file(config_manager, sample_config):
    """Test loading configuration from YAML file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(sample_config, f)
        path = Path(f.name)
    
    await config_manager.load_from_file(path)
    
    assert "test-llm" in config_manager.get_state().endpoints
    
    path.unlink()

@pytest.mark.asyncio
async def test_update_endpoint(config_manager, sample_config):
    """Test updating endpoint configuration."""
    await config_manager.load_from_dict(sample_config)
    
    await config_manager.update_endpoint("test-llm", {"enabled": False})
    
    endpoint = config_manager.get_endpoint("test-llm")
    assert endpoint.enabled == False

@pytest.mark.asyncio
async def test_update_generation_params(config_manager, sample_config):
    """Test updating LLM generation parameters."""
    await config_manager.load_from_dict(sample_config)
    
    await config_manager.update_generation_params(
        "test-llm",
        temperature=0.9,
        max_tokens=2048
    )
    
    endpoint = config_manager.get_endpoint("test-llm")
    assert endpoint.llm_config.temperature == 0.9
    assert endpoint.llm_config.max_tokens == 2048

@pytest.mark.asyncio
async def test_create_ab_test(config_manager):
    """Test creating A/B test."""
    config = {
        "endpoints": {
            "model-a": {"type": "llm", "model_id": "a", "endpoint_url": "http://a"},
            "model-b": {"type": "llm", "model_id": "b", "endpoint_url": "http://b"}
        }
    }
    await config_manager.load_from_dict(config)
    
    test = ABTestConfig(
        name="test-experiment",
        model_a="model-a",
        model_b="model-b",
        traffic_split=0.5
    )
    await config_manager.create_ab_test(test)
    
    tests = config_manager.get_active_ab_tests()
    assert len(tests) == 1
    assert tests[0].name == "test-experiment"

@pytest.mark.asyncio
async def test_rollback(config_manager):
    """Test configuration rollback."""
    # Load initial config
    await config_manager.load_from_dict({
        "endpoints": {"v1": {"type": "llm", "model_id": "v1", "endpoint_url": "http://v1"}}
    })
    
    # Load updated config
    await config_manager.load_from_dict({
        "endpoints": {"v2": {"type": "llm", "model_id": "v2", "endpoint_url": "http://v2"}}
    })
    
    assert "v2" in config_manager.get_state().endpoints
    assert "v1" not in config_manager.get_state().endpoints
    
    # Rollback
    await config_manager.rollback()
    
    assert "v1" in config_manager.get_state().endpoints

@pytest.mark.asyncio
async def test_version_tracking(config_manager, sample_config):
    """Test version tracking."""
    await config_manager.load_from_dict(sample_config)
    v1 = config_manager.get_state().current_version
    
    await config_manager.load_from_dict(sample_config)
    v2 = config_manager.get_state().current_version
    
    assert v2 == v1 + 1
    assert len(config_manager.get_state().version_history) == 2

def test_ab_router_random():
    """Test random A/B routing."""
    manager = ConfigurationManager()
    
    # Mock state
    manager._state.endpoints = {
        "a": ModelEndpoint(name="a", type=ModelType.LLM, model_id="a", endpoint_url="http://a"),
        "b": ModelEndpoint(name="b", type=ModelType.LLM, model_id="b", endpoint_url="http://b")
    }
    manager._state.ab_tests = [
        ABTestConfig(
            name="test",
            model_a="a",
            model_b="b",
            traffic_split=0.5,
            strategy=RoutingStrategy.RANDOM
        )
    ]
    
    router = ABRouter(manager)
    
    # Run multiple times and check distribution
    results = {"a": 0, "b": 0}
    for _ in range(1000):
        result = router.route(ModelType.LLM)
        results[result] += 1
    
    # Should be roughly 50/50 with some tolerance
    assert 400 < results["a"] < 600
    assert 400 < results["b"] < 600

def test_ab_router_user_based():
    """Test user-based A/B routing is consistent."""
    manager = ConfigurationManager()
    
    manager._state.endpoints = {
        "a": ModelEndpoint(name="a", type=ModelType.LLM, model_id="a", endpoint_url="http://a"),
        "b": ModelEndpoint(name="b", type=ModelType.LLM, model_id="b", endpoint_url="http://b")
    }
    manager._state.ab_tests = [
        ABTestConfig(
            name="test",
            model_a="a",
            model_b="b",
            traffic_split=0.5,
            strategy=RoutingStrategy.USER_BASED
        )
    ]
    
    router = ABRouter(manager)
    
    # Same user should always get same result
    user_id = "user-123"
    result1 = router.route(ModelType.LLM, user_id=user_id)
    result2 = router.route(ModelType.LLM, user_id=user_id)
    result3 = router.route(ModelType.LLM, user_id=user_id)
    
    assert result1 == result2 == result3

def test_llm_generation_config_validation():
    """Test LLM config validation."""
    # Valid config
    config = LLMGenerationConfig(temperature=0.5, max_tokens=1024)
    assert config.temperature == 0.5
    
    # Invalid temperature
    with pytest.raises(ValueError):
        LLMGenerationConfig(temperature=3.0)
    
    # Invalid top_p
    with pytest.raises(ValueError):
        LLMGenerationConfig(top_p=1.5)

def test_export_yaml(config_manager, sample_config):
    """Test YAML export."""
    import asyncio
    asyncio.run(config_manager.load_from_dict(sample_config))
    
    yaml_content = config_manager.export_yaml()
    
    # Should be valid YAML
    parsed = yaml.safe_load(yaml_content)
    assert "endpoints" in parsed
    assert "test-llm" in parsed["endpoints"]
```

## Dependencies

```txt
# requirements.txt
pydantic>=2.5.0
pydantic-settings>=2.1.0
pyyaml>=6.0.0
fastapi>=0.104.0
uvicorn>=0.24.0
httpx>=0.25.0
watchfiles>=0.21.0
```

## Definition of Done

- [ ] ConfigurationManager implemented
- [ ] YAML configuration loading working
- [ ] Dynamic parameter updates via API
- [ ] A/B test creation and management
- [ ] All routing strategies implemented
- [ ] Version tracking with rollback
- [ ] Configuration export as YAML
- [ ] File watcher for auto-reload
- [ ] FastAPI configuration API complete
- [ ] Kubernetes ConfigMap example provided
- [ ] Prometheus metrics for routing
- [ ] >90% test coverage
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
