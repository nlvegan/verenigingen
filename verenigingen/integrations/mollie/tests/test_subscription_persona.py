#!/usr/bin/env python3
"""
Interactive Subscription Test Persona
=====================================

Creates and manages "Emma van Subscription" - a test persona for validating
the complete subscription workflow interactively.

Usage:
    from verenigingen.utils.test_subscription_persona import *

    # Create the persona
    emma = create_emma_subscription_persona()

    # Create subscription
    subscription = create_subscription_for_emma(emma)

    # Simulate payment
    payment = simulate_subscription_payment(emma, subscription)

    # Check results
    verify_payment_processing(emma, payment)

    # Clean up
    cleanup_emma_persona(emma, subscription)
"""

import json
from decimal import Decimal

import frappe
from frappe.utils import add_months, flt, today

from verenigingen.utils.security.api_security_framework import OperationType, development_only_api


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def create_emma_subscription_persona():
    """
    Create comprehensive test persona: Emma van Subscription

    Returns:
        dict: Complete persona data with member, customer, membership, dues schedule, and invoice
    """
    try:
        print("🎭 Creating Emma van Subscription - Complete Test Persona")

        # 1. Create member
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Emma",
                "last_name": "van Subscription",
                "email": "emma.subscription@test.veganisme.nl",
                "birth_date": "1985-03-15",
                "iban": "NL91ABNA0417164300",
                "member_number": f"SUB-{frappe.utils.now()[:10].replace('-', '')}",
                "status": "Active",
                "gender": "Female",
                "nationality": "Dutch",
            }
        )
        member.insert()
        print(f"✅ Member created: {member.name} ({member.full_name})")

        # 2. Create customer
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

        # 3. Create active membership
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": "Full Member",
                "membership_status": "Current",
                "from_date": today(),
                "to_date": add_months(today(), 12),
                "amount": 300.00,
                "currency": "EUR",
                "is_paid": 0,
            }
        )
        membership.insert()
        membership.submit()
        print(f"✅ Membership created: {membership.name} (€300/year)")

        # 4. Create test item for invoicing
        if not frappe.db.exists("Item", "MEMBERSHIP-DUES-TEST"):
            item = frappe.get_doc(
                {
                    "doctype": "Item",
                    "item_code": "MEMBERSHIP-DUES-TEST",
                    "item_name": "Test Monthly Membership Dues",
                    "item_group": "Services",
                    "is_sales_item": 1,
                    "is_service_item": 1,
                    "standard_rate": 25.00,
                }
            )
            item.insert()
            print("✅ Test item created: MEMBERSHIP-DUES-TEST")

        # 5. Create unpaid invoice for current period
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
                        "item_code": "MEMBERSHIP-DUES-TEST",
                        "item_name": "Test Monthly Membership Dues",
                        "description": f"Monthly dues for {member.full_name} - {today()}",
                        "qty": 1,
                        "rate": 25.00,
                        "amount": 25.00,
                    }
                ],
                "remarks": f"Test subscription invoice - Member: {member.name}",
            }
        )
        invoice.insert()
        invoice.submit()
        print(f"✅ Invoice created: {invoice.name} (€{invoice.grand_total}) - Status: {invoice.status}")

        persona = {
            "member": member,
            "customer": customer,
            "membership": membership,
            "invoice": invoice,
            "success": True,
        }

        print(f"\n🎉 Emma van Subscription persona complete!")
        print(f"   Member: {member.name}")
        print(f"   Customer: {customer.name}")
        print(f"   Membership: €300/year")
        print(f"   Current Invoice: €25.00 (unpaid)")
        print(f"   Ready for subscription testing!")

        return persona

    except Exception as e:
        frappe.log_error(f"Error creating Emma persona: {str(e)}", "Test Persona Creation")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def create_subscription_for_emma(member_name=None):
    """
    Create real Mollie subscription for Emma

    Args:
        member_name (str): Member document name, or uses latest Emma

    Returns:
        dict: Subscription creation result
    """
    try:
        # Find Emma if not specified
        if not member_name:
            emma_members = frappe.get_all(
                "Member",
                filters={"first_name": "Emma", "last_name": "van Subscription"},
                order_by="creation desc",
                limit=1,
            )
            if not emma_members:
                return {
                    "success": False,
                    "error": "Emma persona not found. Create her first with create_emma_subscription_persona()",
                }
            member_name = emma_members[0].name

        member = frappe.get_doc("Member", member_name)

        if not member.customer:
            return {"success": False, "error": "Member must have customer record"}

        print(f"🔄 Creating Mollie subscription for {member.full_name}...")

        from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")

        # Customer data for Mollie
        customer_data = {"name": member.full_name, "email": member.email, "locale": "nl_NL"}

        # Subscription data
        subscription_data = {
            "amount": {"currency": "EUR", "value": "25.00"},
            "interval": "1 month",
            "description": f"Monthly membership dues - {member.full_name}",
            "webhookUrl": frappe.utils.get_url(
                "/api/method/verenigingen.verenigingen_payments.utils.payment_gateways.mollie_subscription_webhook"
            ),
        }

        result = gateway.create_subscription(customer_data, subscription_data)

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
        frappe.log_error(f"Subscription creation error: {str(e)}", "Emma Subscription Test")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def simulate_subscription_payment(member_name=None):
    """
    Simulate webhook payment for Emma's subscription

    Args:
        member_name (str): Member document name

    Returns:
        dict: Payment simulation result
    """
    try:
        if not member_name:
            emma_members = frappe.get_all(
                "Member",
                filters={"first_name": "Emma", "last_name": "van Subscription"},
                order_by="creation desc",
                limit=1,
            )
            if not emma_members:
                return {"success": False, "error": "Emma not found"}
            member_name = emma_members[0].name

        member = frappe.get_doc("Member", member_name)

        if not member.mollie_subscription_id:
            return {"success": False, "error": "Member has no active subscription"}

        print(f"🔄 Simulating subscription payment for {member.full_name}...")

        # Generate test payment
        import uuid

        payment_id = f"tr_test_{str(uuid.uuid4())[:8]}"

        from verenigingen.verenigingen_payments.utils.payment_gateways import (
            PaymentGatewayFactory,
            _process_subscription_payment,
        )

        # Get gateway and process payment
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")

        # Mock a successful payment
        def mock_payment():
            return type(
                "MockPayment",
                (),
                {
                    "id": payment_id,
                    "status": "paid",
                    "amount": {"value": "25.00", "currency": "EUR"},
                    "is_paid": lambda: True,
                    "customer_id": member.mollie_customer_id,
                    "subscription_id": member.mollie_subscription_id,
                },
            )()

        # Process the payment
        with frappe.utils.patch.object(gateway.client.payments, "get", return_value=mock_payment()):
            result = _process_subscription_payment(
                gateway, member.name, member.customer, payment_id, member.mollie_subscription_id
            )

        print(f"✅ Payment processed!")
        print(f"   Payment ID: {payment_id}")
        print(f"   Amount: €25.00")
        print(f"   Status: {result.get('status', 'processed')}")

        return {"success": True, "payment_id": payment_id, "member": member_name, "result": result}

    except Exception as e:
        frappe.log_error(f"Payment simulation error: {str(e)}", "Emma Payment Test")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def check_emma_payment_status(member_name=None):
    """Check Emma's payment and invoice status"""
    try:
        if not member_name:
            emma_members = frappe.get_all(
                "Member",
                filters={"first_name": "Emma", "last_name": "van Subscription"},
                order_by="creation desc",
                limit=1,
            )
            if not emma_members:
                return {"success": False, "error": "Emma not found"}
            member_name = emma_members[0].name

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
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def cleanup_emma_persona(member_name=None):
    """Clean up Emma's subscription and test data"""
    try:
        if not member_name:
            emma_members = frappe.get_all(
                "Member",
                filters={"first_name": "Emma", "last_name": "van Subscription"},
                order_by="creation desc",
                limit=1,
            )
            if not emma_members:
                return {"success": False, "error": "Emma not found"}
            member_name = emma_members[0].name

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

        return {
            "success": True,
            "message": f"Emma persona cleanup complete: {member_name}",
            "member": member_name,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# Usage Examples:
# ===============
#
# # In Frappe console:
# from verenigingen.utils.test_subscription_persona import *
#
# # 1. Create the persona
# emma = create_emma_subscription_persona()
#
# # 2. Create subscription
# subscription = create_subscription_for_emma()
#
# # 3. Simulate payment
# payment = simulate_subscription_payment()
#
# # 4. Check status
# check_emma_payment_status()
#
# # 5. Clean up
# cleanup_emma_persona()
