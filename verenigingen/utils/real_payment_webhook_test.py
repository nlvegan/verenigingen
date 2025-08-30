"""
Test webhook with real Mollie payment data
"""
import json
from unittest.mock import MagicMock, patch

import frappe


@frappe.whitelist()
def test_webhook_with_real_payment():
    """Test webhook using the real pending payment from Mollie"""
    try:
        # Get Emma's subscription details
        members = frappe.get_all(
            "Member",
            filters={"first_name": "Emma", "last_name": "van Subscription"},
            fields=["name", "customer"],
        )
        if not members:
            return {"error": "Emma van Subscription not found"}

        customer = frappe.get_doc("Customer", members[0]["customer"])
        subscription_id = customer.custom_mollie_subscription_id

        # Use the real payment ID we found
        real_payment_id = "tr_7AGtd7xRcVUhJ3DntVXDJ"

        print(f"🔄 Testing webhook with real payment...")
        print(f"   Member: {members[0]['name']}")
        print(f"   Customer: {customer.name}")
        print(f"   Subscription: {subscription_id}")
        print(f"   Real Payment ID: {real_payment_id}")

        # Create webhook payload with the real payment
        webhook_payload = {"id": subscription_id, "payment": {"id": real_payment_id}}

        # Mock the webhook request
        mock_request = MagicMock()
        mock_request.get_data.return_value = json.dumps(webhook_payload)

        # Import and call the webhook (no mocking needed - use real Mollie data)
        from verenigingen.verenigingen_payments.utils.payment_gateways import mollie_subscription_webhook

        with patch("frappe.request", mock_request):
            result = mollie_subscription_webhook()

        print(f"✅ Webhook processed with real payment!")
        print(f"   Status: {result.get('status')}")
        print(f"   Member: {result.get('member')}")
        print(f"   Actions: {result.get('actions', [])}")

        if result.get("payment_processed"):
            payment_result = result["payment_processed"]
            print(f"   Payment Entry: {payment_result.get('payment_entry')}")
            print(f"   Invoice Paid: {payment_result.get('invoice')}")
            print(f"   Amount: €{payment_result.get('amount')}")

        if result.get("payment_error"):
            print(f"   ⚠️ Payment Error: {result['payment_error']}")

        return {"success": True, "real_payment_used": real_payment_id, "webhook_result": result}

    except Exception as e:
        print(f"❌ Real payment webhook test error: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_payment_status(payment_id="tr_7AGtd7xRcVUhJ3DntVXDJ"):
    """Check the status of our real test payment"""
    try:
        from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        payment = gateway.client.payments.get(payment_id)

        print(f"💳 Payment Status: {payment.id}")
        print(f"   Status: {payment.status}")
        print(f"   Amount: {payment.amount['currency']} {payment.amount['value']}")
        print(f"   Created: {payment.created_at}")
        print(f"   Is Paid: {payment.is_paid()}")

        if hasattr(payment, "settlement_amount") and payment.settlement_amount:
            print(
                f"   Settlement: {payment.settlement_amount['currency']} {payment.settlement_amount['value']}"
            )

        if hasattr(payment, "method"):
            print(f"   Method: {payment.method}")

        return {
            "payment_id": payment.id,
            "status": payment.status,
            "is_paid": payment.is_paid(),
            "amount": payment.amount["value"],
            "currency": payment.amount["currency"],
        }

    except Exception as e:
        print(f"❌ Error checking payment: {str(e)}")
        return {"error": str(e)}
