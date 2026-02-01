# =============================================================================
# Sentient Planner - Setup Script for Windows (PowerShell)
# Initializes LocalStack, applies Terraform, and seeds secrets
# =============================================================================

param(
    [string]$GeminiApiKey = "",
    [switch]$SkipWorker = $false
)

$ErrorActionPreference = "Stop"

Write-Host "========================================"
Write-Host "Sentient Planner - Setup Script"
Write-Host "========================================"

# Configuration
$LOCALSTACK_ENDPOINT = "http://localhost:4566"

# $PSScriptRoot = scripts/ folder, so we need ONE parent to get project root
$PROJECT_ROOT = Split-Path -Parent $PSScriptRoot

if (-not $PROJECT_ROOT -or -not (Test-Path $PROJECT_ROOT)) {
    # Fallback: use current directory
    $PROJECT_ROOT = (Get-Location).Path
}

Write-Host "Project Root: $PROJECT_ROOT" -ForegroundColor Gray

function Write-Step {
    param([string]$Step, [string]$Message)
    Write-Host "`n[$Step] $Message" -ForegroundColor Yellow
}

function Write-Success {
    param([string]$Message)
    Write-Host "✓ $Message" -ForegroundColor Green
}

function Write-Error {
    param([string]$Message)
    Write-Host "✗ $Message" -ForegroundColor Red
}

# [1/6] Check Docker
Write-Step "1/6" "Checking Docker..."
try {
    docker info | Out-Null
    Write-Success "Docker is running"
} catch {
    Write-Error "Docker is not running. Please start Docker Desktop first."
    exit 1
}

# [2/6] Check/Start LocalStack
Write-Step "2/6" "Checking LocalStack..."

# Check if LocalStack is already running
$existingLocalstack = docker ps --filter "name=localstack" --format "{{.Names}}" 2>$null
if ($existingLocalstack) {
    Write-Host "  Found existing LocalStack container: $existingLocalstack" -ForegroundColor Cyan
    Write-Success "LocalStack is already running (skipping docker-compose)"
} else {
    Write-Host "  Starting LocalStack via docker-compose..."
    Set-Location $PROJECT_ROOT
    docker-compose up -d localstack
}

# [3/6] Wait for LocalStack
Write-Step "3/6" "Waiting for LocalStack to be healthy..."
$maxRetries = 30
$retryCount = 0

do {
    $retryCount++
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod -Uri "$LOCALSTACK_ENDPOINT/_localstack/health" -TimeoutSec 5
        $s3Running = $health.services.s3 -eq "running" -or $health.services.s3 -eq "available"
    } catch {
        $s3Running = $false
    }
    Write-Host "Waiting for LocalStack... ($retryCount/$maxRetries)"
} while (-not $s3Running -and $retryCount -lt $maxRetries)

if (-not $s3Running) {
    Write-Error "LocalStack failed to start within timeout"
    exit 1
}
Write-Success "LocalStack is healthy"

# [4/6] Create Lambda packages directory
Write-Step "4/6" "Preparing Lambda packages..."
$packagesDir = Join-Path $PROJECT_ROOT "src\lambdas\packages"
if (-not (Test-Path $packagesDir)) {
    New-Item -ItemType Directory -Path $packagesDir -Force | Out-Null
}

# Package Auth Lambda
Write-Host "  Packaging Auth Lambda..."
$authDir = Join-Path $PROJECT_ROOT "src\lambdas\auth"
if (Test-Path $authDir) {
    Compress-Archive -Path "$authDir\*" -DestinationPath "$packagesDir\auth.zip" -Force
}

# Package Processor Lambda
Write-Host "  Packaging Processor Lambda..."
$processorDir = Join-Path $PROJECT_ROOT "src\lambdas\processor"
if (Test-Path $processorDir) {
    Compress-Archive -Path "$processorDir\*" -DestinationPath "$packagesDir\processor.zip" -Force
}

# Package Plan API Lambda
Write-Host "  Packaging Plan API Lambda..."
$planApiDir = Join-Path $PROJECT_ROOT "src\lambdas\plan_api"
if (Test-Path $planApiDir) {
    Compress-Archive -Path "$planApiDir\*" -DestinationPath "$packagesDir\plan_api.zip" -Force
}

