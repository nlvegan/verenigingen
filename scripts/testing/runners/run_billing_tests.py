#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2025, Foppe de Haan
# License: GNU Affero General Public License v3 (AGPLv3)

"""
Simple Billing Transition Test Runner
Runs the proper billing transition tests using Frappe's centralized testing system
"""

import subprocess
import sys
import time

def run_billing_tests():
    """Run billing transition tests using bench command"""
    print("🧪 Running Billing Transition Tests")
    print("=" * 50)
    
    start_time = time.time()
    
    try:
        # Use Frappe's centralized testing system
        cmd = [
            "bench", "--site", "dev.veganisme.net", 
            "run-tests", "--module", "verenigingen.tests.test_billing_transitions_proper"
        ]
        
        print("Running command:", " ".join(cmd))
        print("-" * 50)
        
        result = subprocess.run(
            cmd,
            cwd="/home/frappe/frappe-bench",
            text=True,
            timeout=120  # 2 minute timeout
        )
        
        end_time = time.time()
        duration = end_time - start_time
        
        print("-" * 50)
        print(f"⏱️  Test execution time: {duration:.2f} seconds")
        
        if result.returncode == 0:
            print("✅ All billing transition tests passed!")
            return True
        else:
            print("❌ Some tests failed")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ Tests timed out after 2 minutes")
        return False
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        return False

def main():
    """Main entry point"""
    success = run_billing_tests()
    
    if success:
        print("\n🎉 Billing transition validation completed successfully!")
        print("✅ No duplicate billing scenarios detected")
        print("✅ Proper BaseTestCase patterns validated")
        print("✅ Mock bank IBAN integration working")
        print("✅ Amendment request workflows validated")
        sys.exit(0)
    else:
        print("\n💥 Billing transition tests failed")
        sys.exit(1)

if __name__ == "__main__":
    main()