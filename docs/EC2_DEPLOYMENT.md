# EC2 Deployment Guide

> **Last Updated:** February 1, 2026
> **Target:** Ubuntu 22.04 LTS (or 24.04 LTS)

This guide covers deploying the LLM Portfolio Journal to EC2 with:
- AWS Secrets Manager for secure credential storage
- Discord bot and FastAPI server running continuously via systemd
- Reliable daily data pipeline via systemd timers
- Nginx reverse proxy with SSL (Certbot)
- OHLCV backfill from Databento

## Current Production Configuration

| Component | Configuration |
|-----------|--------------|
| OS | Ubuntu 22.04/24.04 LTS |
| Instance | t3.micro or t3.small (x86_64) |
| Python | 3.11+ |
| Process Manager | systemd |
| Reverse Proxy | Nginx with Certbot SSL |
| Secret | `qqqAppsecrets` |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Ubuntu EC2 Instance                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │   Nginx     │  │  api.service│  │   discord-bot.service   │ │
│  │  (SSL/443)  │──│  (FastAPI)  │  │   (Discord Bot)         │ │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬─────────────┘ │
│         │                │                     │               │
│         │                └──────────┬──────────┘               │
│         │                           │                          │
│         │                ┌──────────▼──────────┐               │
│         │                │ /etc/llm-portfolio/ │               │
│         │                │     llm.env         │               │
│         │                └──────────┬──────────┘               │
│         │                           │                          │
│         │                ┌──────────▼──────────┐               │
│         │                │  AWS Secrets Manager │              │
│         │                │   (qqqAppsecrets)    │              │
│         │                └─────────────────────┘               │
│         │                                                      │
│  ┌──────▼──────────────────────────────────────────────────┐   │
│  │               nightly-pipeline.timer                     │  │
│  │   (OHLCV backfill + NLP batch + SnapTrade sync)         │  │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
     ┌──────────┐       ┌──────────┐       ┌──────────┐
     │ Supabase │       │  OpenAI  │       │ SnapTrade│
     │ (Postgres)│      │   API    │       │   API    │
     └──────────┘       └──────────┘       └──────────┘
```

## Prerequisites

### AWS Resources
- **EC2 Instance**: t3.micro or t3.small (~$8-15/month)
- **IAM Role**: Attached to EC2 with `secretsmanager:GetSecretValue`
- **Security Group**: Allow inbound 22 (SSH), 80 (HTTP), 443 (HTTPS); outbound all
- **Secrets Manager Secret**: `qqqAppsecrets`

### Secrets Manager Setup

**Main App Secret (`qqqAppsecrets`):**

```json
{
  "DATABASE_URL": "postgresql://postgres.[project]:[service-role-key]@[region].pooler.supabase.com:6543/postgres",
  "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_your_key",
  "OPENAI_API_KEY": "sk-your_openai_key",
  "DISCORD_BOT_TOKEN": "your_discord_bot_token",
  "LOG_CHANNEL_IDS": "channel_id1,channel_id2",
  "SNAPTRADE_CLIENT_ID": "your_client_id",
  "SNAPTRADE_CONSUMER_KEY": "your_consumer_key",
  "SNAPTRADE_CLIENT_SECRET": "your_client_secret",
  "SNAPTRADE_USER_ID": "your_user_id",
  "SNAPTRADE_USER_SECRET": "your_user_secret",
  "DATABENTO_API_KEY": "db-your_databento_key"
}
```

**IAM Policy for EC2 Role:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:us-east-1:298921514475:secret:qqqAppsecrets-FeRqIW"
    }
  ]
}
```

---

## Quick Start

### Option 1: Automated Bootstrap (Recommended)

SSH into your instance and run:

```bash
ssh ubuntu@your-ec2-ip

# Clone and run bootstrap
git clone https://github.com/qmyhd/LLM-portfolio-project.git /home/ubuntu/llm-portfolio
cd /home/ubuntu/llm-portfolio
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh
```

### Option 2: Using EC2 User Data

1. Copy contents of `scripts/ec2_user_data.sh`
2. Paste into EC2 Launch Template → **User Data**
3. Launch instance

---

## Manual Setup

If you prefer step-by-step manual setup:

### Step 1: Install System Dependencies

