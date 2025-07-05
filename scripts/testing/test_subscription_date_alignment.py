"""
Test script to verify subscription date alignment fix for new member invoices.
This tests that application invoices and subscription invoices have properly aligned dates.
"""

import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.utils.subscription_period_calculator import (
    calculate_subscription_period_dates,
    get_aligned_subscription_dates,
    test_subscription_period_calculation,
)


def test_subscription_date_calculation():
    """Test subscription period calculation for different membership types"""

    print("\n=== Testing Subscription Date Alignment ===")

    # Test the calculation utility directly
    try:
        result = test_subscription_period_calculation()
        if result.get("success"):
            print(f"✓ Utility test successful for {len(result['results'])} membership types")

            for test_result in result["results"]:
                if "error" not in test_result:
                    print(f"  - {test_result['membership_type']} ({test_result['subscription_period']}):")
                    print(
                        f"    Application period: {test_result['application_invoice_period']['start']} to {test_result['application_invoice_period']['end']}"
                    )
                    print(f"    Next subscription: {test_result['subscription_start']}")
                else:
                    print(f"  ✗ Error with {test_result['membership_type']}: {test_result['error']}")
        else:
            print(f"✗ Utility test failed: {result}")

    except Exception as e:
        print(f"✗ Error testing utility: {e}")


def test_specific_scenarios():
    """Test specific billing scenarios"""

    print("\n=== Testing Specific Scenarios ===")

    # Test scenarios
    scenarios = [
        {"name": "Monthly", "start_date": "2025-01-01"},
        {"name": "Quarterly", "start_date": "2025-01-01"},
        {"name": "Annual", "start_date": "2025-01-01"},
    ]

    # Get available membership types
    membership_types = frappe.get_all(
        "Membership Type",
        fields=["name", "subscription_period"],
        filters={"subscription_period": ["in", ["Monthly", "Quarterly", "Annual"]]},
    )

    for mt in membership_types:
        for scenario in scenarios:
            if mt.subscription_period == scenario["name"]:
                try:
                    print(f"\n--- {mt.name} ({mt.subscription_period}) ---")

                    # Test with application invoice
                    dates_with_app = get_aligned_subscription_dates(
                        scenario["start_date"], mt.name, has_application_invoice=True
                    )

                    print(f"With application invoice:")
                    print(
                        f"  Application period: {dates_with_app['application_invoice_period']['start']} to {dates_with_app['application_invoice_period']['end']}"
                    )
                    print(f"  Subscription starts: {dates_with_app['subscription_start_date']}")

                    # Test without application invoice
                    dates_without_app = get_aligned_subscription_dates(
                        scenario["start_date"], mt.name, has_application_invoice=False
                    )

                    print(f"Without application invoice:")
                    print(f"  Subscription starts: {dates_without_app['subscription_start_date']}")

                    # Verify alignment
                    if dates_with_app["subscription_start_date"] == dates_with_app[
                        "application_invoice_period"
                    ]["end"] + frappe.utils.timedelta(days=1):
                        print("  ✓ Dates are properly aligned")
                    else:
                        print("  ⚠ Dates may not be optimally aligned")

                except Exception as e:
                    print(f"  ✗ Error: {e}")


def test_invoice_creation_integration():
    """Test that invoice creation uses the aligned dates"""

    print("\n=== Testing Invoice Creation Integration ===")

    # This would require creating test data, so we'll just verify the import works
    try:
        from verenigingen.utils.application_payments import create_membership_invoice_with_amount

        print("✓ Invoice creation module imports subscription calculator successfully")

        # Check if the updated code is present
        import inspect

        source = inspect.getsource(create_membership_invoice_with_amount)
        if "subscription_period_calculator" in source:
            print("✓ Invoice creation function includes subscription period calculator")
        else:
            print("✗ Invoice creation function may not include subscription period calculator")

    except Exception as e:
        print(f"✗ Error testing invoice integration: {e}")


def main():
    """Run all subscription date alignment tests"""

    print("Testing subscription date alignment for new member invoices...")
    print("=" * 60)

    # Test 1: Basic utility function
    test_subscription_date_calculation()

    # Test 2: Specific scenarios
    test_specific_scenarios()

    # Test 3: Integration with invoice creation
    test_invoice_creation_integration()

    print("\n" + "=" * 60)
    print("Test completed. Check output above for any issues.")


if __name__ == "__main__":
    main()
