#!/bin/bash
# Quick wrapper to run test impact analysis
# Usage:
#   ./run-impacted-tests.sh           # Analyze and show impacted tests
#   ./run-impacted-tests.sh --run     # Analyze and run impacted tests
#   ./run-impacted-tests.sh --verbose # Show detailed analysis

cd /home/frappe/frappe-bench/apps/verenigingen
python3 scripts/testing/test_impact_analyzer.py "$@"
