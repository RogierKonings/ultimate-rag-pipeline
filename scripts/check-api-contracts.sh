#!/usr/bin/env bash
# Check for API contract drift between backend Pydantic models and
# the checked-in generated TypeScript types.
#
# This script regenerates TypeScript types from the current backend models
# and compares them against the committed generated-types.ts. A non-zero
# exit code means there is drift that needs to be resolved.
#
# Usage:
#   ./scripts/check-api-contracts.sh
#
# Intended for CI pipelines and pre-commit hooks.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCHEMA_DIR="${REPO_ROOT}/frontend/src/lib/api"
GENERATED_FILE="${SCHEMA_DIR}/generated-types.ts"
TEMP_DIR="$(mktemp -d)"

cleanup() {
    rm -rf "${TEMP_DIR}"
}
trap cleanup EXIT

echo "==> Regenerating TypeScript types from current backend models..."

# Generate fresh schema and types to a temp directory
python3 "${REPO_ROOT}/scripts/extract-api-schemas.py" --output-dir "${TEMP_DIR}"
python3 "${REPO_ROOT}/scripts/json-schema-to-ts.py" "${TEMP_DIR}/api-schema.json" --output "${TEMP_DIR}/generated-types.ts"

if [ ! -f "${GENERATED_FILE}" ]; then
    echo ""
    echo "ERROR: No generated types file found at ${GENERATED_FILE}"
    echo "Run ./scripts/generate-api-types.sh to generate initial types."
    exit 1
fi

echo "==> Comparing against checked-in types..."

if diff -u "${GENERATED_FILE}" "${TEMP_DIR}/generated-types.ts" > "${TEMP_DIR}/diff.txt" 2>&1; then
    echo ""
    echo "OK: Generated types are up to date. No contract drift detected."
    exit 0
else
    echo ""
    echo "ERROR: API contract drift detected!"
    echo ""
    echo "The backend Pydantic models have changed but the generated TypeScript"
    echo "types have not been updated. Differences:"
    echo ""
    cat "${TEMP_DIR}/diff.txt"
    echo ""
    echo "To fix, run:  ./scripts/generate-api-types.sh"
    echo "Then update frontend/src/lib/api/types.ts if needed and commit."
    exit 1
fi
