# 🚀 LLM Portfolio Journal - Quick Start Guide

> **Last Updated:** January 23, 2026  
> **Version:** 1.0.0

## ⚡ One-Liner Setup

```bash
# Clone and setup in one command
git clone https://github.com/qmyhd/LLM-portfolio-project.git && cd LLM-portfolio-project && python -m venv .venv && .venv\Scripts\Activate.ps1 && pip install -r requirements.txt && pip install -e . && copy .env.example .env
```

---

## 📋 Prerequisites

- **Python 3.11+** 
- **PostgreSQL** (Supabase account or local)
- **Git**
- **API Keys:**
  - Supabase (required)
  - Discord Bot Token (for bot)
  - OpenAI API Key (for NLP)
  - SnapTrade (for brokerage data)
  - Databento (for OHLCV data)

---

## 🏠 Local Development Setup

### Step 1: Clone & Virtual Environment

```powershell
# Clone repository
git clone https://github.com/qmyhd/LLM-portfolio-project.git
cd LLM-portfolio-project

# Create virtual environment
python -m venv .venv

# Activate (Windows PowerShell)
.venv\Scripts\Activate.ps1

# Activate (Linux/Mac)
source .venv/bin/activate
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
pip install -e .
```

### Step 3: Configure Environment

```bash
# Copy example config
copy .env.example .env   # Windows
cp .env.example .env     # Linux/Mac

# Edit with your credentials
notepad .env             # Windows
nano .env                # Linux
```

**Required `.env` variables:**
```bash
# Database (Supabase)
DATABASE_URL=postgresql://postgres.xxxx:password@aws-0-us-east-1.pooler.supabase.com:6543/postgres
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key

# OpenAI (NLP Parsing)
OPENAI_API_KEY=sk-...

# Discord Bot
DISCORD_BOT_TOKEN=your_bot_token
LOG_CHANNEL_IDS=channel_id1,channel_id2

# SnapTrade (Brokerage)
SNAPTRADE_CLIENT_ID=your_client_id
SNAPTRADE_CONSUMER_KEY=your_consumer_key
SNAPTRADE_USER_ID=your_user_id
SNAPTRADE_USER_SECRET=your_user_secret
```

### Step 4: Validate & Run

```bash
# Validate environment
python tests/validate_deployment.py

# Run Discord bot
python -m src.bot.bot
```

---

## ☁️ EC2 Deployment (Production)

### Architecture Overview
```
┌─────────────────────────────────────────────────────────────┐
│                        AWS EC2 (t3.micro)                   │
├─────────────────────────────────────────────────────────────┤
│  PM2 Process Manager                                        │
│  ├── discord-bot (src/bot/bot.py)                          │
│  └── Cron: Daily pipeline (6:30 AM ET)                     │
├─────────────────────────────────────────────────────────────┤
│  AWS Secrets Manager                                        │
│  ├── qqqAppsecrets (Main app secrets)                      │
│  └── RDS/ohlcvdata (RDS database credentials)              │
└─────────────────────────────────────────────────────────────┘
          │                      │
          ▼                      ▼
    Supabase (Main)         RDS PostgreSQL
    (Positions, Discord)    (OHLCV data)
```

### Step 1: Create EC2 Instance

```bash
# AWS CLI - Create t3.micro instance
aws ec2 run-instances \
  --image-id ami-0c7217cdde317cfec \
  --instance-type t3.micro \
  --key-name your-key-pair \
  --security-groups discord-bot-sg \
  --iam-instance-profile Name=EC2SecretsManagerRole \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=portfolio-bot}]'
```

### Step 2: Configure AWS Secrets Manager

Your secrets are stored in:
- **`qqqAppsecrets`** - Main app secrets (Discord, OpenAI, Supabase, SnapTrade)
- **`RDS/ohlcvdata`** - RDS database credentials

**IAM Policy Required:**
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue",
                "secretsmanager:DescribeSecret"
            ],
            "Resource": [
                "arn:aws:secretsmanager:us-east-1:*:secret:qqqAppsecrets*",
                "arn:aws:secretsmanager:us-east-1:*:secret:RDS/ohlcvdata*"
            ]
        }
    ]
}
```

### Step 3: Bootstrap EC2

SSH into your instance and run:

```bash
#!/bin/bash
# EC2 Bootstrap Script

# Update system
sudo yum update -y
sudo yum install -y git python3.11 python3.11-pip nodejs npm

# Install PM2 globally
sudo npm install -g pm2

