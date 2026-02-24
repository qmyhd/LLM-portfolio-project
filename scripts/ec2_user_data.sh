#!/bin/bash
# =============================================================================
# EC2 User Data Bootstrap Script
# =============================================================================
#
# This script is designed to be used as EC2 User Data for automatic instance
# setup. It installs all dependencies, configures AWS Secrets Manager
# integration, and starts the Discord bot with PM2.
#
# USAGE:
#   1. Copy this script content into EC2 Launch Template > User Data
#   2. Or pass via AWS CLI:
#      aws ec2 run-instances --user-data file://scripts/ec2_user_data.sh
#
# PREREQUISITES:
#   1. EC2 instance with Amazon Linux 2023 (ARM64 recommended: t4g.micro)
#   2. IAM Role attached with these permissions:
#      - secretsmanager:GetSecretValue for llm-portfolio/*
#      - s3:GetObject, s3:PutObject for your OHLCV bucket (optional)
#   3. Security Group allowing outbound HTTPS (443)
#   4. Secrets created in AWS Secrets Manager:
#      - llm-portfolio/production (containing all API keys)
#
# SECRETS MANAGER SETUP:
#   Create a secret named "llm-portfolio/production" with this JSON:
#   {
#     "DATABASE_URL": "postgresql://...",
#     "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_...",
#     "OPENAI_API_KEY": "sk-...",
#     "DISCORD_BOT_TOKEN": "...",
#     "LOG_CHANNEL_IDS": "channel1,channel2",
#     "SNAPTRADE_CLIENT_ID": "...",
#     "SNAPTRADE_CONSUMER_KEY": "...",
#     "SNAPTRADE_USER_ID": "...",
#     "SNAPTRADE_USER_SECRET": "...",
#     "TWITTER_BEARER_TOKEN": "...",
#     "DATABENTO_API_KEY": "..."
#   }
#
# =============================================================================

set -e

# Configuration - customize these as needed
REPO_URL="https://github.com/qmyhd/LLM-portfolio-project.git"
PROJECT_DIR="/home/ubuntu/llm-portfolio"
AWS_REGION="${AWS_REGION:-us-east-1}"
SECRET_NAME="${SECRET_NAME:-qqqAppsecrets}"
PYTHON_VERSION="3.11"
NODE_VERSION="20"

# Logging
LOG_FILE="/var/log/user-data.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=============================================="
echo "  EC2 Bootstrap Script - $(date)"
echo "=============================================="

# =============================================================================
# STEP 1: System Updates and Dependencies
# =============================================================================
echo ""
echo "📦 Step 1: Installing system dependencies..."

# Update system
dnf update -y

# Install Python 3.11
dnf install -y python${PYTHON_VERSION} python${PYTHON_VERSION}-pip python${PYTHON_VERSION}-devel

# Install Node.js for PM2
dnf install -y nodejs npm

# Install Git
dnf install -y git

# Install PostgreSQL client (for debugging)
dnf install -y postgresql15

# Install development tools (needed for some Python packages)
dnf install -y gcc gcc-c++ make

echo "   ✅ System dependencies installed"

# =============================================================================
# STEP 2: Create Log Directory
# =============================================================================
echo ""
echo "📁 Step 2: Setting up directories..."

# Create log directory
mkdir -p /var/log/discord-bot
chown ubuntu:ubuntu /var/log/discord-bot

echo "   ✅ Directories created"

# =============================================================================
# STEP 3: Clone Repository
# =============================================================================
echo ""
echo "📥 Step 3: Cloning repository..."

# Switch to ubuntu for remaining operations
cd /home/ubuntu

if [ -d "$PROJECT_DIR" ]; then
    echo "   Repository already exists, pulling latest..."
    cd "$PROJECT_DIR"
    sudo -u ubuntu git pull
else
    echo "   Cloning fresh repository..."
    sudo -u ubuntu git clone "$REPO_URL" "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi

chown -R ubuntu:ubuntu "$PROJECT_DIR"

echo "   ✅ Repository ready"

# =============================================================================
# STEP 4: Python Environment
# =============================================================================
echo ""
echo "🐍 Step 4: Setting up Python environment..."

cd "$PROJECT_DIR"

# Create virtual environment
if [ ! -d ".venv" ]; then
    sudo -u ubuntu python${PYTHON_VERSION} -m venv .venv
fi

# Upgrade pip
sudo -u ubuntu .venv/bin/pip install --upgrade pip

