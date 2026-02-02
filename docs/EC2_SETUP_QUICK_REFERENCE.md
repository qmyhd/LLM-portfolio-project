# EC2 Setup Quick Reference - 18 Steps Summary

> **Use this alongside EC2_SETUP_DETAILED.md for full explanations**

## Pre-Flight Checklist

- [ ] AWS Secrets Manager: Create `qqqAppsecrets` secret with all credentials
- [ ] IAM Role: Attach to EC2 with `secretsmanager:GetSecretValue` permission
- [ ] Domain: Point DNS to EC2 public IP (needed for SSL certificate)
- [ ] Security Group: Allow inbound 22 (SSH), 80 (HTTP), 443 (HTTPS)

---

## 18-Step Setup Commands

### STEP 1: SSH into EC2
```bash
ssh -i /path/to/keypair.pem ubuntu@YOUR_EC2_IP
```

### STEP 2: Install Dependencies
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3.11-dev \
    libpq-dev build-essential git nginx certbot python3-certbot-nginx
```

### STEP 3: Create Directories
```bash
# Enable persistent journald logs (survive reboot)
sudo mkdir -p /var/log/journal
sudo systemctl restart systemd-journald
sudo mkdir -p /etc/llm-portfolio && sudo chmod 755 /etc/llm-portfolio
```

### STEP 4: Clone Repository
```bash
cd /home/ubuntu
git clone https://github.com/qmyhd/LLM-portfolio-project.git llm-portfolio
cd llm-portfolio
```

### STEP 5: Create Python Virtual Environment
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
```

### STEP 6: Install Python Dependencies
```bash
pip install -r requirements.txt
pip install -e .
```

### STEP 7: Create AWS Secrets Configuration
```bash
sudo tee /etc/llm-portfolio/llm.env > /dev/null << 'EOF'
USE_AWS_SECRETS=1
AWS_REGION=us-east-1
AWS_SECRET_NAME=qqqAppsecrets
EOF
sudo chmod 644 /etc/llm-portfolio/llm.env
```

### STEP 8: Verify AWS Access
```bash
cd /home/ubuntu/llm-portfolio
source .venv/bin/activate
python scripts/check_secrets.py
```

### STEP 9: Deploy Systemd Services
```bash
sudo cp systemd/*.service /etc/systemd/system/
sudo cp systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl list-unit-files | grep portfolio
```

### STEP 10: Set Timezone
```bash
sudo timedatectl set-timezone America/New_York
timedatectl
```

### STEP 11: Enable & Start Services
```bash
sudo systemctl enable api.service discord-bot.service nightly-pipeline.timer
sudo systemctl start api.service discord-bot.service nightly-pipeline.timer
sudo systemctl status api.service discord-bot.service
systemctl list-timers
```

### STEP 12: Configure Nginx
```bash
sudo cp nginx/api.conf /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/api.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

### STEP 13: Setup SSL Certificate
```bash
# Replace api.llmportfolio.app with your domain
sudo certbot --nginx -d api.llmportfolio.app
sudo certbot certificates
```

### STEP 14: Verify All Services
```bash
# Health check
curl https://api.llmportfolio.app/health

# Database check
python -c "from src.db import healthcheck; print('OK' if healthcheck() else 'FAIL')"

# Service status
sudo systemctl status api.service discord-bot.service
```

### STEP 15: Test Nightly Pipeline
```bash
source .venv/bin/activate
python scripts/nightly_pipeline.py
sudo journalctl -u nightly-pipeline.service -f
```

### STEP 16: Monitor Logs
```bash
# Real-time API logs
sudo journalctl -u api.service -f

# Real-time bot logs
sudo journalctl -u discord-bot.service -f

# Pipeline logs
sudo journalctl -u nightly-pipeline.service -f
```

### STEP 17: Setup Backups
```bash
# Database backup (requires $DATABASE_URL)
pg_dump "$DATABASE_URL" > backup_$(date +%Y%m%d).sql

# Project backup
tar -czf llm-portfolio_backup_$(date +%Y%m%d).tar.gz \
    /home/ubuntu/llm-portfolio/data/ /etc/llm-portfolio/
```

### STEP 18: Schedule Maintenance
```bash
# Clean old journal logs (add to crontab or run monthly)
sudo journalctl --vacuum-time=30d