```bash
ssh ubuntu@your-ec2-ip

# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11 and dependencies
sudo apt install -y python3.11 python3.11-venv python3.11-dev \
    libpq-dev build-essential git nginx certbot python3-certbot-nginx
```

### Step 2: Clone Repository

```bash
cd /home/ubuntu
git clone https://github.com/qmyhd/LLM-portfolio-project.git llm-portfolio
cd llm-portfolio

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

### Step 3: Configure AWS Secrets

Create the central AWS secrets configuration file:

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

### Step 4: Verify Secrets Access

```bash
cd /home/ubuntu/llm-portfolio
source .venv/bin/activate

# Run the secrets check script
python scripts/check_secrets.py

# Or test manually
python -c "
import os
os.environ['USE_AWS_SECRETS'] = '1'
os.environ['AWS_SECRET_NAME'] = 'qqqAppsecrets'
from src.aws_secrets import load_secrets_to_env
count = load_secrets_to_env()
print(f'✅ Loaded {count} secrets')
"
```

### Step 5: Install Systemd Services

```bash
# Create log directories
sudo mkdir -p /var/log/discord-bot /var/log/portfolio-api /var/log/portfolio-nightly
sudo chown -R ubuntu:ubuntu /var/log/discord-bot /var/log/portfolio-api /var/log/portfolio-nightly

