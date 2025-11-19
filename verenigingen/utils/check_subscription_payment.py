"""
Check for donations related to subscription payments
"""

import frappe


def find_donation_for_payment(payment_id="tr_pCb7iw7mYSDAe9xHU47EJ"):
    """
    Find donation record for the given payment ID
    """
    try:
        print(f"=== SEARCHING FOR DONATION WITH PAYMENT ID {payment_id} ===")

        # Search for donation by payment_id
        donations = frappe.get_all(
            "Donation",
            filters={"payment_id": payment_id},
            fields=["name", "paid", "creation", "owner", "amount", "status"],
        )

        if donations:
            print(f"✅ Found {len(donations)} donation(s) with this payment ID:")
            for donation in donations:
                print(f"  - {donation.name}: paid={donation.paid}, status={donation.status}")
                print(f"    Created: {donation.creation} by {donation.owner}")
                print(f"    Amount: {donation.amount}")
        else:
            print("❌ No donations found with this payment ID")

        # Also search recent donations that might be related
        print("\n=== CHECKING RECENT DONATIONS ===")
        recent_donations = frappe.get_all(
            "Donation",
            filters={"creation": [">=", "2025-09-12 10:15:00"]},  # Around subscription creation time
            fields=["name", "payment_id", "paid", "creation", "owner", "amount", "status", "donor"],
            order_by="creation desc",
        )

        if recent_donations:
            print(f"Found {len(recent_donations)} recent donation(s):")
            for donation in recent_donations:
                print(f"  - {donation.name}: {donation.payment_id}")
                print(f"    Paid: {donation.paid}, Status: {donation.status}")
                print(f"    Donor: {donation.donor}, Amount: {donation.amount}")
                print(f"    Created: {donation.creation} by {donation.owner}")
                print()

        return donations

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    find_donation_for_payment()
