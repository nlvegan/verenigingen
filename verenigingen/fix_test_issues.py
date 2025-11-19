"""Fix test issues with donation system"""

import frappe


def analyze_test_failures():
    """Analyze and fix test failure issues"""
    print("Analyzing test failures...")

    # Check what donation types are being used in tests
    print("\n1. Checking donation types used in form submission...")

    # Test the form submission with various parameters
    test_cases = [
        {
            "name": "Test with One-time status",
            "data": {
                "donor_name": "Test Campaign Donor",
                "donor_email": "campaign@example.com",
                "amount": "150.0",
                "donation_type": "General",  # Use existing type
                "donation_status": "One-time",
                "payment_method": "Bank Transfer",
                "donation_purpose_type": "Campaign",
                "campaign_reference": "Test Campaign 123456",
                "donation_notes": "Test campaign donation",
            },
        }
    ]

    from verenigingen.templates.pages.donate import submit_donation

    for test_case in test_cases:
        print(f"\n  Testing: {test_case['name']}")

        try:
            result = submit_donation(**test_case["data"])

            if result.get("success"):
                print(f"    ✓ Success: {result.get('donation_id')}")

                # Check the actual donation
                donation_id = result.get("donation_id")
                donation = frappe.get_doc("Donation", donation_id)
                print(f"    - Campaign field: {getattr(donation, 'campaign', 'NOT SET')}")
                print(f"    - Notes: {getattr(donation, 'donation_notes', 'NOT SET')[:50]}...")
                print(f"    - Purpose type: {getattr(donation, 'donation_purpose_type', 'NOT SET')}")

            else:
                print(f"    ✗ Failed: {result.get('message')}")
                print(f"    - Debug: {result.get('debug_error', 'No debug info')}")

        except Exception as e:
            print(f"    ✗ Exception: {str(e)}")

    # Check campaign integration
    print("\n2. Checking campaign integration...")

    # Create a test campaign
    try:
        test_campaign = frappe.new_doc("Donation Campaign")
        test_campaign.update(
            {
                "campaign_name": "Debug Test Campaign",
                "campaign_type": "Annual Giving",
                "description": "Test campaign for debugging",
                "status": "Active",
                "start_date": frappe.utils.today(),
                "monetary_goal": 1000.00,
                "donor_goal": 10,
                "is_public": 1,
                # Initialize progress tracking fields
                "total_raised": 0.0,
                "total_donors": 0,
                "total_donations": 0,
                "monetary_progress": 0.0,
                "donor_progress": 0.0,
                "average_donation_amount": 0.0,
            }
        )
        test_campaign.save()
        print(f"    ✓ Test campaign created: {test_campaign.name}")

        # Test a donation to this campaign
        campaign_donation_data = {
            "donor_name": "Campaign Test Donor",
            "donor_email": "campaigntest@example.com",
            "amount": "200.0",
            "donation_type": "General",
            "donation_status": "One-time",
            "payment_method": "Bank Transfer",
            "donation_purpose_type": "Campaign",
            "campaign_reference": test_campaign.name,  # Use actual campaign
            "donation_notes": "Test donation to real campaign",
        }

        result = submit_donation(**campaign_donation_data)

        if result.get("success"):
            print(f"    ✓ Campaign donation success: {result.get('donation_id')}")

            # Check if campaign was properly linked
            donation = frappe.get_doc("Donation", result.get("donation_id"))
            print(f"    - Campaign linked: {getattr(donation, 'campaign', 'NOT SET')}")

            # Mark as paid and check campaign updates
            donation.paid = 1
            donation.save()

            # Update campaign progress
            test_campaign.reload()
            if hasattr(test_campaign, "update_progress"):
                test_campaign.update_progress()
                print(f"    - Campaign total after update: {test_campaign.total_raised}")
            else:
                print("    - No update_progress method found on campaign")

        else:
            print(f"    ✗ Campaign donation failed: {result.get('message')}")

    except Exception as e:
        print(f"    ✗ Campaign test exception: {str(e)}")
        import traceback

        traceback.print_exc()

    return True
