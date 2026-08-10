#!/bin/bash
# Jest Pre-commit Wrapper
# Runs Jest tests without creating tracked files that trigger pre-commit failures

set -e

# Parse arguments
TEST_PATTERN=""
TEST_TYPE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --pattern)
            TEST_PATTERN="$2"
            shift 2
            ;;
        --type)
            TEST_TYPE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [[ -z "$TEST_PATTERN" ]]; then
    echo "❌ Error: --pattern is required"
    exit 1
fi

if [[ -z "$TEST_TYPE" ]]; then
    echo "❌ Error: --type is required"
    exit 1
fi

echo "🔍 Running $TEST_TYPE..."

# node_modules is gitignored, so it is absent from every git worktree - and worktrees
# are how branch work is done here, because bench serves the live site straight out of
# the main checkout. Borrow the main checkout's install rather than failing on a cause
# that has nothing to do with the diff: a hook that fails for an unrelated reason
# teaches people to reach for SKIP=, which switches off the checks that do matter.
if [[ ! -x "node_modules/.bin/jest" ]]; then
    MAIN_CHECKOUT=$(dirname "$(git rev-parse --git-common-dir 2>/dev/null || echo .)")
    if [[ -x "$MAIN_CHECKOUT/node_modules/.bin/jest" ]]; then
        echo "ℹ️  No node_modules in this checkout - using $MAIN_CHECKOUT/node_modules"
        export PATH="$MAIN_CHECKOUT/node_modules/.bin:$PATH"
        export NODE_PATH="$MAIN_CHECKOUT/node_modules"
    else
        echo "⏭️  Skipping $TEST_TYPE: jest is not installed. Run 'npm install' to enable it."
        exit 0
    fi
fi

# Create temp directory for test results
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# Set Jest to output to temp directory
export JEST_JUNIT_OUTPUT_DIR="$TEMP_DIR"
export JEST_JUNIT_OUTPUT_NAME="jest-results.xml"

# Run the tests and capture output
echo "Running tests with pattern: $TEST_PATTERN"

if OUTPUT=$(npm test -- --testPathPattern="$TEST_PATTERN" --no-coverage --passWithNoTests 2>&1); then
    # Extract useful information from Jest output
    if echo "$OUTPUT" | grep -q "Test Suites:.*passed"; then
        SUMMARY=$(echo "$OUTPUT" | grep "Test Suites:")
        echo "✅ $TEST_TYPE: $SUMMARY"
    else
        echo "✅ $TEST_TYPE: All tests passed (no output captured)"
    fi
    exit 0
else
    echo "❌ $TEST_TYPE failed:"
    echo "----------------------------------------"
    echo "$OUTPUT"
    echo "----------------------------------------"
    exit 1
fi