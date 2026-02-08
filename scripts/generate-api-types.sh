#!/usr/bin/env bash
# Generate TypeScript type definitions from backend Pydantic models.
#
# This script:
#   1. Extracts JSON Schema from the orchestrator's Pydantic models
#   2. Converts the JSON Schema to TypeScript interfaces
#   3. Writes the result to frontend/src/lib/api/generated-types.ts
#
# Prerequisites: Python 3.11+ with pydantic >= 2.0
#
# Usage:
#   ./scripts/generate-api-types.sh
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCHEMA_DIR="${REPO_ROOT}/frontend/src/lib/api"
SCHEMA_FILE="${SCHEMA_DIR}/api-schema.json"
OUTPUT_FILE="${SCHEMA_DIR}/generated-types.ts"

echo "==> Extracting JSON Schema from Pydantic models..."
python3 "${REPO_ROOT}/scripts/extract-api-schemas.py" --output-dir "${SCHEMA_DIR}"

echo "==> Converting JSON Schema to TypeScript..."
python3 "${REPO_ROOT}/scripts/json-schema-to-ts.py" "${SCHEMA_FILE}" --output "${OUTPUT_FILE}"

echo "==> Done. Generated types at: ${OUTPUT_FILE}"
echo ""
echo "Next steps:"
echo "  - Review the generated types in ${OUTPUT_FILE}"
echo "  - Ensure frontend/src/lib/api/types.ts stays aligned"
echo "  - Run ./scripts/check-api-contracts.sh to verify no drift"
