# Pre-Push Validation Checklist

> **Session Context:** Migration system overhaul (baseline from pg_dump, archive 000-059, hardened deployer with --dry-run)

## 🔍 Step 1: Local Backend Validation

### 1.1 Python Syntax & Import Check
```bash
# Verify no syntax errors
python -m py_compile scripts/deploy_database.py
python -c "from scripts.deploy_database import UnifiedDatabaseDeployer; print('Import OK')"

# Run basic tests
python tests/test_integration.py
```

### 1.2 Database Migration Dry-Run (Local → Supabase)
```bash
# Preview what would be applied (should show 0 pending)
python scripts/deploy_database.py --dry-run --verbose

# Expected output:
#   0 migration(s) to apply, 2 already applied
#   SKIPPED: 060_baseline_current.sql (existing DB)
#   SKIPPED: 061_cleanup_migration_ledger.sql (already applied)
```

### 1.3 Full Deploy Test (Idempotency Check)
```bash
# Should complete with all steps SUCCESS, 0 deployed
python scripts/deploy_database.py --verbose

# Expected: 5/5 steps succeeded, Deployed 0, skipped 1
```

### 1.4 Schema Verification
```bash
python scripts/verify_database.py --verbose

# Should show: 17+ tables, all with RLS, no missing constraints
```

---

## 🚀 Step 2: EC2 Backend Validation

### 2.1 Connect to EC2
```bash
ssh -i ~/.ssh/backfillkey.pem ubuntu@ec2-3-80-44-55.compute-1.amazonaws.com
cd /home/ubuntu/llm-portfolio
```

### 2.2 Pull Latest Code
```bash
# Fetch (don't pull yet — we want to validate first)
git fetch origin main

# Show what would be pulled
git log HEAD..origin/main --oneline --graph

# Show file changes
git diff HEAD origin/main --stat
```

### 2.3 Backup Current State (Safety)
```bash
# Snapshot current schema_migrations ledger
python -c "
from src.db import execute_sql
rows = execute_sql('SELECT * FROM schema_migrations ORDER BY applied_at', fetch_results=True)
for r in rows:
    print(dict(r._mapping))
" > /tmp/migrations_before.txt

cat /tmp/migrations_before.txt
```

### 2.4 Pull & Update Dependencies
```bash
git pull origin main

# Update Python packages (if requirements.txt changed)
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

### 2.5 Run Migration (Dry-Run First)
```bash
# Preview (should show 0 pending if EC2 DB == local DB)
python scripts/deploy_database.py --dry-run -v

# If all clear, run actual deploy
python scripts/deploy_database.py -v

