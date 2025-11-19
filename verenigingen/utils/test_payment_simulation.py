"""
Test payment simulation with webhook processing
"""

import json
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, development_only_api


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_webhook_with_payment():
    """Test full webhook with payment processing"""
    try:
        # Find Emma and her subscription
        members = frappe.get_all(
            "Member",
            filters={"first_name": "Emma", "last_name": "van Subscription"},
            fields=["name", "customer"],
        )
        if not members:
            return {"error": "Emma van Subscription not found"}

        emma = members[0]
        customer = frappe.get_doc("Customer", emma["customer"])
        subscription_id = customer.custom_mollie_subscription_id

        # Create webhook payload with payment
        payment_id = f"tr_test_{frappe.utils.random_string(10)}"
        webhook_payload = {"id": subscription_id, "payment": {"id": payment_id}}

        print(f"🔄 Testing webhook with payment...")
        print(f"   Member: {emma['name']}")
        print(f"   Customer: {emma['customer']}")
        print(f"   Subscription: {subscription_id}")
        print(f"   Payment ID: {payment_id}")

        # Mock the webhook request
        mock_request = MagicMock()
        mock_request.get_data.return_value = json.dumps(webhook_payload)

        # Create mock payment for the webhook processing
        class MockPayment:
            def __init__(self):
                self.id = payment_id
                self.status = "paid"
                self.amount = {"value": "25.00", "currency": "EUR"}

            def is_paid(self):
                return True

        # Import and call the webhook
        from verenigingen.verenigingen_payments.utils.payment_gateways import (
            PaymentGatewayFactory,
            mollie_subscription_webhook,
        )

        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")

        with patch("frappe.request", mock_request):
            with patch.object(gateway.client.payments, "get", return_value=MockPayment()):
                result = mollie_subscription_webhook()

        print(f"✅ Webhook processed!")
        print(f"   Status: {result.get('status')}")
        print(f"   Member: {result.get('member')}")
        print(f"   Actions: {result.get('actions', [])}")

        if result.get("payment_processed"):
            payment_result = result["payment_processed"]
            print(f"   Payment Result: {payment_result}")

        if result.get("payment_error"):
            print(f"   Payment Error: {result['payment_error']}")

        return {"success": True, "webhook_result": result}

    except Exception as e:
        print(f"❌ Webhook test error: {str(e)}")
        frappe.log_error(f"Payment webhook test error: {str(e)}", "Payment Simulation")
        return {"success": False, "error": str(e)}
