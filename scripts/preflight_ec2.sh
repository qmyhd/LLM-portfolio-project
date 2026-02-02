#!/bin/bash
# =============================================================================
# EC2 Preflight Check Script
# =============================================================================
#
# Idempotent script that validates EC2 instance is ready for deployment.
# Checks all prerequisites and prints commands to fix any issues.
#
# Usage:
#   chmod +x scripts/preflight_ec2.sh
#   ./scripts/preflight_ec2.sh
#
# Exit Codes:
#   0: All checks passed
#   1: One or more checks failed
#
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_DIR="/home/ubuntu/llm-portfolio"
VENV_DIR="${PROJECT_DIR}/.venv"
ENV_FILE="/etc/llm-portfolio/llm.env"
SYSTEMD_DIR="/etc/systemd/system"

# Counters
PASSED=0
FAILED=0
WARNINGS=0

echo "=============================================="
echo "  LLM Portfolio Journal - EC2 Preflight Check"
echo "=============================================="
echo ""

# Function to check a condition
check() {
    local name="$1"
    local condition="$2"
    local fix_cmd="$3"
    
    # Temporarily disable set -e for condition evaluation
    set +e
    eval "$condition"
    local result=$?
    set -e
    
    if [ $result -eq 0 ]; then
        echo -e "${GREEN}✅ PASS${NC}: $name"
        ((PASSED++)) || true
    else
        echo -e "${RED}❌ FAIL${NC}: $name"
        if [ -n "$fix_cmd" ]; then
            echo -e "   ${YELLOW}Fix:${NC} $fix_cmd"
        fi
        ((FAILED++)) || true
    fi
    return 0
}

warn() {
    local name="$1"
    local condition="$2"
    local fix_cmd="$3"
    
    # Temporarily disable set -e for condition evaluation
    set +e
    eval "$condition"
    local result=$?
    set -e
    
    if [ $result -eq 0 ]; then
        echo -e "${GREEN}✅ PASS${NC}: $name"
        ((PASSED++)) || true
    else
        echo -e "${YELLOW}⚠️  WARN${NC}: $name"
        if [ -n "$fix_cmd" ]; then
            echo -e "   ${YELLOW}Fix:${NC} $fix_cmd"
        fi
        ((WARNINGS++)) || true
    fi
    return 0
}

echo "📁 Checking directory structure..."
echo "-----------------------------------"

check "Project directory exists" \
    "[ -d '$PROJECT_DIR' ]" \
    "git clone https://github.com/qmyhd/LLM-portfolio-project.git $PROJECT_DIR"

check "Project is a git repository" \
    "[ -d '$PROJECT_DIR/.git' ]" \
    "cd /home/ubuntu && rm -rf llm-portfolio && git clone https://github.com/qmyhd/LLM-portfolio-project.git llm-portfolio"

check "Virtual environment exists" \
    "[ -d '$VENV_DIR' ]" \
    "cd $PROJECT_DIR && python3.11 -m venv .venv"

check "Python in venv works" \
    "[ -x '$VENV_DIR/bin/python' ]" \
    "cd $PROJECT_DIR && rm -rf .venv && python3.11 -m venv .venv"

echo ""
echo "📦 Checking system dependencies..."
echo "-----------------------------------"

check "Python 3.11+ installed" \
    "command -v python3.11 &> /dev/null || python3 --version | grep -q '3.1[1-9]'" \
    "sudo apt update && sudo apt install -y python3.11 python3.11-venv python3.11-dev"

check "Nginx installed" \
    "command -v nginx &> /dev/null" \
    "sudo apt install -y nginx"

check "Certbot installed" \
    "command -v certbot &> /dev/null" \
    "sudo apt install -y certbot python3-certbot-nginx"

check "Git installed" \
    "command -v git &> /dev/null" \
    "sudo apt install -y git"

echo ""
echo "🔐 Checking AWS Secrets configuration..."
echo "-----------------------------------------"

check "Central env file exists" \
    "[ -f '$ENV_FILE' ]" \
    "sudo mkdir -p /etc/llm-portfolio && sudo tee $ENV_FILE > /dev/null << 'EOF'
USE_AWS_SECRETS=1
AWS_REGION=us-east-1
AWS_SECRET_NAME=qqqAppsecrets
EOF"

if [ -f "$ENV_FILE" ]; then
    check "USE_AWS_SECRETS=1 in env file" \
        "grep -q 'USE_AWS_SECRETS=1' '$ENV_FILE'" \
        "echo 'USE_AWS_SECRETS=1' | sudo tee -a $ENV_FILE"
    
    check "AWS_SECRET_NAME in env file" \
        "grep -q 'AWS_SECRET_NAME=' '$ENV_FILE'" \
        "echo 'AWS_SECRET_NAME=qqqAppsecrets' | sudo tee -a $ENV_FILE"
