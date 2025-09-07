#!/bin/bash

##############################################################################
# Mollie Donation Flow E2E Test Runner
#
# This script provides comprehensive test execution for the Mollie donation
# flow end-to-end testing suite with various execution modes and options.
#
# Features:
# - Multiple test execution modes (full, quick, specific scenarios)
# - Browser selection (Chrome, Firefox, mobile)
# - Environment validation and setup
# - Comprehensive reporting and artifact management
# - CI/CD integration support
#
# Usage Examples:
#   ./run_mollie_e2e_tests.sh --full                    # Run complete test suite
#   ./run_mollie_e2e_tests.sh --quick                   # Run essential tests only
#   ./run_mollie_e2e_tests.sh --browser chrome          # Test specific browser
#   ./run_mollie_e2e_tests.sh --headless                # Run in headless mode
#   ./run_mollie_e2e_tests.sh --debug                   # Debug mode with logging
#
##############################################################################

set -e  # Exit on any error

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_RESULTS_DIR="${SCRIPT_DIR}/test-results"
PLAYWRIGHT_CONFIG="${SCRIPT_DIR}/playwright.config.js"

# Default configuration
HEADLESS=false
BROWSER="chrome"
TEST_MODE="full"
DEBUG=false
GENERATE_REPORT=true
CLEANUP_AFTER=true

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

##############################################################################
# Utility Functions
##############################################################################

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_usage() {
    cat << EOF
Mollie Donation Flow E2E Test Runner

Usage: $0 [OPTIONS]

OPTIONS:
    --full              Run complete test suite (default)
    --quick             Run essential tests only
    --smoke             Run smoke tests for basic functionality
    --performance       Run performance and load testing
    --webhook           Run webhook-specific tests only

    --browser BROWSER   Specify browser: chrome, firefox, mobile (default: chrome)
    --headless          Run in headless mode (default: false)
    --debug             Enable debug mode with verbose logging

    --no-setup          Skip environment setup and validation
    --no-cleanup        Skip cleanup after tests
    --no-report         Skip report generation

    --ci                CI mode (headless, no interactive prompts)
    --help              Show this help message

EXAMPLES:
    $0 --full --browser chrome
    $0 --quick --headless --ci
    $0 --webhook --debug
    $0 --performance --no-cleanup

ENVIRONMENT VARIABLES:
    MOLLIE_TEST_API_KEY     Mollie test API key for payment simulation
    MOLLIE_WEBHOOK_SECRET   Webhook signature verification key
    NODE_ENV               Environment (development, testing, ci)
    CI                     Set to 'true' for CI/CD environments

EOF
}

##############################################################################
# Environment Setup and Validation
##############################################################################

validate_environment() {
    log_info "Validating test environment..."

    # Check if we're in the correct directory
    if [[ ! -f "${PLAYWRIGHT_CONFIG}" ]]; then
        log_error "Playwright config not found: ${PLAYWRIGHT_CONFIG}"
        log_error "Please run this script from the verenigingen app directory"
        exit 1
    fi

    # Check if development server is running
    if ! curl -s -k "https://dev.veganisme.net" > /dev/null; then
        log_error "Development server not accessible at https://dev.veganisme.net"
        log_error "Please ensure the development server is running: bench start"
        exit 1
    fi

    # Check Node.js and npm
    if ! command -v node &> /dev/null; then
        log_error "Node.js not found. Please install Node.js"
        exit 1
    fi

    if ! command -v npm &> /dev/null; then
        log_error "npm not found. Please install npm"
        exit 1
    fi

    # Check if Playwright is installed
    if [[ ! -d "node_modules/@playwright/test" ]]; then
        log_warning "Playwright not found. Installing dependencies..."
        npm install
    fi

    # Install Playwright browsers if needed
    if ! npx playwright --version > /dev/null 2>&1; then
        log_info "Installing Playwright browsers..."
        npx playwright install
    fi

    log_success "Environment validation completed"
}

