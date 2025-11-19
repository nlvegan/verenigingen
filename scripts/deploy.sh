#!/bin/bash
# Quick deployment script for Verenigingen app
# Usage: ./deploy.sh [staging|production] [version]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
APP_NAME="verenigingen"
DEFAULT_BRANCH="develop"

# Functions
print_header() {
    echo -e "\n${GREEN}===================================================${NC}"
    echo -e "${GREEN}$1${NC}"
    echo -e "${GREEN}===================================================${NC}\n"
}

print_error() {
    echo -e "${RED}Error: $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}Warning: $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Check arguments
if [ $# -lt 1 ]; then
    echo "Usage: $0 [staging|production] [version]"
    echo "Example: $0 staging"
    echo "Example: $0 production v1.2.3"
    exit 1
fi

ENVIRONMENT=$1
VERSION=${2:-""}

# Validate environment
if [ "$ENVIRONMENT" != "staging" ] && [ "$ENVIRONMENT" != "production" ]; then
    print_error "Invalid environment. Use 'staging' or 'production'"
    exit 1
fi

print_header "Deploying $APP_NAME to $ENVIRONMENT"

# Pre-deployment checks
print_header "Running Pre-deployment Checks"

echo "1. Checking git status..."
if [ -n "$(git status --porcelain)" ]; then
    print_warning "You have uncommitted changes"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    print_success "Working directory clean"
fi

echo -e "\n2. Running syntax checks..."
python scripts/deployment/pre_deploy_checks.py
if [ $? -eq 0 ]; then
    print_success "Pre-deployment checks passed"
else
    print_error "Pre-deployment checks failed"
    exit 1
fi

echo -e "\n3. Checking migrations..."
python scripts/deployment/check_migrations.py
if [ $? -eq 0 ]; then
    print_success "Migration check passed"
else
    print_warning "Migration issues detected"
fi

# Generate version if not provided
if [ -z "$VERSION" ]; then
    echo -e "\n4. Generating version..."
    VERSION=$(python scripts/deployment/generate_version.py)
    print_success "Generated version: $VERSION"
else
    echo -e "\n4. Using provided version: $VERSION"
fi

# Deployment confirmation
print_header "Deployment Summary"
echo "Environment: $ENVIRONMENT"
echo "Version: $VERSION"
echo "Branch: $(git rev-parse --abbrev-ref HEAD)"
echo "Commit: $(git rev-parse --short HEAD)"
echo ""

if [ "$ENVIRONMENT" == "production" ]; then
    print_warning "⚠️  PRODUCTION DEPLOYMENT ⚠️"
    echo "This will deploy to the live production environment."
    read -p "Are you absolutely sure? Type 'deploy production' to confirm: " CONFIRM
    if [ "$CONFIRM" != "deploy production" ]; then
        print_error "Deployment cancelled"
        exit 1
    fi
fi

# Tag the release
print_header "Creating Release Tag"
if git rev-parse "v$VERSION" >/dev/null 2>&1; then
    print_warning "Tag v$VERSION already exists"
else
    git tag -a "v$VERSION" -m "Release v$VERSION"
    print_success "Created tag v$VERSION"
fi

# Push to trigger deployment
print_header "Triggering Deployment"

# Notify deployment start
python scripts/deployment/notify_deployment.py \
    --environment "$ENVIRONMENT" \
    --version "$VERSION" \
    --status started

# Push changes and tags
echo "Pushing to GitHub..."
if [ "$ENVIRONMENT" == "staging" ]; then
    git push origin develop --tags
else
    git push origin main --tags
fi

print_success "Deployment triggered!"

# Wait and monitor
print_header "Monitoring Deployment"
echo "Deployment in progress..."
echo ""
echo "Monitor at:"
echo "  - GitHub Actions: https://github.com/your-org/verenigingen/actions"
echo "  - Frappe Press: https://frappecloud.com/dashboard"
echo ""

# Wait for deployment
echo "Waiting for deployment to complete (this may take 5-10 minutes)..."
sleep 300  # Wait 5 minutes

# Run post-deployment checks
print_header "Running Post-deployment Checks"
python scripts/deployment/post_deploy_checks.py \
    --environment "$ENVIRONMENT" \
    --version "$VERSION"

if [ $? -eq 0 ]; then
    print_success "Deployment successful!"
    
    # Notify success
    python scripts/deployment/notify_deployment.py \
        --environment "$ENVIRONMENT" \
        --version "$VERSION" \
        --status success
else
    print_error "Post-deployment checks failed!"
    
    # Notify failure
    python scripts/deployment/notify_deployment.py \
        --environment "$ENVIRONMENT" \
        --version "$VERSION" \
        --status failed
        
    if [ "$ENVIRONMENT" == "production" ]; then
        echo ""
        read -p "Initiate rollback? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            print_header "Initiating Rollback"
            # Rollback logic here
            python scripts/deployment/notify_deployment.py \
                --environment "$ENVIRONMENT" \
                --status rollback
        fi
    fi
fi

print_header "Deployment Complete"
echo "Version $VERSION has been deployed to $ENVIRONMENT"
echo ""
echo "Next steps:"
echo "  1. Monitor error rates for 30 minutes"
echo "  2. Check user feedback channels"
echo "  3. Verify critical workflows"
echo ""
print_success "Done!"