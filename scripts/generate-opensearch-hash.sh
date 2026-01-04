#!/bin/bash
# =============================================================================
# OpenSearch Password Hash Generator
# =============================================================================
# Generates bcrypt password hashes for OpenSearch internal users.
# Uses the official OpenSearch hash.sh tool inside a Docker container.
#
# Usage:
#   ./scripts/generate-opensearch-hash.sh <password>
#   ./scripts/generate-opensearch-hash.sh                    # prompts for password
#
# Example:
#   ./scripts/generate-opensearch-hash.sh my-secure-password
#
# The generated hash can be used in:
#   k8s/opensearch/security-config.yaml (internal_users.yml section)
# =============================================================================

set -e

OPENSEARCH_VERSION="${OPENSEARCH_VERSION:-2.11.1}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_usage() {
    echo "Usage: $0 [password]"
    echo ""
    echo "Generates a bcrypt hash for OpenSearch internal users."
    echo ""
    echo "Options:"
    echo "  password    The password to hash. If not provided, you'll be prompted."
    echo ""
    echo "Environment variables:"
    echo "  OPENSEARCH_VERSION    OpenSearch image version (default: 2.11.1)"
    echo ""
    echo "Example:"
    echo "  $0 my-secure-password"
    echo "  OPENSEARCH_VERSION=2.12.0 $0 my-password"
}

if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    print_usage
    exit 0
fi

# Get password from argument or prompt
PASSWORD="$1"

if [ -z "$PASSWORD" ]; then
    echo -n "Enter password to hash: "
    read -s PASSWORD
    echo ""
    
    if [ -z "$PASSWORD" ]; then
        echo -e "${RED}Error: Password cannot be empty${NC}"
        exit 1
    fi
    
    echo -n "Confirm password: "
    read -s PASSWORD_CONFIRM
    echo ""
    
    if [ "$PASSWORD" != "$PASSWORD_CONFIRM" ]; then
        echo -e "${RED}Error: Passwords do not match${NC}"
        exit 1
    fi
fi

# Validate password strength (basic checks)
if [ ${#PASSWORD} -lt 8 ]; then
    echo -e "${YELLOW}Warning: Password is less than 8 characters${NC}"
fi

echo -e "${GREEN}Generating bcrypt hash using OpenSearch ${OPENSEARCH_VERSION}...${NC}"
echo ""

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed or not in PATH${NC}"
    exit 1
fi

# Generate the hash using OpenSearch's hash.sh tool
HASH=$(docker run --rm \
    opensearchproject/opensearch:${OPENSEARCH_VERSION} \
    /usr/share/opensearch/plugins/opensearch-security/tools/hash.sh \
    -p "$PASSWORD" 2>/dev/null)

if [ -z "$HASH" ]; then
    echo -e "${RED}Error: Failed to generate hash${NC}"
    exit 1
fi

echo -e "${GREEN}Generated hash:${NC}"
echo ""
echo "$HASH"
echo ""
echo -e "${GREEN}Use this hash in your internal_users.yml configuration:${NC}"
echo ""
echo "  username:"
echo "    hash: \"$HASH\""
echo "    reserved: false"
echo "    backend_roles:"
echo "      - \"your_role\""
echo ""