setup_test_environment() {
    log_info "Setting up test environment..."

    # Create test results directory
    mkdir -p "${TEST_RESULTS_DIR}"

    # Clear previous test results if not in CI
    if [[ "${CI}" != "true" ]] && [[ "${CLEANUP_AFTER}" == "true" ]]; then
        if [[ -d "${TEST_RESULTS_DIR}/html-report" ]]; then
            rm -rf "${TEST_RESULTS_DIR}/html-report"
        fi
        if [[ -f "${TEST_RESULTS_DIR}/test-results.json" ]]; then
            rm -f "${TEST_RESULTS_DIR}/test-results.json"
        fi
    fi

    # Set environment variables for testing
    export NODE_ENV="${NODE_ENV:-testing}"
    export PLAYWRIGHT_TEST_BASE_URL="https://dev.veganisme.net"

    # Set debug flags if debug mode
    if [[ "${DEBUG}" == "true" ]]; then
        export DEBUG="pw:*"
        export PLAYWRIGHT_VIDEO="on"
        export PLAYWRIGHT_SCREENSHOT="on"
    fi

    log_success "Test environment setup completed"
}

##############################################################################
# Test Execution Functions
##############################################################################

run_full_test_suite() {
    log_info "Running complete Mollie donation E2E test suite..."

    local playwright_args=(
        "test"
        "--config=${PLAYWRIGHT_CONFIG}"
        "--project=mollie-donation-${BROWSER}"
    )

    if [[ "${HEADLESS}" == "true" ]]; then
        playwright_args+=("--headed=false")
    fi

    if [[ "${DEBUG}" == "true" ]]; then
        playwright_args+=("--debug")
        playwright_args+=("--timeout=300000")  # 5 minute timeout for debugging
    fi

    npx playwright "${playwright_args[@]}"
    return $?
}

run_quick_test_suite() {
    log_info "Running quick Mollie donation test suite..."

    local playwright_args=(
        "test"
        "--config=${PLAYWRIGHT_CONFIG}"
        "--project=mollie-donation-${BROWSER}"
        "--grep=Happy Path|Single donation"  # Run only essential tests
    )

    if [[ "${HEADLESS}" == "true" ]]; then
        playwright_args+=("--headed=false")
    fi

    npx playwright "${playwright_args[@]}"
    return $?
}

run_smoke_tests() {
    log_info "Running smoke tests for basic functionality..."

    local playwright_args=(
        "test"
        "--config=${PLAYWRIGHT_CONFIG}"
        "--project=mollie-donation-${BROWSER}"
        "--grep=Happy Path"  # Run only the basic happy path test
    )

    if [[ "${HEADLESS}" == "true" ]]; then
        playwright_args+=("--headed=false")
    fi

    npx playwright "${playwright_args[@]}"
    return $?
}

run_performance_tests() {
    log_info "Running performance and load testing..."

    local playwright_args=(
        "test"
        "--config=${PLAYWRIGHT_CONFIG}"
        "--project=performance-testing"
        "--grep=Performance|concurrent"
    )

    if [[ "${HEADLESS}" == "true" ]]; then
        playwright_args+=("--headed=false")
    fi

    npx playwright "${playwright_args[@]}"
    return $?
}

run_webhook_tests() {
    log_info "Running webhook-specific tests..."

    local playwright_args=(
        "test"
        "--config=${PLAYWRIGHT_CONFIG}"
        "--project=webhook-comprehensive"
        "--grep=webhook|Webhook"
    )

    if [[ "${HEADLESS}" == "true" ]]; then
        playwright_args+=("--headed=false")
    fi

    npx playwright "${playwright_args[@]}"
    return $?
}

##############################################################################
# Reporting and Cleanup
##############################################################################

generate_test_report() {
    if [[ "${GENERATE_REPORT}" != "true" ]]; then
        return 0
    fi

    log_info "Generating comprehensive test report..."

    # Generate HTML report if results exist
    if [[ -f "${TEST_RESULTS_DIR}/test-results.json" ]]; then
        npx playwright show-report "${TEST_RESULTS_DIR}/html-report" --host=localhost
    fi

    # Generate custom summary report
    if [[ -f "${TEST_RESULTS_DIR}/test-summary.json" ]]; then
        log_info "Test summary available at: ${TEST_RESULTS_DIR}/test-summary.json"

        # Show key metrics if not in CI
        if [[ "${CI}" != "true" ]]; then
            echo
            log_info "=== TEST EXECUTION SUMMARY ==="
            if command -v jq &> /dev/null; then
                jq -r '"Tests: " + (.execution.totalTests|tostring) + ", Passed: " + (.execution.passed|tostring) + ", Failed: " + (.execution.failed|tostring) + ", Success Rate: " + .metrics.successRate' "${TEST_RESULTS_DIR}/test-summary.json"
            else
                cat "${TEST_RESULTS_DIR}/test-summary.json"
            fi
            echo
        fi
    fi

    log_success "Test report generation completed"
}

