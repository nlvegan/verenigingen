#!/bin/bash
#
# GitHub Actions Self-Hosted Runner Setup Script
# For Verenigingen development and staging environments
#
# Usage:
#   ./scripts/setup-github-runner.sh dev      # Development machine
#   ./scripts/setup-github-runner.sh staging  # Staging server
#   ./scripts/setup-github-runner.sh prod     # Production server (read-only jobs only)
#
# Prerequisites:
#   - Get a registration token from:
#     https://github.com/nlvegan/verenigingen/settings/actions/runners/new
#   - Token is only needed once during setup (expires in 1 hour)
#   - After registration, credentials are permanent
#

set -e

# Configuration
RUNNER_VERSION="2.321.0"
RUNNER_DIR="/home/frappe/actions-runner"
REPO_URL="https://github.com/nlvegan/verenigingen"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get environment label from argument
ENV_LABEL="${1:-dev}"

if [[ ! "$ENV_LABEL" =~ ^(dev|staging|prod)$ ]]; then
    echo -e "${RED}Error: Invalid environment. Use: dev, staging, or prod${NC}"
    echo "Usage: $0 <dev|staging|prod>"
    exit 1
fi

echo -e "${GREEN}=== GitHub Actions Runner Setup ===${NC}"
echo -e "Environment: ${YELLOW}${ENV_LABEL}${NC}"
echo -e "Runner directory: ${RUNNER_DIR}"
echo ""

# Check if runner is already configured
if [[ -f "${RUNNER_DIR}/.runner" ]]; then
    echo -e "${YELLOW}Warning: Runner already configured at ${RUNNER_DIR}${NC}"
    echo "Current configuration:"
    cat "${RUNNER_DIR}/.runner" | grep -E '"agentName"|"gitHubUrl"' || true
    echo ""
    read -p "Remove existing configuration and reconfigure? (y/N): " RECONFIGURE
    if [[ "$RECONFIGURE" != "y" && "$RECONFIGURE" != "Y" ]]; then
        echo "Keeping existing configuration. Exiting."
        exit 0
    fi

    # Stop service if running
    if systemctl is-active --quiet "actions.runner.*" 2>/dev/null; then
        echo "Stopping existing runner service..."
        sudo ./svc.sh stop 2>/dev/null || true
        sudo ./svc.sh uninstall 2>/dev/null || true
    fi

    # Remove old config
    cd "${RUNNER_DIR}"
    ./config.sh remove --token dummy 2>/dev/null || true
    rm -f .runner .credentials .credentials_rsaparams 2>/dev/null || true
fi

# Create runner directory
echo -e "${GREEN}Creating runner directory...${NC}"
mkdir -p "${RUNNER_DIR}"
cd "${RUNNER_DIR}"

# Check if we need to download
CURRENT_VERSION=""
if [[ -f "./bin/Runner.Listener" ]]; then
    CURRENT_VERSION=$(./bin/Runner.Listener --version 2>/dev/null || echo "unknown")
fi

if [[ "$CURRENT_VERSION" != "$RUNNER_VERSION" ]]; then
    echo -e "${GREEN}Downloading runner v${RUNNER_VERSION}...${NC}"
    curl -sL -o actions-runner.tar.gz \
        "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"

    echo "Extracting..."
    tar xzf actions-runner.tar.gz
    rm actions-runner.tar.gz
else
    echo -e "${GREEN}Runner v${CURRENT_VERSION} already installed${NC}"
fi

# Generate runner name
HOSTNAME=$(hostname -s)
RUNNER_NAME="${ENV_LABEL}-${HOSTNAME}"

echo ""
echo -e "${YELLOW}=== Registration ===${NC}"
echo "Runner name will be: ${RUNNER_NAME}"
echo ""
echo "Get your registration token from:"
echo -e "${GREEN}${REPO_URL}/settings/actions/runners/new${NC}"
echo ""
echo "(The token expires in 1 hour but is only needed once)"
echo ""
read -p "Enter registration token: " TOKEN

if [[ -z "$TOKEN" ]]; then
    echo -e "${RED}Error: Token is required${NC}"
    exit 1
fi

# Configure the runner
echo ""
echo -e "${GREEN}Configuring runner...${NC}"
./config.sh \
    --url "${REPO_URL}" \
    --token "${TOKEN}" \
    --name "${RUNNER_NAME}" \
    --labels "self-hosted,linux,x64,${ENV_LABEL},frappe-bench" \
    --work "_work" \
    --unattended

echo ""
echo -e "${GREEN}=== Runner configured successfully ===${NC}"
echo ""

# Install as systemd service
echo -e "${YELLOW}=== Service Installation ===${NC}"
echo "Installing as systemd service requires sudo."
read -p "Install as systemd service? (Y/n): " INSTALL_SERVICE

if [[ "$INSTALL_SERVICE" != "n" && "$INSTALL_SERVICE" != "N" ]]; then
    CURRENT_USER=$(whoami)
    echo "Installing service for user: ${CURRENT_USER}"

    sudo ./svc.sh install "${CURRENT_USER}"
    sudo ./svc.sh start

    echo ""
    echo -e "${GREEN}Service installed and started!${NC}"
    sudo ./svc.sh status
else
    echo ""
    echo "Skipping service installation."
    echo "To run manually: cd ${RUNNER_DIR} && ./run.sh"
    echo "To install later: sudo ./svc.sh install \$(whoami) && sudo ./svc.sh start"
fi

echo ""
echo -e "${GREEN}=== Setup Complete ===${NC}"
echo ""
echo "Runner: ${RUNNER_NAME}"
echo "Labels: self-hosted, linux, x64, ${ENV_LABEL}, frappe-bench"
echo "Directory: ${RUNNER_DIR}"
echo ""
echo "Useful commands:"
echo "  View logs:    journalctl -u actions.runner.* -f"
echo "  Stop:         sudo ./svc.sh stop"
echo "  Start:        sudo ./svc.sh start"
echo "  Uninstall:    sudo ./svc.sh uninstall"
echo ""
echo "In workflows, target this runner with:"
echo "  runs-on: [self-hosted, ${ENV_LABEL}]"
echo ""