# Clone repository
cd /home/ec2-user
git clone https://github.com/qmyhd/LLM-portfolio-project.git
cd LLM-portfolio-project

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

# Create .env with AWS Secrets Manager integration
cat > .env << 'EOF'
# AWS Secrets Manager Configuration
AWS_SECRET_NAME=qqqAppsecrets
AWS_RDS_SECRET_NAME=RDS/ohlcvdata
AWS_REGION=us-east-1

# Secrets loaded at runtime from AWS Secrets Manager
# No hardcoded credentials needed!
EOF

# Test secrets loading
python -c "from src.aws_secrets import load_secrets_to_env; load_secrets_to_env(); print('✅ Secrets loaded successfully')"

# Start with PM2
pm2 start ecosystem.config.js
pm2 save
pm2 startup

echo "✅ EC2 Bootstrap Complete!"
```

### Step 4: Configure PM2 Process Manager

The `ecosystem.config.js` is pre-configured:

```javascript
module.exports = {
  apps: [{
    name: 'discord-bot',
    script: 'python',
    args: '-m src.bot.bot',
    cwd: '/home/ec2-user/LLM-portfolio-project',
    interpreter: '/home/ec2-user/LLM-portfolio-project/.venv/bin/python',
    env: {
      AWS_SECRET_NAME: 'qqqAppsecrets',
      AWS_RDS_SECRET_NAME: 'RDS/ohlcvdata',
      AWS_REGION: 'us-east-1'
    }
  }]
};
```

### Step 5: Setup Cron Jobs

```bash
# Edit crontab
crontab -e

# Add daily pipeline (6:30 AM ET = 11:30 UTC)
30 11 * * 1-5 cd /home/ec2-user/LLM-portfolio-project && /home/ec2-user/LLM-portfolio-project/scripts/run_pipeline_with_secrets.sh >> /var/log/portfolio-pipeline.log 2>&1

# Add OHLCV backfill (7:00 AM ET = 12:00 UTC, weekdays)
0 12 * * 1-5 cd /home/ec2-user/LLM-portfolio-project && source .venv/bin/activate && python scripts/backfill_ohlcv.py --daily >> /var/log/ohlcv-backfill.log 2>&1
```

---

## 🔧 PM2 Commands Reference

```bash
# View running processes
pm2 list

# View logs
pm2 logs discord-bot

# Restart bot
pm2 restart discord-bot

# Stop all
pm2 stop all

# Monitor resources
pm2 monit
```

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run integration tests
python tests/test_integration.py

# Validate deployment readiness
python tests/validate_deployment.py

# Check database health
python -c "from src.db import healthcheck; print(healthcheck())"
```

---

## 📊 Discord Bot Commands

Once running, use these commands in Discord:

| Command | Description |
|---------|-------------|
| `!chart AAPL` | Generate stock chart with positions |
| `!portfolio` | Show current portfolio |
| `!orders` | Show recent orders |
| `!process trading` | Process channel messages |
| `!history 100` | Fetch message history |
| `!twitter TSLA` | Twitter sentiment analysis |
| `!eod` | End-of-day stock lookup |
| `!help` | Interactive help menu |

---

## 🔐 Security Notes

1. **Never commit `.env` file** - It's in `.gitignore`
2. **Use AWS Secrets Manager** in production - No hardcoded secrets
3. **Use service role key** for database writes (bypasses RLS)
4. **Rotate secrets regularly** - Update in Secrets Manager, restart PM2

---

## 🆘 Troubleshooting

### Bot won't start
```bash
# Check Python path
which python
python --version

# Verify dependencies
pip list | grep discord

# Test imports
python -c "from src.bot import create_bot; print('OK')"
```

### Database connection fails
```bash
# Test connection
python -c "from src.db import healthcheck; print(healthcheck())"

# Check credentials
python -c "from src.config import get_database_url; print(get_database_url()[:50])"
```

### Secrets not loading (EC2)
```bash
# Test AWS credentials
aws sts get-caller-identity

# Test secret access
aws secretsmanager get-secret-value --secret-id qqqAppsecrets --query SecretString --output text | python -c "import sys,json; print(list(json.loads(sys.stdin.read()).keys()))"
```

---

## 📚 Additional Resources

- [AGENTS.md](../AGENTS.md) - Comprehensive AI contributor guide
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [EC2_DEPLOYMENT.md](EC2_DEPLOYMENT.md) - Detailed EC2 setup
- [BACKEND_CODE_WALKTHROUGH.md](BACKEND_CODE_WALKTHROUGH.md) - Code walkthrough

---

*Happy trading! 📈*
