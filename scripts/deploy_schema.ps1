# Supabase Schema Deployment Script (PowerShell)
# Run this to deploy the complete schema to your Supabase instance

param(
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [switch]$DryRun = $false
)

Write-Host "🚀 Starting Supabase Schema Deployment..." -ForegroundColor Green

# Check if DATABASE_URL is provided
if (-not $DatabaseUrl) {
    Write-Host "❌ DATABASE_URL environment variable not set" -ForegroundColor Red
    Write-Host "Please set it or pass -DatabaseUrl parameter" -ForegroundColor Yellow
    exit 1
}

# Check if we're in the project root
if (-not (Test-Path "schema/000_baseline.sql")) {
    Write-Host "❌ Please run this script from the project root directory" -ForegroundColor Red
    exit 1
}

if ($DryRun) {
    Write-Host "🔍 DRY RUN MODE - No actual changes will be made" -ForegroundColor Yellow
}

Write-Host "📋 Phase 1: Verify current schema state..." -ForegroundColor Cyan

# Manual verification step
Write-Host "Please run the following command manually to check current state:"
Write-Host "psql `"$DatabaseUrl`" -f scripts/verify_schema_state.sql" -ForegroundColor Yellow

if ($DryRun) {
    Write-Host "Would run schema deployment steps..." -ForegroundColor Yellow
    exit 0
}

Write-Host "📋 Phase 2: Deploy baseline schema..." -ForegroundColor Cyan
$result = psql $DatabaseUrl -f "schema/000_baseline.sql" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Baseline schema deployment failed:" -ForegroundColor Red
    Write-Host $result
    exit 1
}
Write-Host "✅ Baseline schema deployed" -ForegroundColor Green

Write-Host "📋 Phase 3: Apply migrations..." -ForegroundColor Cyan  
# Deploy migrations in numeric order (014, 015, 016)
$migrationFiles = Get-ChildItem "schema" -Filter "*.sql" | Where-Object { 
    $_.Name -match "^\d{3}_" -and $_.Name -ne "000_baseline.sql" 
} | Sort-Object Name

foreach ($migrationFile in $migrationFiles) {
    Write-Host "Applying migration: $($migrationFile.Name)" -ForegroundColor Yellow
    $result = psql $DatabaseUrl -f $migrationFile.FullName 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Migration $($migrationFile.Name) failed:" -ForegroundColor Red
        Write-Host $result
        exit 1
    }
}
Write-Host "✅ All migrations applied" -ForegroundColor Green

Write-Host "📋 Phase 4: Schema deployment verification..." -ForegroundColor Cyan
Write-Host "Schema deployment completed - migrations tracked via 000_baseline.sql + NNN_*.sql files" -ForegroundColor Green

Write-Host ""
Write-Host "✅ Schema deployment complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Verify tables: psql `"$DatabaseUrl`" -f scripts/verify_schema_state.sql"
Write-Host "2. Run bootstrap setup: python scripts/bootstrap.py" -ForegroundColor Yellow
Write-Host "3. Generate journal: python generate_journal.py --force" -ForegroundColor Yellow
