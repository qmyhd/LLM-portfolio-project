# EC2 Deployment Guide

> **Last Updated:** January 23, 2026  
> **Target:** Amazon Linux 2023 on t4g.micro (ARM64)

This guide covers deploying the LLM Portfolio Journal to EC2 with:
- AWS Secrets Manager for secure credential storage
- Discord bot running continuously via PM2 or systemd
- Reliable daily data pipeline via cron jobs
- OHLCV backfill from Databento

## Current Production Configuration

| Secret | Name | Purpose |
|--------|------|---------|
| Main App | `qqqAppsecrets` | Discord, OpenAI, Supabase, SnapTrade, Databento |
| RDS Database | `RDS/ohlcvdata` | OHLCV PostgreSQL credentials |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        AWS EC2 (t4g.micro)                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐     ┌─────────────────┐                   │
│  │   PM2/systemd   │     │   Cron Jobs     │                   │
│  │  Discord Bot    │     │  Daily Pipeline │                   │
│  └────────┬────────┘     └────────┬────────┘                   │
│           │                       │                             │
│           └───────────┬───────────┘                             │
│                       │                                         │
│               ┌───────▼───────┐                                 │
│               │ AWS Secrets   │                                 │
│               │   Manager     │                                 │
│               └───────────────┘                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
     ┌──────────┐       ┌──────────┐       ┌──────────┐
     │ Supabase │       │  OpenAI  │       │ SnapTrade│
     │ (RDS/S3) │       │   API    │       │   API    │
     └──────────┘       └──────────┘       └──────────┘
```

## Prerequisites

### AWS Resources
- **EC2 Instance**: t4g.micro (ARM64) recommended (~$6/month)
- **IAM Role**: Attached to EC2 with these permissions:
  - `secretsmanager:GetSecretValue` for your secrets
  - `s3:GetObject`, `s3:PutObject` for OHLCV bucket (optional)
- **Security Group**: Allow outbound HTTPS (443)
- **Secrets Manager Secrets**: 
  - `qqqAppsecrets` - Main app secrets (Discord, OpenAI, Supabase, etc.)
  - `RDS/ohlcvdata` - RDS database credentials for OHLCV

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
  "SNAPTRADE_USER_ID": "your_user_id",
  "SNAPTRADE_USER_SECRET": "your_user_secret",
  "TWITTER_BEARER_TOKEN": "your_twitter_token",
  "DATABENTO_API_KEY": "db-your_databento_key"
}
```

**RDS Secret (`RDS/ohlcvdata`)** - AWS RDS format:

```json
{
  "host": "your-db.region.rds.amazonaws.com",
  "port": 5432,
  "username": "postgres",
  "password": "your_rds_password",
  "dbname": "postgres"
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
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:*:secret:qqqAppsecrets*",
        "arn:aws:secretsmanager:us-east-1:*:secret:RDS/ohlcvdata*"
      ]
    }
  ]
}
```

---

## Quick Start (User Data)

The easiest way to deploy is using EC2 User Data for automatic setup.

### Option 1: Launch Template with User Data

1. Copy the contents of `scripts/ec2_user_data.sh`
2. Create an EC2 Launch Template
3. Paste the script in **User Data** section
4. Launch instance with the template

### Option 2: Manual Launch with User Data

```bash
aws ec2 run-instances \
  --image-id ami-0c101f26f147fa7fd \
  --instance-type t4g.micro \
  --iam-instance-profile Name=llm-portfolio-role \
  --user-data file://scripts/ec2_user_data.sh \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=llm-portfolio}]'
```

---

## Manual Setup

If you prefer manual setup instead of User Data:

### Step 1: SSH and Clone

```bash
ssh ec2-user@your-ec2-host

# Clone repository
git clone https://github.com/qmyhd/LLM-portfolio-project.git
cd LLM-portfolio-project

# Setup Python environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install boto3  # Required for AWS Secrets Manager
```

### Step 2: Configure AWS Secrets Manager

Create a `.env` file that signals to use AWS Secrets Manager:

```bash
cat > .env << 'EOF'
# AWS Secrets Manager Configuration
USE_AWS_SECRETS=1
AWS_REGION=us-east-1

# Main app secrets (Discord, OpenAI, Supabase, SnapTrade, Databento)
AWS_SECRET_NAME=qqqAppsecrets

# RDS secrets (OHLCV database) - loaded separately
AWS_RDS_SECRET_NAME=RDS/ohlcvdata
EOF
```

