#!/usr/bin/env python3
"""
Template Assignment Validation Test Runner

This script runs comprehensive tests to ensure:
1. Membership Type requires dues_schedule_template field
2. No implicit template lookup occurs
3. All template assignments are explicit and validated
4. System fails fast when required fields are missing

Usage:
    python scripts/testing/runners/template_validation_test_runner.py
    python scripts/testing/runners/template_validation_test_runner.py --verbose
"""

import sys
import os
import subprocess
import argparse
from datetime import datetime

def run_command(cmd, description):
    """Run a command and return success status"""
    print(f"\n🔍 {description}")
    print(f"   Command: {cmd}")
    
    try:
        # Split command properly to avoid shell=True security issue
        import shlex
        if isinstance(cmd, str):
            cmd_list = shlex.split(cmd)
        else:
            cmd_list = cmd
            
        result = subprocess.run(cmd_list, capture_output=True, text=True, cwd=os.getcwd())
        
        if result.returncode == 0:
            print(f"   ✅ PASSED")
            if result.stdout.strip():
                print(f"   Output: {result.stdout.strip()}")
            return True
        else:
            print(f"   ❌ FAILED")
            print(f"   Error: {result.stderr.strip()}")
            if result.stdout.strip():
                print(f"   Output: {result.stdout.strip()}")
            return False
            
    except Exception as e:
        print(f"   💥 EXCEPTION: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Run template assignment validation tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--site", default="dev.veganisme.net", help="Site name")
    args = parser.parse_args()
    
    print(f"🧪 Template Assignment Validation Test Suite")
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🌐 Site: {args.site}")
    print("=" * 80)
    
    tests = [
        {
            "cmd": f"bench --site {args.site} run-tests --app verenigingen --module verenigingen.tests.test_template_assignment_validation",
            "description": "Template Assignment Validation Tests",
            "critical": True
        },
        {
            "cmd": f"bench --site {args.site} execute \"frappe.db.sql('SELECT name, dues_schedule_template FROM `tabMembership Type` WHERE dues_schedule_template IS NULL OR dues_schedule_template = \\\"\\\";')\"",
            "description": "Check for Membership Types missing template assignment",
            "critical": True
        },
        {
            "cmd": f"bench --site {args.site} execute \"frappe.get_all('Membership Dues Schedule', filters={{'is_template': 1}}, fields=['name', 'membership_type', 'minimum_amount'])\"",
            "description": "List all templates and their minimum amounts",
            "critical": False
        }
    ]
    
    passed = 0
    failed = 0
    critical_failures = []
    
    for test in tests:
        success = run_command(test["cmd"], test["description"])
        
        if success:
            passed += 1
        else:
            failed += 1
            if test.get("critical", False):
                critical_failures.append(test["description"])
    
    print("\n" + "=" * 80)
    print(f"🏁 Test Summary:")
    print(f"   ✅ Passed: {passed}")
    print(f"   ❌ Failed: {failed}")
    
    if critical_failures:
        print(f"   🚨 Critical Failures: {len(critical_failures)}")
        for failure in critical_failures:
            print(f"      - {failure}")
    
    print(f"⏰ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if critical_failures:
        print("\n🚨 CRITICAL VALIDATION FAILURES DETECTED!")
        print("   These tests are designed to fail when template assignment is not properly configured.")
        print("   Please fix the issues above before proceeding.")
        sys.exit(1)
    elif failed > 0:
        print(f"\n⚠️  Some non-critical tests failed, but validation passed.")
        sys.exit(0)
    else:
        print(f"\n🎉 All template assignment validation tests passed!")
        sys.exit(0)

if __name__ == "__main__":
    main()