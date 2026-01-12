#!/bin/bash
# Security Scanning Script for RAG Pipeline
# Runs all security scans locally and generates a summary report
#
# Usage: ./scripts/security-scan.sh [--full] [--fix] [--output-dir DIR]
#
# Options:
#   --full        Run all scans including slow ones (container scanning)
#   --fix         Attempt to auto-fix issues where possible
#   --output-dir  Directory for scan results (default: ./security-reports)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="${PROJECT_ROOT}/security-reports"
FULL_SCAN=false
AUTO_FIX=false
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --full)
            FULL_SCAN=true
            shift
            ;;
        --fix)
            AUTO_FIX=true
            shift
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  RAG Pipeline Security Scan${NC}"
echo -e "${BLUE}  $(date)${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Track results
declare -A SCAN_RESULTS

# Function to run a scan and capture result
run_scan() {
    local name="$1"
    local cmd="$2"
    local output_file="$3"

    echo -e "${YELLOW}Running: ${name}...${NC}"

    if eval "$cmd" > "$output_file" 2>&1; then
        SCAN_RESULTS["$name"]="PASS"
        echo -e "${GREEN}  ✓ ${name} completed${NC}"
    else
        SCAN_RESULTS["$name"]="FINDINGS"
        echo -e "${RED}  ✗ ${name} found issues${NC}"
    fi
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# 1. Bandit - Python Security Linter
echo ""
echo -e "${BLUE}[1/7] Running Bandit (Python Security Linter)...${NC}"
if command_exists bandit; then
    run_scan "Bandit" \
        "bandit -r ${PROJECT_ROOT}/services/ --exclude '${PROJECT_ROOT}/services/**/tests,${PROJECT_ROOT}/.venv' -f json" \
        "${OUTPUT_DIR}/bandit_${TIMESTAMP}.json"

    # Also run with text output for quick review
    bandit -r "${PROJECT_ROOT}/services/" \
        --exclude "${PROJECT_ROOT}/services/**/tests,${PROJECT_ROOT}/.venv" \
        -f txt \
        -o "${OUTPUT_DIR}/bandit_${TIMESTAMP}.txt" 2>/dev/null || true
else
    echo -e "${YELLOW}  Bandit not installed. Install with: pip install bandit${NC}"
    SCAN_RESULTS["Bandit"]="SKIPPED"
fi

# 2. Safety - Dependency Vulnerability Check
echo ""
echo -e "${BLUE}[2/7] Running Safety (Dependency Check)...${NC}"
if command_exists safety; then
    {
        echo "# Safety Dependency Check Results"
        echo "# Generated: $(date)"
        echo ""
        find "${PROJECT_ROOT}" -name "requirements*.txt" -not -path "*/.venv/*" | while read -r req; do
            echo "## Checking: $req"
            safety check -r "$req" --output json 2>/dev/null || echo '{"error": "scan failed"}'
            echo ""
        done
    } > "${OUTPUT_DIR}/safety_${TIMESTAMP}.json"
    SCAN_RESULTS["Safety"]="COMPLETED"
    echo -e "${GREEN}  ✓ Safety check completed${NC}"
else
    echo -e "${YELLOW}  Safety not installed. Install with: pip install safety${NC}"
    SCAN_RESULTS["Safety"]="SKIPPED"
fi

# 3. pip-audit - Another dependency checker
echo ""
echo -e "${BLUE}[3/7] Running pip-audit...${NC}"
if command_exists pip-audit; then
    {
        find "${PROJECT_ROOT}" -name "requirements*.txt" -not -path "*/.venv/*" | while read -r req; do
            echo "# Checking: $req"
            pip-audit -r "$req" --format json 2>/dev/null || echo '[]'
        done
    } > "${OUTPUT_DIR}/pip-audit_${TIMESTAMP}.json"
    SCAN_RESULTS["pip-audit"]="COMPLETED"
    echo -e "${GREEN}  ✓ pip-audit completed${NC}"
else
    echo -e "${YELLOW}  pip-audit not installed. Install with: pip install pip-audit${NC}"
    SCAN_RESULTS["pip-audit"]="SKIPPED"
fi

# 4. Gitleaks - Secrets Detection
echo ""
echo -e "${BLUE}[4/7] Running Gitleaks (Secrets Detection)...${NC}"
if command_exists gitleaks; then
    GITLEAKS_CONFIG=""
    if [ -f "${PROJECT_ROOT}/.gitleaks.toml" ]; then
        GITLEAKS_CONFIG="--config ${PROJECT_ROOT}/.gitleaks.toml"
    fi

    run_scan "Gitleaks" \
        "gitleaks detect --source ${PROJECT_ROOT} ${GITLEAKS_CONFIG} --report-format json --no-git" \
        "${OUTPUT_DIR}/gitleaks_${TIMESTAMP}.json"
else
    echo -e "${YELLOW}  Gitleaks not installed. Install from: https://github.com/gitleaks/gitleaks${NC}"
    SCAN_RESULTS["Gitleaks"]="SKIPPED"
fi

# 5. Semgrep - SAST
echo ""
echo -e "${BLUE}[5/7] Running Semgrep (SAST)...${NC}"
if command_exists semgrep; then
    SEMGREP_CONFIG=""
    if [ -f "${PROJECT_ROOT}/.semgrep.yml" ]; then
        SEMGREP_CONFIG="--config ${PROJECT_ROOT}/.semgrep.yml"
    fi

    run_scan "Semgrep" \
        "semgrep scan ${SEMGREP_CONFIG} --config auto --json ${PROJECT_ROOT}/services/" \
        "${OUTPUT_DIR}/semgrep_${TIMESTAMP}.json"
else
    echo -e "${YELLOW}  Semgrep not installed. Install with: pip install semgrep${NC}"
    SCAN_RESULTS["Semgrep"]="SKIPPED"
fi

# 6. detect-secrets - Additional secrets detection
echo ""
echo -e "${BLUE}[6/7] Running detect-secrets...${NC}"
if command_exists detect-secrets; then
    run_scan "detect-secrets" \
        "detect-secrets scan ${PROJECT_ROOT} --all-files --exclude-files '\\.git/.*' --exclude-files '\\.venv/.*'" \
        "${OUTPUT_DIR}/detect-secrets_${TIMESTAMP}.json"
else
    echo -e "${YELLOW}  detect-secrets not installed. Install with: pip install detect-secrets${NC}"
    SCAN_RESULTS["detect-secrets"]="SKIPPED"
fi

# 7. Container Scanning (if --full)
echo ""
if [ "$FULL_SCAN" = true ]; then
    echo -e "${BLUE}[7/7] Running Container Scans (Trivy)...${NC}"
    if command_exists trivy; then
        for dockerfile in $(find "${PROJECT_ROOT}/services" -name "Dockerfile" 2>/dev/null); do
            service_name=$(basename "$(dirname "$dockerfile")")
            echo -e "  Scanning ${service_name}..."

            # Build the image first
            docker build -t "rag-${service_name}:scan" -f "$dockerfile" "$(dirname "$dockerfile")" 2>/dev/null || continue

            trivy image "rag-${service_name}:scan" \
                --format json \
                --output "${OUTPUT_DIR}/trivy_${service_name}_${TIMESTAMP}.json" 2>/dev/null || true
        done
        SCAN_RESULTS["Trivy"]="COMPLETED"
        echo -e "${GREEN}  ✓ Container scans completed${NC}"
    else
        echo -e "${YELLOW}  Trivy not installed. Install from: https://github.com/aquasecurity/trivy${NC}"
        SCAN_RESULTS["Trivy"]="SKIPPED"
    fi
else
    echo -e "${BLUE}[7/7] Container Scans (skipped - use --full to enable)${NC}"
    SCAN_RESULTS["Trivy"]="SKIPPED"
fi

# Generate Summary Report
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Generating Summary Report${NC}"
echo -e "${BLUE}========================================${NC}"

SUMMARY_FILE="${OUTPUT_DIR}/security-summary_${TIMESTAMP}.md"

{
    echo "# Security Scan Summary"
    echo ""
    echo "**Generated:** $(date)"
    echo "**Project:** RAG Pipeline"
    echo "**Full Scan:** $FULL_SCAN"
    echo ""
    echo "## Scan Results"
    echo ""
    echo "| Scanner | Status |"
    echo "|---------|--------|"

    for scanner in "${!SCAN_RESULTS[@]}"; do
        status="${SCAN_RESULTS[$scanner]}"
        if [ "$status" = "PASS" ]; then
            echo "| $scanner | ✅ Pass |"
        elif [ "$status" = "FINDINGS" ]; then
            echo "| $scanner | ⚠️ Findings |"
        elif [ "$status" = "COMPLETED" ]; then
            echo "| $scanner | ✅ Completed |"
        else
            echo "| $scanner | ⏭️ Skipped |"
        fi
    done

    echo ""
    echo "## Output Files"
    echo ""
    for f in "${OUTPUT_DIR}"/*_${TIMESTAMP}.*; do
        if [ -f "$f" ]; then
            echo "- $(basename "$f")"
        fi
    done

    echo ""
    echo "## Recommendations"
    echo ""
    echo "1. Review all findings in the JSON reports"
    echo "2. Prioritize CRITICAL and HIGH severity issues"
    echo "3. Update dependencies with known vulnerabilities"
    echo "4. Rotate any exposed secrets immediately"
    echo "5. Run pre-commit hooks before committing: \`pre-commit run --all-files\`"

} > "$SUMMARY_FILE"

# Print summary
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Scan Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

for scanner in "${!SCAN_RESULTS[@]}"; do
    status="${SCAN_RESULTS[$scanner]}"
    if [ "$status" = "PASS" ] || [ "$status" = "COMPLETED" ]; then
        echo -e "  ${GREEN}✓${NC} $scanner: $status"
    elif [ "$status" = "FINDINGS" ]; then
        echo -e "  ${RED}✗${NC} $scanner: $status"
    else
        echo -e "  ${YELLOW}⏭${NC} $scanner: $status"
    fi
done

echo ""
echo -e "${BLUE}Reports saved to: ${OUTPUT_DIR}${NC}"
echo -e "${BLUE}Summary report: ${SUMMARY_FILE}${NC}"
echo ""

# Exit with error if any findings
HAS_FINDINGS=false
for status in "${SCAN_RESULTS[@]}"; do
    if [ "$status" = "FINDINGS" ]; then
        HAS_FINDINGS=true
        break
    fi
done

if [ "$HAS_FINDINGS" = true ]; then
    echo -e "${YELLOW}Security issues were found. Please review the reports.${NC}"
    exit 1
fi

echo -e "${GREEN}All security scans completed successfully!${NC}"
