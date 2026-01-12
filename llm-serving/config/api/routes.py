"""
Configuration API routes.

Provides REST endpoints for managing model configuration,
A/B tests, and configuration versioning.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ..manager import ConfigurationManager
from ..models import ABTestConfig, ModelType, RoutingStrategy

router = APIRouter(prefix="/config", tags=["configuration"])


# Request/Response models
class UpdateEndpointRequest(BaseModel):
    """Request model for updating an endpoint."""

    enabled: bool | None = None
    timeout_seconds: float | None = None
    max_retries: int | None = None
    llm_config: dict | None = None
    embedding_config: dict | None = None
    reranker_config: dict | None = None


class UpdateGenerationParamsRequest(BaseModel):
    """Request model for updating LLM generation parameters."""

    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    frequency_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    stop_sequences: list[str] | None = None


class CreateABTestRequest(BaseModel):
    """Request model for creating an A/B test."""

    name: str
    description: str | None = None
    model_a: str
    model_b: str
    traffic_split: float = Field(default=0.5, ge=0.0, le=1.0)
    strategy: RoutingStrategy = RoutingStrategy.RANDOM
    start_time: datetime | None = None
    end_time: datetime | None = None


class UpdateABTestRequest(BaseModel):
    """Request model for updating an A/B test."""

    traffic_split: float | None = Field(default=None, ge=0.0, le=1.0)
    active: bool | None = None
    end_time: datetime | None = None


# Dependency placeholder - will be set by main.py
_config_manager: ConfigurationManager | None = None


def set_config_manager(manager: ConfigurationManager) -> None:
    """Set the configuration manager instance."""
    global _config_manager
    _config_manager = manager


def get_config_manager() -> ConfigurationManager:
    """Get configuration manager dependency."""
    if _config_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Configuration manager not initialized",
        )
    return _config_manager


@router.get("")
async def get_configuration(
    manager: ConfigurationManager = Depends(get_config_manager),
):
    """Get current configuration state."""
    state = manager.get_state()
    return {
        "version": state.current_version,
        "endpoints": {
            name: endpoint.model_dump(mode="json") for name, endpoint in state.endpoints.items()
        },
        "ab_tests": [test.model_dump(mode="json") for test in state.ab_tests],
        "active_ab_tests": [test.model_dump(mode="json") for test in state.get_active_tests()],
    }


@router.get("/endpoints")
async def list_endpoints(
    model_type: ModelType | None = None,
    manager: ConfigurationManager = Depends(get_config_manager),
):
    """List all model endpoints."""
    endpoints = manager.get_all_endpoints(model_type)
    return {"endpoints": [e.model_dump(mode="json") for e in endpoints]}


@router.get("/endpoints/{name}")
async def get_endpoint(
    name: str,
    manager: ConfigurationManager = Depends(get_config_manager),
):
    """Get a specific endpoint configuration."""
    endpoint = manager.get_endpoint(name)
    if not endpoint:
        raise HTTPException(status_code=404, detail=f"Endpoint {name} not found")
    return endpoint.model_dump(mode="json")


@router.patch("/endpoints/{name}")
async def update_endpoint(
    name: str,
    request: UpdateEndpointRequest,
    manager: ConfigurationManager = Depends(get_config_manager),
):
    """Update an endpoint's configuration."""
    try:
        await manager.update_endpoint(name, request.model_dump(exclude_unset=True))
        return {"status": "updated", "endpoint": name}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.patch("/endpoints/{name}/generation")
async def update_generation_params(
    name: str,
    request: UpdateGenerationParamsRequest,
    manager: ConfigurationManager = Depends(get_config_manager),
):
    """Update LLM generation parameters."""
    try:
        await manager.update_generation_params(
            name,
            **request.model_dump(exclude_unset=True),
        )
        return {"status": "updated", "endpoint": name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/ab-tests")
async def list_ab_tests(
    active_only: bool = False,
    manager: ConfigurationManager = Depends(get_config_manager),
):
    """List A/B tests."""
    tests = manager.get_active_ab_tests() if active_only else manager.get_state().ab_tests

    return {"ab_tests": [t.model_dump(mode="json") for t in tests]}


@router.post("/ab-tests")
async def create_ab_test(
    request: CreateABTestRequest,
    manager: ConfigurationManager = Depends(get_config_manager),
):
    """Create a new A/B test."""
    try:
        test = ABTestConfig(**request.model_dump())
        await manager.create_ab_test(test)
        return {"status": "created", "test_id": str(test.id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch("/ab-tests/{test_id}")
async def update_ab_test(
    test_id: UUID,
    request: UpdateABTestRequest,
    manager: ConfigurationManager = Depends(get_config_manager),
):
    """Update an A/B test."""
    try:
        await manager.update_ab_test(test_id, request.model_dump(exclude_unset=True))
        return {"status": "updated", "test_id": str(test_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/ab-tests/{test_id}")
async def deactivate_ab_test_endpoint(
    test_id: UUID,
    manager: ConfigurationManager = Depends(get_config_manager),
):
    """Deactivate an A/B test."""
    try:
        await manager.deactivate_ab_test(test_id)
        return {"status": "deactivated", "test_id": str(test_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/rollback")
async def rollback_configuration(
    version: int | None = None,
    manager: ConfigurationManager = Depends(get_config_manager),
):
    """Rollback to a previous configuration version."""
    try:
        await manager.rollback(version)
        return {
            "status": "rolled_back",
            "current_version": manager.get_state().current_version,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/versions")
async def list_versions(
    manager: ConfigurationManager = Depends(get_config_manager),
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
                "description": v.description,
            }
            for v in state.version_history
        ],
    }


@router.get("/export")
async def export_configuration(
    manager: ConfigurationManager = Depends(get_config_manager),
):
    """Export current configuration as YAML."""
    yaml_content = manager.export_yaml()
    return Response(
        content=yaml_content,
        media_type="text/yaml",
        headers={"Content-Disposition": "attachment; filename=config.yaml"},
    )
