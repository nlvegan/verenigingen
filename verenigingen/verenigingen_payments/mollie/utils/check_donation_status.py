"""
Check donation status and webhook processing
"""

import frappe


def check_donation_status(donation_name="Assoc-Dnt-2025-00750"):
    """
    Check the status of a donation record and related webhook processing
    """
    try:
        print(f"=== CHECKING DONATION {donation_name} ===")

        # Check if donation exists
        try:
            donation = frappe.get_doc("Donation", donation_name)
            print(f"✅ Donation found: {donation.name}")
            print(f"  Paid: {donation.paid}")
            print(f"  Payment ID: {getattr(donation, 'payment_id', 'None')}")
            print(f"  Payment Status: {getattr(donation, 'payment_status', 'None')}")
            print(f"  Mollie Subscription ID: {getattr(donation, 'mollie_subscription_id', 'None')}")
            print(f"  Amount: {donation.amount}")
            print(f"  Donor: {donation.donor}")

        except frappe.DoesNotExistError:
            print(f"❌ Donation {donation_name} does not exist")
            return

        # Check for any error logs related to this donation
        print("\n=== CHECKING ERROR LOGS ===")
        error_logs = frappe.get_all(
            "Error Log",
            filters={"creation": [">=", "2025-09-12 08:00:00"], "error": ["like", f"%{donation_name}%"]},
            fields=["name", "error", "creation"],
            order_by="creation desc",
            limit=5,
        )

        if error_logs:
            print(f"Found {len(error_logs)} error logs:")
            for log in error_logs:
                print(f"  {log.creation}: {log.name}")
                print(f"    Error: {log.error[:200]}...")
        else:
            print("No specific error logs found for this donation")

        # Check for webhook processing logs if they exist
        print("\n=== CHECKING WEBHOOK LOGS ===")
        try:
            webhook_logs = frappe.get_all(
                "Webhook Processing Log",
                filters={"processed_at": [">=", "2025-09-12 08:00:00"]},
                fields=["name", "webhook_id", "status", "processed_at", "error_details"],
                order_by="processed_at desc",
                limit=10,
            )

            if webhook_logs:
                print(f"Found {len(webhook_logs)} recent webhook logs:")
                for log in webhook_logs:
                    print(f"  {log.processed_at}: {log.webhook_id} - {log.status}")
                    if log.error_details:
                        print(f"    Error: {log.error_details[:100]}...")
            else:
                print("No webhook processing logs found")

        except frappe.DoesNotExistError:
            print("Webhook Processing Log doctype not found - using alternative approach")

        # Check general error logs from the webhook timeframe
        print("\n=== CHECKING GENERAL ERROR LOGS FROM WEBHOOK TIME ===")
        recent_errors = frappe.get_all(
            "Error Log",
            filters={"creation": ["between", ["2025-09-12 08:03:30", "2025-09-12 08:04:00"]]},
            fields=["name", "method", "error", "creation"],
            order_by="creation desc",
        )

        if recent_errors:
            print(f"Found {len(recent_errors)} errors around webhook time:")
            for error in recent_errors:
                print(f"  {error.creation}: {error.method}")
                print(f"    Error: {error.error[:150]}...")
        else:
            print("No errors found around webhook processing time")

        return donation

    except Exception as e:
        print(f"❌ Error checking donation: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    check_donation_status()
