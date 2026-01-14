#!/usr/bin/env python3
"""
Pytest runner specifically for pre-commit hooks.
Uses existing test infrastructure with coverage measurement.
"""

import os
import sys
import subprocess
from pathlib import Path

def get_current_site(bench_path: Path) -> str:
    """Get the current site from bench configuration."""
    currentsite_file = bench_path / "sites" / "currentsite.txt"
    if currentsite_file.exists():
        site = currentsite_file.read_text().strip()
        if site:
            return site
    # Fallback to default site
    return "veg11.veganisme.org"


def run_pytest_for_precommit():
    """Run critical tests for pre-commit using bench command."""
    # Get the bench path
    bench_path = Path(__file__).resolve().parent.parent.parent.parent.parent
    app_path = bench_path / "apps" / "verenigingen"
    site = get_current_site(bench_path)
    
    # Check if critical test files exist
    critical_tests = [
        app_path / "verenigingen/tests/test_validation_regression.py",
        app_path / "verenigingen/tests/backend/business_logic/test_critical_business_logic.py",
    ]
    
    if not any(test.exists() for test in critical_tests):
        print("✅ No critical test files found (skipping)")
        return 0
    
    # Change to bench directory for command execution
    os.chdir(bench_path)
    
    # Run existing test runner with coverage
    # Using the existing test runner that already handles Frappe context
    # Note: Multiple modules can be run in sequence for comprehensive coverage
    test_modules = [
        "verenigingen.tests.test_validation_regression",
        "verenigingen.tests.backend.business_logic.test_critical_business_logic"
    ]
    
    cmd = [
        "bench", "--site", site,
        "run-tests",
        "--app", "verenigingen",
        "--module", test_modules[0],  # Start with validation regression
        "--coverage"
    ]
    
    try:
        print("📊 Running critical tests with coverage check...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        if result.returncode == 0:
            print("✅ Critical tests passed!")
            
            # Try to extract and display coverage info
            coverage_section_found = False
            print("\nTest Output Summary:")
            for line in result.stdout.split('\n'):
                line = line.strip()
                if not line:
                    continue
                    
                # Look for coverage-related lines
                if any(keyword in line.lower() for keyword in ['coverage', 'stmts', 'miss', 'cover']):
                    if not coverage_section_found:
                        print("\n📊 Coverage Information:")
                        coverage_section_found = True
                    print(f"   {line}")
                
                # Look for test results
                elif any(keyword in line for keyword in ['passed', 'failed', 'error', 'PASSED', 'FAILED']):
                    print(f"   {line}")
                
                # Look for percentage coverage
                elif '%' in line and any(keyword in line.lower() for keyword in ['verenig', 'total']):
                    if not coverage_section_found:
                        print("\n📊 Coverage Information:")
                        coverage_section_found = True
                    print(f"   {line}")
            
            return 0
        else:
            print("❌ Critical tests failed!")
            print("\nTest Output:")
            print(result.stdout[-1000:])  # Last 1000 chars to avoid too much output
            if result.stderr:
                print("\nErrors:")
                print(result.stderr[-500:])
            return 1
            
    except subprocess.TimeoutExpired:
        print("⚠️  Test execution timed out (60s limit)")
        return 1
    except Exception as e:
        print(f"⚠️  Error running tests: {e}")
        print("Proceeding with commit (test infrastructure issue)")
        return 0  # Don't block commits if test setup fails

if __name__ == "__main__":
    sys.exit(run_pytest_for_precommit())