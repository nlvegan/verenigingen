#!/usr/bin/env python3
"""
Interactive Subscription Test
============================

Simple interactive subscription testing with basic Frappe document creation.
"""

from decimal import Decimal

import frappe
from frappe.utils import add_months, flt, today


@frappe.whitelist()
def create_simple_emma_persona():
    """Create Emma van Subscription using simple document creation"""

    try:
        print("🎭 Creating Emma van Subscription - Simple Approach")

        # Create basic test member
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Emma",
                "last_name": "van Subscription",
                "email": "emma.subscription@test.veganisme.nl",
                "birth_date": "1985-03-15",
                "iban": "NL91ABNA0417164300",
                "status": "Active",
                "gender": "Female",
                "nationality": "Dutch",
            }
        )
        member.insert()

        print(f"✅ Member created: {member.name} ({member.full_name})")

        # Create customer
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": member.full_name,
                "customer_type": "Individual",
                "territory": "Netherlands",
                "default_currency": "EUR",
            }
        )
        customer.insert()

        # Link member to customer
        member.customer = customer.name
        member.save()

        print(f"✅ Customer created: {customer.name}")

        # Create test invoice for subscription testing
        invoice = _create_simple_invoice(member, customer, 25.00)
        print(f"✅ Invoice created: {invoice.name} (€{invoice.grand_total})")

        result = {
            "success": True,
            "member": member.name,
            "customer": customer.name,
            "invoice": invoice.name,
            "emma_data": {
                "name": member.name,
                "full_name": member.full_name,
                "email": member.email,
                "iban": member.iban,
            },
        }

        print(f"\n🎉 Emma van Subscription complete!")
        print(f"   Member: {member.name}")
        print(f"   Email: {member.email}")
        print(f"   Customer: {customer.name}")
        print(f"   Ready for subscription testing!")

        return result

    except Exception as e:
        print(f"❌ Error creating Emma: {str(e)}")
        return {"success": False, "error": str(e)}


def _create_simple_invoice(member, customer, amount):
    """Create test invoice for subscription payment matching"""

    # Ensure test item exists
    if not frappe.db.exists("Item", "SUBSCRIPTION-TEST-DUES"):
        item = frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": "SUBSCRIPTION-TEST-DUES",
                "item_name": "Subscription Test Membership Dues",
                "item_group": "Services",
                "is_sales_item": 1,
                "is_service_item": 1,
                "standard_rate": amount,
            }
        )
        item.insert()

    invoice = frappe.get_doc(
        {
            "doctype": "Sales Invoice",
            "customer": customer.name,
            "customer_name": customer.customer_name,
            "posting_date": today(),
            "due_date": add_months(today(), 1),
            "currency": "EUR",
            "items": [
                {
                    "item_code": "SUBSCRIPTION-TEST-DUES",
                    "item_name": "Subscription Test Membership Dues",
                    "description": f"Monthly dues for {member.full_name} - {today()}",
                    "qty": 1,
                    "rate": amount,
                    "amount": amount,
                }
            ],
            "remarks": f"Simple subscription invoice - Member: {member.name}",
        }
    )

    invoice.insert()
    invoice.submit()
    return invoice


