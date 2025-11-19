#!/usr/bin/env python3
"""
Run critical tests with pytest-cov within Frappe context.
This is meant to be called via bench execute.
"""

import sys
import subprocess
from pathlib import Path

def run_critical_tests_with_coverage(app_path):
    """Run critical tests with coverage measurement."""
    app_path = Path(app_path[0]) if isinstance(app_path, list) else Path(app_path)
    
    critical_tests = [
        "verenigingen/tests/test_validation_regression.py::TestValidationRegression::test_critical_api_endpoints_field_compliance",
        "verenigingen/tests/test_critical_business_logic.py::TestCriticalBusinessLogic::test_member_creation_with_all_required_fields",
    ]
    
    # Run pytest with coverage
    cmd = [
        sys.executable, "-m", "pytest",
        "--cov=verenigingen",
        "--cov-branch",
        "--cov-fail-under=60",
        "--cov-report=term-missing:skip-covered",
        "-v",
        "--tb=short",
        "--maxfail=5",
    ] + critical_tests
    
    result = subprocess.run(cmd, cwd=app_path, capture_output=True, text=True)
    
    print(result.stdout)
    if result.stderr:
        print("Errors:", result.stderr)
    
    return result.returncode == 0