### Step 3: Test Secrets Access

```bash
python -c "
import os
os.environ['USE_AWS_SECRETS'] = '1'
os.environ['AWS_SECRET_NAME'] = 'qqqAppsecrets'
os.environ['AWS_RDS_SECRET_NAME'] = 'RDS/ohlcvdata'
from src.aws_secrets import load_secrets_to_env
count = load_secrets_to_env()
print(f'Loaded {count} secrets')
print(f'RDS_HOST: {os.environ.get(\"RDS_HOST\", \"NOT SET\")}')
"
```

### Step 4: Run Setup Script

```bash
chmod +x scripts/setup_ec2_services.sh
./scripts/setup_ec2_services.sh --pm2
```

---

## Discord Bot - Continuous Running

### Option 1: PM2 (Recommended)

PM2 is a process manager that automatically restarts your bot if it crashes.

```bash
# Start bot (loads secrets from AWS Secrets Manager)
pm2 start ecosystem.config.js

# Configure auto-start on boot
pm2 save
pm2 startup

# Useful commands
pm2 status              # Check status
pm2 logs discord-bot    # View logs
pm2 restart discord-bot # Restart
pm2 stop discord-bot    # Stop
```

### Option 2: systemd

For deeper OS integration:

```bash
# Copy service file
sudo cp docker/discord-bot.service /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable discord-bot
sudo systemctl start discord-bot

# Useful commands
sudo systemctl status discord-bot
sudo journalctl -u discord-bot -f
```

---

## Daily Data Pipeline

The daily pipeline runs three tasks with file-based locking to prevent concurrent runs:

1. **SnapTrade Sync** - Fetch positions, orders, balances
2. **Discord NLP Processing** - Parse unprocessed messages with OpenAI
3. **OHLCV Backfill** - Fetch daily price bars from Databento

### Manual Run

```bash
cd /home/ec2-user/LLM-portfolio-project
source .venv/bin/activate

# Run all tasks
./scripts/run_pipeline_with_secrets.sh

# Run specific tasks
./scripts/run_pipeline_with_secrets.sh --snaptrade
./scripts/run_pipeline_with_secrets.sh --discord
./scripts/run_pipeline_with_secrets.sh --ohlcv

# Dry run (preview only)
./scripts/run_pipeline_with_secrets.sh --dry-run
```

### Cron Schedule

The setup script configures these cron jobs (all times in UTC):

| Time (UTC) | Time (ET) | Task | Description |
|------------|-----------|------|-------------|
| 06:00 | 01:00 AM | Full pipeline | SnapTrade + Discord NLP + OHLCV |
| 01:00 | 08:00 PM | SnapTrade only | End-of-day positions |
| */5 * * * * | Every 5 min | Health check | Restart bot if unresponsive |

View cron jobs:
```bash
crontab -l
```

### Manual Cron Entry

```bash
crontab -e

# Add these lines:
0 6 * * * /home/ec2-user/LLM-portfolio-project/scripts/run_pipeline_with_secrets.sh >> /var/log/discord-bot/daily_pipeline.log 2>&1
0 1 * * * /home/ec2-user/LLM-portfolio-project/scripts/run_pipeline_with_secrets.sh --snaptrade >> /var/log/discord-bot/snaptrade_sync.log 2>&1
*/5 * * * * pm2 ping discord-bot >/dev/null 2>&1 || pm2 restart discord-bot
```

---

## OHLCV Backfill

For historical data backfill:

```bash
# Last 5 days (default)
python scripts/backfill_ohlcv.py --daily

# Custom date range
python scripts/backfill_ohlcv.py --start 2024-01-01 --end 2024-12-31
```

---

## Log Files

| Log | Location |
|-----|----------|
| Discord bot | `/var/log/discord-bot/combined.log` |
| Bot errors | `/var/log/discord-bot/error.log` |
| Daily pipeline | `/var/log/discord-bot/daily_pipeline.log` |
| SnapTrade sync | `/var/log/discord-bot/snaptrade_sync.log` |
| EC2 User Data | `/var/log/user-data.log` |

