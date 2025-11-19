"""
Webhook Testing Utilities for Mollie Subscription Integration
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, development_only_api
from verenigingen.verenigingen_payments.utils.payment_gateways import (
    PaymentGatewayFactory,
    _process_subscription_payment,
)


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def recreate_emma_with_mollie_ids():
    """Recreate Emma with the actual Mollie IDs from our successful subscription"""
    try:
        # Create Emma with the real Mollie IDs
        emma = frappe.new_doc("Member")
        emma.first_name = "Emma"
        emma.last_name = "van Subscription"
        emma.email = "emma.subscription@test.veganisme.nl"
        emma.birth_date = "1985-03-15"
        emma.iban = "NL91ABNA0417164300"
        emma.status = "Active"
        emma.gender = "Female"
        emma.nationality = "Dutch"

        # Set the actual Mollie IDs from our successful subscription creation
        emma.mollie_customer_id = "cst_9NfuyWyhAe"
        emma.mollie_subscription_id = "sub_x2W8R6eLGd"
        emma.subscription_status = "active"
        emma.next_payment_date = "2025-09-30"

        emma.insert()

        print(f"✅ Recreated Emma: {emma.name}")
        print(f"   Mollie Customer: {emma.mollie_customer_id}")
        print(f"   Subscription: {emma.mollie_subscription_id}")
        print(f"   Status: {emma.subscription_status}")

        return {
            "success": True,
            "member_name": emma.name,
            "mollie_customer_id": emma.mollie_customer_id,
            "mollie_subscription_id": emma.mollie_subscription_id,
        }

    except Exception as e:
        print(f"❌ Error recreating Emma: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def find_emma():
    """Find Emma van Subscription member"""
    try:
        members = frappe.get_all(
            "Member",
            filters={"first_name": "Emma", "last_name": "van Subscription"},
            fields=["name", "full_name", "mollie_subscription_id"],
        )

        print(f"Found Emma members: {len(members)}")
        for member in members:
            print(
                f"  {member['name']}: {member['full_name']} - {member.get('mollie_subscription_id', 'No subscription')}"
            )

        return members

    except Exception as e:
        print(f"❌ Error finding Emma: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def check_emma_status(member_name=None):
    """Check Emma van Subscription's current status and invoice situation"""
    try:
        if not member_name:
            # Find Emma first
            members = frappe.get_all(
                "Member", filters={"first_name": "Emma", "last_name": "van Subscription"}, fields=["name"]
            )
            if not members:
                return {"error": "Emma van Subscription not found"}
            member_name = members[0]["name"]

        emma = frappe.get_doc("Member", member_name)

        print(f"🧑‍💼 Member: {emma.full_name}")
        print(f"   Customer: {emma.customer}")
        print(f"   Mollie Customer: {emma.mollie_customer_id}")
        print(f"   Subscription: {emma.mollie_subscription_id}")
        print(f"   Status: {emma.subscription_status}")
        print(f"   Next Payment: {emma.next_payment_date}")
        print()

        # Check for unpaid invoices
        unpaid_invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": emma.customer,
                "docstatus": 1,
                "status": ["in", ["Unpaid", "Overdue", "Partly Paid"]],
            },
            fields=["name", "grand_total", "currency", "posting_date", "status"],
            order_by="posting_date desc",
        )

        print(f"💰 Unpaid Invoices: {len(unpaid_invoices)}")
        for inv in unpaid_invoices:
            print(f"   {inv['name']}: €{inv['grand_total']} ({inv['status']}) - {inv['posting_date']}")
        print()

        # Check existing payment entries
        payment_entries = frappe.get_all(
            "Payment Entry",
            filters={
                "party": emma.customer,
                "docstatus": 1,
                "reference_no": ["like", "%tr_%"],  # Mollie payment IDs start with tr_
            },
            fields=["name", "paid_amount", "reference_no", "posting_date", "remarks"],
            order_by="posting_date desc",
        )

        print(f"💳 Recent Mollie Payments: {len(payment_entries)}")
        for payment in payment_entries:
            print(
                f"   {payment['name']}: €{payment['paid_amount']} - {payment['reference_no']} ({payment['posting_date']})"
            )
        print()

        return {
            "member": emma.name,
            "customer": emma.customer,
            "subscription_id": emma.mollie_subscription_id,
            "unpaid_invoices": len(unpaid_invoices),
            "recent_payments": len(payment_entries),
        }

    except Exception as e:
        print(f"❌ Error checking Emma's status: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def create_test_invoice_for_emma(member_name=None):
    """Create a test membership invoice for Emma to test payment processing"""
    try:
        if not member_name:
            # Find Emma first
            members = frappe.get_all(
                "Member", filters={"first_name": "Emma", "last_name": "van Subscription"}, fields=["name"]
            )
            if not members:
                return {"error": "Emma van Subscription not found"}
            member_name = members[0]["name"]

        emma = frappe.get_doc("Member", member_name)

        # Create a simple membership dues invoice
        sales_invoice = frappe.new_doc("Sales Invoice")
        sales_invoice.customer = emma.customer
        sales_invoice.posting_date = frappe.utils.today()
        sales_invoice.due_date = frappe.utils.add_days(frappe.utils.today(), 30)

        # Get a simple item or create generic service
        existing_items = frappe.get_all("Item", fields=["name"], limit=1)

        if existing_items:
            item_code = existing_items[0]["name"]
        else:
            # Create a simple service item
            item = frappe.new_doc("Item")
            item.item_code = "Membership Dues Service"
            item.item_name = "Membership Dues"
            item.item_group = "All Item Groups"
            item.is_service = 1
            item.is_sales_item = 1
            item.insert()
            item_code = item.name

        # Add membership dues item
        sales_invoice.append(
            "items",
            {
                "item_code": item_code,
                "description": "Monthly Membership Dues - Test Invoice",
                "qty": 1,
                "rate": 25.00,
                "amount": 25.00,
            },
        )

        sales_invoice.insert()
        sales_invoice.submit()

        print(f"✅ Created test invoice: {sales_invoice.name}")
        print(f"   Amount: €{sales_invoice.grand_total}")
        print(f"   Customer: {sales_invoice.customer}")
        print(f"   Status: {sales_invoice.status}")

        return {
            "invoice_name": sales_invoice.name,
            "amount": sales_invoice.grand_total,
            "status": sales_invoice.status,
        }

    except Exception as e:
        print(f"❌ Error creating test invoice: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def simulate_webhook_payment():
    """Simulate a webhook payment for Emma's subscription"""
    try:
        # Find Emma first
        members = frappe.get_all(
            "Member", filters={"first_name": "Emma", "last_name": "van Subscription"}, fields=["name"]
        )
        if not members:
            return {"success": False, "error": "Emma van Subscription not found"}

        emma = frappe.get_doc("Member", members[0]["name"])

        # Generate a mock payment ID
        payment_id = f"tr_test_{frappe.utils.random_string(10)}"

        print(f"🔄 Simulating webhook payment...")
        print(f"   Member: {emma.full_name}")
        print(f"   Payment ID: {payment_id}")
        print(f"   Amount: €25.00")
        print()

        # Create a mock payment object
        class MockPayment:
            def __init__(self):
                self.id = payment_id
                self.status = "paid"
                self.amount = {"value": "25.00", "currency": "EUR"}

            def is_paid(self):
                return True

        # Get payment gateway
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")

        # Process the payment with mock
        from unittest.mock import patch

        with patch.object(gateway.client.payments, "get", return_value=MockPayment()):
            result = _process_subscription_payment(
                gateway, emma.name, emma.customer, payment_id, emma.mollie_subscription_id
            )

        print(f"✅ Payment processed!")
        print(f"   Status: {result.get('status')}")
        if result.get("payment_entry"):
            print(f"   Payment Entry: {result['payment_entry']}")
        if result.get("invoice"):
            print(f"   Invoice Paid: {result['invoice']}")

        return {"success": True, "payment_id": payment_id, "result": result}

    except Exception as e:
        print(f"❌ Payment simulation error: {str(e)}")
        frappe.log_error(f"Webhook simulation error: {str(e)}", "Webhook Testing")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_full_webhook():
    """Test the full webhook endpoint with Emma's subscription"""
    try:
        # Find Emma first
        members = frappe.get_all(
            "Member", filters={"first_name": "Emma", "last_name": "van Subscription"}, fields=["name"]
        )
        if not members:
            return {"success": False, "error": "Emma van Subscription not found"}

        emma = frappe.get_doc("Member", members[0]["name"])

        # Create a webhook payload that simulates Mollie sending a subscription payment
        webhook_payload = {
            "id": emma.mollie_subscription_id,
            "payment": {"id": f"tr_webhook_{frappe.utils.random_string(10)}"},
        }

        print(f"🔄 Testing full webhook endpoint...")
        print(f"   Subscription: {emma.mollie_subscription_id}")
        print(f"   Mock Payment: {webhook_payload['payment']['id']}")
        print()

        # Mock the webhook request
        import json
        from unittest.mock import MagicMock, patch

        mock_request = MagicMock()
        mock_request.get_data.return_value = json.dumps(webhook_payload)

        # Create mock payment for the webhook processing
        class MockPayment:
            def __init__(self):
                self.id = webhook_payload["payment"]["id"]
                self.status = "paid"
                self.amount = {"value": "25.00", "currency": "EUR"}

            def is_paid(self):
                return True

        # Import and call the webhook
        from verenigingen.verenigingen_payments.utils.payment_gateways import mollie_subscription_webhook

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
            print(f"   Payment Entry: {payment_result.get('payment_entry')}")
            print(f"   Invoice: {payment_result.get('invoice')}")

        return {"success": True, "webhook_result": result}

    except Exception as e:
        print(f"❌ Webhook test error: {str(e)}")
        frappe.log_error(f"Full webhook test error: {str(e)}", "Webhook Testing")
        return {"success": False, "error": str(e)}
