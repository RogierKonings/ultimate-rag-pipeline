#!/bin/bash
# =============================================================================
# MinIO Service Account Creation Script
# =============================================================================
# Creates service accounts for RAG applications and backup services.
# Stores credentials in Kubernetes secrets.
#
# Usage:
#   ./scripts/create-minio-service-accounts.sh [namespace]
#
# Example:
#   ./scripts/create-minio-service-accounts.sh rag-pipeline
# =============================================================================

set -e

NAMESPACE=${1:-rag-pipeline}
MINIO_ALIAS="rag"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}  MinIO Service Account Creation                       ${NC}"
echo -e "${BLUE}======================================================${NC}"
echo ""
echo -e "Namespace: ${YELLOW}$NAMESPACE${NC}"
echo ""

# Check prerequisites
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed${NC}"
    exit 1
fi

# Wait for bootstrap job to complete
echo -e "${BLUE}Waiting for bootstrap job to complete...${NC}"
kubectl wait --for=condition=complete job/minio-bootstrap -n $NAMESPACE --timeout=300s 2>/dev/null || true

# Get MinIO pod
MINIO_POD=$(kubectl get pods -n $NAMESPACE -l app=minio -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

if [ -z "$MINIO_POD" ]; then
    echo -e "${RED}Error: MinIO pod not found in namespace $NAMESPACE${NC}"
    exit 1
fi

echo -e "MinIO pod: ${GREEN}$MINIO_POD${NC}"
echo ""

# Function to create service account
create_service_account() {
    local USERNAME=$1
    local POLICY=$2
    local SECRET_NAME=$3
    
    echo -e "${BLUE}Creating service account: $USERNAME${NC}"
    
    # Generate random password
    SECRET_KEY=$(openssl rand -hex 32)
    
    # Create user in MinIO
    kubectl exec -n $NAMESPACE $MINIO_POD -- \
        mc admin user add $MINIO_ALIAS $USERNAME $SECRET_KEY 2>/dev/null || \
        echo -e "${YELLOW}User $USERNAME may already exist${NC}"
    
    # Attach policy
    kubectl exec -n $NAMESPACE $MINIO_POD -- \
        mc admin policy attach $MINIO_ALIAS $POLICY --user=$USERNAME 2>/dev/null || \
        echo -e "${YELLOW}Policy $POLICY may already be attached${NC}"
    
    # Create Kubernetes secret
    kubectl create secret generic $SECRET_NAME \
        --namespace=$NAMESPACE \
        --from-literal=access-key=$USERNAME \
        --from-literal=secret-key=$SECRET_KEY \
        --dry-run=client -o yaml | kubectl apply -f -
    
    echo -e "${GREEN}Created secret: $SECRET_NAME${NC}"
    echo ""
}

# ========================================
# Create RAG Service Account
# ========================================
echo -e "${BLUE}>>> Creating RAG service account...${NC}"
create_service_account "rag-service" "rag-readwrite" "minio-rag-credentials"

# ========================================
# Create Backup Service Account
# ========================================
echo -e "${BLUE}>>> Creating backup service account...${NC}"
create_service_account "backup-service" "backup-write" "minio-backup-credentials"

# ========================================
# Create Monitoring Service Account
# ========================================
echo -e "${BLUE}>>> Creating monitoring service account...${NC}"
create_service_account "monitoring-service" "readonly" "minio-monitoring-credentials"

# ========================================
# Verification
# ========================================
echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}  Verification                                         ${NC}"
echo -e "${BLUE}======================================================${NC}"
echo ""

echo -e "${BLUE}MinIO Users:${NC}"
kubectl exec -n $NAMESPACE $MINIO_POD -- mc admin user list $MINIO_ALIAS

echo ""
echo -e "${BLUE}Kubernetes Secrets:${NC}"
kubectl get secrets -n $NAMESPACE | grep minio

echo ""
echo -e "${GREEN}======================================================${NC}"
echo -e "${GREEN}  Service accounts created successfully!               ${NC}"
echo -e "${GREEN}======================================================${NC}"
echo ""
echo "To use these credentials in your deployments, reference the secrets:"
echo ""
echo "  env:"
echo "    - name: MINIO_ACCESS_KEY"
echo "      valueFrom:"
echo "        secretKeyRef:"
echo "          name: minio-rag-credentials"
echo "          key: access-key"
echo "    - name: MINIO_SECRET_KEY"
echo "      valueFrom:"
echo "        secretKeyRef:"
echo "          name: minio-rag-credentials"
echo "          key: secret-key"
echo ""
