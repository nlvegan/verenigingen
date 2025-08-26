#!/bin/bash

###############################################################################
# Verenigingen JavaScript Test Runner
#
# This script provides a comprehensive test runner for the Verenigingen
# association management system's JavaScript test suite. It supports multiple
# test categories, coverage reporting, and CI/CD integration.
#
# Usage:
#   ./scripts/run-js-tests.sh [OPTIONS] [TEST_CATEGORY]
#
# Options:
#   --coverage          Generate coverage report
#   --watch            Run in watch mode for development
#   --ci               Run in CI mode (no interactive features)
#   --debug            Run with debugging enabled
#   --quick            Run only quick unit tests
#   --verbose          Show detailed test output
#   --help             Show this help message
#
# Test Categories:
#   all                Run all tests (default)
#   unit               Unit tests only
#   doctypes           All DocType tests
#   integration        Integration/workflow tests
#   tier1              Tier 1 DocTypes (Member, Direct Debit, Chapter)
#   tier2              Tier 2 DocTypes (SEPA Mandate, Volunteer, Donor)
#   member             Member DocType only
#   payments           Payment-related DocTypes
#   workflows          Business workflow integration tests
#
# Examples:
#   ./scripts/run-js-tests.sh --coverage
#   ./scripts/run-js-tests.sh --watch tier1
#   ./scripts/run-js-tests.sh --ci --coverage
#   ./scripts/run-js-tests.sh member --verbose
#
# Author: Verenigingen Development Team
# Version: 1.0.0
###############################################################################

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Default options
COVERAGE=false
WATCH=false
CI=false
DEBUG=false
QUICK=false
VERBOSE=false
TEST_CATEGORY="all"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to show help
show_help() {
    cat << EOF
Verenigingen JavaScript Test Runner

USAGE:
    $0 [OPTIONS] [TEST_CATEGORY]

OPTIONS:
    --coverage          Generate comprehensive coverage report
    --watch            Run in watch mode for development
    --ci               Run in CI mode (no interactive features)
    --debug            Run with debugging enabled
    --quick            Run only quick unit tests
    --verbose          Show detailed test output
    --help             Show this help message

TEST CATEGORIES:
    all                Run all tests (default)
    unit               Unit tests only
    doctypes           All DocType tests
    integration        Integration/workflow tests
    tier1              Tier 1 DocTypes (Member, Direct Debit, Chapter)
    tier2              Tier 2 DocTypes (SEPA Mandate, Volunteer, Donor)
    member             Member DocType only
    payments           Payment-related DocTypes
    workflows          Business workflow integration tests

EXAMPLES:
    $0                                    # Run all tests
    $0 --coverage                         # Run all tests with coverage
    $0 --watch tier1                      # Watch Tier 1 DocTypes
    $0 --ci --coverage                    # CI mode with coverage
    $0 member --verbose                   # Run Member tests with verbose output
    $0 --quick                           # Quick validation tests

COVERAGE REPORTS:
    Coverage reports are generated in multiple formats:
    - Console output for immediate feedback
    - HTML report in coverage/lcov-report/index.html
    - LCOV format for CI/CD integration
    - JSON format for programmatic access

PERFORMANCE:
    - Quick tests: < 30 seconds
    - Full test suite: < 2 minutes
    - Coverage generation: + 30 seconds

For more information, see verenigingen/tests/frontend/README.md
EOF
}

# Function to validate prerequisites
validate_prerequisites() {
    print_status "Validating prerequisites..."
    
    # Check if we're in the right directory
    if [[ ! -f "$PROJECT_ROOT/package.json" ]]; then
        print_error "package.json not found. Please run from project root."
        exit 1
    fi
    
    # Check if node_modules exists
    if [[ ! -d "$PROJECT_ROOT/node_modules" ]]; then
        print_warning "node_modules not found. Running npm install..."
        cd "$PROJECT_ROOT" && npm install
    fi
    
    # Check if Jest is available
    if ! command -v npx &> /dev/null; then
        print_error "npx not found. Please install Node.js and npm."
        exit 1
    fi
    
    # Check if test files exist
    if [[ ! -d "$PROJECT_ROOT/verenigingen/tests/frontend" ]]; then
        print_error "Test directory not found: verenigingen/tests/frontend"
        exit 1
    fi
    
    print_success "Prerequisites validated"
}

