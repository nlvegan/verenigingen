"""Debug campaign donation integration"""

import frappe
from frappe.utils import flt, today


def debug_campaign_integration():
    """Debug campaign donation linking"""
    print("=== DEBUGGING CAMPAIGN INTEGRATION ===")

    # Create a test campaign
    campaign = frappe.new_doc("Donation Campaign")
    campaign.update(
        {
            "campaign_name": "Debug Campaign Test",
            "campaign_type": "Annual Giving",
            "description": "Debug test campaign",
            "status": "Active",
            "start_date": today(),
            "monetary_goal": 1000.00,
            "donor_goal": 10,
            "is_public": 1,
            "total_raised": 0.0,
            "total_donors": 0,
            "total_donations": 0,
            "monetary_progress": 0.0,
            "donor_progress": 0.0,
            "average_donation_amount": 0.0,
        }
    )
    campaign.insert()
    print(f"✓ Campaign created: {campaign.name}")

    # Create a test donor
    donor = frappe.new_doc("Donor")
    donor.update(
        {
            "donor_name": "Debug Test Donor",
            "donor_email": "debug@test.com",
            "donor_type": "Individual",
            "contact_person": "Debug Test Donor",
            "donor_category": "Regular Donor",
        }
    )
    donor.insert()
    print(f"✓ Donor created: {donor.name}")

    # Create a donation linked to the campaign
    donation = frappe.new_doc("Donation")
    donation.update(
        {
            "company": frappe.get_list("Company", limit=1)[0].name,
            "donor": donor.name,
            "campaign": campaign.name,  # Link to campaign
            "donation_date": today(),
            "amount": 200.00,
            "donation_type": "General",
            "mode_of_payment": "Bank Transfer",
            "status": "One-time",
            "donation_purpose_type": "Campaign",
            "paid": 1,  # Mark as paid
        }
    )
    donation.insert()
    # Mark as submitted without triggering on_submit hooks (avoids fiscal year issues)
    frappe.db.set_value("Donation", donation.name, "docstatus", 1)
    donation.reload()  # Reload to get updated status
    print(f"✓ Donation created: {donation.name}")
    print(f"  - Campaign: {donation.campaign}")
    print(f"  - Amount: {donation.amount}")
    print(f"  - Paid: {donation.paid}")
    print(f"  - DocStatus: {donation.docstatus}")

    # Check campaign totals before update
    print(f"\nBEFORE UPDATE:")
    print(f"  - Campaign total_raised: {campaign.total_raised}")
    print(f"  - Campaign total_donations: {campaign.total_donations}")

    # Update campaign progress
    campaign.reload()
    campaign.update_progress()
    campaign.save()

    print(f"\nAFTER UPDATE:")
    print(f"  - Campaign total_raised: {campaign.total_raised}")
    print(f"  - Campaign total_donations: {campaign.total_donations}")
    print(f"  - Campaign total_donors: {campaign.total_donors}")

    # Check what donations are found by the query
    donations_found = frappe.get_all(
        "Donation",
        filters={"campaign": campaign.name, "paid": 1, "docstatus": 1},
        fields=["name", "amount", "donor", "campaign", "paid", "docstatus"],
    )

    print(f"\nDONATIONS QUERY RESULT:")
    print(f"  - Found {len(donations_found)} donations")
    for d in donations_found:
        print(f"    * {d.name}: €{d.amount} (paid={d.paid}, status={d.docstatus})")

    # Cleanup
    frappe.delete_doc("Donation", donation.name, force=True)
    frappe.delete_doc("Donor", donor.name, force=True)
    frappe.delete_doc("Donation Campaign", campaign.name, force=True)

    print("\n✓ Cleanup completed")
    return True
