# Systemd Services Installation Guide

This guide covers installing and managing the LLM Portfolio Journal services on EC2/Linux using systemd.

## Prerequisites

1. **EC2 Instance with Amazon Linux 2023 or Ubuntu 22.04+**
2. **Python 3.11+ with virtual environment**
3. **AWS IAM role with Secrets Manager access**
4. **PostgreSQL/Supabase connectivity**

## Service Overview

| Service | Type | Purpose |
|---------|------|---------|
| `discord-bot.service` | Long-running | Discord bot for message collection |
| `api.service` | Long-running | FastAPI backend server |
| `nightly-pipeline.service` | One-shot | Daily OHLCV, NLP, refresh jobs |
| `nightly-pipeline.timer` | Timer | Triggers nightly pipeline at 1 AM ET |

## Installation Steps

### 1. Create Log Directories

```bash
sudo mkdir -p /var/log/discord-bot
sudo mkdir -p /var/log/portfolio-api
sudo mkdir -p /var/log/portfolio-nightly
sudo chown -R ec2-user:ec2-user /var/log/discord-bot /var/log/portfolio-api /var/log/portfolio-nightly
```

### 2. Set System Timezone (for timer accuracy)

```bash
# Set timezone to Eastern for market-aligned scheduling
sudo timedatectl set-timezone America/New_York
timedatectl  # Verify
```

### 3. Copy Service Files

```bash
# From project root
sudo cp systemd/*.service /etc/systemd/system/
sudo cp systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

### 4. Enable and Start Services

```bash
# Discord Bot (always running)
sudo systemctl enable discord-bot.service
sudo systemctl start discord-bot.service

# API Server (if running FastAPI backend)
sudo systemctl enable api.service
sudo systemctl start api.service

# Nightly Pipeline Timer
sudo systemctl enable nightly-pipeline.timer
sudo systemctl start nightly-pipeline.timer
```

## Management Commands

### Check Service Status

```bash
systemctl status discord-bot.service
systemctl status api.service
systemctl status nightly-pipeline.timer
systemctl list-timers  # View all scheduled timers
```

### View Logs

```bash
# Real-time logs
journalctl -u discord-bot.service -f

# Last 100 lines
journalctl -u discord-bot.service -n 100

# Since last boot
journalctl -u discord-bot.service -b

# Log files (if using StandardOutput=append)
tail -f /var/log/discord-bot/combined.log
```

### Restart Services

```bash
sudo systemctl restart discord-bot.service
sudo systemctl restart api.service
```

### Stop Services

```bash
sudo systemctl stop discord-bot.service
sudo systemctl stop api.service
sudo systemctl stop nightly-pipeline.timer
```

### Run Nightly Pipeline Manually

```bash
sudo systemctl start nightly-pipeline.service
journalctl -u nightly-pipeline.service -f
```

## Troubleshooting

### Service Fails to Start

```bash
# Check detailed logs
journalctl -u discord-bot.service -n 50 --no-pager

# Verify Python path
/home/ec2-user/LLM-portfolio-project/.venv/bin/python --version

# Test script directly
cd /home/ec2-user/LLM-portfolio-project
.venv/bin/python scripts/start_bot_with_secrets.py
```

### Permission Issues

```bash
# Fix ownership
sudo chown -R ec2-user:ec2-user /home/ec2-user/LLM-portfolio-project
sudo chmod +x /home/ec2-user/LLM-portfolio-project/scripts/*.py
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

- Services run as `ec2-user` (not root)
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
