"""
Simple webhook test without Payment Entry complexities
"""
import json
from unittest.mock import MagicMock, patch

import frappe


@frappe.whitelist()
def test_webhook_member_lookup():
    """Test if webhook can find Emma by subscription ID"""
    try:
        # Find Emma first
        members = frappe.get_all(
            "Member",
            filters={"first_name": "Emma", "last_name": "van Subscription"},
            fields=["name", "customer"],
        )
        if not members:
            return {"error": "Emma van Subscription not found"}

        emma = members[0]

        # Get subscription ID from Customer record (correct location)
        customer = frappe.get_doc("Customer", emma["customer"])
        subscription_id = customer.custom_mollie_subscription_id

        print(f"✅ Found Emma: {emma['name']}")
        print(f"   Customer: {emma['customer']}")
        print(f"   Subscription: {subscription_id}")

        # Test webhook payload without payment
        webhook_payload = {
            "id": subscription_id
            # No payment field - just subscription update
        }

        # Mock the webhook request
        mock_request = MagicMock()
        mock_request.get_data.return_value = json.dumps(webhook_payload)

        # Import and call the webhook
        from verenigingen.verenigingen_payments.utils.payment_gateways import mollie_subscription_webhook

        with patch("frappe.request", mock_request):
            result = mollie_subscription_webhook()

        print(f"✅ Webhook result: {result}")
        return {"success": True, "emma_found": True, "webhook_result": result}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_payment_entry_issue():
    """Investigate the Payment Entry creation issue"""
    try:
        # Check what Payment Entry DocType exists
        doctypes = frappe.get_all(
            "DocType", filters={"name": ["like", "%Payment%"]}, fields=["name", "module"]
        )

        print("💳 Payment-related DocTypes:")
        for dt in doctypes:
            print(f"   {dt['name']} ({dt['module']})")

        # Check if we can create a simple Payment Entry
        print("\n🔄 Testing Payment Entry creation...")
        payment_entry = frappe.new_doc("Payment Entry")
        print(f"   Created: {type(payment_entry)} - {payment_entry.doctype}")

        # Check attributes
        has_party_account = hasattr(payment_entry, "party_account")
        print(f"   Has party_account: {has_party_account}")

        if not has_party_account:
            attrs = [attr for attr in dir(payment_entry) if not attr.startswith("_")]
            print(f"   Available attributes: {', '.join(attrs[:10])}...")

        return {
            "success": True,
            "payment_doctypes": [dt["name"] for dt in doctypes],
            "payment_entry_type": str(type(payment_entry)),
            "has_party_account": has_party_account,
        }

    except Exception as e:
        print(f"❌ Error investigating Payment Entry: {str(e)}")
        return {"success": False, "error": str(e)}
