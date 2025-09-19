"""
Test Payment Entry creation specifically
"""

import frappe


def test_payment_entry_creation():
    """
    Test creating Payment Entry for the failed donation
    """
    try:
        print("=== TESTING PAYMENT ENTRY CREATION ===")

        payment_id = "tr_ubPbvN2sJEEzqabCPA7EJ"
        donation_name = "Assoc-Dnt-2025-00752"

        # Set webhook user context
        frappe.set_user("webhook.user@veganisme.org")

        # Get donation
        donation = frappe.get_doc("Donation", donation_name)
        print(f"Donation: {donation.name}")
        print(f"Donor: {donation.donor}")
        print(f"Amount: {donation.amount}")

        # Check if donor exists
        donor_exists = frappe.db.exists("Donor", donation.donor)
        print(f"Donor exists: {donor_exists}")

        if donor_exists:
            donor = frappe.get_doc("Donor", donation.donor)
            print(f"Donor name: {donor.donor_name}")
            print(f"Donor type: {getattr(donor, 'donor_type', 'None')}")

        # Check existing Payment Entries
        existing_pes = frappe.get_all(
            "Payment Entry", filters={"reference_no": payment_id}, fields=["name", "docstatus"]
        )
        print(f"Existing Payment Entries: {len(existing_pes)}")
        for pe in existing_pes:
            print(f"  {pe.name} (status: {pe.docstatus})")

        if existing_pes:
            print("Payment Entry already exists - no need to create")
            return True

        # Try creating Payment Entry manually
        print("\n--- Attempting Payment Entry creation ---")

        # Mock mollie data
        mollie_data = {
            "payment_id": payment_id,
            "status": "paid",
            "amount": "50.00",
            "currency": "EUR",
            "method": "ideal",
        }

        # Import the function
        from verenigingen.api.mollie_payment_webhook import create_payment_entry_for_donation

        payment_entry = create_payment_entry_for_donation(donation, mollie_data)

        if payment_entry:
            print(f"✅ Payment Entry created: {payment_entry.name}")
            return True
        else:
            print("❌ Payment Entry creation returned None")
            return False

    except Exception as e:
        print(f"❌ Payment Entry creation failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_payment_entry_creation()
