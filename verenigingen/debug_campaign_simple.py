"""Simple debug for campaign integration"""

import frappe
from frappe.utils import flt, today


def debug_single_test():
    """Debug the specific test case that's failing"""
    print("=== DEBUGGING SINGLE TEST CASE ===")

    # Create test donor (replicating test setup)
    from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory

    factory = EnhancedTestDataFactory(seed=12345, use_faker=True)

    # Create donor
    donor = factory.create_test_donor(donor_name="Test Donor", donor_email="test@example.com")
    print(f"✓ Donor created: {donor.name}")

    # Create campaign (replicating test setup)
    campaign = frappe.new_doc("Donation Campaign")
    campaign.update(
        {
            "campaign_name": f"Test Campaign {frappe.generate_hash(length=6)}",
            "campaign_type": "Annual Giving",
            "description": "Test campaign for donation integration",
            "status": "Active",
            "start_date": today(),
            "monetary_goal": 1000.00,
            "donor_goal": 10,
            "is_public": 1,
            # Initialize progress tracking fields to prevent NoneType errors
            "total_raised": 0.0,
            "total_donors": 0,
            "total_donations": 0,
            "monetary_progress": 0.0,
            "donor_progress": 0.0,
            "average_donation_amount": 0.0,
        }
    )
    campaign.save()
    print(f"✓ Campaign created: {campaign.name}")
    print(f"  Initial total_raised: {campaign.total_raised}")

    # Record initial state
    initial_raised = campaign.total_raised
    initial_donors = campaign.total_donors
    print(f"✓ Initial state recorded: raised={initial_raised}, donors={initial_donors}")

    # Create donation using Enhanced Test Factory (matching the test)
    donation = factory.create_test_donation(
        donor=donor.name, amount=150.00, donation_type="General", campaign=campaign.name, paid=1
    )
    print(f"✓ Donation created: {donation.name}")
    print(f"  - Campaign: {donation.campaign}")
    print(f"  - Amount: {donation.amount}")
    print(f"  - Paid: {donation.paid}")
    print(f"  - DocStatus: {donation.docstatus}")

    # Update campaign progress (matching the test)
    campaign.reload()
    print(f"✓ Campaign reloaded")

    campaign.update_progress()
    print(f"✓ Campaign progress updated")

    # Check campaign totals (matching the test expectation)
    print(f"\nFINAL RESULTS:")
    print(f"  - Campaign total_raised: {campaign.total_raised} (type: {type(campaign.total_raised)})")
    print(f"  - Campaign total_donors: {campaign.total_donors}")
    print(f"  - Initial raised: {initial_raised} (type: {type(initial_raised)})")

    # This is the failing assertion from the test
    try:
        result = flt(campaign.total_raised - initial_raised)
        expected = 150.00
        print(f"  - Calculation result: {result} (expected: {expected})")
        print(f"  - Test assertion: {result} == {expected} -> {result == expected}")

        if result == expected:
            print("✅ TEST WOULD PASS")
        else:
            print("❌ TEST WOULD FAIL")

    except Exception as e:
        print(f"❌ Calculation error: {e}")

    # Cleanup
    try:
        frappe.delete_doc("Donation", donation.name, force=True)
        frappe.delete_doc("Donor", donor.name, force=True)
        frappe.delete_doc("Donation Campaign", campaign.name, force=True)
        print("✓ Cleanup completed")
    except:
        print("⚠ Cleanup had issues (expected for submitted docs)")

    return True
