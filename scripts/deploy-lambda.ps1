# =============================================================================
# Sentient Planner - Lambda Hot Reload Script
# Quickly deploy Lambda code changes to LocalStack
# =============================================================================

param(
    [Parameter(Position=0)]
    [ValidateSet("auth", "processor", "plan_api", "all")]
    [string]$Lambda = "all",
    
    [switch]$Watch = $false
)

$ErrorActionPreference = "Stop"

# Configuration
$LOCALSTACK_ENDPOINT = "http://localhost:4566"
$PROJECT_ROOT = Split-Path -Parent $PSScriptRoot
$LAMBDAS_DIR = Join-Path $PROJECT_ROOT "src\lambdas"
$PACKAGES_DIR = Join-Path $LAMBDAS_DIR "packages"

# Lambda configurations
$LAMBDA_CONFIG = @{
    "auth" = @{
        "name" = "sentient_planner_auth"
        "dir" = "auth"
        "handler" = "auth.handler"
    }
    "processor" = @{
        "name" = "sentient_planner_processor"
        "dir" = "processor"
        "handler" = "processor.handler"
    }
    "plan_api" = @{
        "name" = "sentient_planner_plan_api"
        "dir" = "plan_api"
        "handler" = "plan_api.handler"
    }
}

function Write-Status {
    param([string]$Message, [string]$Color = "White")
    Write-Host "[$((Get-Date).ToString('HH:mm:ss'))] $Message" -ForegroundColor $Color
}

function Deploy-Lambda {
    param([string]$LambdaKey)
    
    $config = $LAMBDA_CONFIG[$LambdaKey]
    $lambdaName = $config["name"]
    $lambdaDir = Join-Path $LAMBDAS_DIR $config["dir"]
    $zipPath = Join-Path $PACKAGES_DIR "$LambdaKey.zip"
    
    Write-Status "Deploying $lambdaName..." "Yellow"
    
    # Ensure packages directory exists
    if (-not (Test-Path $PACKAGES_DIR)) {
        New-Item -ItemType Directory -Path $PACKAGES_DIR -Force | Out-Null
    }
    
    # Remove old zip if exists
    if (Test-Path $zipPath) {
        Remove-Item $zipPath -Force
    }
    
    # Create zip file
    Write-Status "  Creating ZIP package..."
    Compress-Archive -Path "$lambdaDir\*" -DestinationPath $zipPath -Force
    
    # Convert to base64 for update
    $zipBytes = [System.IO.File]::ReadAllBytes($zipPath)
    $zipBase64 = [Convert]::ToBase64String($zipBytes)
    
    # Update Lambda function code
    Write-Status "  Updating Lambda code..."
    try {
        aws --endpoint-url $LOCALSTACK_ENDPOINT --region us-east-1 --no-cli-pager `
            lambda update-function-code `
            --function-name $lambdaName `
            --zip-file "fileb://$zipPath" 2>&1 | Out-Null
        
        Write-Status "  ✓ $lambdaName deployed successfully!" "Green"
    } catch {
        Write-Status "  ✗ Failed to deploy $lambdaName" "Red"
        Write-Host $_.Exception.Message -ForegroundColor Red
    }
}

function Deploy-All {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Lambda Hot Reload" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    
    foreach ($key in $LAMBDA_CONFIG.Keys) {
        Deploy-Lambda -LambdaKey $key
    }
    
    Write-Host ""
    Write-Status "All lambdas deployed!" "Green"
}

function Watch-Lambdas {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Lambda Watch Mode" -ForegroundColor Cyan
    Write-Host "  Press Ctrl+C to stop" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    
    # Initial deploy
    Deploy-All
    
    # Create file system watcher
    $watcher = New-Object System.IO.FileSystemWatcher
    $watcher.Path = $LAMBDAS_DIR
    $watcher.Filter = "*.py"
    $watcher.IncludeSubdirectories = $true
    $watcher.EnableRaisingEvents = $true
    
    # Keep track of last change to debounce
    $script:lastChange = Get-Date
    $debounceMs = 1000
    
    $onChange = {
        $now = Get-Date
        $diff = ($now - $script:lastChange).TotalMilliseconds
        
        if ($diff -gt $debounceMs) {
            $script:lastChange = $now
            $path = $Event.SourceEventArgs.FullPath
            
            Write-Host ""
            Write-Status "Change detected: $path" "Yellow"
            
            # Determine which lambda changed
            if ($path -match "\\auth\\") {
                Deploy-Lambda -LambdaKey "auth"
            } elseif ($path -match "\\processor\\") {
                Deploy-Lambda -LambdaKey "processor"
            } elseif ($path -match "\\plan_api\\") {
                Deploy-Lambda -LambdaKey "plan_api"
            } else {
                Write-Status "Unknown lambda, deploying all..." "Yellow"
                Deploy-All
            }
        }
    }
    
    # Register event handlers
    $created = Register-ObjectEvent $watcher "Created" -Action $onChange
    $changed = Register-ObjectEvent $watcher "Changed" -Action $onChange
    
    Write-Status "Watching for changes in $LAMBDAS_DIR..." "Cyan"
    Write-Host ""
    
    try {
        while ($true) {
            Start-Sleep -Seconds 1
        }
    } finally {
        # Cleanup
        Unregister-Event -SubscriptionId $created.Id
        Unregister-Event -SubscriptionId $changed.Id
        $watcher.Dispose()
        Write-Host ""
        Write-Status "Watch mode stopped." "Yellow"
    }
}

# Main execution
if ($Watch) {
    Watch-Lambdas
} elseif ($Lambda -eq "all") {
    Deploy-All
} else {
    Deploy-Lambda -LambdaKey $Lambda
}
