#!/usr/bin/env bash
# doctor_ec2.sh — Environment health check for LLM Portfolio on EC2.
#
# Ensures the venv, database, and local API are operational.
# Exit 0 = all checks pass; exit 1 = one or more failures.
#
# Usage:
#   ./scripts/doctor_ec2.sh          # from repo root
#   bash scripts/doctor_ec2.sh       # equivalent

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}OK${NC}   $1"; }
fail() { echo -e "  ${RED}FAIL${NC} $1"; FAILURES=$((FAILURES + 1)); }
warn() { echo -e "  ${YELLOW}WARN${NC} $1"; }

FAILURES=0

echo "╔═══════════════════════════════════════════╗"
echo "║   LLM Portfolio — EC2 Environment Doctor  ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

# ── 0. Repo root check ──────────────────────────────────────────────
if [[ ! -f "src/db.py" || ! -f "src/config.py" ]]; then
    echo -e "${RED}ERROR: Run this script from the repo root (/home/ubuntu/llm-portfolio).${NC}"
    echo "  cd /home/ubuntu/llm-portfolio && ./scripts/doctor_ec2.sh"
    exit 1
fi
ok "Running from repo root ($(pwd))"

# ── 1. Venv check ───────────────────────────────────────────────────
VENV_PYTHON=".venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
    fail "Virtual environment not found at .venv/bin/python"
    echo "       Fix: python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt"
else
    PYVER=$($VENV_PYTHON --version 2>&1)
    ok "Venv Python: $PYVER"
fi

# ── 2. Load central env (non-fatal) ─────────────────────────────────
ENV_FILE="/etc/llm-portfolio/llm.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
    ok "Loaded $ENV_FILE"
else
    warn "$ENV_FILE not found (OK for local dev, required on EC2)"
fi

# ── 3. Python import checks ─────────────────────────────────────────
echo ""
echo "── Python imports ──"

for mod in sqlalchemy fastapi uvicorn; do
    if $VENV_PYTHON -c "import $mod" 2>/dev/null; then
        ok "import $mod"
    else
        fail "import $mod"
        echo "       Fix: .venv/bin/pip install $mod"
    fi
done

# ── 4. Database connectivity ─────────────────────────────────────────
echo ""
echo "── Database ──"

DB_OUTPUT=$($VENV_PYTHON -c "
import sys, os
sys.path.insert(0, '.')
from src.env_bootstrap import bootstrap_env
bootstrap_env()
from src.db import test_connection
result = test_connection()
if result:
    for k, v in result.items():
        print(f'{k}: {v}')
else:
    print('ERROR: test_connection returned None')
    sys.exit(1)
" 2>&1) && DB_OK=1 || DB_OK=0

if [[ $DB_OK -eq 1 ]]; then
    ok "Database connection"
    echo "$DB_OUTPUT" | sed 's/^/       /'
else
    fail "Database connection"
    echo "$DB_OUTPUT" | sed 's/^/       /'
    echo ""
    echo "       Common fixes:"
    echo "       • Missing DATABASE_URL? Source env first:"
    echo "           source /etc/llm-portfolio/llm.env"
    echo "       • AWS secrets not loading? Check USE_AWS_SECRETS=1 in $ENV_FILE"
    echo "       • Supabase pooler down? Try direct URL: DATABASE_DIRECT_URL"
fi

# ── 5. Local API health check ────────────────────────────────────────
echo ""
echo "── FastAPI (local) ──"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:8000/health 2>/dev/null || echo "000")

if [[ "$HTTP_CODE" == "200" ]]; then
    ok "GET /health → 200"
else
    if [[ "$HTTP_CODE" == "000" ]]; then
        fail "FastAPI not reachable at 127.0.0.1:8000"
        echo "       Fix: sudo systemctl start api.service"
        echo "            journalctl -u api.service -n 20 --no-pager"
    else
        fail "GET /health → $HTTP_CODE (expected 200)"
        echo "       Fix: journalctl -u api.service -n 20 --no-pager"
    fi
fi

# ── 6. Systemd services (informational) ──────────────────────────────
echo ""
echo "── Systemd services ──"

for svc in api.service discord-bot.service nightly-pipeline.timer; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        ok "$svc is active"
    else
        STATUS=$(systemctl is-active "$svc" 2>/dev/null || echo "unknown")
        warn "$svc is $STATUS"
    fi
done

# ── 7. Nginx config check (warn-only) ─────────────────────────────────
echo ""
echo "── Nginx ──"

if command -v nginx &>/dev/null; then
    if sudo nginx -t 2>/dev/null; then
        ok "nginx -t (config syntax valid)"
    else
        fail "nginx -t (config syntax invalid)"
        echo "       Fix: sudoedit /etc/nginx/sites-available/api.conf"
        echo "            sudo nginx -t   # repeat until clean"
    fi

    # Warn if limit_req_zone appears more than once across enabled configs
    ZONE_COUNT=$(sudo grep -R "limit_req_zone" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | wc -l)
    if [[ "$ZONE_COUNT" -gt 1 ]]; then
        warn "limit_req_zone declared $ZONE_COUNT times (risk of duplicate zone error)"
        echo "       Check: sudo grep -rn limit_req_zone /etc/nginx/sites-enabled/ /etc/nginx/conf.d/"
    else
        ok "limit_req_zone count: $ZONE_COUNT (no duplicates)"
    fi

    # Note about backups
    BAK_COUNT=$(ls /etc/nginx/sites-available/*.bak 2>/dev/null | wc -l)
    if [[ "$BAK_COUNT" -gt 0 ]]; then
        ok "$BAK_COUNT .bak file(s) in sites-available (harmless, not loaded)"
    fi
else
    warn "nginx not installed (skip nginx checks)"
fi

# ── Summary ──────────────────────────────────────────────────────────
echo ""
if [[ $FAILURES -eq 0 ]]; then
    echo -e "${GREEN}All checks passed.${NC}"
    exit 0
else
    echo -e "${RED}$FAILURES check(s) failed.${NC} See fixes above."
    exit 1
fi
