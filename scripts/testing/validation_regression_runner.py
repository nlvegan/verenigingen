#!/usr/bin/env python3
"""
Validation Regression Test Runner
================================

Quick runner for validation regression tests that prevent database field 
reference issues and other structural problems.

Usage:
    python scripts/testing/validation_regression_runner.py
    python scripts/testing/validation_regression_runner.py --verbose
    python scripts/testing/validation_regression_runner.py --quick
"""

import subprocess
import sys
import time
from pathlib import Path


def run_validation_tests(quick=False, verbose=False):
    """Run validation regression tests"""
    
    print("🔍 Running Validation Regression Tests...")
    print("=" * 60)
    
    if quick:
        print("⚡ Quick mode - running full test suite with brief output")
        cmd = [
            "bench", "--site", "dev.veganisme.net", "run-tests",
            "--app", "verenigingen", "--module", "verenigingen.tests.test_validation_regression"
        ]
        
        result = subprocess.run(cmd, capture_output=not verbose, text=True)
        
        if result.returncode == 0:
            print("   ✅ PASSED")
            return True
        else:
            print("   ❌ FAILED")
            if verbose:
                print(f"   Error: {result.stderr}")
            return False
                
    else:
        print("🧪 Full validation regression test suite")
        cmd = [
            "bench", "--site", "dev.veganisme.net", "run-tests",
            "--app", "verenigingen", "--module", "verenigingen.tests.test_validation_regression"
        ]
        
        start_time = time.time()
        result = subprocess.run(cmd, capture_output=not verbose, text=True)
        end_time = time.time()
        
        if result.returncode == 0:
            print(f"✅ All validation tests PASSED ({end_time - start_time:.2f}s)")
            return True
        else:
            print(f"❌ Validation tests FAILED ({end_time - start_time:.2f}s)")
            if verbose:
                print("Error output:")
                print(result.stderr)
            return False
    
    return True


def run_field_validation():
    """Run the standalone field validator"""
    
    print("\n🔧 Running Field Reference Validator...")
    print("-" * 40)
    
    try:
        cmd = ["python", "scripts/validation/field_validator.py"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Field validation completed")
            print(result.stdout)
            return True
        else:
            print("❌ Field validation failed")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"❌ Error running field validator: {e}")
        return False


def main():
    """Main test runner"""
    
    import argparse
    parser = argparse.ArgumentParser(description="Run validation regression tests")
    parser.add_argument("--quick", action="store_true", help="Run quick tests only")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--field-validation-only", action="store_true", 
                       help="Run only field validation, not regression tests")
    
    args = parser.parse_args()
    
    print("🛡️  Validation Regression Test Runner")
    print("=====================================")
    
    if args.field_validation_only:
        success = run_field_validation()
    else:
        # Run regression tests
        test_success = run_validation_tests(quick=args.quick, verbose=args.verbose)
        
        # Run field validation as well
        field_success = run_field_validation()
        
        success = test_success and field_success
    
    if success:
        print("\n🎉 All validation checks PASSED!")
        print("📈 Code quality: GOOD")
        print("🔒 Regression protection: ACTIVE")
        sys.exit(0)
    else:
        print("\n⚠️  Some validation checks FAILED!")
        print("📉 Code quality: NEEDS ATTENTION")
        print("🚨 Regression risk: ELEVATED")
        sys.exit(1)


if __name__ == "__main__":
    main()