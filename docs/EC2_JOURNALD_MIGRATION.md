# EC2 Journald Migration Guide

> **For existing EC2 instances upgrading from file-based logging to journald-only**
>
> **Current Status**: You have LLM Portfolio installed, services running, but still using file-based logging (append:/var/log/*)
>
> **Goal**: Migrate to journald-only with persistent storage and production configuration
>
> **Time**: ~15-20 minutes
>
> **Risk**: Low - no data loss, easy rollback

---

## Prerequisites

✅ EC2 instance running Ubuntu 22.04+  
✅ LLM Portfolio installed at `/home/ubuntu/llm-portfolio`  
✅ Services running (api.service, discord-bot.service, nightly-pipeline.timer)  
✅ SSH access to the instance  
✅ git configured (can run git pull)

---

## Step 1: SSH to Your Instance

```bash
ssh -i /path/to/keypair.pem ubuntu@YOUR_EC2_IP
cd /home/ubuntu/llm-portfolio
```

---

## Step 2: Check Current State (Run Preflight)

Before making changes, verify what's currently running:

```bash
# Check if old file-based logging is still in use
grep -r "append:/var/log" /etc/systemd/system/ 2>/dev/null && echo "❌ Old logging found" || echo "✅ No old logging"

# Check if drop-in journald config exists
[ -f /etc/systemd/journald.conf.d/99-llm-portfolio.conf ] && echo "✅ journald config exists" || echo "❌ Need to create journald config"

# Check if /var/log/journal exists (persistent storage)
[ -d /var/log/journal ] && echo "✅ Persistent journal storage enabled" || echo "❌ Need to enable persistent storage"

# Check current service status
systemctl status api.service --no-pager
systemctl status discord-bot.service --no-pager
```

---

## Step 3: Pull Latest Code

This gets the updated systemd unit files with journald configuration:

```bash
cd /home/ubuntu/llm-portfolio
git pull origin main

# Verify you got the latest files
ls -la systemd/*.service
cat systemd/api.service | grep -A2 "StandardOutput"
```

Expected output should show:
```
StandardOutput=journal
StandardError=journal
SyslogIdentifier=llm-portfolio-api
```

If you still see `append:/var/log`, something went wrong. Double-check your git pull.

---

## Step 4: Enable Persistent Journald Storage

This ensures logs survive reboot:

```bash
# Create persistent journal directory
sudo mkdir -p /var/log/journal

# Restart journald to enable persistent mode
sudo systemctl restart systemd-journald

# Verify persistent mode is enabled
sudo journalctl --disk-usage

# Expected output: "Archived and active journals take up X on disk"
```

---

## Step 5: Create Production Journald Configuration

This creates a drop-in config file with size limits and compression:

```bash
# Create the drop-in configuration directory
sudo mkdir -p /etc/systemd/journald.conf.d

# Create the production config (99- prefix ensures it loads last)
sudo tee /etc/systemd/journald.conf.d/99-llm-portfolio.conf > /dev/null << 'EOF'
# LLM Portfolio - Production journald configuration (drop-in)
# File: /etc/systemd/journald.conf.d/99-llm-portfolio.conf
[Journal]
Storage=persistent
SystemMaxUse=1G
SystemKeepFree=2G
Compress=yes
RateLimitBurst=10000
RateLimitIntervalSec=30s
EOF

# Verify the file was created
sudo cat /etc/systemd/journald.conf.d/99-llm-portfolio.conf

# Restart journald to apply the new configuration
sudo systemctl restart systemd-journald

# Verify configuration is applied
sudo journalctl -xn 5

# Expected: Should see journal restart messages
```

---

## Step 6: Stop Running Services

Stop services gracefully before deploying new unit files:

```bash
# Stop services (this gives them time to shut down cleanly)
sudo systemctl stop api.service
sudo systemctl stop discord-bot.service
sudo systemctl stop nightly-pipeline.timer

# Wait for graceful shutdown
sleep 5

# Verify they're stopped
sudo systemctl status api.service --no-pager | grep -i "inactive\|dead"
sudo systemctl status discord-bot.service --no-pager | grep -i "inactive\|dead"
```

---

## Step 7: Deploy Updated Systemd Units

Copy the updated unit files from the repo:

```bash
# Copy service files (they now use StandardOutput=journal)
sudo cp /home/ubuntu/llm-portfolio/systemd/*.service /etc/systemd/system/

# Copy timer file
sudo cp /home/ubuntu/llm-portfolio/systemd/*.timer /etc/systemd/system/

# Reload systemd daemon to recognize new configs
sudo systemctl daemon-reload

# Verify the new unit files are loaded
sudo systemctl status api.service --no-pager | head -5
```

Expected to see:
```
● api.service - LLM Portfolio Journal API Server (FastAPI)
     Loaded: loaded (/etc/systemd/system/api.service; enabled; ...)
```

---

## Step 8: Clean Up Old Log Directories (Optional)

If you want to clean up the old file-based log directories:

```bash
# List old directories
ls -la /var/log/ | grep -E "portfolio|discord"

# Remove old log directories (optional - they won't be used anymore)
sudo rm -rf /var/log/portfolio-api
sudo rm -rf /var/log/discord-bot
sudo rm -rf /var/log/portfolio-nightly

# Verify they're gone
ls -la /var/log/ | grep -E "portfolio|discord" && echo "Still exist" || echo "Cleaned up"
```

---

## Step 9: Start Services

Start the services with the new journald configuration:

```bash
# Enable services to auto-start on reboot
sudo systemctl enable api.service discord-bot.service nightly-pipeline.timer

# Start all services
sudo systemctl start api.service
sudo systemctl start discord-bot.service
sudo systemctl start nightly-pipeline.timer

# Check they're running
sudo systemctl status api.service --no-pager | grep -i active
sudo systemctl status discord-bot.service --no-pager | grep -i active

# Check timer is active
systemctl list-timers nightly-pipeline.timer
```

Expected:
```
● api.service - LLM Portfolio Journal API Server (FastAPI)
     Active: active (running) since ...
     
● discord-bot.service - LLM Portfolio Journal Discord Bot
     Active: active (running) since ...
```

---

## Step 10: Verify Logs Are Being Written to Journald

This is the critical verification - make sure logs are appearing in journald:

```bash
# View API logs (real-time)
sudo journalctl -u api.service -f

# In another terminal, test the API:
curl http://127.0.0.1:8000/health

# You should see the request logged in journald

# View bot logs
sudo journalctl -u discord-bot.service -n 50

# View pipeline service logs
sudo journalctl -u nightly-pipeline.service -n 20
```

---

## Step 11: Test API Health

Ensure the API is responding correctly:

```bash
# Health check (localhost - private)
curl -s http://127.0.0.1:8000/health | jq .

# Or through Nginx (if configured)
curl -s https://api.llmportfolio.app/health | jq .
```

Expected response:
```json
{
  "status": "ok"
}
```

---

## Step 12: Test Nightly Pipeline (Optional)

Verify the pipeline works with journald logging:

```bash
# Start the pipeline manually to test
sudo systemctl start nightly-pipeline.service

# Watch the logs in real-time
sudo journalctl -u nightly-pipeline.service -f

# It should run for a few seconds/minutes depending on your data

# After completion, check the logs
sudo journalctl -u nightly-pipeline.service -n 100 --no-pager
```

---

## Step 13: Run Preflight Checks

Now that everything is updated, run the preflight script to validate:

```bash
cd /home/ubuntu/llm-portfolio
bash scripts/preflight_ec2.sh

# Expected output: All checks should pass
# ✅ All required checks passed!
```

If any checks fail, review the output for specific fixes.

---

## Step 14: Configure Log Cleanup (Recommended)

Set up regular cleanup of old journal logs to prevent disk fill:

```bash
# Manual cleanup: Remove logs older than 30 days
sudo journalctl --vacuum-time=30d

# Add to crontab for automated cleanup (first Sunday each month)
sudo crontab -e

# Add this line:
# 0 0 * * 0 journalctl --vacuum-time=30d

# Or add to systemd timer (more elegant)
sudo cp /home/ubuntu/llm-portfolio/systemd/journal-cleanup.timer /etc/systemd/system/ 2>/dev/null || echo "Timer not in repo yet"
```

---

## Monitoring Logs with Journald

### Canonical Commands

```bash
# Real-time logs
sudo journalctl -u api.service -f                    # API logs
sudo journalctl -u discord-bot.service -f            # Bot logs
sudo journalctl -u nightly-pipeline.service -f       # Pipeline logs

# By SyslogIdentifier
sudo journalctl -t llm-portfolio-api -f              # API (alternative)
sudo journalctl -t llm-portfolio-bot -f              # Bot (alternative)
sudo journalctl -t llm-portfolio-nightly -f          # Pipeline (alternative)

# Historical queries
sudo journalctl -u api.service -n 100                # Last 100 lines
sudo journalctl -u api.service -p err                # Errors only
sudo journalctl -u api.service --since "1 hour ago"  # Last hour
sudo journalctl -u api.service --since "2026-02-01"  # Since date

# By priority level
sudo journalctl -p debug                             # Debug and above
sudo journalctl -p info                              # Info and above
sudo journalctl -p warning                           # Warnings and above
sudo journalctl -p err                               # Errors only
sudo journalctl -p crit                              # Critical errors

# Disk usage
sudo journalctl --disk-usage

# Vacuum old logs
sudo journalctl --vacuum-time=30d                    # Delete >30d old
sudo journalctl --vacuum-size=500M                   # Keep <500MB
```

---

## Troubleshooting

### Service won't start
```bash
# Check detailed error
sudo journalctl -u api.service -n 50 --no-pager

# Check service file for syntax errors
sudo systemctl status api.service

# Verify the env file exists
[ -f /etc/llm-portfolio/llm.env ] && echo "✅ Env file exists" || echo "❌ Missing env file"
```

### Journald logs not appearing
```bash
# Check if journald is running
sudo systemctl status systemd-journald

# Check journal storage mode
sudo journalctl --header | grep Storage

# Verify the SyslogIdentifier in unit file
grep SyslogIdentifier /etc/systemd/system/api.service

# Check if directory exists
sudo ls -la /var/log/journal/
```

### High disk usage
```bash
# Check journal size
sudo journalctl --disk-usage

# Clean up old logs
sudo journalctl --vacuum-time=14d

# Check config limits
sudo cat /etc/systemd/journald.conf.d/99-llm-portfolio.conf
```

### Old log directories still exist (after cleanup)
```bash
# They're safe to leave, but can be removed
sudo rm -rf /var/log/portfolio-api /var/log/discord-bot /var/log/portfolio-nightly
```

---

## Rollback (If Needed)

If you need to rollback to file-based logging (not recommended):

```bash
# This would require reverting the systemd unit files to old versions
# and recreating the log directories. Not documented here since we've
# moved to a better approach.

# Instead, if services are broken:
sudo systemctl stop api.service discord-bot.service
git checkout HEAD~1 -- systemd/
sudo systemctl daemon-reload
sudo systemctl start api.service discord-bot.service

# Then contact support for help.
```

---

## Verification Checklist

After completing the migration, verify:

- [ ] `git pull` succeeded and got latest code
- [ ] `systemctl status api.service` shows "active (running)"
- [ ] `systemctl status discord-bot.service` shows "active (running)"
- [ ] `systemctl list-timers` shows nightly-pipeline.timer is next scheduled
- [ ] `sudo journalctl -u api.service -n 5` shows recent logs
- [ ] `/var/log/journal/` directory exists and has files
- [ ] `/etc/systemd/journald.conf.d/99-llm-portfolio.conf` exists with correct config
- [ ] `/var/log/portfolio-*` directories don't exist (or are empty)
- [ ] `curl http://127.0.0.1:8000/health` returns HTTP 200
- [ ] `sudo bash scripts/preflight_ec2.sh` passes all checks

---

## Summary

✅ **Journald migration complete!**

You've successfully migrated from file-based logging to journald-only logging with:

- **Persistent storage**: Logs survive reboot in `/var/log/journal/`
- **Production config**: SystemMaxUse=1G, compression enabled, rate limiting
- **Drop-in config**: At `/etc/systemd/journald.conf.d/99-llm-portfolio.conf` (doesn't modify main config)
- **SyslogIdentifiers**: For easy filtering by service
- **Idempotent scripts**: bootstrap.sh and preflight_ec2.sh handle journald setup correctly

All logs are now accessible via:
```bash
sudo journalctl -u api.service -f
sudo journalctl -u discord-bot.service -f
sudo journalctl -u nightly-pipeline.service -f
```

No more need to manage `/var/log/portfolio-*/` directories!

---

## Next Steps

1. **Monitor**: Watch logs for a few hours to ensure everything is stable
2. **Schedule cleanup**: Add `journalctl --vacuum-time=30d` to cron/systemd timer
3. **Update documentation**: Share this guide with your team
4. **Archive old logs**: `tar -czf old-logs.tar.gz /var/log/portfolio-*` (if you want to keep them for archival)

---

## Questions?

If you encounter issues:

1. Run `sudo bash scripts/preflight_ec2.sh` for automated diagnostics
2. Check journalctl output: `sudo journalctl -p err --since "1 hour ago"`
3. Review `/etc/systemd/journald.conf.d/99-llm-portfolio.conf` configuration
4. Consult systemd/README.md in the project for more details
