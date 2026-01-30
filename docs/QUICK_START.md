# 🚀 LLM Portfolio Journal - Quick Start Guide

> **Last Updated:** January 29, 2026
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
│                   Ubuntu EC2 Instance                       │
├─────────────────────────────────────────────────────────────┤
│  systemd Services                                           │
│  ├── api.service (FastAPI backend)                         │
│  ├── discord-bot.service (Discord bot)                     │
│  └── nightly-pipeline.timer (Daily jobs at 1 AM ET)        │
├─────────────────────────────────────────────────────────────┤
│  Nginx (SSL/443) → FastAPI (127.0.0.1:8000)                │
├─────────────────────────────────────────────────────────────┤
│  AWS Secrets Manager → qqqAppsecrets                       │
└─────────────────────────────────────────────────────────────┘
                    │
                    ▼
              Supabase (PostgreSQL)
```

### Step 1: Create EC2 Instance

- **OS**: Ubuntu 22.04 LTS or 24.04 LTS
- **Instance Type**: t3.micro or t3.small
- **IAM Role**: Attach role with `secretsmanager:GetSecretValue` permission
- **Security Group**: Allow inbound 22, 80, 443; outbound all

### Step 2: Configure AWS Secrets Manager

Your secrets are stored in `qqqAppsecrets`.

**IAM Policy Required:**
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

### Step 3: Bootstrap EC2

SSH into your instance and run:

```bash
ssh ubuntu@your-ec2-ip

# Update system
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3.11-dev \
    libpq-dev build-essential git nginx certbot python3-certbot-nginx

# Clone repository
cd /home/ubuntu
git clone https://github.com/qmyhd/LLM-portfolio-project.git llm-portfolio
cd llm-portfolio

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

# Create AWS Secrets configuration
sudo mkdir -p /etc/llm-portfolio
sudo tee /etc/llm-portfolio/llm.env > /dev/null << 'EOF'
USE_AWS_SECRETS=1
AWS_REGION=us-east-1
AWS_SECRET_NAME=qqqAppsecrets
EOF
sudo chmod 644 /etc/llm-portfolio/llm.env

# Test secrets loading
python scripts/check_secrets.py

echo "✅ EC2 Bootstrap Complete!"
```

### Step 4: Install Systemd Services

```bash
# Create log directories
sudo mkdir -p /var/log/discord-bot /var/log/portfolio-api /var/log/portfolio-nightly
sudo chown -R ubuntu:ubuntu /var/log/discord-bot /var/log/portfolio-api /var/log/portfolio-nightly

# Copy service files
sudo cp systemd/*.service /etc/systemd/system/
sudo cp systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload

# Enable and start services
sudo systemctl enable api.service discord-bot.service nightly-pipeline.timer
sudo systemctl start api.service discord-bot.service nightly-pipeline.timer
```

### Step 5: Configure Nginx and SSL

```bash
# Install nginx config (Ubuntu standard: sites-available + sites-enabled)
sudo cp nginx/api.conf /etc/nginx/sites-available/api.conf
sudo ln -sf /etc/nginx/sites-available/api.conf /etc/nginx/sites-enabled/api.conf
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t

# Obtain SSL certificate (requires DNS pointing to this server)
sudo certbot --nginx -d api.llmportfolio.app

# Start nginx
sudo systemctl enable nginx
sudo systemctl start nginx
```

---

## 🔧 Systemd Commands Reference

```bash
# View service status
sudo systemctl status api.service discord-bot.service

# View logs (real-time)
sudo journalctl -u discord-bot.service -f

# Restart service
sudo systemctl restart discord-bot.service

# Stop service
sudo systemctl stop discord-bot.service

# View scheduled timers
systemctl list-timers
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
4. **Rotate secrets regularly** - Update in Secrets Manager, restart systemd services

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

# Run secrets check script
python scripts/check_secrets.py
```

---

## 📚 Additional Resources

- [AGENTS.md](../AGENTS.md) - Comprehensive AI contributor guide
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [EC2_DEPLOYMENT.md](EC2_DEPLOYMENT.md) - Detailed EC2 setup

---

*Happy trading! 📈*