View logs in real-time:
```bash
tail -f /var/log/discord-bot/combined.log
pm2 logs discord-bot
```

---

## Monitoring & Health Checks

### Check Bot Status

```bash
# PM2
pm2 status
pm2 describe discord-bot

# systemd
sudo systemctl status discord-bot
```

### Check Database Connectivity

```bash
python -c "from src.db import healthcheck; print(healthcheck())"
```

### Check Pipeline Status

```bash
cat data/.pipeline_status.json
```

### Check AWS Secrets Access

```bash
python -c "
from src.aws_secrets import fetch_secret
secrets = fetch_secret('llm-portfolio/production')
print(f'Secret has {len(secrets)} keys')
"
```

---

## Troubleshooting

### Bot Won't Start

1. Check PM2 logs: `pm2 logs discord-bot`
2. Verify IAM role has `secretsmanager:GetSecretValue`
3. Test secrets: `python -c "from src.aws_secrets import load_secrets_to_env; print(load_secrets_to_env())"`
4. Test manually: `python scripts/start_bot_with_secrets.py`

### Pipeline Fails

1. Check log: `tail -100 /var/log/discord-bot/daily_pipeline.log`
2. Check for lock file: `ls -la data/.pipeline.lock`
3. Test individual tasks:
   ```bash
   ./scripts/run_pipeline_with_secrets.sh --snaptrade --dry-run
   ```

### Secrets Not Loading

1. Check IAM role attached to EC2: `curl http://169.254.169.254/latest/meta-data/iam/security-credentials/`
2. Verify secret exists: `aws secretsmanager describe-secret --secret-id llm-portfolio/production`
3. Check region: Ensure `AWS_REGION` matches secret location

### Database Connection Issues

1. Test secrets loaded: Check for `DATABASE_URL` in environment
2. Check security group allows outbound 6543 (Supabase pooler)
3. Test: `python -c "from src.db import test_connection; print(test_connection())"`

---

## Alternative: Lambda + EventBridge (Serverless)

For a fully serverless, decoupled architecture with no EC2 management:

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     EventBridge (Scheduler)                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐   │
│  │ Every 30 min    │ │ Every 15 min    │ │ Daily 5:30 PM   │   │
│  │ (market hours)  │ │                 │ │ (after close)   │   │
│  └────────┬────────┘ └────────┬────────┘ └────────┬────────┘   │
│           ▼                   ▼                   ▼             │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐   │
│  │  SnapTrade      │ │  Discord NLP    │ │  OHLCV          │   │
│  │  Sync Lambda    │ │  Lambda         │ │  Backfill       │   │
│  └────────┬────────┘ └────────┬────────┘ └────────┬────────┘   │
│           │                   │                   │             │
│           └───────────┬───────┴───────────────────┘             │
│                       ▼                                         │
│               ┌───────────────┐                                 │
│               │ AWS Secrets   │                                 │
│               │   Manager     │                                 │
│               └───────────────┘                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                               │
       ┌───────────────────────┼───────────────────────┐
       ▼                       ▼                       ▼
┌──────────┐            ┌──────────┐            ┌──────────┐
│ Supabase │            │   RDS    │            │    S3    │
│ (main)   │            │ (OHLCV)  │            │ (archive)│
└──────────┘            └──────────┘            └──────────┘
```

### Benefits

| Aspect | EC2 + Cron | Lambda + EventBridge |
|--------|------------|----------------------|
| Cost | ~$20/month fixed | Pay-per-invocation (~$5/month) |
| Scaling | Manual | Automatic |
| Maintenance | OS updates, restarts | Zero |
| Reliability | Single point of failure | Highly available |
| Cold starts | None | ~500ms |

### Quick Deploy with SAM

The project includes a SAM template for deploying all Lambda functions:

```bash
# Install AWS SAM CLI
pip install aws-sam-cli

# Deploy (development environment)
python scripts/deploy_lambdas.py --env development

# Deploy (production with guided setup)
python scripts/deploy_lambdas.py --env production --guided

