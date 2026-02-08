#!/usr/bin/env python3
"""Extract JSON Schema from orchestrator Pydantic models.

This script imports the Pydantic response/request models directly (without
starting the full FastAPI application) and exports their JSON Schema
representations. This avoids needing database connections or other
infrastructure to generate the API contract.

Usage:
    python scripts/extract-api-schemas.py [--output-dir DIR]

The output is a single JSON file containing all model schemas, suitable
for conversion to TypeScript types.
"""

import argparse
import importlib.util
import json
import sys
import types
from pathlib import Path

ORCHESTRATOR_DIR = Path(__file__).resolve().parent.parent / "services" / "orchestrator"
MODELS_DIR = ORCHESTRATOR_DIR / "api" / "models"


def _load_module_from_file(name: str, filepath: Path) -> types.ModuleType:
    """Load a Python module from a file path without triggering parent __init__.py."""
    spec = importlib.util.spec_from_file_location(name, filepath)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {filepath}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract JSON Schema from Pydantic models")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "frontend" / "src" / "lib" / "api",
        help="Directory to write the schema file to",
    )
    args = parser.parse_args()

    # Load model modules directly from their files, bypassing the api/__init__.py
    # which imports the full FastAPI app and its heavy dependencies.
    responses_mod = _load_module_from_file(
        "_api_models_responses", MODELS_DIR / "responses.py"
    )
    requests_mod = _load_module_from_file(
        "_api_models_requests", MODELS_DIR / "requests.py"
    )
    usage_mod = _load_module_from_file(
        "_api_models_usage", MODELS_DIR / "usage.py"
    )

    # All models to export, grouped by category for documentation.
    MODELS = {
        # Responses
        "QueryResponse": responses_mod.QueryResponse,
        "SourceDocument": responses_mod.SourceDocument,
        "UsageInfo": responses_mod.UsageInfo,
        "VerificationInfo": responses_mod.VerificationInfo,
        "SessionResponse": responses_mod.SessionResponse,
        "SessionInfo": responses_mod.SessionInfo,
        "HistoryResponse": responses_mod.HistoryResponse,
        "MessageInfo": responses_mod.MessageInfo,
        "HealthResponse": responses_mod.HealthResponse,
        "ComponentHealth": responses_mod.ComponentHealth,
        "ErrorResponse": responses_mod.ErrorResponse,
        "ErrorDetail": responses_mod.ErrorDetail,
        "FeedbackResponse": responses_mod.FeedbackResponse,
        "ClearSessionResponse": responses_mod.ClearSessionResponse,
        "DeleteSessionResponse": responses_mod.DeleteSessionResponse,
        # Requests
        "QueryRequest": requests_mod.QueryRequest,
        "StreamQueryRequest": requests_mod.StreamQueryRequest,
        "FeedbackRequest": requests_mod.FeedbackRequest,
        "CreateSessionRequest": requests_mod.CreateSessionRequest,
        # Usage
        "UsageByModel": usage_mod.UsageByModel,
        "UsageStatsResponse": usage_mod.UsageStatsResponse,
        "QuotaStatusResponse": usage_mod.QuotaStatusResponse,
        "QuotaUpdateRequest": usage_mod.QuotaUpdateRequest,
        "QuotaUpdateResponse": usage_mod.QuotaUpdateResponse,
    }

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build a combined schema document with all models.
    schemas: dict = {}
    for name, model_cls in MODELS.items():
        schema = model_cls.model_json_schema()
        schemas[name] = schema

    output_file = output_dir / "api-schema.json"
    output_file.write_text(json.dumps(schemas, indent=2, default=str) + "\n")

    print(f"Exported {len(schemas)} model schemas to {output_file}")


if __name__ == "__main__":
    main()