cleanup_test_environment() {
    if [[ "${CLEANUP_AFTER}" != "true" ]]; then
        return 0
    fi

    log_info "Performing test environment cleanup..."

    # Archive old test runs (keep last 5)
    if [[ -d "${TEST_RESULTS_DIR}/archive" ]]; then
        local archive_count=$(find "${TEST_RESULTS_DIR}/archive" -maxdepth 1 -type d -name "run-*" | wc -l)
        if [[ $archive_count -gt 5 ]]; then
            find "${TEST_RESULTS_DIR}/archive" -maxdepth 1 -type d -name "run-*" | sort | head -n $(($archive_count - 5)) | xargs rm -rf
            log_info "Archived old test runs (keeping last 5)"
        fi
    fi

    log_success "Cleanup completed"
}

##############################################################################
# Main Execution Logic
##############################################################################

main() {
    local test_result=0
    local start_time=$(date +%s)

    log_info "=== Mollie Donation E2E Test Suite ==="
    log_info "Mode: ${TEST_MODE}, Browser: ${BROWSER}, Headless: ${HEADLESS}"
    log_info "Configuration: ${PLAYWRIGHT_CONFIG}"
    echo

    # Environment setup
    if [[ "${1}" != "--no-setup" ]]; then
        validate_environment
        setup_test_environment
    fi

    # Execute tests based on mode
    case "${TEST_MODE}" in
        "full")
            run_full_test_suite
            test_result=$?
            ;;
        "quick")
            run_quick_test_suite
            test_result=$?
            ;;
        "smoke")
            run_smoke_tests
            test_result=$?
            ;;
        "performance")
            run_performance_tests
            test_result=$?
            ;;
        "webhook")
            run_webhook_tests
            test_result=$?
            ;;
        *)
            log_error "Unknown test mode: ${TEST_MODE}"
            show_usage
            exit 1
            ;;
    esac

    # Report and cleanup
    generate_test_report
    cleanup_test_environment

    # Final summary
    local end_time=$(date +%s)
    local duration=$(($end_time - $start_time))

    echo
    log_info "=== TEST EXECUTION COMPLETED ==="
    log_info "Duration: ${duration} seconds"

    if [[ $test_result -eq 0 ]]; then
        log_success "All tests passed successfully! ✅"
    else
        log_error "Some tests failed ❌"
        log_info "Check test results at: ${TEST_RESULTS_DIR}/html-report/index.html"
    fi

    exit $test_result
}

##############################################################################
# Command Line Argument Processing
##############################################################################

while [[ $# -gt 0 ]]; do
    case $1 in
        --full)
            TEST_MODE="full"
            shift
            ;;
        --quick)
            TEST_MODE="quick"
            shift
            ;;
        --smoke)
            TEST_MODE="smoke"
            shift
            ;;
        --performance)
            TEST_MODE="performance"
            shift
            ;;
        --webhook)
            TEST_MODE="webhook"
            shift
            ;;
        --browser)
            BROWSER="$2"
            shift 2
            ;;
        --headless)
            HEADLESS=true
            shift
            ;;
        --debug)
            DEBUG=true
            shift
            ;;
        --no-setup)
            shift  # This is handled in main()
            ;;
        --no-cleanup)
            CLEANUP_AFTER=false
            shift
            ;;
        --no-report)
            GENERATE_REPORT=false
            shift
            ;;
        --ci)
            HEADLESS=true
            CI=true
            DEBUG=false
            shift
            ;;
        --help)
            show_usage
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Execute main function
main "$@"
