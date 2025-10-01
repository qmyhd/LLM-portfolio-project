#!/usr/bin/env pwsh
# Execute Migration Plan Script for Supabase Database
# This script safely applies the complete migration plan to align the database with expected schema

param(
    [string]$DatabaseUrl = "",
    [switch]$DryRun = $false,
    [switch]$Verbose = $false
)

# Color output functions
function Write-Success { param($msg) Write-Host "✅ $msg" -ForegroundColor Green }
function Write-Error { param($msg) Write-Host "❌ $msg" -ForegroundColor Red }
function Write-Info { param($msg) Write-Host "ℹ️  $msg" -ForegroundColor Blue }
function Write-Warning { param($msg) Write-Host "⚠️  $msg" -ForegroundColor Yellow }

# Get the script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir
$MigrationFile = Join-Path $ScriptDir "complete_migration_plan.sql"

Write-Info "LLM Portfolio Database Migration Script"
Write-Info "======================================="

# Check if migration file exists
if (-not (Test-Path $MigrationFile)) {
    Write-Error "Migration file not found: $MigrationFile"
    Write-Info "Please ensure complete_migration_plan.sql exists in the reports directory"
    exit 1
}

# Get database URL from environment if not provided
if (-not $DatabaseUrl) {
    # Try to load from .env file
    $EnvFile = Join-Path $ProjectRoot ".env"
    if (Test-Path $EnvFile) {
        Write-Info "Loading database URL from .env file..."
        $envContent = Get-Content $EnvFile
        foreach ($line in $envContent) {
            if ($line -match "^DATABASE_URL=(.+)$") {
                $DatabaseUrl = $matches[1].Trim('"')
                break
            }
        }
    }
    
    if (-not $DatabaseUrl) {
        Write-Error "DATABASE_URL not found in environment or .env file"
        Write-Info "Please provide database URL via -DatabaseUrl parameter or set DATABASE_URL environment variable"
        exit 1
    }
}

# Validate database URL format
if ($DatabaseUrl -notmatch "^postgresql://") {
    Write-Error "Invalid database URL format. Expected PostgreSQL connection string starting with postgresql://"
    exit 1
}

Write-Success "Database URL loaded successfully"

# Check if psql is available
try {
    $psqlVersion = psql --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Success "psql found: $($psqlVersion -split "`n" | Select-Object -First 1)"
    } else {
        throw "psql not available"
    }
} catch {
    Write-Error "psql (PostgreSQL client) is not installed or not in PATH"
    Write-Info "Please install PostgreSQL client tools and ensure psql is available"
    exit 1
}

# Display migration file info
$MigrationSize = (Get-Item $MigrationFile).Length
$LineCount = (Get-Content $MigrationFile | Measure-Object -Line).Lines
Write-Info "Migration file: $MigrationFile"
Write-Info "File size: $MigrationSize bytes, $LineCount lines"

if ($DryRun) {
    Write-Warning "DRY RUN MODE - No changes will be made to the database"
    Write-Info "Would execute migration with command:"
    Write-Info "psql `"$DatabaseUrl`" -f `"$MigrationFile`""
    
    # Show first few lines of migration
    Write-Info "`nFirst 10 lines of migration file:"
    Write-Host "$(Get-Content $MigrationFile -Head 10 -Raw)" -ForegroundColor Gray
    
    exit 0
}

# Execute migration
Write-Info "Executing migration plan..."
Write-Warning "This will modify your database schema. Ensure you have a backup if needed."

$ConfirmMessage = "Do you want to proceed with the database migration? (y/N)"
$Confirmation = Read-Host $ConfirmMessage

if ($Confirmation -ne "y" -and $Confirmation -ne "Y") {
    Write-Info "Migration cancelled by user"
    exit 0
}

Write-Info "Starting migration execution..."

try {
    # Execute the migration using psql
    $psqlArgs = @(
        $DatabaseUrl,
        "-f", $MigrationFile,
        "--echo-errors"
    )
    
    if ($Verbose) {
        $psqlArgs += "--echo-all"
    }
    
    Write-Info "Running: psql <DATABASE_URL> -f $MigrationFile $(if($Verbose){'--echo-all'})"
    
    $result = & psql @psqlArgs
    
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Migration completed successfully!"
        Write-Info "Database schema has been aligned with expected structure"
        
        # Show result summary if available
        if ($result) {
            Write-Info "`nMigration output:"
            Write-Host $result -ForegroundColor Gray
        }
        
        # Suggest next steps
        Write-Info "`nNext steps:"
        Write-Info "1. Verify migration with: python scripts/verify_database.py --mode=post-migration"
        Write-Info "2. Test database connectivity with your application"
        Write-Info "3. Run schema validation: python scripts/verify_database.py --mode=comprehensive"
        
    } else {
        Write-Error "Migration failed with exit code: $LASTEXITCODE"
        if ($result) {
            Write-Error "Error output:"
            Write-Host $result -ForegroundColor Red
        }
        exit 1
    }
    
} catch {
    Write-Error "Migration execution failed: $($_.Exception.Message)"
    exit 1
}

Write-Success "Database migration completed successfully!"
