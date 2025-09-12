#!/usr/bin/env python3
"""
Debug script to investigate Mollie subscription issue with transaction tr_8gAtxfRYWdfbvaRDTC3EJ
"""

import json
from decimal import Decimal

import frappe


def debug_mollie_transaction(payment_id="tr_8gAtxfRYWdfbvaRDTC3EJ"):
    """
    Debug the specific Mollie transaction and compare with subscription requirements
    """
    try:
        # Get Mollie settings and client
        print("=== MOLLIE SUBSCRIPTION DEBUG ===")
        print(f"Investigating payment: {payment_id}")
        print()

        # Initialize Frappe if not already done
        if not frappe.db:
            frappe.init(site="dev.veganisme.net")
            frappe.connect()

        # Get Mollie settings
        mollie_settings = frappe.get_single("Mollie Settings")
        print(f"Test Mode: {mollie_settings.test_mode}")
        print(f"Subscriptions Enabled: {getattr(mollie_settings, 'enable_subscriptions', False)}")
        print()

        # Get Mollie client
        client = mollie_settings.get_mollie_client()
        print("✅ Mollie client connected successfully")
        print()

        # Query the specific payment
        print("=== PAYMENT DETAILS ===")
        try:
            payment = client.payments.get(payment_id)

            # Print comprehensive payment details
            print(f"Payment ID: {payment.id}")
            print(f"Status: {payment.status}")
            print(f"Amount: {payment.amount['value']} {payment.amount['currency']}")
            print(f"Description: {payment.description}")
            print(f"Method: {getattr(payment, 'method', 'N/A')}")
            print(f"Mode: {getattr(payment, 'mode', 'N/A')}")
            print(f"Created At: {payment.created_at}")
            print(f"Paid At: {getattr(payment, 'paid_at', 'N/A')}")
            print(f"Expires At: {getattr(payment, 'expires_at', 'N/A')}")
            print(f"Profile ID: {getattr(payment, 'profile_id', 'N/A')}")
            print(f"Settlement ID: {getattr(payment, 'settlement_id', 'N/A')}")

            # Check sequence type (critical for subscriptions)
            sequence_type = getattr(payment, "sequence_type", None)
            print(f"Sequence Type: {sequence_type}")

            # Check customer ID
            customer_id = getattr(payment, "customer_id", None)
            print(f"Customer ID: {customer_id}")

            # Check if there are any subscriptions associated
            subscription_id = getattr(payment, "subscription_id", None)
            print(f"Subscription ID: {subscription_id}")

            # Metadata
            metadata = getattr(payment, "metadata", {})
            print(f"Metadata: {json.dumps(metadata, indent=2)}")

            # Links
            if hasattr(payment, "_links"):
                links = payment._links
                print(f"Links: {dir(links)}")
                if hasattr(links, "checkout") and hasattr(links.checkout, "href"):
                    print(f"Checkout URL: {links.checkout.href}")

            print()

            # Check if this was meant to be a subscription setup
            print("=== SUBSCRIPTION ANALYSIS ===")

            if sequence_type == "first":
                print("✅ This is a 'first' payment - correct for subscription setup")

                if customer_id:
                    print(f"✅ Customer ID found: {customer_id}")

                    # Try to get the customer and check for subscriptions
                    try:
                        customer = client.customers.get(customer_id)
                        print(f"Customer Name: {customer.name}")
                        print(f"Customer Email: {customer.email}")
                        print(f"Customer Created: {customer.created_at}")

                        # List customer's subscriptions
                        subscriptions = customer.subscriptions.list()
                        print(f"Number of subscriptions: {len(subscriptions['data'])}")

                        for sub in subscriptions["data"]:
                            print(
                                f"  Subscription {sub.id}: {sub.status} - {sub.amount['value']} {sub.amount['currency']} every {sub.interval}"
                            )

                    except Exception as e:
                        print(f"❌ Error getting customer details: {e}")
                else:
                    print("❌ No customer ID - subscription setup incomplete")

            elif sequence_type == "recurring":
                print("⚠️ This is a 'recurring' payment - subscription should already exist")
            elif sequence_type == "oneoff":
                print("⚠️ This is a 'oneoff' payment - not for subscriptions")
            else:
                print("❌ No sequence type or unknown type - subscription setup likely failed")

            print()

            # Parse description to understand the intent
            print("=== DESCRIPTION ANALYSIS ===")
            description = payment.description
            print(f"Description: '{description}'")

            try:
                # Try to parse as JSON (our metadata format)
                if description.startswith("{"):
                    parsed_desc = json.loads(description)
                    print("✅ Description contains JSON metadata:")
                    print(json.dumps(parsed_desc, indent=2))

                    if parsed_desc.get("type") == "recurring":
                        print("✅ Payment was intended for recurring subscription")
                        interval = parsed_desc.get("interval", "unknown")
                        print(f"Intended interval: {interval}")
                    else:
                        print("⚠️ Payment was not marked as recurring in metadata")

            except json.JSONDecodeError:
                print("⚠️ Description is not JSON - likely a simple description")

            print()

            # Check payment success
            print("=== PAYMENT SUCCESS CHECK ===")
            if payment.is_paid():
                print("✅ Payment was successful")
                print(f"Paid at: {payment.paid_at}")

                # If this was a first payment that succeeded but no subscription exists, that's the problem
                if sequence_type == "first" and customer_id:
                    customer = client.customers.get(customer_id)
                    subscriptions = customer.subscriptions.list()

                    if len(subscriptions["data"]) == 0:
                        print(
                            "❌ PROBLEM IDENTIFIED: First payment succeeded but no subscription was created!"
                        )
                        print("This suggests the subscription creation step failed after the payment.")
                    else:
                        print(f"✅ Customer has {len(subscriptions['data'])} subscription(s)")

            elif payment.is_pending():
                print("⏳ Payment is still pending")
            elif payment.is_canceled():
                print("❌ Payment was canceled")
            elif payment.is_expired():
                print("❌ Payment expired")
            elif payment.is_failed():
                print("❌ Payment failed")
            else:
                print(f"❓ Payment status: {payment.status}")

            print()

            return {
                "payment": payment,
                "sequence_type": sequence_type,
                "customer_id": customer_id,
                "subscription_id": subscription_id,
                "is_paid": payment.is_paid(),
                "description": description,
            }

        except Exception as e:
            print(f"❌ Error retrieving payment: {e}")
            return None

    except Exception as e:
        print(f"❌ Error in debug script: {e}")
        import traceback

        traceback.print_exc()
        return None