# Verify
python scripts/verify_database.py --verbose
```

### 2.6 Restart Services
```bash
# Update systemd files (if changed)
sudo cp systemd/*.service /etc/systemd/system/
sudo cp systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload

# Update nginx (if changed)
sudo cp nginx/api.conf /etc/nginx/sites-available/api.conf
sudo nginx -t && sudo systemctl reload nginx

# Restart backend services
sudo systemctl restart api.service discord-bot.service
sudo systemctl restart nightly-pipeline.timer

# Check status
sudo systemctl status api.service discord-bot.service --no-pager
```

### 2.7 Health Check
```bash
# Test API health endpoint
curl -s http://127.0.0.1:8000/health | python3 -m json.tool

# Test authenticated endpoint (replace with your API_SECRET_KEY)
curl -s -H "Authorization: Bearer YOUR_API_SECRET_KEY" \
  http://127.0.0.1:8000/portfolio | python3 -m json.tool | head -30

# Check logs for errors
sudo journalctl -u api.service -n 50 --no-pager
sudo journalctl -u discord-bot.service -n 20 --no-pager
```

---

## 🌐 Step 3: Frontend Validation

### 3.1 Verify No Changes Needed
```bash
cd c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-frontend
git status

# Should show: nothing to commit, working tree clean
```

### 3.2 Test Local Frontend → EC2 Backend Integration
```bash
# In frontend repo
cd frontend
npm install  # If package.json changed

# Start dev server
npm run dev
```

**Browser Tests (http://localhost:3000):**
1. **Login** → Sign in with your Google account
2. **Portfolio Page** → Should load positions from EC2 backend
3. **Orders Page** → Should show recent orders
4. **Stock Detail** → Click on a position → Should show chart, ideas, raw messages
5. **Watchlist** → Test add/remove symbol
6. **Console Check** → Open browser DevTools → No `401 Unauthorized` or CORS errors

### 3.3 Test Production Frontend (Vercel)
**After backend push is deployed to EC2:**

Visit your production frontend URL (Vercel deployment)

1. **Full login flow** → Google OAuth → Redirect to dashboard
2. **Portfolio loads** → Positions from live EC2 backend
3. **Stock charts render** → Click position → Chart with OHLCV data
4. **Network tab** → All API calls to `process.env.NEXT_PUBLIC_API_URL` (your EC2 domain)
5. **No 500 errors** → Check for backend errors in responses

---

## 🔐 Step 4: Security Validation

### 4.1 Check No Secrets in Git
```bash
# Backend repo
cd c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-project
git diff --cached | Select-String -Pattern "sk-|sb_secret|password|eyJ|Bearer"

# Should return nothing
```

### 4.2 Verify .env Files Not Tracked
```bash
# Backend
git ls-files | Select-String -Pattern "\.env$"

# Frontend
cd c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-frontend
git ls-files | Select-String -Pattern "\.env$"

# Both should return empty (only .env.example is tracked)
```

### 4.3 Verify API_SECRET_KEY Not Exposed
**Frontend DevTools check:**
1. Open browser → http://localhost:3000
2. DevTools → Network tab → Reload page
3. Click on any API request to `/api/portfolio`, `/api/stocks/*`, etc.
4. **Response tab** → Should see data, NOT the `API_SECRET_KEY` or `SUPABASE_SERVICE_ROLE_KEY`
5. **Preview tab** → Same check

---

## 📊 Step 5: Data Integrity Check

### 5.1 Verify Schema Matches Production
```bash
# On EC2
python -c "
from src.db import execute_sql
# Check table count
tables = execute_sql(\"\"\"
    SELECT COUNT(*) FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
\"\"\", fetch_results=True)
print(f'Tables: {tables[0][0]}')

# Check migration ledger
migrations = execute_sql('SELECT COUNT(*) FROM schema_migrations', fetch_results=True)
print(f'Migrations applied: {migrations[0][0]}')
"
```

**Expected:**
- Tables: 17-20
- Migrations applied: ~50 (including baseline and cleanup)

### 5.2 Spot-Check Key Tables
```bash
# Positions
python -c "from src.db import execute_sql; print(execute_sql('SELECT COUNT(*) FROM positions', fetch_results=True))"

# OHLCV data
python -c "from src.db import execute_sql; print(execute_sql('SELECT symbol, COUNT(*) FROM ohlcv_daily GROUP BY 1 ORDER BY 2 DESC LIMIT 5', fetch_results=True))"

# Discord parsed ideas
python -c "from src.db import execute_sql; print(execute_sql('SELECT COUNT(*) FROM discord_parsed_ideas', fetch_results=True))"
```

---

## ✅ Step 6: Final Pre-Push Checklist

**Before `git push`:**
- [ ] Local backend dry-run shows 0 pending migrations
- [ ] Local backend full deploy succeeds (5/5 steps)
- [ ] `verify_database.py` passes with no issues
- [ ] EC2 pull simulation shows expected changes
- [ ] No `.env` files in git
- [ ] No API keys in git diff
- [ ] Frontend dev server connects to backend
- [ ] Browser console shows no auth errors

**After `git push` + EC2 deploy:**
- [ ] EC2 services restart cleanly (`systemctl status`)
- [ ] EC2 health endpoint responds
- [ ] EC2 authenticated endpoints return data
- [ ] Production frontend (Vercel) loads
- [ ] Production frontend fetches live data from EC2
- [ ] No 500 errors in Vercel logs

---

## 🆘 Rollback Plan (If Issues Arise)

### If EC2 Deploy Fails
```bash
# On EC2, revert to previous commit
git log --oneline -10  # Find commit hash before pull
git reset --hard <previous-commit-hash>

# Restart services with old code
sudo systemctl restart api.service discord-bot.service
```

### If Database Migration Fails
**The deployer stops on first failure and doesn't record partial migrations.**
No manual rollback needed — just fix the SQL and re-run.

### If Frontend Breaks
**Vercel auto-deploys from `main`.** If frontend has issues:
1. Vercel dashboard → Deployments → Find last working deploy → "Promote to Production"
2. Or revert the git commit and push

---

## 📝 Commit Message Template

```
feat: overhaul database migration system

- Replace hand-crafted baseline with pg_dump --schema-only (060)
- Archive legacy migrations 000-059 to schema/archive/
- Harden deploy_database.py: better baseline guard, stop-on-first-failure
- Add --dry-run flag for safe migration preview
- Normalize line endings (.gitattributes for LF on EC2)
- Update EC2 deployment docs with migration architecture
- Fix deploy_database.py verification step (tables_exist → existing_tables)

Testing:
- ✅ Idempotency test on production DB (0 pending, all skipped)
- ✅ Dry-run shows correct behavior
- ✅ Full deploy: 5/5 steps succeeded
- ✅ Schema verification passes (17 tables, all RLS enabled)
- ✅ No secrets exposed in frontend
- ✅ All API routes protected with authGuard()

Breaking changes: None (backward-compatible, existing DBs skip baseline)
```

---

## 🎯 Quick Command Reference

```bash
# Backend validation (run in LLM-portfolio-project/)
python scripts/deploy_database.py --dry-run -v
python scripts/deploy_database.py -v
python scripts/verify_database.py

# EC2 validation (after SSH)
git fetch origin main && git diff HEAD origin/main --stat
python scripts/deploy_database.py --dry-run -v
sudo systemctl restart api.service discord-bot.service
curl -s http://127.0.0.1:8000/health | python3 -m json.tool

# Frontend validation (run in LLM-portfolio-frontend/frontend/)
npm run dev
# Open browser → http://localhost:3000 → Test login + portfolio
```
