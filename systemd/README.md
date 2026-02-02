# Systemd Services Installation Guide

This guide covers installing and managing the LLM Portfolio Journal services on EC2/Linux using systemd.

## Prerequisites

1. **EC2 Instance with Ubuntu 22.04+**
2. **Python 3.11+ with virtual environment**
3. **AWS IAM role with Secrets Manager access** (ARN: `arn:aws:secretsmanager:us-east-1:298921514475:secret:qqqAppsecrets-FeRqIW`)
4. **PostgreSQL/Supabase connectivity**

## Service Overview

| Service | Type | Purpose |
|---------|------|---------|
| `api.service` | Long-running | FastAPI backend server |
| `discord-bot.service` | Long-running | Discord bot for message collection |
| `nightly-pipeline.service` | One-shot | Daily OHLCV, NLP, refresh jobs |
| `nightly-pipeline.timer` | Timer | Triggers nightly pipeline at 1 AM ET |

## Installation Steps

### 1. Create AWS Secrets Configuration (REQUIRED)

All services read AWS Secrets Manager configuration from a central env file.

**⚠️ Services will fail to start if this file is missing!** Each service has an
`ExecStartPre` check that ensures `/etc/llm-portfolio/llm.env` exists before starting.
This provides a clear error message instead of cryptic AWS credential failures.

```bash
sudo mkdir -p /etc/llm-portfolio
sudo tee /etc/llm-portfolio/llm.env > /dev/null << 'EOF'
# AWS Secrets Manager Configuration
USE_AWS_SECRETS=1
AWS_REGION=us-east-1
AWS_SECRET_NAME=qqqAppsecrets
EOF
sudo chmod 644 /etc/llm-portfolio/llm.env
```

### 2. Enable Persistent Journald Logs (Recommended)

Services log to journald by default. Enable persistent storage so logs survive reboot:

```bash
# Enable persistent journald storage
sudo mkdir -p /var/log/journal

# Production journald configuration (drop-in, 99- prefix ensures it loads last)
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/99-llm-portfolio.conf > /dev/null << 'EOF'
[Journal]
Storage=persistent
SystemMaxUse=1G
SystemKeepFree=2G
Compress=yes
RateLimitBurst=10000
RateLimitIntervalSec=30s
EOF

sudo systemctl restart systemd-journald
```

### 3. Set System Timezone (for timer accuracy)

```bash
# Set timezone to Eastern for market-aligned scheduling
sudo timedatectl set-timezone America/New_York
timedatectl  # Verify
```

### 4. Copy Service Files

```bash
# From project root
sudo cp systemd/*.service /etc/systemd/system/
sudo cp systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

### 5. Enable and Start Services

```bash
# API Server (FastAPI backend)
sudo systemctl enable api.service
sudo systemctl start api.service

# Discord Bot (always running)
sudo systemctl enable discord-bot.service
sudo systemctl start discord-bot.service

# Nightly Pipeline Timer
sudo systemctl enable nightly-pipeline.timer
sudo systemctl start nightly-pipeline.timer
```

## Management Commands

### Check Service Status

```bash
systemctl status api.service
systemctl status discord-bot.service
systemctl status nightly-pipeline.timer
systemctl list-timers  # View all scheduled timers
```

### View Logs

```bash
# Real-time logs
journalctl -u api.service -f
journalctl -u discord-bot.service -f

# Last 100 lines
journalctl -u discord-bot.service -n 100

# Since last boot
journalctl -u discord-bot.service -b

# Errors only
journalctl -u api.service -p err

# By SyslogIdentifier
journalctl -t llm-portfolio-api -f
journalctl -t llm-portfolio-bot -f
journalctl -t llm-portfolio-nightly -f

# Clean up old logs (optional)
sudo journalctl --vacuum-time=30d
```

### Restart Services

```bash
sudo systemctl restart api.service
sudo systemctl restart discord-bot.service
```

### Stop Services

```bash
sudo systemctl stop api.service
sudo systemctl stop discord-bot.service
sudo systemctl stop nightly-pipeline.timer
```

### Run Nightly Pipeline Manually

```bash
sudo systemctl start nightly-pipeline.service
journalctl -u nightly-pipeline.service -f
```

## Troubleshooting

### Service Fails to Start - Missing Env File

If you see this error:
```
ExecStartPre=/usr/bin/test -f /etc/llm-portfolio/llm.env failed
```

**Solution**: Create the required env file (Step 1 above):
```bash
sudo mkdir -p /etc/llm-portfolio
sudo tee /etc/llm-portfolio/llm.env > /dev/null << 'EOF'
USE_AWS_SECRETS=1
AWS_REGION=us-east-1
AWS_SECRET_NAME=qqqAppsecrets
EOF
sudo chmod 644 /etc/llm-portfolio/llm.env
```

### Service Fails to Start - Other Issues

```bash
# Check detailed logs
journalctl -u api.service -n 50 --no-pager
journalctl -u discord-bot.service -n 50 --no-pager

# Verify Python path
/home/ubuntu/llm-portfolio/.venv/bin/python --version

# Test script directly
cd /home/ubuntu/llm-portfolio
.venv/bin/python scripts/start_bot_with_secrets.py
```

### Permission Issues

```bash
# Fix ownership
sudo chown -R ubuntu:ubuntu /home/ubuntu/llm-portfolio
sudo chmod +x /home/ubuntu/llm-portfolio/scripts/*.py
```

### Timer Not Firing

```bash
# Check timer status
systemctl list-timers --all | grep nightly

# Check system timezone
timedatectl

# Force trigger
sudo systemctl start nightly-pipeline.service
```

## Security Notes

- Services run as `ubuntu` (not root)
- `NoNewPrivileges=true` prevents privilege escalation
- `ProtectSystem=strict` makes /usr, /boot read-only
- Secrets loaded from AWS Secrets Manager (no .env files)

## Removing PM2 (If Previously Used)

If you previously used PM2, remove it:

```bash
pm2 stop all
pm2 delete all
pm2 unstartup  # Remove from system startup
npm uninstall -g pm2  # Optional: remove globally
```
