#!/bin/bash
# =============================================================================
# Storage Encryption Validation Script
# =============================================================================
# Validates that all PVCs in a namespace use encrypted storage classes.
# Used for compliance audits and pre-deployment verification.
#
# Usage:
#   ./scripts/validate-storage-encryption.sh [namespace]
#
# Example:
#   ./scripts/validate-storage-encryption.sh rag-pipeline
# =============================================================================

set -e

# Configuration
NAMESPACE=${1:-rag-pipeline}

# Known encrypted storage classes by provider
ENCRYPTED_CLASSES=(
    # GKE
    "premium-rwo"
    "standard-rwo"
    "encrypted-premium"
    # EKS
    "encrypted-gp3"
    "encrypted-gp3-cmk"
    "gp3"  # When default encryption is enabled
    # AKS
    "managed-csi-premium"
    "managed-csi"
    "encrypted-premium-cmk"
    # Generic
    "encrypted"
)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}  Storage Encryption Validation                        ${NC}"
echo -e "${BLUE}======================================================${NC}"
echo ""
echo -e "Namespace: ${YELLOW}$NAMESPACE${NC}"
echo -e "Timestamp: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed or not in PATH${NC}"
    exit 1
fi

# Check if namespace exists
if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
    echo -e "${RED}Error: Namespace '$NAMESPACE' does not exist${NC}"
    exit 1
fi

# Get all PVCs in namespace
echo -e "${BLUE}Checking PersistentVolumeClaims...${NC}"
echo ""

PVCS=$(kubectl get pvc -n "$NAMESPACE" -o jsonpath='{range .items[*]}{.metadata.name}|{.spec.storageClassName}|{.status.phase}|{.spec.resources.requests.storage}{"\n"}{end}' 2>/dev/null)

if [ -z "$PVCS" ]; then
    echo -e "${YELLOW}No PVCs found in namespace $NAMESPACE${NC}"
    exit 0
fi

TOTAL=0
ENCRYPTED=0
UNENCRYPTED=0
PENDING=0

printf "%-30s %-25s %-10s %-10s %s\n" "PVC NAME" "STORAGE CLASS" "STATUS" "SIZE" "ENCRYPTED"
printf "%-30s %-25s %-10s %-10s %s\n" "--------" "-------------" "------" "----" "---------"

while IFS='|' read -r pvc_name storage_class phase size; do
    if [ -z "$pvc_name" ]; then
        continue
    fi
    
    TOTAL=$((TOTAL + 1))
    
    # Check if storage class is in encrypted list
    IS_ENCRYPTED=false
    for enc_class in "${ENCRYPTED_CLASSES[@]}"; do
        if [ "$storage_class" == "$enc_class" ]; then
            IS_ENCRYPTED=true
            break
        fi
    done
    
    # Format status
    if [ "$phase" != "Bound" ]; then
        PENDING=$((PENDING + 1))
        STATUS_COLOR="${YELLOW}"
    else
        STATUS_COLOR="${NC}"
    fi
    
    # Format encryption status
    if [ "$IS_ENCRYPTED" = true ]; then
        ENCRYPTED=$((ENCRYPTED + 1))
        ENC_STATUS="${GREEN}✅ Yes${NC}"
    else
        UNENCRYPTED=$((UNENCRYPTED + 1))
        ENC_STATUS="${RED}❌ No${NC}"
    fi
    
    printf "%-30s %-25s ${STATUS_COLOR}%-10s${NC} %-10s %b\n" \
        "$pvc_name" "$storage_class" "$phase" "$size" "$ENC_STATUS"
        
done <<< "$PVCS"

echo ""
echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}  Summary                                              ${NC}"
echo -e "${BLUE}======================================================${NC}"
echo ""
echo -e "Total PVCs:      $TOTAL"
echo -e "Encrypted:       ${GREEN}$ENCRYPTED${NC}"
echo -e "Not Encrypted:   ${RED}$UNENCRYPTED${NC}"
echo -e "Pending/Unbound: ${YELLOW}$PENDING${NC}"
echo ""

# List storage classes for reference
echo -e "${BLUE}Available Storage Classes:${NC}"
kubectl get storageclass -o custom-columns='NAME:.metadata.name,PROVISIONER:.provisioner,RECLAIM:.reclaimPolicy,DEFAULT:.metadata.annotations.storageclass\.kubernetes\.io/is-default-class' 2>/dev/null || echo "Unable to list storage classes"
echo ""

# Exit with appropriate code
if [ $UNENCRYPTED -gt 0 ]; then
    echo -e "${RED}======================================================${NC}"
    echo -e "${RED}  VALIDATION FAILED                                    ${NC}"
    echo -e "${RED}======================================================${NC}"
    echo ""
    echo -e "${RED}$UNENCRYPTED PVC(s) are not using encrypted storage classes.${NC}"
    echo ""
    echo "To fix, update PVCs to use one of these storage classes:"
    for enc_class in "${ENCRYPTED_CLASSES[@]}"; do
        echo "  - $enc_class"
    done
    echo ""
    exit 1
else
    echo -e "${GREEN}======================================================${NC}"
    echo -e "${GREEN}  VALIDATION PASSED                                    ${NC}"
    echo -e "${GREEN}======================================================${NC}"
    echo ""
    echo -e "${GREEN}All PVCs use encrypted storage classes.${NC}"
    exit 0
fi