Write-Success "Lambda packages created"

# [5/6] Apply Terraform
Write-Step "5/6" "Applying Terraform..."
$terraformDir = Join-Path $PROJECT_ROOT "deployment\terraform"
Set-Location $terraformDir

# Check if tflocal exists
$tfCommand = Get-Command tflocal -ErrorAction SilentlyContinue
if (-not $tfCommand) {
    Write-Host "  tflocal not found, using terraform with LocalStack endpoint..."
    $env:TF_VAR_localstack_endpoint = $LOCALSTACK_ENDPOINT
    $tfCommand = "terraform"
} else {
    $tfCommand = "tflocal"
}

# Initialize and apply
& $tfCommand init -input=false
& $tfCommand apply -auto-approve -input=false

Write-Success "Terraform applied successfully"

# Get outputs
try {
    $apiGatewayUrl = & $tfCommand output -raw api_gateway_url 2>$null
} catch {
    $apiGatewayUrl = "$LOCALSTACK_ENDPOINT/restapis/<api-id>/dev/_user_request_"
}

# [6/6] Seed Secrets
Write-Step "6/6" "Seeding secrets..."

if ([string]::IsNullOrEmpty($GeminiApiKey)) {
    $GeminiApiKey = Read-Host "Enter your Gemini API Key (or press Enter for placeholder)"
    if ([string]::IsNullOrEmpty($GeminiApiKey)) {
        $GeminiApiKey = "your-gemini-api-key-here"
    }
}

# Generate random JWT secret
$bytes = New-Object byte[] 32
(New-Object System.Security.Cryptography.RNGCryptoServiceProvider).GetBytes($bytes)
$JwtSecret = [Convert]::ToBase64String($bytes)

# Create/Update secret
$secretJson = @{
    GEMINI_KEY = $GeminiApiKey
    JWT_SECRET = $JwtSecret
} | ConvertTo-Json -Compress

# Try to update (most common case), then create if not exists
try {
    aws --endpoint-url $LOCALSTACK_ENDPOINT --region us-east-1 --no-cli-pager `
        secretsmanager put-secret-value `
        --secret-id "app-secrets" `
        --secret-string $secretJson 2>$null
} catch {
    # Create if doesn't exist
    aws --endpoint-url $LOCALSTACK_ENDPOINT --region us-east-1 --no-cli-pager `
        secretsmanager create-secret `
        --name "app-secrets" `
        --secret-string $secretJson 2>$null
}

Write-Success "Secrets seeded"

# Build and start worker (optional - skip by default since LocalStack is already running)
# To build worker separately: docker build -t sentiment-worker ./src/worker
# To run worker separately: docker run --network host -e IS_LOCAL=true sentiment-worker
if (-not $SkipWorker) {
    Write-Step "BONUS" "Skipping worker build (use -SkipWorker:$false to enable)"
    Write-Host "  Worker can be built separately with:" -ForegroundColor Gray
    Write-Host "    docker build -t sentiment-worker ./src/worker" -ForegroundColor Gray
}

# Print summary
Set-Location $PROJECT_ROOT

Write-Host "`n========================================"
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "========================================"
Write-Host ""
Write-Host "API Gateway URL:"
Write-Host "  $apiGatewayUrl" -ForegroundColor Cyan
Write-Host ""
Write-Host "JWT Secret (save this for token generation):"
Write-Host "  $JwtSecret" -ForegroundColor Cyan
Write-Host ""
Write-Host "Resources created:"
Write-Host "  - S3 Bucket: sentient-planner-bucket"
Write-Host "  - DynamoDB Table: sentient-planner-table"
Write-Host "  - Kinesis Stream: sentient-planner-stream"
Write-Host "  - SQS Queue: ascii-gen-queue"
Write-Host "  - Lambda Functions: auth, processor"
Write-Host "  - API Gateway: Sentient Planner API"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Generate a JWT token using the JWT_SECRET above"
Write-Host "  2. POST /analyze with Bearer token and JSON body: {`"text`": `"your thoughts`", `"userId`": `"user1`"}"
Write-Host "  3. GET /plan/{userId} to retrieve your plan"
Write-Host ""

# Return to original directory
Set-Location $PROJECT_ROOT
