"""
Test webhook directly to find the issue
"""

import frappe


def test_webhook_processing():
    """
    Test webhook processing directly
    """
    try:
        print("=== TESTING WEBHOOK PROCESSING ===")

        payment_id = "tr_ubPbvN2sJEEzqabCPA7EJ"

        # Check if webhook user exists
        webhook_user = "webhook.user@veganisme.org"
        user_exists = frappe.db.exists("User", webhook_user)
        print(f"Webhook user exists: {user_exists}")

        if user_exists:
            user_enabled = frappe.db.get_value("User", webhook_user, "enabled")
            print(f"Webhook user enabled: {user_enabled}")

        # Set user context like webhook does
        frappe.set_user(webhook_user)
        print(f"Set user context to: {frappe.session.user}")

        # Import webhook functions
        from verenigingen.api.mollie_payment_webhook import (
            find_donation_for_payment_by_id,
            find_donation_for_subscription_payment,
        )

        # Try to find donation
        donation = find_donation_for_payment_by_id(payment_id)
        print(f"Found donation by payment_id: {donation.name if donation else 'None'}")

        if donation:
            print(f"Donation status: {donation.status}")
            print(f"Donation paid: {donation.paid}")

        # Try webhook handler
        from verenigingen.api.mollie_payment_webhook import handle_mollie_payment_webhook

        # Set form_dict
        original_form_dict = getattr(frappe, "form_dict", {})
        frappe.form_dict = {"id": payment_id, "status": "paid"}

        try:
            result = handle_mollie_payment_webhook()
            print(f"Webhook handler result: {result}")
        finally:
            frappe.form_dict = original_form_dict

        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_webhook_processing()
