#!/usr/bin/env python3
"""
Email Template Test Runner

Runs email template validation tests as part of the test suite.
Can be integrated into CI/CD pipelines and development workflows.

Usage:
    python run_email_template_tests.py [--suite all|syntax|fixtures|python] [--fix] [--verbose]
"""

import argparse
import os
import sys
import subprocess

# Add the app to Python path for imports
sys.path.insert(0, '/home/frappe/frappe-bench/apps/verenigingen')


def run_frappe_tests():
    """Run email template tests using Frappe's test runner"""
    print("Running email template validation tests with Frappe...")
    
    try:
        cmd = [
            'bench', '--site', 'dev.veganisme.net', 'run-tests',
            '--app', 'verenigingen',
            '--module', 'verenigingen.tests.test_email_template_validation'
        ]
        
        result = subprocess.run(cmd, cwd='/home/frappe/frappe-bench', 
                              capture_output=True, text=True)
        
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        
        return result.returncode == 0
        
    except Exception as e:
        print(f"Error running Frappe tests: {e}")
        return False


def run_precommit_validation(fix_issues=False, verbose=False):
    """Run standalone pre-commit validation"""
    print("Running standalone email template validation...")
    
    try:
        script_path = '/home/frappe/frappe-bench/apps/verenigingen/scripts/validation/email_template_precommit_check.py'
        cmd = ['python', script_path]
        
        if fix_issues:
            cmd.append('--fix-issues')
        if verbose:
            cmd.append('--verbose')
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        
        return result.returncode == 0
        
    except Exception as e:
        print(f"Error running pre-commit validation: {e}")
        return False


def run_syntax_tests():
    """Run only syntax validation tests"""
    print("Running email template syntax tests...")
    
    try:
        # Import and run specific test methods
        from verenigingen.tests.test_email_template_validation import run_email_template_validation
        return run_email_template_validation()
        
    except Exception as e:
        print(f"Error running syntax tests: {e}")
        return False


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Run email template tests")
    parser.add_argument("--suite", choices=["all", "syntax", "fixtures", "python"], 
                       default="all", help="Test suite to run")
    parser.add_argument("--fix", action="store_true", 
                       help="Attempt to fix issues automatically")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Enable verbose output")
    parser.add_argument("--standalone", action="store_true",
                       help="Run standalone validation without Frappe context")
    
    args = parser.parse_args()
    
    print("="*60)
    print("EMAIL TEMPLATE TEST RUNNER")
    print("="*60)
    
    success = True
    
    if args.suite in ["all", "syntax"]:
        print("\n🔍 Running syntax validation tests...")
        if args.standalone:
            success &= run_precommit_validation(args.fix, args.verbose)
        else:
            success &= run_syntax_tests()
    
    if args.suite in ["all", "fixtures"]:
        print("\n📁 Running fixture validation tests...")
        success &= run_precommit_validation(args.fix, args.verbose)
    
    if args.suite in ["all", "python"]:
        print("\n🐍 Running Python code validation tests...")
        success &= run_precommit_validation(args.fix, args.verbose)
    
    if args.suite == "all" and not args.standalone:
        print("\n🧪 Running comprehensive Frappe tests...")
        success &= run_frappe_tests()
    
    print("\n" + "="*60)
    if success:
        print("✅ All email template tests PASSED!")
        print("="*60)
        sys.exit(0)
    else:
        print("❌ Some email template tests FAILED!")
        print("="*60)
        sys.exit(1)


if __name__ == "__main__":
    main()