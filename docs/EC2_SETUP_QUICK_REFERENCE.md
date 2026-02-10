# EC2 Setup Quick Reference

> **Canonical guide:** [EC2_DEPLOYMENT.md](EC2_DEPLOYMENT.md) (kept current).
> This file is a compact checklist only.

## Quick Redeploy (existing EC2)

```bash
ssh -i /path/to/keypair.pem ubuntu@YOUR_EC2_IP
cd /home/ubuntu/llm-portfolio
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt

sudo cp systemd/*.service /etc/systemd/system/
sudo cp systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload

sudo cp nginx/api.conf /etc/nginx/sites-available/api.conf
sudo nginx -t && sudo systemctl reload nginx

python scripts/deploy_database.py                    # auto-detects fresh vs existing
python scripts/verify_database.py
sudo systemctl restart api.service discord-bot.service nightly-pipeline.timer
```

## First-Time Setup (condensed)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3.11-dev \
    libpq-dev postgresql-client build-essential git nginx certbot python3-certbot-nginx

cd /home/ubuntu
git clone https://github.com/qmyhd/LLM-portfolio-project.git llm-portfolio
cd llm-portfolio

python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -e .

sudo mkdir -p /etc/llm-portfolio
sudo tee /etc/llm-portfolio/llm.env > /dev/null << 'EOF'
USE_AWS_SECRETS=1
AWS_REGION=us-east-1
AWS_SECRET_NAME=qqqAppsecrets
EOF
sudo chmod 644 /etc/llm-portfolio/llm.env

python scripts/check_secrets.py

sudo mkdir -p /var/log/journal
sudo systemctl restart systemd-journald

sudo cp systemd/*.service /etc/systemd/system/
sudo cp systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload

sudo cp nginx/api.conf /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/api.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

sudo certbot --nginx -d api.llmportfolio.app

sudo systemctl enable api.service discord-bot.service nightly-pipeline.timer
sudo systemctl start api.service discord-bot.service nightly-pipeline.timer
```

## Verify

```bash
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
sudo systemctl status api.service discord-bot.service nightly-pipeline.timer
sudo journalctl -u api.service -n 50 --no-pager
```

## References

- [EC2_DEPLOYMENT.md](EC2_DEPLOYMENT.md) (full guide, troubleshooting, backups)
- [ARCHITECTURE.md](ARCHITECTURE.md) (system overview)