# Function to build npm script based on options
build_npm_script() {
    local base_script=""
    
    case "$TEST_CATEGORY" in
        "all")
            base_script="test"
            ;;
        "unit")
            base_script="test:unit"
            ;;
        "doctypes")
            base_script="test:doctypes"
            ;;
        "integration")
            base_script="test:integration"
            ;;
        "tier1")
            base_script="test:tier1"
            ;;
        "tier2")
            base_script="test:tier2"
            ;;
        "member")
            base_script="test:member"
            ;;
        "payments")
            base_script="test:payments"
            ;;
        "workflows")
            base_script="test:workflows"
            ;;
        *)
            print_error "Unknown test category: $TEST_CATEGORY"
            echo "Available categories: all, unit, doctypes, integration, tier1, tier2, member, payments, workflows"
            exit 1
            ;;
    esac
    
    # Modify script based on options
    if [[ "$QUICK" == true ]]; then
        base_script="test:quick"
    elif [[ "$COVERAGE" == true ]]; then
        base_script="test:coverage"
    elif [[ "$WATCH" == true ]]; then
        base_script="test:watch"
    elif [[ "$CI" == true ]]; then
        base_script="test:ci"
    elif [[ "$DEBUG" == true ]]; then
        base_script="test:debug"
    fi
    
    echo "$base_script"
}

# Function to add additional Jest options
build_jest_options() {
    local options=""
    
    if [[ "$VERBOSE" == true ]]; then
        options="$options --verbose"
    fi
    
    if [[ "$CI" == true ]]; then
        options="$options --ci --watchAll=false"
    fi
    
    if [[ "$DEBUG" == true ]]; then
        options="$options --runInBand --detectOpenHandles --forceExit"
    fi
    
    echo "$options"
}

# Function to run tests
run_tests() {
    local npm_script
    local jest_options
    
    npm_script=$(build_npm_script)
    jest_options=$(build_jest_options)
    
    print_status "Running tests with category: $TEST_CATEGORY"
    print_status "Using npm script: $npm_script"
    
    if [[ -n "$jest_options" ]]; then
        print_status "Additional Jest options: $jest_options"
    fi
    
    cd "$PROJECT_ROOT"
    
    # Run the tests
    if [[ -n "$jest_options" ]]; then
        npm run "$npm_script" -- $jest_options
    else
        npm run "$npm_script"
    fi
}

# Function to display test results summary
display_summary() {
    local exit_code=$1
    
    echo ""
    echo "=========================================="
    echo "         TEST EXECUTION SUMMARY"
    echo "=========================================="
    echo "Category: $TEST_CATEGORY"
    echo "Coverage: $([ "$COVERAGE" == true ] && echo "Enabled" || echo "Disabled")"
    echo "Watch Mode: $([ "$WATCH" == true ] && echo "Enabled" || echo "Disabled")"
    echo "CI Mode: $([ "$CI" == true ] && echo "Enabled" || echo "Disabled")"
    echo "Debug Mode: $([ "$DEBUG" == true ] && echo "Enabled" || echo "Disabled")"
    echo "=========================================="
    
    if [[ $exit_code -eq 0 ]]; then
        print_success "All tests passed successfully!"
        
        if [[ "$COVERAGE" == true ]]; then
            echo ""
            print_status "Coverage reports generated:"
            echo "  - Console output (above)"
            echo "  - HTML: coverage/lcov-report/index.html"
            echo "  - LCOV: coverage/lcov.info"
            echo "  - JSON: coverage/coverage-final.json"
        fi
        
        if [[ "$CI" != true ]]; then
            echo ""
            print_status "Available test commands:"
            echo "  npm run test:watch         # Development watch mode"
            echo "  npm run test:coverage      # Full coverage report"
            echo "  npm run test:tier1         # Critical DocTypes only"
            echo "  npm run test:quick         # Fast validation tests"
        fi
    else
        print_error "Tests failed with exit code: $exit_code"
        echo ""
        print_status "Debugging tips:"
        echo "  - Run with --debug for detailed output"
        echo "  - Run with --verbose for more information"
        echo "  - Check specific test file: npm test -- member.test.js"
        echo "  - Run specific test: npm test -- --testNamePattern=\"test name\""
    fi
    
    echo "=========================================="
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --coverage)
            COVERAGE=true
            shift
            ;;
        --watch)
            WATCH=true
            shift
            ;;
        --ci)
            CI=true
            shift
            ;;
        --debug)
            DEBUG=true
            shift
            ;;
        --quick)
            QUICK=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --help)
            show_help
            exit 0
            ;;
        -*)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
        *)
            if [[ -z "$TEST_CATEGORY" ]] || [[ "$TEST_CATEGORY" == "all" ]]; then
                TEST_CATEGORY="$1"
            else
                print_error "Multiple test categories specified: $TEST_CATEGORY and $1"
                exit 1
            fi
            shift
            ;;
    esac
done

# Main execution
main() {
    echo "=========================================="
    echo "    Verenigingen JavaScript Test Suite"
    echo "=========================================="
    echo ""
    
    validate_prerequisites
    
    # Capture start time
    local start_time=$(date +%s)
    
    # Run tests and capture exit code
    local exit_code=0
    run_tests || exit_code=$?
    
    # Calculate execution time
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    echo ""
    print_status "Test execution completed in ${duration} seconds"
    
    # Display summary
    display_summary $exit_code
    
    # Exit with the same code as the tests
    exit $exit_code
}

# Execute main function
main "$@"