def check_mollie_subscription_documentation():
    """
    Check the requirements for creating subscriptions according to Mollie docs
    """
    print("=== MOLLIE SUBSCRIPTION REQUIREMENTS ===")
    print()
    print("According to Mollie API documentation:")
    print("1. First payment must have sequenceType: 'first'")
    print("2. Customer must be created before subscription")
    print("3. First payment establishes mandate/authorization")
    print("4. After first payment succeeds, subscription must be created separately")
    print("5. Subsequent payments will have sequenceType: 'recurring'")
    print()
    print("For 1-day intervals:")
    print("- Mollie supports 'every day' but with minimum limits")
    print("- Some payment methods may not support daily intervals")
    print("- Bank transfers typically have minimum intervals")
    print()


if __name__ == "__main__":
    # Run the debug
    result = debug_mollie_transaction()
    print()
    check_mollie_subscription_documentation()

    if result:
        print("=== RECOMMENDED NEXT STEPS ===")
        if result["sequence_type"] == "first" and result["is_paid"] and result["customer_id"]:
            print("1. Check webhook processing - did the subscription creation webhook fire?")
            print("2. Look for subscription creation errors in Frappe error logs")
            print("3. Manually trigger subscription creation for this customer")
            print("4. Verify 1-day interval is supported by the payment method used")
        else:
            print("1. Check if payment was set up correctly as a 'first' payment")
            print("2. Verify customer creation succeeded before payment")
            print("3. Check if 1-day interval is causing validation issues")
