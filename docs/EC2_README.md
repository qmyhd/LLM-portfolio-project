# EC2 Deployment Documentation Index

> **Complete guide to deploying LLM Portfolio Journal to AWS EC2**

## 📚 Documentation Files

### 1. **START HERE** - [EC2_SETUP_QUICK_REFERENCE.md](EC2_SETUP_QUICK_REFERENCE.md)
**Best for:** Quick reference, copy-paste commands, checklist  
**Contains:**
- 18-step command summary
- Essential commands reference
- Troubleshooting quick lookup
- File locations reference
- Post-setup verification checklist

**When to use:** You're setting up EC2 and want commands you can copy-paste directly.

---

### 2. **MAIN GUIDE** - [EC2_DEPLOYMENT.md](EC2_DEPLOYMENT.md)
**Best for:** Step-by-step setup with detailed explanations  
**Contains:**
- **18 comprehensive steps** with full explanations
- What each command does and why
- Detailed comments about each component
- Troubleshooting solutions
- AWS Secrets Manager setup
- SSL/TLS certificate configuration
- Service management and monitoring
- Backup and recovery procedures

**When to use:** You want to understand *why* you're running each command, not just what to run.

**Estimated time:** 30-45 minutes following along

---

### 3. **ARCHITECTURE** - [ARCHITECTURE.md](ARCHITECTURE.md)
**Best for:** Understanding how components interact  
**Contains:**
- Complete system architecture diagram (ASCII art)
- Component communication flows
- Data flow between services
- Database layer details
- Module structure and NLP pipeline
- Integration points and data conventions

**When to use:** You want to understand the "big picture" or debug issues by understanding how systems talk to each other.

---

### 4. **COMMAND REFERENCE** - [EC2_SETUP_QUICK_REFERENCE.md](EC2_SETUP_QUICK_REFERENCE.md)
**Best for:** Copy-paste commands without detailed explanations  
**Contains:**
- 18-step command summary
- Essential commands reference
- Quick troubleshooting lookup

**When to use:** You prefer the concise version without detailed explanations.

---

## 🚀 Quick Start Paths

### Path 1: "Just Give Me The Commands" (5 minutes)
1. Read: [EC2_SETUP_QUICK_REFERENCE.md](EC2_SETUP_QUICK_REFERENCE.md)
2. Verify you have prerequisites (AWS Secret, IAM role, domain)
3. Copy commands and run them step-by-step
4. Use the verification checklist at the end

### Path 2: "I Want To Understand Everything" (45 minutes)
1. Read: [ARCHITECTURE.md](ARCHITECTURE.md) to understand the big picture
2. Follow: [EC2_DEPLOYMENT.md](EC2_DEPLOYMENT.md) step-by-step
3. After each step, reference the architecture doc to understand how it fits together
4. When done, review the troubleshooting section

### Path 3: "I'm Experienced, Just Need Details" (20 minutes)
1. Skim: [EC2_DEPLOYMENT.md](EC2_DEPLOYMENT.md) to verify you're not missing anything
2. Use: [EC2_SETUP_QUICK_REFERENCE.md](EC2_SETUP_QUICK_REFERENCE.md) for commands
3. Reference: [ARCHITECTURE.md](ARCHITECTURE.md) for specific component details

---

## 🎯 Common Tasks & Where To Find Them

### I want to...

