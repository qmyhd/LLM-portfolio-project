#!/bin/bash
# =============================================================================
# EC2 Services Setup Script
# =============================================================================
# 
# This script sets up the Discord bot as a persistent service and configures
# cron jobs for the daily data pipeline.
#
# Usage:
#   chmod +x scripts/setup_ec2_services.sh
#   ./scripts/setup_ec2_services.sh [--pm2 | --systemd]
#
# Options:
#   --pm2      Use PM2 process manager (recommended, easier to use)
#   --systemd  Use systemd service (more integrated with OS)
#
# Requirements:
#   - EC2 instance with Amazon Linux 2023 or Ubuntu
#   - Python 3.11+ with virtual environment at .venv/
#   - Node.js (for PM2 option)
#   - Project cloned to /home/ec2-user/LLM-portfolio-project
#
# =============================================================================

set -e

# Configuration
PROJECT_DIR="${PROJECT_DIR:-/home/ec2-user/LLM-portfolio-project}"
VENV_DIR="$PROJECT_DIR/.venv"
LOG_DIR="/var/log"
USER="${USER:-ec2-user}"

echo "=============================================="
echo "  LLM Portfolio Journal - EC2 Services Setup"
echo "=============================================="
echo ""

# Check we're in the right directory
if [ ! -f "$PROJECT_DIR/src/bot/bot.py" ]; then
    echo "❌ Error: Cannot find project at $PROJECT_DIR"
    echo "   Set PROJECT_DIR environment variable or run from project root"
    exit 1
fi

# Check virtual environment
if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "❌ Error: Virtual environment not found at $VENV_DIR"
    echo "   Run: python -m venv .venv && pip install -r requirements.txt"
    exit 1
fi

# Parse arguments
USE_PM2=false
USE_SYSTEMD=false
if [ "$1" = "--pm2" ]; then
    USE_PM2=true
elif [ "$1" = "--systemd" ]; then
    USE_SYSTEMD=true
else
    echo "Choose process manager:"
    echo "  1) PM2 (recommended - easier to manage)"
    echo "  2) systemd (OS-integrated service)"
    read -p "Selection [1]: " choice
    case $choice in
        2) USE_SYSTEMD=true ;;
        *) USE_PM2=true ;;
    esac
fi

# =============================================================================
# Setup Log Directory
# =============================================================================
echo ""
echo "📁 Setting up log directories..."
sudo mkdir -p /var/log/discord-bot
sudo chown $USER:$USER /var/log/discord-bot

# =============================================================================
# PM2 Setup
# =============================================================================
if [ "$USE_PM2" = true ]; then
    echo ""
    echo "🔧 Setting up PM2..."
    
    # Check if Node.js is installed
    if ! command -v node &> /dev/null; then
        echo "   Installing Node.js..."
        # Amazon Linux 2023
        if [ -f /etc/amazon-linux-release ]; then
            sudo dnf install -y nodejs
        # Ubuntu
        elif [ -f /etc/lsb-release ]; then
            curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
            sudo apt-get install -y nodejs
        fi
    fi
    
    # Install PM2
    if ! command -v pm2 &> /dev/null; then
        echo "   Installing PM2..."
        sudo npm install -g pm2
    fi
    
    # Start the Discord bot
    echo "   Starting Discord bot with PM2..."
    cd "$PROJECT_DIR"
    pm2 start ecosystem.config.js
    
    # Save process list
    pm2 save
    
    # Configure startup
    echo "   Configuring PM2 startup..."
    pm2 startup | tail -1 | bash || true
    
    echo ""
    echo "✅ PM2 setup complete!"
    echo ""
    echo "   Useful commands:"
    echo "     pm2 status           # Check bot status"
    echo "     pm2 logs discord-bot # View logs"
    echo "     pm2 restart discord-bot"
    echo "     pm2 stop discord-bot"
fi

# =============================================================================
# systemd Setup
# =============================================================================
if [ "$USE_SYSTEMD" = true ]; then
    echo ""
    echo "🔧 Setting up systemd service..."
    
    # Copy service file
    sudo cp "$PROJECT_DIR/docker/discord-bot.service" /etc/systemd/system/
    
    # Reload systemd
    sudo systemctl daemon-reload
    
    # Enable and start service
    sudo systemctl enable discord-bot
    sudo systemctl start discord-bot
    
    echo ""
    echo "✅ systemd service setup complete!"
    echo ""
    echo "   Useful commands:"
    echo "     sudo systemctl status discord-bot"
    echo "     sudo journalctl -u discord-bot -f"
    echo "     sudo systemctl restart discord-bot"
    echo "     sudo systemctl stop discord-bot"
fi

# =============================================================================
# Cron Jobs Setup
# =============================================================================
echo ""
echo "🕐 Setting up cron jobs..."

# Create cron job entries
CRON_FILE=$(mktemp)

# Preserve existing cron jobs
crontab -l 2>/dev/null > "$CRON_FILE" || true

# Check if our jobs already exist
if grep -q "daily_pipeline.py" "$CRON_FILE" 2>/dev/null; then
    echo "   Cron jobs already configured, skipping..."
else
    cat >> "$CRON_FILE" << EOF

# =============================================================================
# LLM Portfolio Journal - Daily Data Pipeline
# =============================================================================

# Daily full pipeline at 1:00 AM ET (6:00 AM UTC)
# Runs: SnapTrade sync + Discord NLP processing + OHLCV backfill
0 6 * * * cd $PROJECT_DIR && $VENV_DIR/bin/python scripts/daily_pipeline.py >> /var/log/discord-bot/daily_pipeline.log 2>&1

# Evening SnapTrade sync at 8:00 PM ET (1:00 AM UTC next day)
# Captures end-of-day positions after market close
0 1 * * * cd $PROJECT_DIR && $VENV_DIR/bin/python scripts/daily_pipeline.py --snaptrade >> /var/log/discord-bot/snaptrade_sync.log 2>&1

# Weekly log cleanup (keep 30 days)
0 0 * * 0 find /var/log/discord-bot -name "*.log" -mtime +30 -delete

EOF
    
    # Install new crontab
    crontab "$CRON_FILE"
    echo "   ✅ Cron jobs installed"
fi

rm -f "$CRON_FILE"

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "=============================================="
echo "  Setup Complete!"
echo "=============================================="
echo ""
echo "📋 Installed components:"
if [ "$USE_PM2" = true ]; then
    echo "   ✅ Discord bot running via PM2"
fi
if [ "$USE_SYSTEMD" = true ]; then
    echo "   ✅ Discord bot running via systemd"
fi
echo "   ✅ Cron jobs for daily pipeline"
echo ""
echo "📅 Scheduled tasks:"
echo "   • 1:00 AM ET - Full daily pipeline (SnapTrade + Discord + OHLCV)"
echo "   • 8:00 PM ET - Evening SnapTrade sync"
echo ""
echo "📁 Log locations:"
echo "   • Bot logs: /var/log/discord-bot/"
echo "   • Pipeline logs: /var/log/discord-bot/daily_pipeline.log"
echo ""
echo "🔍 Verify cron jobs:"
echo "   crontab -l"
echo ""