# Copy service files
sudo cp systemd/*.service /etc/systemd/system/
sudo cp systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload

# Enable services
sudo systemctl enable api.service discord-bot.service nightly-pipeline.timer
```

### Step 6: Configure Nginx and SSL

```bash
# Install nginx config (Ubuntu standard: sites-available + sites-enabled)
sudo cp nginx/api.conf /etc/nginx/sites-available/api.conf
sudo ln -sf /etc/nginx/sites-available/api.conf /etc/nginx/sites-enabled/api.conf

# Remove default site if present
sudo rm -f /etc/nginx/sites-enabled/default

# Test nginx config
sudo nginx -t

# Obtain SSL certificate (requires DNS pointing to this server)
sudo certbot --nginx -d api.llmportfolio.app

# Start nginx
sudo systemctl enable nginx
sudo systemctl start nginx
```

> **Note:** If your nginx uses `/etc/nginx/conf.d/` instead (check with `ls /etc/nginx/`),
> use `sudo cp nginx/api.conf /etc/nginx/conf.d/api.conf` instead.

### Step 7: Start Services

```bash
# Start all services
sudo systemctl start api.service
sudo systemctl start discord-bot.service
sudo systemctl start nightly-pipeline.timer

# Verify status
sudo systemctl status api.service discord-bot.service nightly-pipeline.timer
```

---

## Service Management

### Systemd Services

| Service | Type | Purpose |
|---------|------|---------|
| `api.service` | Long-running | FastAPI backend (port 8000) |
| `discord-bot.service` | Long-running | Discord bot for message collection |
| `nightly-pipeline.service` | One-shot | Daily OHLCV + NLP + SnapTrade sync |
| `nightly-pipeline.timer` | Timer | Triggers nightly pipeline at 1 AM ET |

### Common Commands

```bash
# Check status
sudo systemctl status api.service
sudo systemctl status discord-bot.service
systemctl list-timers

# View logs (real-time)
sudo journalctl -u api.service -f
sudo journalctl -u discord-bot.service -f
sudo journalctl -u nightly-pipeline.service -f

# View last 100 lines
sudo journalctl -u discord-bot.service -n 100

# Restart services
sudo systemctl restart api.service
sudo systemctl restart discord-bot.service

# Stop services
sudo systemctl stop api.service
sudo systemctl stop discord-bot.service
```

---

## Daily Pipeline

The nightly pipeline runs automatically via systemd timer at 1 AM ET:

1. **SnapTrade Sync** - Fetch positions, orders, balances
2. **Discord NLP Processing** - Parse unprocessed messages with OpenAI
3. **OHLCV Backfill** - Fetch daily price bars from Databento

### Manual Run

```bash
cd /home/ubuntu/llm-portfolio
source .venv/bin/activate

# Run all tasks
./scripts/run_pipeline_with_secrets.sh

# Run specific tasks
./scripts/run_pipeline_with_secrets.sh --snaptrade
./scripts/run_pipeline_with_secrets.sh --discord
./scripts/run_pipeline_with_secrets.sh --ohlcv

# Or trigger via systemd
sudo systemctl start nightly-pipeline.service
```

### OHLCV Backfill

```bash
# Last 5 days (default)
python scripts/backfill_ohlcv.py --daily

# Custom date range
python scripts/backfill_ohlcv.py --start 2024-01-01 --end 2024-12-31
```

---

## Health Checks

### API Health Endpoint

```bash
# Via nginx (HTTPS)
curl https://api.llmportfolio.app/health

# Local (direct)
curl http://127.0.0.1:8000/health
```

### Database Connectivity

```bash
python -c "from src.db import healthcheck; print('DB OK' if healthcheck() else 'DB FAIL')"
```

### Secrets Access

```bash
python scripts/check_secrets.py
```

### Preflight Check (Full System)

```bash
./scripts/preflight_ec2.sh
```

---

## Log Files

| Log | Location | Command |
|-----|----------|---------|
| API server | `/var/log/portfolio-api/combined.log` | `tail -f /var/log/portfolio-api/combined.log` |
| Discord bot | `/var/log/discord-bot/combined.log` | `tail -f /var/log/discord-bot/combined.log` |
| Nightly pipeline | `/var/log/portfolio-nightly/combined.log` | `sudo journalctl -u nightly-pipeline.service -f` |
| Nginx access | `/var/log/nginx/api_access.log` | `tail -f /var/log/nginx/api_access.log` |
| Nginx error | `/var/log/nginx/api_error.log` | `tail -f /var/log/nginx/api_error.log` |

---

## Troubleshooting

### Service Won't Start - Missing Env File

```
ExecStartPre=/usr/bin/test -f /etc/llm-portfolio/llm.env failed
```

**Solution:** Create the required env file:
```bash
sudo mkdir -p /etc/llm-portfolio
sudo tee /etc/llm-portfolio/llm.env > /dev/null << 'EOF'
USE_AWS_SECRETS=1
AWS_REGION=us-east-1
AWS_SECRET_NAME=qqqAppsecrets
EOF
sudo chmod 644 /etc/llm-portfolio/llm.env
```

### Bot Won't Start

```bash
# Check logs
sudo journalctl -u discord-bot.service -n 50

# Test manually
cd /home/ubuntu/llm-portfolio
source .venv/bin/activate
python scripts/start_bot_with_secrets.py
```

### Secrets Not Loading

```bash
# Check IAM role
curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/

# Verify secret exists
aws secretsmanager describe-secret --secret-id qqqAppsecrets

# Run secrets check
python scripts/check_secrets.py
```

### Database Connection Issues

```bash
# Test connection
python -c "from src.db import healthcheck, get_database_size; print(f'Health: {healthcheck()}, Size: {get_database_size()}')"

# Check security group allows outbound 6543 (Supabase pooler)
```

### Nginx/SSL Issues

```bash
# Test nginx config
sudo nginx -t

# Check certificate status
sudo certbot certificates

# Renew certificate
sudo certbot renew --force-renewal
```

---

## Updates

```bash
# Pull latest code
cd /home/ubuntu/llm-portfolio
git pull

# Update dependencies
source .venv/bin/activate
pip install -r requirements.txt

# Restart services
sudo systemctl restart api.service discord-bot.service
```

---

## Cost Optimization

| Resource | Cost (monthly) |
|----------|----------------|
| EC2 t3.micro | ~$8 |
| EC2 t3.small | ~$15 |
| Secrets Manager | ~$0.40/secret |
| Databento | Pay-per-query |

**Typical monthly cost: ~$10-20**

---

## Files Reference

| File | Purpose |
|------|---------|
| `systemd/api.service` | FastAPI systemd service |
| `systemd/discord-bot.service` | Discord bot systemd service |
| `systemd/nightly-pipeline.service` | Nightly pipeline service |
| `systemd/nightly-pipeline.timer` | Nightly pipeline timer (1 AM ET) |
| `nginx/api.conf` | Nginx reverse proxy config |
| `scripts/bootstrap.sh` | Automated EC2 setup |
| `scripts/check_secrets.py` | AWS Secrets Manager validation |
| `scripts/preflight_ec2.sh` | EC2 readiness check |
| `scripts/start_bot_with_secrets.py` | Bot startup with secrets |
| `scripts/run_pipeline_with_secrets.sh` | Pipeline wrapper |
| `src/aws_secrets.py` | AWS Secrets Manager helper |
