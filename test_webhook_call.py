"""
Test actual webhook call to see what's failing
"""

import frappe


def test_webhook_call():
    """
    Simulate the actual webhook call that Mollie makes
    """
    try:
        print("=== TESTING ACTUAL WEBHOOK CALL ===")

        # Import the webhook handler
        from verenigingen.api.mollie_payment_webhook import handle_mollie_payment_webhook

        payment_id = "tr_fNhhAiAV4CsAmRFPcB7EJ"

        # Set up form_dict like Mollie webhook would
        original_form_dict = getattr(frappe, "form_dict", {})
        frappe.form_dict = {"id": payment_id, "status": "paid"}

        print(f"Webhook payload: {frappe.form_dict}")

        try:
            # Call the webhook handler exactly like Mollie does
            result = handle_mollie_payment_webhook()
            print(f"Webhook result: {result}")

            if result.get("status") == "success":
                print("✅ Webhook call succeeded")
            elif result.get("status") == "already_processed":
                print("✅ Webhook call - already processed")
            else:
                print(f"❌ Webhook call failed: {result}")

        finally:
            # Restore original form_dict
            frappe.form_dict = original_form_dict

        return result

    except Exception as e:
        print(f"❌ Webhook test error: {e}")
        import traceback

        traceback.print_exc()
        return None


if __name__ == "__main__":
    test_webhook_call()
