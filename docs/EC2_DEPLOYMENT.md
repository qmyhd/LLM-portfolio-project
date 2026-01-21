# EC2 Deployment Guide

> **Last Updated:** January 21, 2026  
> **Target:** Amazon Linux 2023 on t4g.micro (ARM64)

This guide covers deploying the LLM Portfolio Journal to EC2 with:
- Discord bot running continuously via PM2 or systemd
- Daily data pipeline via cron jobs
- OHLCV backfill from Databento

## Prerequisites

- EC2 instance (t4g.micro recommended, ~$6/month)
- IAM role with access to RDS, S3, and Secrets Manager
- Security group allowing outbound HTTPS (443)
- SSH access configured

## Quick Start

```bash
# SSH into EC2
ssh ec2-user@your-ec2-host

# Clone repository
git clone https://github.com/qmyhd/LLM-portfolio-project.git
cd LLM-portfolio-project

# Setup Python environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
nano .env  # Add your API keys

# Run setup script
chmod +x scripts/setup_ec2_services.sh
./scripts/setup_ec2_services.sh --pm2
```

## Environment Variables

Create `.env` with these variables:

```ini
# Discord Bot (required for real-time message capture)
DISCORD_BOT_TOKEN=your_discord_bot_token
LOG_CHANNEL_IDS=channel_id1,channel_id2

# Supabase (required for database)
DATABASE_URL=postgresql://postgres.[project]:[service-role-key]@[region].pooler.supabase.com:6543/postgres
SUPABASE_SERVICE_ROLE_KEY=sb_secret_your_key

# OpenAI (required for NLP parsing)
OPENAI_API_KEY=sk-your_openai_key

# SnapTrade (optional - for brokerage data)
SNAPTRADE_CLIENT_ID=your_client_id
SNAPTRADE_CONSUMER_KEY=your_consumer_key
SNAPTRADE_USER_ID=your_user_id
SNAPTRADE_USER_SECRET=your_user_secret

# Databento (optional - for OHLCV data)
DATABENTO_API_KEY=db-your_databento_key

# RDS (optional - for OHLCV storage)
RDS_HOST=your-db.region.rds.amazonaws.com
RDS_PORT=5432
RDS_DB=postgres
RDS_USER=postgres
RDS_PASSWORD=your_password

# S3 (optional - for Parquet archive)
S3_BUCKET_NAME=your-ohlcv-bucket
S3_RAW_DAILY_PREFIX=ohlcv/daily/
```

## Discord Bot - Continuous Running

### Option 1: PM2 (Recommended)

PM2 is a process manager that automatically restarts your bot if it crashes.

```bash
# Install PM2
sudo npm install -g pm2

# Start bot
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

For deeper OS integration, use the systemd service:

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

## Daily Data Pipeline

The daily pipeline runs three tasks:
1. **SnapTrade Sync** - Fetch positions, orders, balances
2. **Discord NLP Processing** - Parse unprocessed messages
3. **OHLCV Backfill** - Fetch daily price bars from Databento

### Manual Run

```bash
cd /home/ec2-user/LLM-portfolio-project
source .venv/bin/activate

# Run all tasks
python scripts/daily_pipeline.py

# Run specific tasks
python scripts/daily_pipeline.py --snaptrade
python scripts/daily_pipeline.py --discord
python scripts/daily_pipeline.py --ohlcv

# Dry run (preview only)
python scripts/daily_pipeline.py --dry-run
```

### Cron Schedule

The setup script configures these cron jobs (all times in UTC):

| Time (UTC) | Time (ET) | Task |
|------------|-----------|------|
| 06:00 | 01:00 AM | Full daily pipeline |
| 01:00 | 08:00 PM | Evening SnapTrade sync |

View cron jobs:
```bash
crontab -l
```

Edit cron jobs:
```bash
crontab -e
```

### Manual Cron Entry

If you need to add cron jobs manually:

```bash
crontab -e

# Add these lines:
# Daily pipeline at 1:00 AM ET (6:00 AM UTC)
0 6 * * * cd /home/ec2-user/LLM-portfolio-project && .venv/bin/python scripts/daily_pipeline.py >> /var/log/discord-bot/daily_pipeline.log 2>&1

# Evening SnapTrade sync at 8:00 PM ET (1:00 AM UTC)
0 1 * * * cd /home/ec2-user/LLM-portfolio-project && .venv/bin/python scripts/daily_pipeline.py --snaptrade >> /var/log/discord-bot/snaptrade_sync.log 2>&1
```

## OHLCV Backfill

For historical data backfill:

```bash
# Last 5 days (default)
python scripts/backfill_ohlcv.py --daily

# Full historical (uses more Databento credits)
python scripts/backfill_ohlcv.py --full

# Custom date range
python scripts/backfill_ohlcv.py --start 2024-01-01 --end 2024-12-31

# Prune old data (keep 1 year in RDS)
python scripts/backfill_ohlcv.py --prune
```

## Log Files

| Log | Location |
|-----|----------|
| Discord bot | `/var/log/discord-bot/combined.log` |
| Daily pipeline | `/var/log/discord-bot/daily_pipeline.log` |
| SnapTrade sync | `/var/log/discord-bot/snaptrade_sync.log` |

View logs in real-time:
```bash
tail -f /var/log/discord-bot/combined.log
```

## Monitoring

### Check Bot Status

```bash
# PM2
pm2 status

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

## Troubleshooting

### Bot Won't Start

1. Check logs: `pm2 logs discord-bot` or `journalctl -u discord-bot`
2. Verify `.env` has `DISCORD_BOT_TOKEN`
3. Test manually: `python -m src.bot.bot`

### Pipeline Fails

1. Check log: `tail -100 /var/log/discord-bot/daily_pipeline.log`
2. Test individual tasks:
   ```bash
   python scripts/daily_pipeline.py --snaptrade --dry-run
   ```

### Database Connection Issues

1. Verify `DATABASE_URL` in `.env`
2. Check security group allows outbound 6543 (Supabase pooler)
3. Test: `python -c "from src.db import test_connection; print(test_connection())"`

## Cost Optimization

- **t4g.micro**: ~$6/month (ARM64, 1GB RAM)
- **RDS t4g.micro**: ~$13/month (if using RDS for OHLCV)
- **S3**: ~$0.023/GB/month for Parquet archive
- **Databento**: Pay-per-query (~$0.001 per symbol per day)

Total estimated cost: **~$20-30/month** for full setup

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