# Check system health (run monthly)
df -h /
free -h
sudo systemctl restart api.service
```

---

## Essential Commands

### Service Management
```bash
sudo systemctl start api.service                  # Start service
sudo systemctl stop api.service                   # Stop service
sudo systemctl restart api.service                # Restart
sudo systemctl enable api.service                 # Auto-start on boot
sudo systemctl status api.service                 # Check status
```

### View Logs
```bash
sudo journalctl -u api.service -f                 # Real-time logs
sudo journalctl -u api.service -n 100             # Last 100 lines
sudo journalctl -u api.service -p err             # Errors only
sudo journalctl -u api.service --since "1 hour ago"  # Last hour
```

### Health Checks
```bash
curl https://api.llmportfolio.app/health          # API health
sudo nginx -t                                     # Nginx config
sudo certbot certificates                         # SSL status
systemctl list-timers                             # Scheduled tasks
```

### Database
```bash
python -c "from src.db import healthcheck; print(healthcheck())"
python -c "from src.db import get_database_size; print(get_database_size())"
```

### Secrets
```bash
aws secretsmanager get-secret-value --secret-id qqqAppsecrets | jq '.SecretString | fromjson'
```

### Nginx
```bash
sudo nginx -t                        # Test config
sudo systemctl reload nginx          # Reload without restart
sudo tail -f /var/log/nginx/api_access.log  # Access logs
```

---

## Troubleshooting

| Problem | Command | Solution |
|---------|---------|----------|
| Service won't start | `journalctl -u api.service` | Check logs for error message |
| DB connection error | `python -c "from src.db import healthcheck; print(healthcheck())"` | Verify DATABASE_URL in Secrets Manager |
| SSL certificate error | `sudo certbot renew --force-renewal` | Renew certificate |
| Bot won't connect | `journalctl -u discord-bot.service` | Verify DISCORD_BOT_TOKEN and intents |
| High memory usage | `ps aux \| head -20` | Check resource usage and restart services |
| Nginx error | `sudo nginx -t` | Test configuration syntax |

---

## File Locations

| Component | Path |
|-----------|------|
| Project | `/home/ubuntu/llm-portfolio/` |
| Virtual Env | `/home/ubuntu/llm-portfolio/.venv/` |
| Secrets Config | `/etc/llm-portfolio/llm.env` |
| Systemd Services | `/etc/systemd/system/api.service` |
| Systemd Services | `/etc/systemd/system/discord-bot.service` |
| Systemd Services | `/etc/systemd/system/nightly-pipeline.service` |
| Systemd Timer | `/etc/systemd/system/nightly-pipeline.timer` |
| Nginx Config | `/etc/nginx/sites-available/api.conf` |
| SSL Certs | `/etc/letsencrypt/live/api.llmportfolio.app/` |
| Nginx Logs | `/var/log/nginx/api_access.log` |
| Journald Logs | `journalctl -u api.service` |
| Journald Logs | `journalctl -u discord-bot.service` |
| Journald Logs | `journalctl -u nightly-pipeline.service` |

---

## Scheduled Tasks

| When | What | Command |
|------|------|---------|
| Daily 1 AM ET | Nightly pipeline | systemd timer (automatic) |
| Every 90 days | SSL renewal | certbot (automatic) |
| Monthly (manual) | Journal cleanup | `sudo journalctl --vacuum-time=30d` |
| Monthly (manual) | System updates | `sudo apt update && sudo apt upgrade -y` |

---

## Performance Tuning

```bash
# Check system resources
free -h                    # Memory
df -h /                    # Disk
top -b -n 1               # CPU

# Service memory limits (in systemd files)
api.service: 1GB max
discord-bot.service: 500MB max
nightly-pipeline.service: unlimited

# If services are slow, upgrade instance type:
# t3.micro → t3.small (2x memory, 2x CPU)
# Cost increase: ~$8/month → ~$15/month
```

---

## Emergency Recovery

```bash
# Restart all services
sudo systemctl restart api.service discord-bot.service

# Stop all services for maintenance
sudo systemctl stop api.service discord-bot.service nightly-pipeline.timer

# View recent errors
sudo journalctl -p err --since "1 hour ago"

# Clean up disk space (remove old journal logs)
sudo journalctl --vacuum-time=30d

# Reset Nginx
sudo nginx -t && sudo systemctl reload nginx
```

---

## Verification Checklist (Post-Setup)

- [ ] SSH access working
- [ ] All dependencies installed
- [ ] AWS Secrets accessible
- [ ] Virtual environment activated
- [ ] systemd services enabled
- [ ] Services showing as "active (running)"
- [ ] FastAPI responding on localhost:8000
- [ ] Nginx responding on 80/443
- [ ] SSL certificate valid
- [ ] Database connection working
- [ ] Discord bot connected
- [ ] Nightly pipeline tested
- [ ] Logs clean (no errors)
- [ ] Domain pointing to EC2 IP

---

For detailed explanations, see: [EC2_SETUP_DETAILED.md](EC2_SETUP_DETAILED.md)
