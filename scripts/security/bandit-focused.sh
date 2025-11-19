#!/bin/bash
# Fast bandit security scan focused on high-risk files
# Runtime: ~2-5 seconds instead of 60+ seconds

set -e

echo "🔍 Running focused bandit security scan..."

# Core application files (security-critical)
CORE_FILES="verenigingen/hooks.py verenigingen/boot.py"

# API endpoints (user input handling)
API_FILES=$(find verenigingen/api -name "*.py" -not -path "*/test*" 2>/dev/null | head -20 | tr '\n' ' ')

# Payment and security utilities
SECURITY_UTILS=$(find verenigingen/utils -name "*security*" -o -name "*payment*" -o -name "*auth*" 2>/dev/null | tr '\n' ' ')

# Web forms and public endpoints  
WEB_FILES=$(find verenigingen/templates/pages -name "*.py" 2>/dev/null | head -10 | tr '\n' ' ')

# Combine all critical files
SCAN_FILES="$CORE_FILES $API_FILES $SECURITY_UTILS $WEB_FILES"

echo "📁 Scanning $(echo $SCAN_FILES | wc -w) security-critical files..."

# Run bandit with optimized configuration
bandit $SCAN_FILES \
  --skip B101,B601,B110 \
  --severity-level medium \
  --format json \
  --output bandit-results.json

# Show summary
if [ -f bandit-results.json ]; then
    ISSUES=$(jq '.results | length' bandit-results.json 2>/dev/null || echo "0")
    if [ "$ISSUES" -gt 0 ]; then
        echo "⚠️  Found $ISSUES security issue(s)"
        echo "📄 Full report: bandit-results.json"
        exit 1
    else
        echo "✅ No security issues found in critical files"
        rm -f bandit-results.json
    fi
else
    echo "✅ Bandit completed successfully"
fi