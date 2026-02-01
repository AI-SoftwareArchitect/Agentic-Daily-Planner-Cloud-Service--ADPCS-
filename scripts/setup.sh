#!/bin/bash
# =============================================================================
# Sentient Planner - Setup & Deploy Script
# Initializes LocalStack, applies Terraform, and seeds secrets
# =============================================================================

set -e

echo "========================================"
echo "Sentient Planner - Setup Script"
echo "========================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
LOCALSTACK_ENDPOINT="http://localhost:4566"
PROJECT_ROOT=$(dirname "$(dirname "$(readlink -f "$0")")")

# Check if Docker is running
echo -e "${YELLOW}[1/6] Checking Docker...${NC}"
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Docker is not running. Please start Docker first.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker is running${NC}"

# Start LocalStack
echo -e "${YELLOW}[2/6] Starting LocalStack...${NC}"
cd "$PROJECT_ROOT"
docker-compose up -d localstack

# Wait for LocalStack to be ready
echo -e "${YELLOW}[3/6] Waiting for LocalStack to be healthy...${NC}"
MAX_RETRIES=30
RETRY_COUNT=0
until curl -s "$LOCALSTACK_ENDPOINT/_localstack/health" | grep -q '"s3": "running"'; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo -e "${RED}LocalStack failed to start within timeout${NC}"
        exit 1
    fi
    echo "Waiting for LocalStack... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done
echo -e "${GREEN}✓ LocalStack is healthy${NC}"

# Install Lambda dependencies
echo -e "${YELLOW}[4/6] Installing Lambda dependencies...${NC}"
cd "$PROJECT_ROOT/src/lambdas/auth"
pip install -r requirements.txt -t . --quiet
cd "$PROJECT_ROOT/src/lambdas/processor"
pip install -r requirements.txt -t . --quiet
cd "$PROJECT_ROOT/src/lambdas/plan_api"
pip install -r requirements.txt -t . --quiet
echo -e "${GREEN}✓ Lambda dependencies installed${NC}"

# Apply Terraform
echo -e "${YELLOW}[5/6] Applying Terraform...${NC}"
cd "$PROJECT_ROOT/deployment/terraform"

# Initialize Terraform
tflocal init -input=false

# Apply Terraform
tflocal apply -auto-approve -input=false

echo -e "${GREEN}✓ Terraform applied successfully${NC}"

# Seed secrets
echo -e "${YELLOW}[6/6] Seeding secrets...${NC}"
echo "Enter your Gemini API Key (or press Enter for placeholder):"
read -r GEMINI_KEY
GEMINI_KEY=${GEMINI_KEY:-"your-gemini-api-key-here"}

# Generate random JWT secret
JWT_SECRET=$(openssl rand -base64 32 || echo "default-jwt-secret-for-development")

# Create secret in LocalStack
awslocal secretsmanager put-secret-value \
    --secret-id app-secrets \
    --secret-string "{\"GEMINI_KEY\":\"${GEMINI_KEY}\",\"JWT_SECRET\":\"${JWT_SECRET}\"}" \
    --endpoint-url "$LOCALSTACK_ENDPOINT" \
    2>/dev/null || echo "Note: Secret may already exist, updating..."

echo -e "${GREEN}✓ Secrets seeded${NC}"

# Build and start worker
echo -e "${YELLOW}[BONUS] Building and starting ASCII Worker...${NC}"
cd "$PROJECT_ROOT"
docker-compose up -d --build sentiment-worker
echo -e "${GREEN}✓ Worker started${NC}"

# Print summary
echo ""
echo "========================================"
echo -e "${GREEN}Setup Complete!${NC}"
echo "========================================"
echo ""
echo "API Gateway URL:"
tflocal -chdir="$PROJECT_ROOT/deployment/terraform" output -raw api_gateway_url 2>/dev/null || echo "$LOCALSTACK_ENDPOINT/restapis/YOUR_API_ID/dev/_user_request_"
echo ""
echo "JWT Secret (save this for token generation):"
echo "$JWT_SECRET"
echo ""
echo "Resources created:"
echo "  - S3 Bucket: sentient-planner-bucket"
echo "  - DynamoDB Table: sentient-planner-table"
echo "  - Kinesis Stream: sentient-planner-stream"
echo "  - SQS Queue: ascii-gen-queue"
echo "  - Lambda Functions: auth, processor"
echo "  - API Gateway: Sentient Planner API"
echo ""
echo "Next steps:"
echo "  1. Generate a JWT token using the JWT_SECRET above"
echo "  2. POST /analyze with Bearer token and JSON body: {\"text\": \"your thoughts\", \"userId\": \"user1\"}"
echo "  3. GET /plan/{userId} to retrieve your plan"
echo ""
