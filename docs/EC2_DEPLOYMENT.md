# EC2 Deployment Guide

> **Last Updated:** February 8, 2026
> **Target:** Ubuntu 22.04 LTS (or 24.04 LTS)

This guide covers deploying the LLM Portfolio Journal to EC2 with:
- AWS Secrets Manager for secure credential storage
- Discord bot and FastAPI server running continuously via systemd
- Reliable daily data pipeline via systemd timers
- Nginx reverse proxy with SSL (Certbot)
- OHLCV backfill from Databento

> **Frontend Note:** The Next.js frontend is deployed automatically via **Vercel** on every push to `LLM-portfolio-frontend/main`. No EC2 steps are needed for frontend changes. Vercel reads environment variables (`NEXT_PUBLIC_API_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `NEXTAUTH_SECRET`, `ALLOWED_EMAILS`, `API_SECRET_KEY`) from its project settings.

---

## Updating an Existing EC2 (Quick Redeploy)

If you already have an EC2 running and want to deploy the latest code changes:

```bash
ssh ubuntu@your-ec2-ip
cd /home/ubuntu/llm-portfolio

# 1. Pull latest code
git pull origin main

# 2. Update Python dependencies
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

# 3. Update systemd service files (if changed)
sudo cp systemd/*.service /etc/systemd/system/
sudo cp systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload

# 4. Update Nginx config (if changed)
sudo cp nginx/api.conf /etc/nginx/sites-available/api.conf
sudo nginx -t && sudo systemctl reload nginx

# 5. Run database migrations
#    The deployer auto-detects fresh vs existing databases.
#    Fresh install: runs 060_baseline_current.sql then incremental migrations.
#    Existing DB:   skips baseline, runs only unapplied 06N_*.sql files.
#    Stops on first failure; never edit an applied migration.
python scripts/deploy_database.py
python scripts/verify_database.py

# 6. Ensure API_SECRET_KEY is in AWS Secrets Manager (required for auth)
# Add to qqqAppsecrets if not already present:
#   "API_SECRET_KEY": "your-secure-random-key"
# The Vercel frontend sends this as: Authorization: Bearer <API_SECRET_KEY>

# 7. Restart all services
sudo systemctl restart api.service discord-bot.service
sudo systemctl restart nightly-pipeline.timer

# 8. Verify everything is running
sudo systemctl status api.service discord-bot.service nightly-pipeline.timer
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
sudo journalctl -u api.service -n 20 --no-pager
```

### Post-Deploy Smoke Tests

```bash
# Health check
curl -s http://127.0.0.1:8000/health

# Portfolio (requires auth in production)
curl -s -H "Authorization: Bearer YOUR_API_SECRET_KEY" http://127.0.0.1:8000/portfolio | python3 -m json.tool | head -30

# Orders
curl -s -H "Authorization: Bearer YOUR_API_SECRET_KEY" "http://127.0.0.1:8000/orders?limit=5" | python3 -m json.tool | head -30

# Stock profile (use a symbol you have in positions)
curl -s -H "Authorization: Bearer YOUR_API_SECRET_KEY" http://127.0.0.1:8000/stocks/ABNB | python3 -m json.tool

# OHLCV (only works if ohlcv_daily has data for the symbol)
curl -s -H "Authorization: Bearer YOUR_API_SECRET_KEY" "http://127.0.0.1:8000/stocks/ABNB/ohlcv?period=1M" | python3 -m json.tool

# Ideas
curl -s -H "Authorization: Bearer YOUR_API_SECRET_KEY" "http://127.0.0.1:8000/stocks/ABNB/ideas?limit=5" | python3 -m json.tool
```

### OHLCV Data Backfill

If charts show no data, you need to backfill. The nightly timer only fetches the last 5 days:

```bash
source .venv/bin/activate

# Backfill last 5 days (default)
python scripts/backfill_ohlcv.py --daily

# Backfill new symbols (90 days for any positions missing OHLCV data)
python scripts/backfill_ohlcv.py --new-symbols

# Backfill a full year for chart coverage
python scripts/backfill_ohlcv.py --start 2025-02-01 --end 2026-02-08

# Verify data loaded
python -c "
from src.db import execute_sql
rows = execute_sql('SELECT symbol, COUNT(*) FROM ohlcv_daily GROUP BY 1 ORDER BY 2 DESC LIMIT 5', fetch_results=True)
for r in rows: print(dict(r._mapping))
"
```

### Session 8 Post-Push (Feb 8, 2026) — Copy-Paste Block

This session's backend changes: webhook signature hardening (single canonical `Signature` header, removed deprecated `X-SnapTrade-Signature` fallback) and nginx security hardening (scanner blocking, method filtering, docs hiding). No new schema migrations. No backend Python dependency changes.

> **Frontend:** The new UI components (CursorTrail, StarfieldBackground, SigninIntro, scroll-snap CSS) deploy automatically via Vercel on push to `LLM-portfolio-frontend/main`. No EC2 action required for frontend.

```bash
ssh -i "~/.ssh/backfillkey.pem" ubuntu@ec2-3-80-44-55.compute-1.amazonaws.com
cd /home/ubuntu/llm-portfolio

# Pull + redeploy (no new deps or migrations)
git pull origin main
source .venv/bin/activate

# Update nginx config (scanner blocking, method filtering, docs hiding)
sudo cp nginx/api.conf /etc/nginx/sites-available/api.conf
sudo nginx -t && sudo systemctl reload nginx

# Restart API (webhook hardening: canonical Signature header only)
sudo systemctl restart api.service

# Quick smoke test
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
sudo systemctl status api.service discord-bot.service --no-pager
sudo journalctl -u api.service -n 10 --no-pager
```

---

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

### Database Migrations

The project follows an **immutable-ledger** migration strategy:

| Directory | Purpose |
|-----------|---------|
| `schema/060_baseline_current.sql` | Full `pg_dump --schema-only` snapshot for fresh installs |
| `schema/061_*.sql`, `062_*.sql` … | Incremental migrations (never edited once applied) |
| `schema/archive/` | Retired migrations 000–059 (reference only, never executed) |

**How the deployer works** (`scripts/deploy_database.py`):
1. Checks if any user tables exist in `public` schema.
2. **Empty DB** → runs the baseline, then all incremental migrations.
3. **Existing DB** → skips baseline, runs only unapplied `06N_*.sql` files.
4. Tracks applied migrations by exact filename stem in `schema_migrations`.
5. Stops on first failure; uses raw psycopg2 (no SQL splitting).

**Creating a new migration:** add `schema/06N_descriptive_name.sql` with the next available number.
Never edit an already-applied file—always create a new one.

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
  "DATABENTO_API_KEY": "db-your_databento_key",
  "API_SECRET_KEY": "your-secure-random-key",
  "ENVIRONMENT": "production"
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
# Enable persistent journald storage (recommended)
sudo mkdir -p /var/log/journal
sudo systemctl restart systemd-journald

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

## Nightly Pipeline (Canonical)

The nightly pipeline runs automatically via systemd timer at 1 AM ET:

1. **SnapTrade Sync** - Fetch positions, orders, balances (optional - see below)
2. **OHLCV Backfill** - Fetch daily price bars from Databento
   - 2a. **New Symbol Auto-Detect** - Backfill 90 days for any new position symbols missing from `ohlcv_daily`
3. **NLP Batch Processing** - Parse unprocessed messages with OpenAI
4. **Stock Profile Refresh** - Optional refresh if script exists (600s timeout, non-fatal)

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REQUIRE_SNAPTRADE` | `0` | Set to `1` to abort pipeline on SnapTrade failure |
| `BATCH_OUTPUT_DIR` | `logs/batch_output` | Directory for NLP batch processing output |

### SnapTrade Behavior

By default (`REQUIRE_SNAPTRADE=0`), SnapTrade sync failures are logged but don't abort the pipeline. The pipeline:
1. Runs a smoke test (`verify_user_auth()`) before full sync
2. Logs debug-safe credential info (key presence, not values)
3. Continues to OHLCV/NLP steps even if SnapTrade fails

Set `REQUIRE_SNAPTRADE=1` in AWS Secrets Manager to make SnapTrade failures fatal.

### Databento OHLCV Handling

The pipeline handles Databento's `data_end_after_available_end` error automatically by:
1. Parsing the available end date from the error message
2. Clamping the request to the available range
3. Retrying with the adjusted date range

### Manual Run

```bash
cd /home/ubuntu/llm-portfolio
source .venv/bin/activate

# Run the canonical pipeline directly
python scripts/nightly_pipeline.py

# Or trigger via systemd
sudo systemctl start nightly-pipeline.service

# Test SnapTrade auth before running
python -c "
from src.snaptrade_collector import SnapTradeCollector
c = SnapTradeCollector()
c.log_credentials_debug_info()
success, msg = c.verify_user_auth()
print(f'Auth: {success}, {msg}')
"
```



### OHLCV Backfill

```bash
# Last 5 days (default)
python scripts/backfill_ohlcv.py --daily

# Custom date range
python scripts/backfill_ohlcv.py --start 2024-01-01 --end 2024-12-31

# Backfill new symbols only (90 days, auto-detects from positions table)
python scripts/backfill_ohlcv.py --new-symbols
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
| API server | journald | `sudo journalctl -u api.service -f` |
| Discord bot | journald | `sudo journalctl -u discord-bot.service -f` |
| Nightly pipeline | journald | `sudo journalctl -u nightly-pipeline.service -f` |
| Nginx access | `/var/log/nginx/api_access.log` | `tail -f /var/log/nginx/api_access.log` |
| Nginx error | `/var/log/nginx/api_error.log` | `tail -f /var/log/nginx/api_error.log` |

---

## Journald Logging (Existing Instances)

If an older instance still writes to `/var/log/portfolio-*`, migrate to journald-only:

```bash
# 1) Enable persistent journald storage
sudo mkdir -p /var/log/journal

# 2) Add a production journald config (optional but recommended)
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

# 3) Restart journald
sudo systemctl restart systemd-journald

# 4) Redeploy systemd units from repo (they log to journald)
sudo cp /home/ubuntu/llm-portfolio/systemd/*.service /etc/systemd/system/
sudo cp /home/ubuntu/llm-portfolio/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload

# 5) Restart services
sudo systemctl restart api.service discord-bot.service
sudo systemctl restart nightly-pipeline.timer
```


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

### SnapTrade Auth Failures (401/1076 Error)

```bash
# Run debug-safe credential check
python -c "
from src.snaptrade_collector import SnapTradeCollector
c = SnapTradeCollector()
c.log_credentials_debug_info()
success, msg = c.verify_user_auth()
print(f'Auth: {success}, Message: {msg}')
"
```

**Common causes:**
- **Missing `SNAPTRADE_CLIENT_SECRET`** - Add to AWS Secrets Manager
- **Expired user secret** - Regenerate in SnapTrade portal
- **Wrong `SNAPTRADE_USER_ID`** - Verify matches your account

**Secrets Manager keys required:**
```json
{
  "SNAPTRADE_CLIENT_ID": "your_client_id",
  "SNAPTRADE_CONSUMER_KEY": "your_consumer_key",
  "SNAPTRADE_CLIENT_SECRET": "your_client_secret",
  "SNAPTRADE_USER_ID": "your_user_id",
  "SNAPTRADE_USER_SECRET": "your_user_secret"
}
```

**To continue pipeline without SnapTrade:** Leave `REQUIRE_SNAPTRADE=0` (default).

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
| `scripts/nightly_pipeline.py` | Canonical nightly pipeline orchestrator |
| `src/aws_secrets.py` | AWS Secrets Manager helper |
| `src/snaptrade_collector.py` | SnapTrade API integration |

### EC2 Directories

| Directory | Purpose |
|-----------|---------|
| `/var/log/journal/` | Persistent journald storage |
| `/home/ubuntu/llm-portfolio/logs/` | Optional local artifacts (if generated) |
| `/home/ubuntu/llm-portfolio/logs/batch_output/` | NLP batch processing output |
| `/home/ubuntu/llm-portfolio/charts/` | Chart image output |
