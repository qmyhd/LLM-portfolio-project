#!/usr/bin/env bash
# deploy_ec2.sh — Pull latest code, validate environment, restart services.
#
# Runs checks in order and stops early on any failure.
# Must be run from the repo root on EC2.
#
# Usage:
#   ./scripts/deploy_ec2.sh

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

step()  { echo -e "\n${GREEN}▸${NC} $1"; }
die()   { echo -e "\n${RED}✗ $1${NC}"; exit 1; }

# ── 0. Repo root check ──────────────────────────────────────────────
if [[ ! -f "src/db.py" || ! -f "src/config.py" ]]; then
    die "Run from repo root: cd /home/ubuntu/llm-portfolio && ./scripts/deploy_ec2.sh"
fi

VENV_PYTHON=".venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
    die "Venv not found at $VENV_PYTHON — run: python3.11 -m venv .venv"
fi

# ── 1. Ensure clean working tree ────────────────────────────────────
step "Checking working tree..."
if [[ -n "$(git status --porcelain)" ]]; then
    git status --short
    die "Working tree is dirty. Commit or stash changes before deploying."
fi

# ── 2. Pull latest from main ────────────────────────────────────────
step "Switching to main and pulling..."
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
    git checkout main
fi
git pull --ff-only || die "git pull failed (is main diverged?)"

# ── 2b. Install/update dependencies if requirements changed ──────────
step "Installing dependencies..."
$VENV_PYTHON -m pip install -q -r requirements.txt || die "pip install failed"

# ── 3. Run doctor checks ────────────────────────────────────────────
step "Running doctor_ec2.sh..."
bash ./scripts/doctor_ec2.sh || die "doctor_ec2.sh reported failures — fix before deploying."

# ── 4. Nginx syntax check ───────────────────────────────────────────
step "Validating nginx config..."
sudo nginx -t || die "nginx -t failed — fix config before deploying."

# ── 5. Restart services ─────────────────────────────────────────────
step "Restarting api.service..."
sudo systemctl restart api.service

step "Restarting discord-bot.service..."
sudo systemctl restart discord-bot.service

# ── 6. Wait for API to come up, then health check ───────────────────
step "Waiting for API to start (up to 15s)..."
sleep 3

RETRIES=4
for i in $(seq 1 $RETRIES); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:8000/health 2>/dev/null || echo "000")
    if [[ "$HTTP_CODE" == "200" ]]; then
        break
    fi
    if [[ "$i" -eq "$RETRIES" ]]; then
        die "Health check failed after $RETRIES attempts (last HTTP $HTTP_CODE)"
    fi
    echo "  Attempt $i/$RETRIES — got $HTTP_CODE, retrying in 3s..."
    sleep 3
done

echo ""
echo -e "${GREEN}Deploy complete.${NC} /health → 200"
echo "  api.service:         $(systemctl is-active api.service)"
echo "  discord-bot.service: $(systemctl is-active discord-bot.service)"
