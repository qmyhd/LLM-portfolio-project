#!/bin/bash
# =============================================================================
# LLM Portfolio Journal - Ubuntu EC2 Bootstrap Script
# =============================================================================
# This script sets up an Ubuntu EC2 instance with all dependencies for:
# - Python 3.12+ environment with virtual env
# - FastAPI backend (systemd service)
# - Discord bot (systemd service)
# - Nginx reverse proxy with SSL (via Certbot)
# - PM2 for Node.js (frontend)
#
# Usage:
#   chmod +x bootstrap.sh
#   ./bootstrap.sh [--skip-ssl] [--skip-nginx]
#
# Environment Variables (set in AWS Secrets Manager):
#   API_SECRET_KEY, DATABASE_URL, OPENAI_API_KEY, DISCORD_BOT_TOKEN, etc.
# =============================================================================

set -e  # Exit on error
set -o pipefail

# =============================================================================
# Configuration
# =============================================================================
PROJECT_NAME="llm-portfolio"
PROJECT_DIR="/home/ubuntu/${PROJECT_NAME}"
VENV_DIR="${PROJECT_DIR}/.venv"
PYTHON_VERSION="3.12"
NODE_VERSION="20"  # LTS version
DOMAIN="api.llmportfolio.app"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# =============================================================================
# Utility Functions
# =============================================================================
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -eq 0 ]]; then
        log_error "Do not run this script as root. Run as 'ubuntu' user."
        exit 1
    fi
}

# =============================================================================
# Parse Arguments
# =============================================================================
SKIP_SSL=false
SKIP_NGINX=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-ssl)
            SKIP_SSL=true
            shift
            ;;
        --skip-nginx)
            SKIP_NGINX=true
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# =============================================================================
# Step 1: System Update and Base Packages
# =============================================================================
install_base_packages() {
    log_info "Updating system packages..."
    sudo apt update && sudo apt upgrade -y

    log_info "Installing base packages..."
    sudo apt install -y \
        software-properties-common \
        build-essential \
        curl \
        wget \
        git \
        unzip \
        jq \
        htop \
        tmux \
        vim \
        libpq-dev \
        libssl-dev \
        libffi-dev \
        python3-dev \
        python3-pip \
        python3-venv
}

# =============================================================================
# Step 2: Install Python 3.12
# =============================================================================
install_python() {
    log_info "Installing Python ${PYTHON_VERSION}..."
    
    # Add deadsnakes PPA for latest Python versions
    sudo add-apt-repository -y ppa:deadsnakes/ppa
    sudo apt update
    
    sudo apt install -y \
        python${PYTHON_VERSION} \
        python${PYTHON_VERSION}-venv \
        python${PYTHON_VERSION}-dev \
        python${PYTHON_VERSION}-distutils
    
    # Set Python 3.12 as default python3
    sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python${PYTHON_VERSION} 1
    
    log_info "Python version: $(python3 --version)"
}

# =============================================================================
# Step 3: Install Node.js and PM2
# =============================================================================
install_nodejs() {
    log_info "Installing Node.js ${NODE_VERSION}.x..."
    
    # Install Node.js via NodeSource
    curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | sudo -E bash -
    sudo apt install -y nodejs
    
    log_info "Node version: $(node --version)"
    log_info "NPM version: $(npm --version)"
    
    # Install PM2 globally
    log_info "Installing PM2..."
    sudo npm install -g pm2
    
    # Setup PM2 to start on boot
    pm2 startup systemd -u ubuntu --hp /home/ubuntu | tail -1 | sudo bash || true
}

# =============================================================================
# Step 4: Clone and Setup Project
# =============================================================================
setup_project() {
    log_info "Setting up project..."
    
    # Clone if not exists
    if [ ! -d "${PROJECT_DIR}" ]; then
        log_info "Cloning repository..."
        cd /home/ubuntu
        git clone https://github.com/qmyhd/LLM-portfolio-project.git ${PROJECT_NAME} || {
    cd "${PROJECT_DIR}"
    
    # Create virtual environment
    log_info "Creating Python virtual environment..."
    python3 -m venv ${VENV_DIR}
    
    # Activate and install dependencies
    source ${VENV_DIR}/bin/activate
    pip install --upgrade pip wheel setuptools
    pip install -r requirements.txt
    pip install -e .
    
    log_info "Python dependencies installed"
}

# =============================================================================
# Step 5: Install Nginx
# =============================================================================
install_nginx() {
    if [ "$SKIP_NGINX" = true ]; then
        log_warn "Skipping Nginx installation"
        return
    fi
    
    log_info "Installing Nginx..."
    sudo apt install -y nginx
    
# Copy nginx config (Ubuntu standard: sites-available + sites-enabled)
    if [ -f "${PROJECT_DIR}/nginx/api.conf" ]; then
        log_info "Configuring Nginx..."
        sudo cp ${PROJECT_DIR}/nginx/api.conf /etc/nginx/sites-available/api.conf
        sudo ln -sf /etc/nginx/sites-available/api.conf /etc/nginx/sites-enabled/api.conf

        # Update server_name with actual domain
        sudo sed -i "s/server_name .*;/server_name ${DOMAIN};/" /etc/nginx/sites-available/api.conf
        
        # Remove default site if exists
        sudo rm -f /etc/nginx/sites-enabled/default
        
        # Test config
        sudo nginx -t
        
        # Restart nginx
        sudo systemctl restart nginx
        sudo systemctl enable nginx
    else
        log_warn "nginx/api.conf not found, skipping Nginx config"
    fi
}

