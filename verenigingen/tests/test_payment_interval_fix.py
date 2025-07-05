"""
Test payment interval fix for contribution calculator
"""

import frappe


@frappe.whitelist()
def test_payment_interval_mapping():
    """Test that payment intervals correctly map to membership types"""

    # Get available membership types
    membership_types = frappe.get_all(
        "Membership Type",
        fields=["name", "membership_type_name", "description", "subscription_period", "amount"],
        filters={"is_active": 1},
    )

    print(f"Available membership types: {len(membership_types)}")
    for mt in membership_types:
        print(f"  - {mt['name']}: {mt['subscription_period']} (Amount: {mt['amount']})")

    # Test the mapping logic that would be used in JavaScript
    subscription_period_mapping = {"monthly": "Monthly", "quarterly": "Quarterly", "annually": "Annual"}

    test_results = {}

    for interval, target_period in subscription_period_mapping.items():
        # Find matching membership type
        matching_type = None
        for mt in membership_types:
            if mt["subscription_period"] and mt["subscription_period"].lower() == target_period.lower():
                matching_type = mt
                break

        test_results[interval] = {
            "target_period": target_period,
            "found_match": matching_type is not None,
            "matching_type": matching_type["name"] if matching_type else None,
            "subscription_period": matching_type["subscription_period"] if matching_type else None,
        }

        print(f"\n{interval.upper()} -> {target_period}:")
        if matching_type:
            print(f"  ✓ Found: {matching_type['name']} ({matching_type['subscription_period']})")
        else:
            print("  ✗ No match found")

    # Check for potential issues
    issues = []

    if not test_results["annually"]["found_match"]:
        issues.append("No Annual membership type found - 'annually' selection will fail")

    if not test_results["monthly"]["found_match"]:
        issues.append("No Monthly membership type found - 'monthly' selection will fail")

    if not test_results["quarterly"]["found_match"]:
        issues.append("No Quarterly membership type found - 'quarterly' selection will fail")

    return {
        "success": len(issues) == 0,
        "membership_types": membership_types,
        "test_results": test_results,
        "issues": issues,
        "message": "All payment intervals work correctly"
        if len(issues) == 0
        else f'Issues found: {"; ".join(issues)}',
    }


if __name__ == "__main__":
    result = test_payment_interval_mapping()
    print(f"\nTest Result: {result['message']}")
