#!/bin/bash

# Verenigingen JavaScript Controller E2E Test Runner
# This script runs comprehensive Cypress E2E tests that validate the actual
# JavaScript DocType controllers and business workflows.

set -e  # Exit on any error

echo "🚀 Verenigingen JavaScript Controller E2E Testing Suite"
echo "================================================="
echo "Testing Strategy: Real JavaScript controllers without mocking"
echo "Focus: Dutch business logic, SEPA compliance, form interactions"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if development server is running
echo -e "${BLUE}Checking development server status...${NC}"
if ! curl -s http://dev.veganisme.net:8000/api/method/ping > /dev/null; then
    echo -e "${RED}❌ Development server not accessible at dev.veganisme.net:8000${NC}"
    echo "Please ensure the development server is running with:"
    echo "  bench --site dev.veganisme.net serve --port 8000"
    exit 1
fi
echo -e "${GREEN}✅ Development server is accessible${NC}"
echo ""

# Check if Cypress is installed
echo -e "${BLUE}Checking Cypress installation...${NC}"
if ! command -v npx cypress &> /dev/null; then
    echo -e "${RED}❌ Cypress not found${NC}"
    echo "Installing Cypress and dependencies..."
    npm install
fi
echo -e "${GREEN}✅ Cypress is available${NC}"
echo ""

# Function to run specific test with summary
run_test() {
    local test_file=$1
    local test_name=$2
    local priority=$3
    
    echo -e "${YELLOW}🧪 Running: ${test_name} (Priority ${priority})${NC}"
    echo "File: ${test_file}"
    echo "Focus: Testing real JavaScript controllers and business logic"
    echo ""
    
    if npx cypress run --spec "cypress/integration/${test_file}" --reporter json > /tmp/cypress-result.json 2>&1; then
        echo -e "${GREEN}✅ PASSED: ${test_name}${NC}"
        
        # Extract test stats if available
        if command -v jq &> /dev/null && [ -f /tmp/cypress-result.json ]; then
            local tests=$(jq -r '.stats.tests // 0' /tmp/cypress-result.json 2>/dev/null || echo "?")
            local passes=$(jq -r '.stats.passes // 0' /tmp/cypress-result.json 2>/dev/null || echo "?")
            local duration=$(jq -r '.stats.duration // 0' /tmp/cypress-result.json 2>/dev/null || echo "?")
            echo "   Tests: ${tests}, Passed: ${passes}, Duration: ${duration}ms"
        fi
    else
        echo -e "${RED}❌ FAILED: ${test_name}${NC}"
        
        # Show error summary
        if [ -f /tmp/cypress-result.json ]; then
            echo "Error details:"
            tail -n 20 /tmp/cypress-result.json | grep -E "(Error|Failed|AssertionError)" || echo "Check full logs for details"
        fi
        
        return 1
    fi
    echo ""
}

# Test execution plan
echo -e "${BLUE}📋 Test Execution Plan${NC}"
echo "Priority 1: Core Business Workflows (Critical JavaScript controllers)"
echo "Priority 2: Integration and Edge Cases"
echo "Priority 3: Advanced Features and Error Handling"
echo ""

# Track results
PASSED_TESTS=0
FAILED_TESTS=0
TOTAL_TESTS=0

# Priority 1 Tests - Core Business Workflows
echo -e "${BLUE}🎯 PRIORITY 1: Core Business Workflows${NC}"
echo "These tests validate the most critical JavaScript controllers"
echo ""

# Member DocType JavaScript Controller Tests
TOTAL_TESTS=$((TOTAL_TESTS + 1))
if run_test "member-lifecycle-management.spec.js" "Member JavaScript Controller Tests" "1"; then
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi

# SEPA Direct Debit Processing Tests
TOTAL_TESTS=$((TOTAL_TESTS + 1))
if run_test "sepa-direct-debit-processing.spec.js" "SEPA JavaScript Processing Tests" "1"; then
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi

# Chapter Management Tests
TOTAL_TESTS=$((TOTAL_TESTS + 1))
if run_test "chapter-geographic-management.spec.js" "Chapter JavaScript Management Tests" "1"; then
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi

# Priority 2 Tests - Dutch Business Logic Validation
echo -e "${BLUE}🇳🇱 PRIORITY 2: Dutch Business Logic Validation${NC}"
echo "Testing Dutch-specific validation and compliance features"
echo ""

TOTAL_TESTS=$((TOTAL_TESTS + 1))
if run_test "dutch-business-logic-validation.spec.js" "Dutch Compliance Tests" "2"; then
    PASSED_TESTS=$((PASSED_TESTS + 1))
else
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi

# Optional: Run additional integration tests if they exist
if [ -f "cypress/integration/volunteer-management-workflow.spec.js" ]; then
    echo -e "${BLUE}👥 PRIORITY 3: Volunteer Management${NC}"
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    if run_test "volunteer-management-workflow.spec.js" "Volunteer JavaScript Tests" "3"; then
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
fi

# Test Summary
echo "================================================="
echo -e "${BLUE}📊 Test Execution Summary${NC}"
echo "================================================="
echo "Total Tests Run: ${TOTAL_TESTS}"
echo -e "Passed: ${GREEN}${PASSED_TESTS}${NC}"
echo -e "Failed: ${RED}${FAILED_TESTS}${NC}"

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}🎉 All JavaScript controller tests PASSED!${NC}"
    echo "✅ Member DocType controllers functioning correctly"
    echo "✅ SEPA payment processing workflows validated"
    echo "✅ Chapter management features working"
    echo "✅ Dutch business logic compliance verified"
    echo ""
    echo "Your JavaScript controllers are ready for production! 🚀"
else
    echo -e "${RED}⚠️  Some tests FAILED${NC}"
    echo "Please review the failed tests and fix the JavaScript controller issues."
    echo ""
    echo "Common issues to check:"
    echo "• JavaScript modules not loading correctly"
    echo "• Form event handlers not triggering"
    echo "• Validation logic errors"
    echo "• Dutch business rule implementation"
    echo "• SEPA compliance issues"
fi

echo ""
echo -e "${BLUE}📈 Key Test Metrics Validated:${NC}"
echo "• JavaScript form controller initialization"
echo "• Real-time field validation and events"
echo "• Dutch naming conventions (tussenvoegsel)"
echo "• IBAN validation for all major Dutch banks"
echo "• Postal code geographic assignment"
echo "• SEPA XML generation and compliance"
echo "• Age-based eligibility calculations"
echo "• Chapter assignment algorithms"
echo "• Payment workflow state management"

echo ""
echo -e "${BLUE}🎯 Testing Strategy Highlights:${NC}"
echo "• No mocking - tests run against real JavaScript controllers"
echo "• Uses authentic Dutch data (IBANs, postal codes, names)"
echo "• Validates actual UI interactions and form behaviors"
echo "• Tests JavaScript business logic in browser environment"
echo "• Verifies regulatory compliance (SEPA, Dutch banking)"

# Exit with appropriate code
if [ $FAILED_TESTS -eq 0 ]; then
    exit 0
else
    exit 1
fi
