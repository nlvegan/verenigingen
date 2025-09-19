"""
Check real Mollie payments for our test subscription
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api
from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def check_subscription_payments():
    """Check what payments exist for Emma's subscription"""
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
        customer_id = customer.custom_mollie_customer_id
        subscription_id = customer.custom_mollie_subscription_id

        print(f"🔍 Checking payments for subscription: {subscription_id}")
        print(f"   Customer: {customer_id}")

        # Get Mollie gateway
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")

        # Get subscription details from Mollie
        mollie_customer = gateway.client.customers.get(customer_id)
        subscription = mollie_customer.subscriptions.get(subscription_id)

        print(f"✅ Subscription Status: {subscription.status}")
        print(f"   Next Payment: {subscription.next_payment_date}")
        print(f"   Amount: {subscription.amount['currency']} {subscription.amount['value']}")

        # Check for payments associated with this subscription
        payments = gateway.client.payments.list()
        subscription_payments = []

        print("\n💳 Recent Payments:")
        for payment in payments:
            # Check if payment is related to our customer or subscription
            if (
                (hasattr(payment, "customer_id") and payment.customer_id == customer_id)
                or (hasattr(payment, "subscription_id") and payment.subscription_id == subscription_id)
                or (
                    hasattr(payment, "metadata")
                    and payment.metadata
                    and payment.metadata.get("member_id") == members[0]["name"]
                )
            ):
                subscription_payments.append(
                    {
                        "id": payment.id,
                        "status": payment.status,
                        "amount": f"{payment.amount['currency']} {payment.amount['value']}",
                        "created": payment.created_at,
                        "description": payment.description,
                    }
                )

                print(
                    f"   {payment.id}: {payment.status} - {payment.amount['currency']} {payment.amount['value']}"
                )
                print(f"      Created: {payment.created_at}")
                print(f"      Description: {payment.description}")

        if not subscription_payments:
            print("   No payments found for this subscription yet")
            print("   (This is normal - payments are created when due)")

        return {
            "success": True,
            "customer_id": customer_id,
            "subscription_id": subscription_id,
            "subscription_status": subscription.status,
            "next_payment_date": subscription.next_payment_date,
            "subscription_payments": subscription_payments,
        }

    except Exception as e:
        print(f"❌ Error checking subscription payments: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def list_all_mollie_payments():
    """List all payments in the Mollie test account"""
    try:
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")

        # Get recent payments
        payments = gateway.client.payments.list(limit=20)

        print("📋 Recent Mollie Payments (last 20):")
        payment_list = []

        for payment in payments:
            payment_info = {
                "id": payment.id,
                "status": payment.status,
                "amount": f"{payment.amount['currency']} {payment.amount['value']}",
                "created": payment.created_at,
                "description": payment.description,
                "method": getattr(payment, "method", "unknown"),
            }

            payment_list.append(payment_info)

            print(f"   {payment.id}: {payment.status}")
            print(f"      Amount: {payment.amount['currency']} {payment.amount['value']}")
            print(f"      Method: {getattr(payment, 'method', 'unknown')}")
            print(f"      Created: {payment.created_at}")
            print(f"      Description: {payment.description}")
            print()

        return {"success": True, "payments": payment_list}

    except Exception as e:
        print(f"❌ Error listing payments: {str(e)}")
        return {"error": str(e)}