# Install dependencies (including boto3 for AWS Secrets Manager)
sudo -u ubuntu .venv/bin/pip install -r requirements.txt
sudo -u ubuntu .venv/bin/pip install boto3

# Install package in development mode
sudo -u ubuntu .venv/bin/pip install -e .

echo "   ✅ Python environment ready"

# =============================================================================
# STEP 5: AWS Secrets Manager Configuration
# =============================================================================
echo ""
echo "🔐 Step 5: Configuring AWS Secrets Manager..."

# Create central AWS secrets configuration file (used by systemd services)
sudo mkdir -p /etc/llm-portfolio
sudo tee /etc/llm-portfolio/llm.env > /dev/null << EOF
# AWS Secrets Manager Configuration
# This file is read by all systemd services for consistent secret loading
USE_AWS_SECRETS=1
AWS_REGION=${AWS_REGION}
AWS_SECRET_NAME=qqqAppsecrets
EOF
sudo chown root:ubuntu /etc/llm-portfolio/llm.env
sudo chmod 640 /etc/llm-portfolio/llm.env

# Also create project .env for local/manual runs
cat > "$PROJECT_DIR/.env" << EOF
# AWS Secrets Manager Configuration
# This file tells the application to fetch secrets from AWS Secrets Manager
# instead of reading them from this file.

USE_AWS_SECRETS=1
AWS_REGION=${AWS_REGION}

# Main app secrets (Discord, OpenAI, Supabase, SnapTrade, Databento)
AWS_SECRET_NAME=qqqAppsecrets

# RDS secrets (OHLCV database) - loaded separately
AWS_RDS_SECRET_NAME=RDS/ohlcvdata

# Note: All other secrets (DATABASE_URL, OPENAI_API_KEY, DISCORD_BOT_TOKEN, etc.)
# are fetched from AWS Secrets Manager at runtime.
EOF

chown ubuntu:ubuntu "$PROJECT_DIR/.env"

# Test secrets access (will fail if IAM role is not configured)
echo "   Testing AWS Secrets Manager access..."
sudo -u ubuntu .venv/bin/python -c "
import boto3
import json
client = boto3.client('secretsmanager', region_name='${AWS_REGION}')

# Test main app secret
try:
    response = client.get_secret_value(SecretId='qqqAppsecrets')
    secrets = json.loads(response['SecretString'])
    print(f'   ✅ Successfully accessed qqqAppsecrets with {len(secrets)} keys')
    # Verify critical keys
    required = ['DATABASE_URL', 'OPENAI_API_KEY', 'DISCORD_BOT_TOKEN']
    for key in required:
        if key in secrets:
            print(f'   ✅ {key}: configured')
        else:
            print(f'   ⚠️ {key}: MISSING')
except Exception as e:
    print(f'   ❌ Failed to access qqqAppsecrets: {e}')
    exit(1)

# Test RDS secret
try:
    response = client.get_secret_value(SecretId='RDS/ohlcvdata')
    secrets = json.loads(response['SecretString'])
    print(f'   ✅ Successfully accessed RDS/ohlcvdata with {len(secrets)} keys')
except Exception as e:
    print(f'   ⚠️ RDS secret not accessible (optional): {e}')
" || {
    echo "   ⚠️ Warning: Could not verify secrets access"
    echo "   The bot may fail to start if IAM role is not configured correctly"
}

echo "   ✅ AWS Secrets Manager configured"

# =============================================================================
# STEP 6: PM2 Setup
# =============================================================================
echo ""
echo "🔧 Step 6: Installing and configuring PM2..."

# Install PM2 globally
npm install -g pm2

# Create wrapper script that loads secrets before starting the bot
cat > "$PROJECT_DIR/scripts/start_bot_with_secrets.py" << 'EOF'
#!/usr/bin/env python3
"""
Bot Startup Wrapper - Loads AWS Secrets Manager secrets before starting the bot.
"""
import os
import sys

# Add project root to path
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load secrets from AWS Secrets Manager
from src.aws_secrets import load_secrets_to_env
count = load_secrets_to_env()
print(f"Loaded {count} secrets from AWS Secrets Manager")

# Now import and run the bot
from src.bot.bot import main
main()
EOF

chmod +x "$PROJECT_DIR/scripts/start_bot_with_secrets.py"
chown ubuntu:ubuntu "$PROJECT_DIR/scripts/start_bot_with_secrets.py"