# =============================================================================
# Step 6: Install Certbot and Get SSL Certificate
# =============================================================================
setup_ssl() {
    if [ "$SKIP_SSL" = true ]; then
        log_warn "Skipping SSL setup"
        return
    fi
    
    if [ "$SKIP_NGINX" = true ]; then
        log_warn "Skipping SSL (Nginx not installed)"
        return
    fi
    
    log_info "Installing Certbot..."
    sudo apt install -y certbot python3-certbot-nginx
    
    log_info "Obtaining SSL certificate for ${DOMAIN}..."
    log_warn "Make sure DNS is configured to point ${DOMAIN} to this server's IP!"
    
    # Non-interactive SSL certificate
    sudo certbot --nginx -d ${DOMAIN} --non-interactive --agree-tos --email admin@llmportfolio.app || {
        log_warn "SSL certificate failed - you may need to configure DNS first"
        log_info "Run manually later: sudo certbot --nginx -d ${DOMAIN}"
    }
    
    # Setup auto-renewal
    sudo systemctl enable certbot.timer
    sudo systemctl start certbot.timer
}

# =============================================================================
# Step 7: Setup Systemd Services
# =============================================================================
setup_services() {
    log_info "Setting up systemd services..."

    # Create central AWS Secrets Manager configuration file
    log_info "Creating central AWS secrets configuration..."
    sudo mkdir -p /etc/llm-portfolio
    sudo tee /etc/llm-portfolio/llm.env > /dev/null << EOF
# AWS Secrets Manager Configuration
# This file is read by all systemd services for consistent secret loading
# REQUIRED: All services will fail to start if this file is missing
USE_AWS_SECRETS=1
AWS_REGION=us-east-1
AWS_SECRET_NAME=qqqAppsecrets
EOF
    sudo chmod 644 /etc/llm-portfolio/llm.env

    # Create log directories
    sudo mkdir -p /var/log/portfolio-api /var/log/discord-bot /var/log/portfolio-nightly
    sudo chown -R ubuntu:ubuntu /var/log/portfolio-api /var/log/discord-bot /var/log/portfolio-nightly

    # Copy canonical systemd service files from repository
    log_info "Copying systemd service files from repository..."
    if [ -d "${PROJECT_DIR}/systemd" ]; then
        sudo cp ${PROJECT_DIR}/systemd/*.service /etc/systemd/system/
        sudo cp ${PROJECT_DIR}/systemd/*.timer /etc/systemd/system/
    else
        log_error "systemd/ directory not found in project"
        return 1
    fi

    # Reload systemd
    sudo systemctl daemon-reload

    # Enable services (don't start yet - need secrets)
    sudo systemctl enable api.service
    sudo systemctl enable discord-bot.service
    sudo systemctl enable nightly-pipeline.timer

    log_info "Systemd services created and enabled"
    log_warn "Services NOT started yet - verify AWS Secrets Manager access first"
        unzip -q awscliv2.zip
        sudo ./aws/install
        rm -rf awscliv2.zip aws
    fi
    
    log_info "AWS CLI version: $(aws --version)"
    log_info "Configure AWS credentials via IAM role attached to EC2 instance"
}

# =============================================================================
# Step 9: Create Log Directories
# =============================================================================
setup_logs() {
    log_info "Setting up log directories..."
    
    mkdir -p ${PROJECT_DIR}/logs
    chmod 755 ${PROJECT_DIR}/logs
    
    # Configure logrotate
    sudo tee /etc/logrotate.d/llm-portfolio > /dev/null << EOF
${PROJECT_DIR}/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 640 ubuntu ubuntu
}
EOF
}

# =============================================================================
# Step 10: Print Status and Next Steps
# =============================================================================
print_summary() {
    log_info "=============================================="
    log_info "Bootstrap Complete!"
    log_info "=============================================="
    echo ""
    echo "Project installed to: ${PROJECT_DIR}"
    echo "Python environment: ${VENV_DIR}"
    echo ""
    echo "NEXT STEPS:"
    echo "1. Verify AWS Secrets Manager access:"
    echo "   aws secretsmanager get-secret-value --secret-id qqqAppsecrets --query 'Name'"
    echo ""
    echo "2. Start services:"
    echo "   sudo systemctl start api.service"
    echo "   sudo systemctl start discord-bot.service"
    echo "   sudo systemctl start nightly-pipeline.timer"
    echo ""
    echo "3. Check service status:"
    echo "   sudo systemctl status api.service discord-bot.service"
    echo "   sudo journalctl -u api.service -f"
    echo ""
    if [ "$SKIP_SSL" = false ] && [ "$SKIP_NGINX" = false ]; then
        echo "4. SSL should be configured for ${DOMAIN}"
        echo "   If not, run: sudo certbot --nginx -d ${DOMAIN}"
    fi
    echo ""
    echo "5. Test API endpoint:"
    echo "   curl https://${DOMAIN}/health"
    echo ""
}

# =============================================================================
# Main Execution
# =============================================================================
main() {
    log_info "Starting LLM Portfolio bootstrap for Ubuntu..."
    check_root
    
    install_base_packages
    install_python
    install_nodejs
    setup_project
    install_nginx
    setup_ssl
    setup_services
    setup_aws
    setup_logs
    print_summary
}

main "$@"
