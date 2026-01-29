# EC2 Backend Deployment Guide

Complete step-by-step guide for deploying the LLM Portfolio Journal backend to EC2.

## Prerequisites

- AWS EC2 instance (Ubuntu 22.04+ recommended)
- Domain name pointed to your EC2 IP: `api.llmportfolio.app`
- AWS Secrets Manager secrets configured
- SSH access to EC2

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Ubuntu EC2 Instance                       │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Nginx      │───▶│   FastAPI    │    │  Discord Bot │  │
│  │  (SSL/443)   │    │  (8000)      │    │  (systemd)   │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│          │                   │                   │          │
│          │                   ▼                   ▼          │
│          │           ┌──────────────────────────────┐       │
│          │           │        Supabase              │       │
│          │           │      (PostgreSQL)            │       │
│          └──────────▶│   - All OHLCV data          │       │
│                      │   - Positions, Orders       │       │
│                      │   - Discord messages        │       │
│                      └──────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

## Table of Contents

1. [Automated Setup (Recommended)](#1-automated-setup-recommended)
2. [Manual Setup](#2-manual-setup)
3. [Configure AWS Secrets](#3-configure-aws-secrets)
4. [Install Nginx and SSL](#4-install-nginx-and-ssl)
5. [Start Services](#5-start-services)
6. [Verify Deployment](#6-verify-deployment)
7. [Updates and Maintenance](#7-updates-and-maintenance)

---

## 1. Automated Setup (Recommended)

### SSH into your EC2 instance

```bash
ssh -i ~/.ssh/your-key.pem ubuntu@your-ec2-ip
```

### Run the bootstrap script

```bash
# Clone the repository first
cd /home/ubuntu
git clone https://github.com/YOUR_USERNAME/LLM-portfolio-project.git llm-portfolio
cd llm-portfolio

# Run automated setup
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh
```

The bootstrap script will:
- Install Python 3.12, Node.js 20, and all dependencies
- Create virtual environment and install Python packages
- Configure Nginx with your domain
- Set up SSL with Certbot
- Create systemd services for API, Discord bot, and scheduled tasks

**Skip to [Configure AWS Secrets](#3-configure-aws-secrets) after bootstrap completes.**

---

## 2. Manual Setup

If you prefer manual installation or need to customize:

### Update system packages

```bash
sudo apt update && sudo apt upgrade -y
```

### Install Python 3.12

```bash
# Add deadsnakes PPA
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update

# Install Python 3.12
sudo apt install -y \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    libpq-dev \
    build-essential
```

### Install Node.js 20 (for frontend)

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pm2
```

### Clone and setup project

```bash
cd /home/ubuntu
git clone https://github.com/YOUR_USERNAME/LLM-portfolio-project.git llm-portfolio
cd llm-portfolio

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

---

## 3. Configure AWS Secrets

### Required Secrets in AWS Secrets Manager

Create a secret named `llm-portfolio/production` with these keys:

```json
{
    "API_SECRET_KEY": "your-generated-key-here",
    "DATABASE_URL": "postgresql://postgres.xxx:password@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
    "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_xxx",
    "SUPABASE_URL": "https://xxx.supabase.co",
    "SUPABASE_KEY": "eyJxxx",
    "OPENAI_API_KEY": "sk-xxx",
    "DISCORD_BOT_TOKEN": "xxx",
    "LOG_CHANNEL_IDS": "123,456",
    "SNAPTRADE_CLIENT_ID": "xxx",
    "SNAPTRADE_CONSUMER_KEY": "xxx",
    "SNAPTRADE_CLIENT_SECRET": "xxx",
    "SNAPTRADE_USER_ID": "xxx",
    "SNAPTRADE_USER_SECRET": "xxx",
    "DATABENTO_API_KEY": "db-xxx"
}
```

### Generate API Secret Key

```bash
openssl rand -hex 32
```

### IAM Role Policy

Attach this policy to your EC2 instance's IAM role:

```json
{
    "Effect": "Allow",
    "Action": [
        "secretsmanager:GetSecretValue"
    ],
    "Resource": [
        "arn:aws:secretsmanager:us-east-1:*:secret:llm-portfolio/*"
    ]
}
```

### Verify secrets are accessible

```bash
cd /home/ubuntu/llm-portfolio
source .venv/bin/activate
python -c "
import os
os.environ['USE_AWS_SECRETS'] = '1'
from src.aws_secrets import load_secrets_to_env
load_secrets_to_env()
print('DATABASE_URL:', 'SET' if os.getenv('DATABASE_URL') else 'MISSING')
print('API_SECRET_KEY:', 'SET' if os.getenv('API_SECRET_KEY') else 'MISSING')
print('OPENAI_API_KEY:', 'SET' if os.getenv('OPENAI_API_KEY') else 'MISSING')
"
```

---

## 4. Install Nginx and SSL

### Install Nginx

```bash
sudo apt install -y nginx
```

### Copy Nginx configuration

```bash
sudo cp /home/ubuntu/llm-portfolio/nginx/api.conf /etc/nginx/conf.d/api.conf

# Update domain (already set to api.llmportfolio.app)
sudo sed -i 's/YOUR_DOMAIN/api.llmportfolio.app/g' /etc/nginx/conf.d/api.conf

# Remove default site
sudo rm -f /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t
```

### Obtain SSL certificate

```bash
# Make sure DNS is pointing to this server first!
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.llmportfolio.app
```

### Start Nginx

```bash
sudo systemctl start nginx
sudo systemctl enable nginx
```

---

## 5. Start Services

### Create systemd services (if not using bootstrap)

```bash
# The bootstrap script creates these automatically
# See scripts/bootstrap.sh for service definitions
```

### Start API server

```bash
sudo systemctl start llm-api
sudo systemctl status llm-api
```

### Start Discord bot

```bash
sudo systemctl start discord-bot
sudo systemctl status discord-bot
```

### Start scheduled timers

```bash
# OHLCV daily update (6 AM UTC)
sudo systemctl start ohlcv-daily.timer
sudo systemctl enable ohlcv-daily.timer

# SnapTrade sync (every 5 minutes)
sudo systemctl start snaptrade-notify.timer
sudo systemctl enable snaptrade-notify.timer
```

### Verify all services

```bash
# Check all services
sudo systemctl status llm-api discord-bot ohlcv-daily.timer snaptrade-notify.timer

# View logs
sudo journalctl -u llm-api -f
sudo journalctl -u discord-bot -f
```

---

## 6. Verify Deployment

### Test health endpoint

```bash
# Via Nginx (HTTPS)
curl https://api.llmportfolio.app/api/health

# Local (direct)
curl http://127.0.0.1:8000/api/health
```

### Test authenticated endpoint

```bash
# Without auth (should fail)
curl https://api.llmportfolio.app/api/portfolio
# Expected: {"detail":"Not authenticated"}

# With auth
curl -H "Authorization: Bearer YOUR_API_SECRET_KEY" \
     https://api.llmportfolio.app/api/portfolio
```

### Test database connectivity

```bash
cd /home/ubuntu/llm-portfolio
source .venv/bin/activate
python -c "from src.db import healthcheck; print('DB OK' if healthcheck() else 'DB FAIL')"
```

### Test OHLCV data

```bash
python -c "
from src.price_service import get_latest_close
price = get_latest_close('AAPL')
print(f'AAPL latest close: ${price:.2f}' if price else 'No data')
"
```

---

## 7. Updates and Maintenance

### Pull and deploy updates

```bash
cd /home/ubuntu/llm-portfolio

# Pull latest changes
git pull origin main

# Update dependencies
source .venv/bin/activate
pip install -r requirements.txt

# Restart services
sudo systemctl restart llm-api
sudo systemctl restart discord-bot
```

### View logs

```bash
# API logs
sudo journalctl -u llm-api -f

# Discord bot logs
sudo journalctl -u discord-bot -f

# OHLCV update logs
sudo journalctl -u ohlcv-daily -f
```

### Manual OHLCV backfill

```bash
cd /home/ubuntu/llm-portfolio
source .venv/bin/activate

# Last 5 days
python scripts/backfill_ohlcv.py --daily

# Full historical backfill
python scripts/backfill_ohlcv.py --full

# Custom date range
python scripts/backfill_ohlcv.py --start 2024-01-01 --end 2024-12-31
```

---

## Security Checklist

- [ ] EC2 security group only allows ports 22, 80, 443
- [ ] API binds to 127.0.0.1 (not accessible directly from internet)
- [ ] SSL certificate installed and auto-renewing
- [ ] API_SECRET_KEY stored in AWS Secrets Manager (not in code)
- [ ] IAM role has minimal required permissions
- [ ] Nginx has rate limiting configured

---

## Troubleshooting

### API won't start

```bash
# Check logs
sudo journalctl -u llm-api -n 50

# Test manually
cd /home/ubuntu/llm-portfolio
source .venv/bin/activate
USE_AWS_SECRETS=1 python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### SSL certificate issues

```bash
# Check certificate status
sudo certbot certificates

# Renew manually
sudo certbot renew --force-renewal

# Check Nginx error log
sudo tail -f /var/log/nginx/error.log
```

### Secrets not loading

```bash
# Verify IAM role is attached
curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/

# Test secrets access
aws secretsmanager get-secret-value --secret-id llm-portfolio/production --region us-east-1
```

### Database connection issues

```bash
source .venv/bin/activate
python -c "
from src.db import healthcheck, get_database_size
print('Health:', healthcheck())
print('Size:', get_database_size())
"
```
