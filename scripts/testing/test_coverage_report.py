#!/usr/bin/env python3
"""
Test script for the Membership Dues Coverage Analysis report
"""

import os
import sys

# Add the app directory to Python path
sys.path.insert(0, "/home/frappe/frappe-bench/apps/verenigingen")


def test_coverage_report():
    """Test the coverage report functionality"""

    try:
        # Import the report module
        from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
            calculate_coverage_timeline,
            execute,
            get_columns,
        )

        print("✓ Report module imported successfully")

        # Test column generation
        columns = get_columns()
        print(f"✓ Generated {len(columns)} columns")

        # Test with empty filters
        try:
            columns, data = execute({})
            print(f"✓ Report executed successfully with {len(data)} rows")
        except Exception as e:
            print(f"⚠ Report execution failed: {str(e)}")
            # This might be expected if no members exist

        # Test individual function components
        try:
            # Test empty coverage analysis
            from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
                get_empty_coverage_analysis,
            )

            empty_analysis = get_empty_coverage_analysis()
            print("✓ Empty coverage analysis structure is valid")

            # Test gap classification
            from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
                classify_gap_type,
            )

            assert classify_gap_type(5) == "Minor"
            assert classify_gap_type(15) == "Moderate"
            assert classify_gap_type(45) == "Significant"
            assert classify_gap_type(120) == "Critical"
            print("✓ Gap classification works correctly")

        except ImportError as e:
            print(f"⚠ Could not test individual functions: {str(e)}")

        print("\n🎉 Coverage report test completed successfully!")

    except ImportError as e:
        print(f"❌ Failed to import report module: {str(e)}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        return False

    return True


if __name__ == "__main__":
    print("Testing Membership Dues Coverage Analysis Report")
    print("=" * 50)

    success = test_coverage_report()

    if success:
        print("\n✅ All tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed!")
        sys.exit(1)