**Deploy to EC2 from scratch**
→ [EC2_DEPLOYMENT.md - Manual Setup](EC2_DEPLOYMENT.md#manual-setup)

**Understand how everything works together**
→ [ARCHITECTURE.md](ARCHITECTURE.md)

**Get quick commands to run**
→ [EC2_SETUP_QUICK_REFERENCE.md](EC2_SETUP_QUICK_REFERENCE.md)

**Setup AWS Secrets Manager**
→ [EC2_DEPLOYMENT.md - Secrets Manager Setup](EC2_DEPLOYMENT.md#secrets-manager-setup)

**Setup SSL/HTTPS certificate**
→ [EC2_DEPLOYMENT.md - Step 6: Configure Nginx and SSL](EC2_DEPLOYMENT.md#step-6-configure-nginx-and-ssl)

**Configure Nginx**
→ [EC2_DEPLOYMENT.md - Step 6: Configure Nginx and SSL](EC2_DEPLOYMENT.md#step-6-configure-nginx-and-ssl)

**Understand systemd services**
→ [EC2_DEPLOYMENT.md - Step 5: Install Systemd Services](EC2_DEPLOYMENT.md#step-5-install-systemd-services)

**View service logs**
→ [EC2_DEPLOYMENT.md - Service Management](EC2_DEPLOYMENT.md#service-management)

**Debug a failing service**
→ [EC2_DEPLOYMENT.md - Troubleshooting](EC2_DEPLOYMENT.md#troubleshooting)  
→ [ARCHITECTURE.md - System Architecture](ARCHITECTURE.md#system-architecture)

**Test the nightly pipeline**
→ [EC2_DEPLOYMENT.md - Manual Run](EC2_DEPLOYMENT.md#manual-run)

**Setup backups**
→ [EC2_DEPLOYMENT.md - Backup & Recovery](EC2_DEPLOYMENT.md#backup--recovery)

**Schedule maintenance tasks**
→ [EC2_DEPLOYMENT.md - Nightly Pipeline](EC2_DEPLOYMENT.md#nightly-pipeline-canonical)

**Verify everything is working**
→ [EC2_DEPLOYMENT.md - Health Checks](EC2_DEPLOYMENT.md#health-checks)

---

## 📋 Pre-Deployment Checklist

Before starting setup, verify you have:

### AWS Resources
- [ ] EC2 instance running (Ubuntu 22.04 or 24.04 LTS, t3.micro or larger)
- [ ] IAM role attached to EC2 with `secretsmanager:GetSecretValue` permission
- [ ] AWS Secrets Manager secret created: `qqqAppsecrets`
- [ ] Secret contains all required credentials (see [EC2_DEPLOYMENT.md](EC2_DEPLOYMENT.md#secrets-manager-setup))
- [ ] Security Group allows: inbound SSH (22), HTTP (80), HTTPS (443)

### Domain & SSL
- [ ] Domain name (e.g., `api.llmportfolio.app`)
- [ ] Domain DNS points to EC2 public IP
- [ ] Port 80 and 443 open in Security Group (for Let's Encrypt validation)

### Credentials
- [ ] Discord Bot Token (for Discord integration)
- [ ] OpenAI API Key (for NLP processing)
- [ ] Supabase/PostgreSQL connection URL
- [ ] SnapTrade credentials (optional, but pipeline can still run)
- [ ] Databento API Key (for OHLCV data)

### Local Machine
- [ ] SSH key pair file downloaded from AWS
- [ ] SSH access to EC2 verified (`ssh -i keypair.pem ubuntu@YOUR_IP`)

---

## 📖 Documentation Map

```
EC2 Deployment Documentation
│
├─ EC2_SETUP_QUICK_REFERENCE.md (Start here if experienced)
│  ├─ 18 steps with commands
│  ├─ Command reference
│  ├─ Troubleshooting lookup
│  └─ Verification checklist
│
├─ EC2_DEPLOYMENT.md (Start here if new to EC2/Linux)
│  ├─ Step 1: Install System Dependencies
│  ├─ Step 2: Clone Repository
│  ├─ Step 3-4: AWS Secrets Manager
│  ├─ Step 5: Install Systemd Services
│  ├─ Step 6: Configure Nginx & SSL
│  ├─ Step 7: Start Services
│  ├─ Service Management
│  ├─ Nightly Pipeline
│  ├─ Health Checks
│  ├─ Troubleshooting
│  ├─ SnapTrade Auth Failures
│  └─ OHLCV Backfill
│
├─ ARCHITECTURE.md (Understand the system)
│  ├─ Complete system architecture (ASCII diagram)
│  ├─ Component communication flows
│  ├─ Database layer details
│  ├─ Module structure
│  ├─ NLP pipeline and integration points
│  └─ Data conventions
│
└─ EC2_SETUP_QUICK_REFERENCE.md (Command cheat sheet)
   ├─ Quick commands
   ├─ Service management
   └─ Health checks
```

---

## 🔍 Troubleshooting by Symptom

| Symptom | Document | Section |
|---------|----------|---------|
| Service won't start | DEPLOYMENT | [Troubleshooting](EC2_DEPLOYMENT.md#troubleshooting) |
| Database connection timeout | DEPLOYMENT | [Database Connection Issues](EC2_DEPLOYMENT.md#database-connection-issues) |
| SSL certificate error | DEPLOYMENT | [Nginx/SSL Issues](EC2_DEPLOYMENT.md#nginxssl-issues) |
| Bot won't connect | DEPLOYMENT | [Bot Won't Start](EC2_DEPLOYMENT.md#bot-wont-start) |
| High memory/CPU usage | DEPLOYMENT | [Troubleshooting](EC2_DEPLOYMENT.md#troubleshooting) |
| Nginx returns 502 | DEPLOYMENT | [Nginx/SSL Issues](EC2_DEPLOYMENT.md#nginxssl-issues) |
| Can't understand how it works | ARCH | [Complete Architecture](ARCHITECTURE.md) |
| Need to find a command | QUICK | [Command Reference](EC2_SETUP_QUICK_REFERENCE.md#essential-commands) |

---

## ⏱️ Time Estimates

| Task | Time | Document |
|------|------|----------|
| Read architecture overview | 10 min | ARCHITECTURE |
| Read quick reference | 5 min | QUICK_REFERENCE |
| Read deployment guide | 30 min | DEPLOYMENT |
| Actual EC2 setup | 30-45 min | DEPLOYMENT + QUICK_REFERENCE |
| **Total (first time, reading + setup)** | **1.5 hours** | All three |
| Repeat setup (experienced) | 20 min | QUICK_REFERENCE |

---

## 💡 Pro Tips

### Read First, Copy Later
- Don't copy-paste blindly
- Read each section to understand what you're doing
- This prevents mistakes and makes troubleshooting easier

### Use Architecture Doc for Understanding
- When confused about "why" something works
- When debugging issues
- When understanding data flow
- Reference the ASCII diagrams

### Keep Commands Accessible
- Print or bookmark [EC2_SETUP_QUICK_REFERENCE.md](EC2_SETUP_QUICK_REFERENCE.md)
- Use the "Command Reference" section while working
- Copy entire command blocks to avoid typos

### Monitor Everything
- Keep terminal with `journalctl -u api.service -f` open
- Check logs after each step
- Don't assume everything worked - verify it

### Test Before Going Live
- Test manually running nightly pipeline (STEP 15)
- Verify database connectivity (STEP 14)
- Check SSL certificate (STEP 13)

---

## 🚨 Critical Steps (Don't Skip These)

1. **STEP 8**: Verify AWS Secrets Access
   - If this fails, services will crash
   
2. **STEP 7**: Create `/etc/llm-portfolio/llm.env`
   - All services depend on this file
   - ExecStartPre will fail if missing

3. **STEP 13**: Setup SSL Certificate
   - Nginx will serve over HTTPS
   - Required for production

4. **STEP 14**: Verify All Services
   - Catch issues before they become production problems
   - Use the verification checklist

5. **STEP 15**: Test Nightly Pipeline
   - Ensures scheduled jobs will work
   - Catches data pipeline issues early

---

## 📞 Support & Questions

If you're stuck:

1. **Check the Troubleshooting Section**
   - [EC2_DEPLOYMENT.md Troubleshooting](EC2_DEPLOYMENT.md#troubleshooting)

2. **Review the Architecture**
   - Understanding how components talk helps debug issues
   - [ARCHITECTURE.md](ARCHITECTURE.md)

3. **Check Service Logs**
   ```bash
   journalctl -u api.service -n 50
   journalctl -u discord-bot.service -n 50
   journalctl -u nightly-pipeline.service -n 50
   ```

4. **Verify Systemd Configuration**
   ```bash
   sudo systemctl status api.service
   sudo systemctl cat api.service
   ```

5. **Test Components Individually**
   - Database: `python -c "from src.db import healthcheck; print(healthcheck())"`
   - Secrets: `python scripts/check_secrets.py`
   - Nginx: `sudo nginx -t`

---

## 📚 Related Documentation

- **Main AGENTS.md**: [../AGENTS.md](../AGENTS.md)
- **Architecture Guide**: [./ARCHITECTURE.md](./ARCHITECTURE.md)
- **Codebase Map**: [../docs/codebase-map.md](../docs/codebase-map.md)

---

## ✅ After Setup is Complete

- [ ] Services are running (verify with `systemctl status`)
- [ ] Health endpoint responds (curl the API)
- [ ] Database connected (no connection errors in logs)
- [ ] SSL certificate valid (browser shows green lock)
- [ ] Nightly pipeline works (test manual run)
- [ ] Logs are clean (no ERROR or CRITICAL messages)
- [ ] Monitoring is set up (know where to check logs)

**Congratulations! Your LLM Portfolio Journal is now deployed on EC2.** 🎉

---

For immediate assistance or to report issues:
1. Check [EC2_DEPLOYMENT.md - Troubleshooting](EC2_DEPLOYMENT.md#troubleshooting)
2. Review service logs: `journalctl -u [service-name] -n 100`
3. Verify all prerequisites were completed
