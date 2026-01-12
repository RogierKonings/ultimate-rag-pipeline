#!/bin/bash
#
# Generate RSA key pair for JWT signing (RS256).
#
# Usage:
#   ./scripts/generate-jwt-keys.sh [output_dir]
#
# Output:
#   - jwt-private.pem: RSA private key (4096 bit)
#   - jwt-public.pem: RSA public key
#
# The private key is used for signing tokens.
# The public key is used for verifying tokens.
#
# SECURITY NOTE:
#   - Keep the private key secure and never commit it to version control
#   - Store keys in HashiCorp Vault or Kubernetes Secrets
#   - Rotate keys periodically (recommended: every 90 days)
#

set -e

# Configuration
KEY_SIZE=4096
OUTPUT_DIR="${1:-./keys}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== JWT Key Generation ===${NC}"
echo "Generating ${KEY_SIZE}-bit RSA key pair for JWT signing..."
echo ""

# Create output directory
mkdir -p "$OUTPUT_DIR"

PRIVATE_KEY="$OUTPUT_DIR/jwt-private.pem"
PUBLIC_KEY="$OUTPUT_DIR/jwt-public.pem"

# Check if keys already exist
if [ -f "$PRIVATE_KEY" ] || [ -f "$PUBLIC_KEY" ]; then
    echo -e "${YELLOW}Warning: Existing keys found in $OUTPUT_DIR${NC}"
    read -p "Do you want to overwrite them? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# Generate private key
echo "Generating private key..."
openssl genrsa -out "$PRIVATE_KEY" "$KEY_SIZE" 2>/dev/null

# Extract public key
echo "Extracting public key..."
openssl rsa -in "$PRIVATE_KEY" -pubout -out "$PUBLIC_KEY" 2>/dev/null

# Set appropriate permissions
chmod 600 "$PRIVATE_KEY"
chmod 644 "$PUBLIC_KEY"

echo ""
echo -e "${GREEN}Keys generated successfully!${NC}"
echo ""
echo "Files:"
echo "  Private key: $PRIVATE_KEY (keep this secure!)"
echo "  Public key:  $PUBLIC_KEY"
echo ""
echo "Key fingerprint:"
openssl rsa -in "$PRIVATE_KEY" -pubout -outform DER 2>/dev/null | openssl dgst -sha256 | awk '{print $2}'
echo ""

# Display usage instructions
echo -e "${YELLOW}Usage Instructions:${NC}"
echo ""
echo "1. For local development, set environment variables:"
echo "   export JWT_SECRET_KEY=\"\$(cat $PRIVATE_KEY)\""
echo "   export JWT_PUBLIC_KEY=\"\$(cat $PUBLIC_KEY)\""
echo "   export JWT_ALGORITHM=RS256"
echo ""
echo "2. For Kubernetes, create a secret:"
echo "   kubectl create secret generic jwt-keys \\"
echo "     --from-file=private-key=$PRIVATE_KEY \\"
echo "     --from-file=public-key=$PUBLIC_KEY \\"
echo "     -n rag-pipeline"
echo ""
echo "3. For HashiCorp Vault:"
echo "   vault kv put secret/rag-pipeline/jwt \\"
echo "     private_key=@$PRIVATE_KEY \\"
echo "     public_key=@$PUBLIC_KEY"
echo ""
echo -e "${RED}IMPORTANT: Do not commit private keys to version control!${NC}"
echo "Add the following to your .gitignore:"
echo "  keys/"
echo "  *.pem"