fi

echo ""
echo "⚙️  Checking systemd services..."
echo "---------------------------------"

check "api.service exists" \
    "[ -f '$SYSTEMD_DIR/api.service' ]" \
    "sudo cp $PROJECT_DIR/systemd/api.service $SYSTEMD_DIR/ && sudo systemctl daemon-reload"

check "discord-bot.service exists" \
    "[ -f '$SYSTEMD_DIR/discord-bot.service' ]" \
    "sudo cp $PROJECT_DIR/systemd/discord-bot.service $SYSTEMD_DIR/ && sudo systemctl daemon-reload"

check "nightly-pipeline.service exists" \
    "[ -f '$SYSTEMD_DIR/nightly-pipeline.service' ]" \
    "sudo cp $PROJECT_DIR/systemd/nightly-pipeline.service $SYSTEMD_DIR/ && sudo systemctl daemon-reload"

check "nightly-pipeline.timer exists" \
    "[ -f '$SYSTEMD_DIR/nightly-pipeline.timer' ]" \
    "sudo cp $PROJECT_DIR/systemd/nightly-pipeline.timer $SYSTEMD_DIR/ && sudo systemctl daemon-reload"

echo ""
echo "Checking journald logging setup..."
echo "--------------------------------------"

check "No legacy file logging in unit files" \
    "! grep -q 'append:/var/log' $SYSTEMD_DIR/api.service $SYSTEMD_DIR/discord-bot.service $SYSTEMD_DIR/nightly-pipeline.service 2>/dev/null" \
    "Redeploy unit files: sudo cp $PROJECT_DIR/systemd/*.service $SYSTEMD_DIR/ && sudo systemctl daemon-reload"

check "Persistent journald storage enabled" \
    "[ -d '/var/log/journal' ]" \
    "sudo mkdir -p /var/log/journal && sudo systemctl restart systemd-journald"

warn "Journald drop-in config exists" \
    "[ -f '/etc/systemd/journald.conf.d/99-llm-portfolio.conf' ]" \
    "Run bootstrap.sh to create production journald config"

echo ""
echo "🌐 Checking Nginx configuration..."
echo "-----------------------------------"

warn "Nginx config exists" \
    "[ -f '/etc/nginx/sites-enabled/api.conf' ] || [ -f '/etc/nginx/conf.d/api.conf' ]" \
    "sudo cp $PROJECT_DIR/nginx/api.conf /etc/nginx/sites-available/api.conf && sudo ln -sf /etc/nginx/sites-available/api.conf /etc/nginx/sites-enabled/api.conf"

warn "Nginx config valid" \
    "sudo nginx -t 2>/dev/null" \
    "sudo nginx -t"

echo ""
echo "🏥 Checking service health..."
echo "------------------------------"

# Only check API health if services are expected to be running
if systemctl is-active --quiet api.service 2>/dev/null; then
    check "API health endpoint responds" \
        "curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1" \
        "Check API logs: sudo journalctl -u api.service -n 100 --no-pager"
else
    warn "API service is running" \
        "systemctl is-active --quiet api.service 2>/dev/null" \
        "Start API: sudo systemctl start api.service"
fi

echo ""
echo "=============================================="
echo "  Summary"
echo "=============================================="
echo ""
echo -e "  ${GREEN}Passed${NC}:   $PASSED"
echo -e "  ${RED}Failed${NC}:   $FAILED"
echo -e "  ${YELLOW}Warnings${NC}: $WARNINGS"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All required checks passed!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Verify secrets: python scripts/check_secrets.py"
    echo "  2. Start services: sudo systemctl start api.service discord-bot.service nightly-pipeline.timer"
    echo "  3. Check health:   curl http://127.0.0.1:8000/health"
    echo ""
    echo "View logs with journald:"
    echo "  sudo journalctl -u api.service -f"
    echo "  sudo journalctl -u discord-bot.service -f"
    echo "  sudo journalctl -u nightly-pipeline.service -f"
    exit 0
else
    echo -e "${RED}❌ $FAILED check(s) failed. See fixes above.${NC}"
    echo ""
    echo "Quick fix all:"
    echo "  ./scripts/bootstrap.sh"
    echo ""
    echo "Actionable debug commands:"
    echo "  sudo systemctl status api.service discord-bot.service --no-pager"
    echo "  sudo journalctl -u api.service -n 100 --no-pager"
    echo "  sudo journalctl -u discord-bot.service -n 100 --no-pager"
    exit 1
fi