# Validate template only
python scripts/deploy_lambdas.py --validate-only
```

### Lambda Functions Created

| Function | Schedule | Purpose |
|----------|----------|---------|
| `snaptrade-sync` | Every 30 min (market hours) | Sync positions, orders, balances |
| `discord-nlp` | Every 15 min | Process pending Discord messages |
| `ohlcv-backfill` | Daily 5:30 PM EST | Fetch daily OHLCV from Databento |

### EventBridge Rules (Cron Expressions)

```yaml
# SnapTrade: Every 30 min, 9 AM - 4:30 PM EST (Mon-Fri)
Schedule: cron(0/30 14-21 ? * MON-FRI *)

# Discord NLP: Every 15 min (24/7)
Schedule: rate(15 minutes)

# OHLCV: Daily 5:30 PM EST (Mon-Fri)  
Schedule: cron(30 22 ? * MON-FRI *)
```

### Manual Invocation

```bash
# Invoke SnapTrade sync
aws lambda invoke \
  --function-name llm-portfolio-snaptrade-sync-production \
  --payload '{}' \
  response.json

# Invoke Discord NLP with custom batch size
aws lambda invoke \
  --function-name llm-portfolio-discord-nlp-production \
  --payload '{"batch_size": 100, "dry_run": false}' \
  response.json

# Invoke OHLCV backfill for specific date
aws lambda invoke \
  --function-name llm-portfolio-ohlcv-backfill-production \
  --payload '{"start_date": "2025-01-17", "end_date": "2025-01-17"}' \
  response.json
```

### RDS Connection Support

Lambda functions can connect to RDS using environment-based credentials:

```json
// In your Secrets Manager secret
{
  "RDS_HOST": "your-db.region.rds.amazonaws.com",
  "RDS_PORT": "5432",
  "RDS_DATABASE": "postgres",
  "RDS_USER": "postgres",
  "RDS_PASSWORD": "your_password"
}
```

The `src/aws_secrets.py` module builds the connection URL automatically:

```python
from src.aws_secrets import get_rds_connection_url

rds_url = get_rds_connection_url()
# Returns: postgresql://postgres:pass@host:5432/postgres?sslmode=require
```

### Hybrid Architecture

For a **Discord bot + serverless pipeline**, use:

1. **EC2 (t4g.micro)**: Run Discord bot 24/7 for real-time message collection
2. **Lambda + EventBridge**: Handle all batch processing (SnapTrade, NLP, OHLCV)

This eliminates cron jobs from EC2 and makes the architecture more resilient.

### SAM Template Reference

The `template.yaml` file at project root defines:
- **IAM Role**: Lambda execution role with Secrets Manager + S3 access
- **S3 Bucket**: For OHLCV Parquet archives
- **Lambda Layer**: Shared Python dependencies
- **CloudWatch Alarms**: Error monitoring for each function

---

## Cost Optimization

| Resource | Cost (monthly) |
|----------|----------------|
| EC2 t4g.micro | ~$6 |
| RDS t4g.micro (optional) | ~$13 |
| S3 storage | ~$0.023/GB |
| Secrets Manager | ~$0.40/secret |
| Databento | Pay-per-query |
| **Lambda** (optional) | ~$5 for typical usage |

**EC2-only: ~$20-30/month**  
**Lambda + EC2 hybrid: ~$15-20/month** (less EC2 load)

---

## Updates

```bash
# Pull latest code
cd /home/ec2-user/LLM-portfolio-project
git pull

# Reinstall dependencies
pip install -r requirements.txt

# Restart bot
pm2 restart discord-bot
# or
sudo systemctl restart discord-bot
```

---

## Files Reference

| File | Purpose |
|------|---------|
| `scripts/ec2_user_data.sh` | EC2 User Data bootstrap script |
| `scripts/start_bot_with_secrets.py` | Bot startup wrapper with AWS Secrets |
| `scripts/run_pipeline_with_secrets.sh` | Pipeline wrapper for cron jobs |
| `scripts/daily_pipeline.py` | Main pipeline orchestrator |
| `scripts/setup_ec2_services.sh` | Manual PM2/systemd setup |
| `scripts/deploy_lambdas.py` | SAM deployment script for Lambda |
| `ecosystem.config.js` | PM2 configuration |
| `docker/discord-bot.service` | systemd service file |
| `template.yaml` | SAM/CloudFormation template for Lambda |
| `src/aws_secrets.py` | AWS Secrets Manager helper |
| `lambdas/` | Lambda handler functions |