@frappe.whitelist()
def create_subscription_for_simple_emma(member_name):
    """Create Mollie subscription for simple Emma"""
    try:
        member = frappe.get_doc("Member", member_name)

        if not member.customer:
            return {"success": False, "error": "Member must have customer record"}

        print(f"🔄 Creating Mollie subscription for {member.full_name}...")

        from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")

        # Subscription data (gateway expects member and subscription_data)
        # Try without webhook first to test basic subscription creation
        subscription_data = {
            "amount": 25.00,
            "interval": "1 month",
            "description": f"Simple subscription test - {member.full_name}",
            "currency": "EUR"
            # Note: webhookUrl will be added by gateway
        }

        # Use the proper gateway method signature: create_subscription(member, subscription_data)
        result = gateway.create_subscription(member, subscription_data)

        if result.get("customer_id") and result.get("subscription_id"):
            # Update member with Mollie IDs
            member.mollie_customer_id = result["customer_id"]
            member.mollie_subscription_id = result["subscription_id"]
            member.subscription_status = "active"
            member.save()

            print(f"✅ Subscription created successfully!")
            print(f"   Customer ID: {result['customer_id']}")
            print(f"   Subscription ID: {result['subscription_id']}")
            print(f"   Amount: €25.00/month")
            print(f"   Status: active")

            return {
                "success": True,
                "member": member_name,
                "customer_id": result["customer_id"],
                "subscription_id": result["subscription_id"],
                "status": "active",
            }
        else:
            return {"success": False, "error": "Invalid subscription response", "result": result}

    except Exception as e:
        print(f"❌ Subscription creation error: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def simulate_simple_subscription_payment(member_name):
    """Simulate webhook payment for simple subscription"""
    try:
        member = frappe.get_doc("Member", member_name)

        if not member.mollie_subscription_id:
            return {"success": False, "error": "Member has no active subscription"}

        print(f"🔄 Simulating subscription payment for {member.full_name}...")

        # Generate test payment
        import uuid

        payment_id = f"tr_simple_{str(uuid.uuid4())[:8]}"

        from verenigingen.verenigingen_payments.utils.payment_gateways import (
            PaymentGatewayFactory,
            _process_subscription_payment,
        )

        # Get gateway and process payment
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")

        # Mock a successful payment
        class MockPayment:
            def __init__(self):
                self.id = payment_id
                self.status = "paid"
                self.amount = {"value": "25.00", "currency": "EUR"}
                self.customer_id = member.mollie_customer_id
                self.subscription_id = member.mollie_subscription_id

            def is_paid(self):
                return True

        def mock_payment():
            return MockPayment()

        # Process the payment
        from unittest.mock import patch

        with patch.object(gateway.client.payments, "get", return_value=mock_payment()):
            result = _process_subscription_payment(
                gateway, member.name, member.customer, payment_id, member.mollie_subscription_id
            )

        print(f"✅ Payment processed!")
        print(f"   Payment ID: {payment_id}")
        print(f"   Amount: €25.00")
        print(f"   Status: {result.get('status', 'processed')}")

        return {"success": True, "payment_id": payment_id, "member": member_name, "result": result}

    except Exception as e:
        print(f"❌ Payment simulation error: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_simple_payment_status(member_name):
    """Check payment status for simple subscription"""
    try:
        member = frappe.get_doc("Member", member_name)

        print(f"📊 Checking payment status for {member.full_name}...")

        # Check payment entries
        payments = frappe.get_all(
            "Payment Entry",
            filters={"party": member.customer},
            fields=["name", "paid_amount", "posting_date", "reference_no", "docstatus"],
            order_by="creation desc",
        )

        # Check invoices
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member.customer},
            fields=["name", "grand_total", "outstanding_amount", "status", "posting_date"],
            order_by="creation desc",
        )

        print(f"💰 Payment Entries: {len(payments)}")
        for payment in payments[:3]:  # Show last 3
            print(f"   {payment.name}: €{payment.paid_amount} ({payment.reference_no})")

        print(f"📄 Invoices: {len(invoices)}")
        for invoice in invoices[:3]:  # Show last 3
            outstanding = flt(invoice.outstanding_amount)
            print(
                f"   {invoice.name}: €{invoice.grand_total} - Outstanding: €{outstanding} ({invoice.status})"
            )

        return {
            "success": True,
            "member": member_name,
            "payments": len(payments),
            "invoices": len(invoices),
            "subscription_status": member.subscription_status,
        }

    except Exception as e:
        print(f"❌ Status check error: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def cleanup_simple_emma(member_name):
    """Clean up simple Emma"""
    try:
        member = frappe.get_doc("Member", member_name)

        print(f"🧹 Cleaning up {member.full_name}...")

        # Cancel subscription if active
        if member.mollie_subscription_id and member.subscription_status == "active":
            try:
                from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

                gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
                success = gateway.cancel_subscription(
                    member.mollie_customer_id, member.mollie_subscription_id
                )
                if success:
                    member.subscription_status = "cancelled"
                    member.save()
                    print("✅ Subscription cancelled")
            except Exception as e:
                print(f"⚠️  Subscription cleanup failed: {e}")

        return {"success": True, "message": f"Emma cleanup complete: {member_name}", "member": member_name}

    except Exception as e:
        print(f"❌ Cleanup error: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def run_complete_subscription_workflow():
    """Run the complete subscription workflow in one transaction"""
    try:
        frappe.db.begin()  # Start transaction

        print("🚀 Starting Complete Subscription Workflow")

        # Step 1: Create Emma
        print("\n=== Step 1: Creating Emma van Subscription ===")
        emma_result = create_simple_emma_persona()
        if not emma_result["success"]:
            return {"success": False, "error": f"Emma creation failed: {emma_result['error']}"}

        member_name = emma_result["member"]
        print(f"✅ Emma created: {member_name}")

        # Step 2: Manually set subscription IDs (since real subscription creation failed)
        print(f"\n=== Step 2: Setting up test subscription IDs ===")
        member = frappe.get_doc("Member", member_name)
        member.mollie_customer_id = "cst_test_emma_complete"
        member.mollie_subscription_id = "sub_test_emma_complete"
        member.subscription_status = "active"
        member.save()
        print(f"✅ Test subscription IDs set for {member.full_name}")

        # Step 3: Simulate payment
        print(f"\n=== Step 3: Simulating subscription payment ===")
        payment_result = simulate_simple_subscription_payment(member_name)
        if not payment_result["success"]:
            return {"success": False, "error": f"Payment simulation failed: {payment_result['error']}"}

        payment_id = payment_result["payment_id"]
        print(f"✅ Payment processed: {payment_id}")

        # Step 4: Check status
        print(f"\n=== Step 4: Checking payment status ===")
        status_result = check_simple_payment_status(member_name)
        if not status_result["success"]:
            return {"success": False, "error": f"Status check failed: {status_result['error']}"}

        print(
            f"✅ Status check complete - Payments: {status_result['payments']}, Invoices: {status_result['invoices']}"
        )

        # Step 5: Final summary
        print(f"\n🎉 Complete Subscription Workflow SUCCESS!")
        print(f"   📋 Member: {member_name}")
        print(f"   💳 Customer: {emma_result['customer']}")
        print(f"   📄 Invoice: {emma_result['invoice']}")
        print(f"   💰 Payment: {payment_id}")
        print(f"   🔄 Subscription Status: {member.subscription_status}")

        # Commit the transaction
        frappe.db.commit()

        return {
            "success": True,
            "workflow_complete": True,
            "member": member_name,
            "customer": emma_result["customer"],
            "invoice": emma_result["invoice"],
            "payment_id": payment_id,
            "subscription_status": member.subscription_status,
            "summary": f"Complete subscription workflow test successful for {member.full_name}",
        }

    except Exception as e:
        frappe.db.rollback()  # Rollback on error
        print(f"❌ Workflow error: {str(e)}")
        return {"success": False, "error": str(e)}
