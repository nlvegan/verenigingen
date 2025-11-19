#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Lifecycle Test Runner
Executes the complete member lifecycle workflow test
"""

import os
import subprocess
import sys
from datetime import datetime


def run_lifecycle_test():
    """Run the member lifecycle test via bench"""

    print("=" * 60)
    print("MEMBER LIFECYCLE TEST RUNNER")
    print("=" * 60)
    print(f"Started at: {datetime.now()}")
    print()

    # Change to bench directory
    bench_dir = "/home/frappe/frappe-bench"
    app_dir = "/home/frappe/frappe-bench/apps/verenigingen"

    print(f"Bench directory: {bench_dir}")
    print(f"App directory: {app_dir}")
    print()

    # Verify we're in the right location
    if not os.path.exists(os.path.join(bench_dir, "sites", "dev.veganisme.net")):
        print("ERROR: Site dev.veganisme.net not found")
        return False

    if not os.path.exists(
        os.path.join(app_dir, "verenigingen", "tests", "workflows", "test_member_lifecycle.py")
    ):
        print("ERROR: Lifecycle test file not found")
        return False

    # Build the test command
    test_command = [
        "bench",
        "--site",
        "dev.veganisme.net",
        "run-tests",
        "--app",
        "verenigingen",
        "--module",
        "verenigingen.tests.workflows.test_member_lifecycle",
    ]

    print("Running command:")
    print(" ".join(test_command))
    print()

    try:
        # Execute the test
        result = subprocess.run(
            test_command, cwd=bench_dir, capture_output=True, text=True, timeout=300  # 5 minute timeout
        )

        print("STDOUT:")
        print("-" * 40)
        print(result.stdout)
        print()

        if result.stderr:
            print("STDERR:")
            print("-" * 40)
            print(result.stderr)
            print()

        print(f"Return code: {result.returncode}")

        if result.returncode == 0:
            print("✅ LIFECYCLE TEST PASSED")
            return True
        else:
            print("❌ LIFECYCLE TEST FAILED")
            return False

    except subprocess.TimeoutExpired:
        print("❌ TEST TIMED OUT (5 minutes)")
        return False
    except Exception as e:
        print(f"❌ ERROR RUNNING TEST: {e}")
        return False
    finally:
        print()
        print(f"Completed at: {datetime.now()}")


if __name__ == "__main__":
    success = run_lifecycle_test()
    sys.exit(0 if success else 1)
