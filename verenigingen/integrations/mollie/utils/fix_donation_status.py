"""
Fix donation status issues
"""

import frappe


def fix_donation_status(donation_name="Assoc-Dnt-2025-00750"):
    """
    Fix the donation status and check recurring detection
    """
    try:
        print(f"=== FIXING DONATION STATUS FOR {donation_name} ===")

        donation = frappe.get_doc("Donation", donation_name)

        print(f"Current status: {donation.status}")
        print(f"Has subscription ID: {getattr(donation, 'mollie_subscription_id', 'None')}")
        print(f"Recurring frequency: {getattr(donation, 'recurring_frequency', 'None')}")

        # Set status to Recurring since it has a subscription
        if getattr(donation, "mollie_subscription_id", None):
            donation.status = "Recurring"
            donation.save()
            print("✅ Updated status to Recurring")
        else:
            print("❌ No subscription ID found")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    fix_donation_status()
