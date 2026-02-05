"""
Verification script for fee query consolidation tests.

Run via: bench --site veg11.veganisme.org execute verenigingen.run_fee_query_tests.run
"""

import unittest
import sys


def run():
    """Run the fee query consolidation tests and print results."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName(
        "verenigingen.tests.backend.unit.utils.test_fee_query_consolidation.TestFeeQueryConsolidation"
    )

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    # Summary
    print("\n" + "=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    if result.failures:
        print("\nFAILED tests:")
        for test, traceback in result.failures:
            print(f"  - {test}")

    if result.errors:
        print("\nERROR tests:")
        for test, traceback in result.errors:
            print(f"  - {test}")

    if not result.failures and not result.errors:
        print("\nAll tests PASSED!")

    return {
        "total": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
    }
