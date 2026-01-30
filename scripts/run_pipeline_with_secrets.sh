#!/bin/bash
# =============================================================================
# Pipeline Runner with AWS Secrets Manager
# =============================================================================
#
# This wrapper script runs the daily pipeline with AWS Secrets Manager
# integration. Used by cron jobs on EC2.
#
# Usage:
#   ./scripts/run_pipeline_with_secrets.sh           # Run all tasks
#   ./scripts/run_pipeline_with_secrets.sh --snaptrade
#   ./scripts/run_pipeline_with_secrets.sh --discord
#   ./scripts/run_pipeline_with_secrets.sh --ohlcv
#
# =============================================================================

set -e

# Configuration
PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/llm-portfolio}"
VENV_DIR="$PROJECT_DIR/.venv"
LOG_DIR="/var/log/discord-bot"

# Navigate to project directory
cd "$PROJECT_DIR"

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Configure AWS Secrets Manager
export USE_AWS_SECRETS=1
export AWS_REGION="${AWS_REGION:-us-east-1}"

# Main app secrets (Discord, OpenAI, Supabase, SnapTrade, Databento)
export AWS_SECRET_NAME="${AWS_SECRET_NAME:-qqqAppsecrets}"

# RDS secrets (OHLCV database) - loaded separately
export AWS_RDS_SECRET_NAME="${AWS_RDS_SECRET_NAME:-RDS/ohlcvdata}"

# Set Python path
export PYTHONPATH="$PROJECT_DIR"

# Log start time
echo "========================================"
echo "Pipeline started at: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "Arguments: $@"
echo "========================================"

# Run the pipeline with all arguments passed through
python scripts/daily_pipeline.py "$@"

# Log completion
EXIT_CODE=$?
echo "========================================"
echo "Pipeline completed at: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "Exit code: $EXIT_CODE"
echo "========================================"

exit $EXIT_CODE