# Update ecosystem.config.js to use the wrapper script
cat > "$PROJECT_DIR/ecosystem.config.js" << 'EOF'
// PM2 Ecosystem Configuration for Discord Bot with AWS Secrets Manager
//
// This configuration runs the Discord bot with automatic secret loading
// from AWS Secrets Manager. PM2 automatically restarts the bot if it crashes.
//
// Usage:
//   pm2 start ecosystem.config.js
//   pm2 status
//   pm2 logs discord-bot
//   pm2 restart discord-bot

module.exports = {
  apps: [
    {
      name: 'discord-bot',
      script: 'scripts/start_bot_with_secrets.py',
      cwd: '/home/ubuntu/llm-portfolio',

      // Use Python from virtual environment
      interpreter: '/home/ubuntu/llm-portfolio/.venv/bin/python',

      // Environment - signals to use AWS Secrets Manager
      env: {
        PYTHONPATH: '/home/ubuntu/llm-portfolio',
        PYTHONUNBUFFERED: '1',
        USE_AWS_SECRETS: '1',
        AWS_REGION: 'us-east-1',
        AWS_SECRETS_PREFIX: 'llm-portfolio',
        AWS_SECRETS_ENV: 'production'
      },
      
      // Process management
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      
      // Restart behavior
      max_restarts: 10,
      min_uptime: '30s',
      restart_delay: 5000,
      
      // Logging
      log_file: '/var/log/discord-bot/combined.log',
      out_file: '/var/log/discord-bot/out.log',
      error_file: '/var/log/discord-bot/error.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      
      // Cron restart (optional - restart daily at 5 AM UTC)
      cron_restart: '0 5 * * *'
    }
  ]
};
EOF

chown ubuntu:ubuntu "$PROJECT_DIR/ecosystem.config.js"

# Start bot with PM2
cd "$PROJECT_DIR"
sudo -u ubuntu pm2 start ecosystem.config.js

# Save PM2 process list
sudo -u ubuntu pm2 save

# Configure PM2 to start on boot
env PATH=$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u ubuntu --hp /home/ubuntu

echo "   ✅ PM2 configured and bot started"

# =============================================================================
# STEP 7: Nightly Pipeline (systemd timer)
# =============================================================================
echo ""
echo "🕐 Step 7: Enabling nightly pipeline timer..."

# Enable systemd timer for nightly pipeline
if systemctl list-unit-files | grep -q "nightly-pipeline.timer"; then
    systemctl enable nightly-pipeline.timer
    systemctl start nightly-pipeline.timer
    echo "   ✅ nightly-pipeline.timer enabled"
else
    echo "   ⚠️ nightly-pipeline.timer not found. Ensure systemd units are installed."
fi

# Health check every 5 minutes (restart bot if not responding)
# (kept as cron to match existing PM2 setup)
CRON_FILE=$(mktemp)
sudo -u ubuntu crontab -l 2>/dev/null > "$CRON_FILE" || true
if ! grep -q "pm2 ping discord-bot" "$CRON_FILE" 2>/dev/null; then
    cat >> "$CRON_FILE" << 'EOF'

# Health check every 5 minutes (restart bot if not responding)
*/5 * * * * pm2 ping discord-bot >/dev/null 2>&1 || pm2 restart discord-bot

EOF
    sudo -u ubuntu crontab "$CRON_FILE"
fi
rm -f "$CRON_FILE"

# =============================================================================
# STEP 8: Verification
# =============================================================================
echo ""
echo "🔍 Step 8: Verifying installation..."

# Check PM2 status
echo "   PM2 Status:"
sudo -u ubuntu pm2 status

# Check bot logs (wait a moment for startup)
sleep 5
echo ""
echo "   Recent bot logs:"
tail -20 /var/log/discord-bot/combined.log 2>/dev/null || echo "   (no logs yet)"

# =============================================================================
# COMPLETE
# =============================================================================
echo ""
echo "=============================================="
echo "  ✅ EC2 Bootstrap Complete!"
echo "=============================================="
echo ""
echo "📋 Summary:"
echo "   • Discord bot running via PM2"
echo "   • AWS Secrets Manager integration configured"
echo "   • nightly-pipeline.timer enabled"
echo ""
echo "🔍 Useful commands:"
echo "   pm2 status           # Check bot status"
echo "   pm2 logs discord-bot # View bot logs"
echo "   pm2 restart discord-bot"
echo ""
echo "📁 Log locations:"
echo "   /var/log/discord-bot/combined.log"
echo "   journalctl -u nightly-pipeline.service"
echo ""
echo "🔐 Secrets:"
echo "   AWS Secrets Manager: ${SECRET_NAME}"
echo ""
