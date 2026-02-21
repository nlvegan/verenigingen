"""
Complete payment test: simulate payment completion and reconciliation
"""

import json
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, development_only_api


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def simulate_payment_completion():
    """Simulate the complete payment flow: mark payment as paid and process webhook"""
    try:
        # Get Emma's details
        members = frappe.get_all(
            "Member",
            filters={"first_name": "Emma", "last_name": "van Subscription"},
            fields=["name", "customer"],
        )
        if not members:
            return {"error": "Emma van Subscription not found"}

        customer = frappe.get_doc("Customer", members[0]["customer"])
        subscription_id = customer.custom_mollie_subscription_id
        real_payment_id = "tr_7AGtd7xRcVUhJ3DntVXDJ"

        print(f"🔄 Simulating complete payment flow...")
        print(f"   Member: {members[0]['name']}")
        print(f"   Payment: {real_payment_id}")
        print(f"   Subscription: {subscription_id}")

        # Check existing invoices before processing
        unpaid_invoices_before = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": customer.name,
                "docstatus": 1,
                "status": ["in", ["Unpaid", "Overdue", "Partly Paid"]],
            },
            fields=["name", "grand_total", "status"],
        )

        print(f"\n📋 Invoices before payment:")
        for inv in unpaid_invoices_before:
            print(f"   {inv['name']}: €{inv['grand_total']} ({inv['status']})")

        # Create a mock payment that returns "paid" status
        class MockPaidPayment:
            def __init__(self):
                self.id = real_payment_id
                self.status = "paid"  # This is the key change
                self.amount = {"value": "25.00", "currency": "EUR"}
                self.created_at = "2025-08-30T18:35:19+00:00"

            def is_paid(self):
                return True  # This will allow Payment Entry creation

        # Create webhook payload
        webhook_payload = {"id": subscription_id, "payment": {"id": real_payment_id}}

        # Mock the webhook request
        mock_request = MagicMock()
        mock_request.get_data.return_value = json.dumps(webhook_payload)

        # Import and call the webhook with our "paid" payment mock
        from verenigingen.verenigingen_payments.utils.payment_gateways import mollie_subscription_webhook

        # Mock at the module level to ensure it affects all gateway instances
        with patch("frappe.request", mock_request):
            with patch(
                "verenigingen.verenigingen_payments.utils.payment_gateways.PaymentGatewayFactory.get_gateway"
            ) as mock_gateway_factory:
                # Create a mock gateway with our MockPaidPayment
                mock_gateway = MagicMock()
                mock_gateway.client.payments.get.return_value = MockPaidPayment()
                mock_gateway.get_subscription_status.return_value = {
                    "status": "success",
                    "subscription": {"status": "active", "next_payment_date": "2025-09-30"},
                }
                mock_gateway_factory.return_value = mock_gateway

                result = mollie_subscription_webhook()

        print(f"\n✅ Webhook processed with 'paid' payment!")
        print(f"   Status: {result.get('status')}")
        print(f"   Actions: {result.get('actions', [])}")

        if result.get("payment_processed"):
            payment_result = result["payment_processed"]
            print(f"   💳 Payment Entry: {payment_result.get('payment_entry')}")
            print(f"   📄 Invoice Paid: {payment_result.get('invoice')}")
            print(f"   💰 Amount: €{payment_result.get('amount')}")

        # Check invoices after processing
        unpaid_invoices_after = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": customer.name,
                "docstatus": 1,
                "status": ["in", ["Unpaid", "Overdue", "Partly Paid"]],
            },
            fields=["name", "grand_total", "status"],
        )

        print(f"\n📋 Invoices after payment:")
        if unpaid_invoices_after:
            for inv in unpaid_invoices_after:
                print(f"   {inv['name']}: €{inv['grand_total']} ({inv['status']})")
        else:
            print("   ✅ No unpaid invoices remaining!")

        # Check created Payment Entries
        payment_entries = frappe.get_all(
            "Payment Entry",
            filters={"party": customer.name, "reference_no": real_payment_id},
            fields=["name", "paid_amount", "posting_date", "docstatus"],
            order_by="creation desc",
        )

        print(f"\n💳 Created Payment Entries:")
        for pe in payment_entries:
            print(
                f"   {pe['name']}: €{pe['paid_amount']} (Status: {'Submitted' if pe['docstatus'] == 1 else 'Draft'})"
            )

        return {
            "success": True,
            "webhook_result": result,
            "unpaid_before": len(unpaid_invoices_before),
            "unpaid_after": len(unpaid_invoices_after),
            "payment_entries_created": len(payment_entries),
        }

    except Exception as e:
        print(f"❌ Complete payment test error: {str(e)}")
        frappe.log_error(f"Complete payment test error: {str(e)}", "Payment Completion Test")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def check_reconciliation_status():
    """Check the reconciliation status after payment processing"""
    try:
        # Get Emma's details
        members = frappe.get_all(
            "Member",
            filters={"first_name": "Emma", "last_name": "van Subscription"},
            fields=["name", "customer"],
        )
        if not members:
            return {"error": "Emma van Subscription not found"}

        customer_name = members[0]["customer"]
        payment_id = "tr_7AGtd7xRcVUhJ3DntVXDJ"

        print(f"🔍 Checking reconciliation status...")
        print(f"   Customer: {customer_name}")
        print(f"   Payment: {payment_id}")

        # Check Payment Entry References (reconciliation)
        payment_refs = frappe.get_all(
            "Payment Entry Reference",
            filters={"reference_doctype": "Sales Invoice"},
            fields=["parent", "reference_name", "allocated_amount", "outstanding_amount"],
        )

        # Filter for our customer's references
        mollie_payment_refs = []
        for ref in payment_refs:
            pe = frappe.get_doc("Payment Entry", ref["parent"])
            if pe.party == customer_name and pe.reference_no == payment_id:
                mollie_payment_refs.append(
                    {
                        "payment_entry": ref["parent"],
                        "invoice": ref["reference_name"],
                        "allocated": ref["allocated_amount"],
                        "outstanding": ref["outstanding_amount"],
                    }
                )

        print(f"\n🔗 Payment Entry References:")
        for ref in mollie_payment_refs:
            print(f"   {ref['payment_entry']} → {ref['invoice']}")
            print(f"      Allocated: €{ref['allocated']}")
            print(f"      Outstanding: €{ref['outstanding']}")

        return {
            "success": True,
            "customer": customer_name,
            "reconciliation_count": len(mollie_payment_refs),
            "reconciliations": mollie_payment_refs,
        }

    except Exception as e:
        print(f"❌ Reconciliation check error: {str(e)}")
        return {"error": str(e)}
