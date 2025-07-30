#!/usr/bin/env python3
"""
Pytest runner with Frappe integration for verenigingen app.

This script initializes the Frappe environment and database connection
before running pytest, ensuring all tests have proper access to the
Frappe framework and database.
"""

import os
import sys
import subprocess
from pathlib import Path

# Add the frappe bench to Python path
bench_path = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(bench_path))
sys.path.insert(0, str(bench_path / "apps"))

import frappe


def setup_frappe_for_pytest():
    """Initialize Frappe context for pytest execution."""
    site = os.environ.get("FRAPPE_SITE", "dev.veganisme.net")
    
    try:
        # Initialize Frappe if not already initialized
        if not hasattr(frappe, 'local') or not hasattr(frappe.local, 'db'):
            frappe.init(site=site)
            frappe.connect()
        
        # Set admin user for permissions
        frappe.set_user("Administrator")
        
        # Set test flags
        frappe.flags.in_test = True
        frappe.flags.ignore_test_email_queue = True
        
        # Clear cache to ensure fresh test state
        frappe.clear_cache()
        
    except Exception as e:
        print(f"Error initializing Frappe: {e}")
        sys.exit(1)


def run_pytest_with_coverage():
    """Run pytest with coverage in Frappe context."""
    # Ensure we're in the app directory
    app_path = Path(__file__).resolve().parent.parent.parent
    os.chdir(app_path)
    
    # Setup Frappe environment
    setup_frappe_for_pytest()
    
    # Build pytest command with all arguments passed to this script
    pytest_args = sys.argv[1:] if len(sys.argv) > 1 else []
    
    # Default coverage args if --cov not already specified
    if not any(arg.startswith("--cov") for arg in pytest_args):
        pytest_args.extend([
            "--cov=verenigingen",
            "--cov-branch",
            "--cov-report=term-missing:skip-covered",
        ])
    
    # Execute pytest
    cmd = ["python", "-m", "pytest"] + pytest_args
    
    try:
        result = subprocess.run(cmd, check=False)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\nTest run interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error running pytest: {e}")
        sys.exit(1)


def run_selective_tests_for_precommit():
    """Run a selective set of critical tests for pre-commit hook."""
    # Define critical test modules for pre-commit
    critical_tests = [
        "verenigingen/tests/test_validation_regression.py",
        "verenigingen/tests/test_critical_business_logic.py",
        "verenigingen/tests/test_security_comprehensive.py",
    ]
    
    # Filter to only existing test files
    existing_tests = [test for test in critical_tests if Path(test).exists()]
    
    if not existing_tests:
        print("Warning: No critical test files found")
        return
    
    # Add coverage threshold for pre-commit
    pytest_args = [
        "--cov=verenigingen",
        "--cov-branch",
        "--cov-fail-under=70",  # Conservative start
        "--cov-report=term-missing:skip-covered",
        "-v",
        "--tb=short",
        "--maxfail=5",  # Stop after 5 failures
    ] + existing_tests
    
    # Run with standard pytest runner
    run_pytest_with_coverage_args(pytest_args)


def run_pytest_with_coverage_args(args):
    """Helper to run pytest with specific arguments."""
    original_argv = sys.argv
    sys.argv = [sys.argv[0]] + args
    try:
        run_pytest_with_coverage()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    # Check if running in pre-commit mode
    if "--pre-commit" in sys.argv:
        sys.argv.remove("--pre-commit")
        run_selective_tests_for_precommit()
    else:
        run_pytest_with_coverage()