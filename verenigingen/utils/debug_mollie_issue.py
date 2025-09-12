"""
Debug Mollie subscription creation issue
"""

import json

import frappe


def debug_specific_transaction(payment_id="tr_8gAtxfRYWdfbvaRDTC3EJ"):
    """
    Debug the specific transaction that had subscription issues
    """
    try:
        print(f"=== DEBUGGING MOLLIE PAYMENT {payment_id} ===")

        # Get Mollie settings and client
        mollie_settings = frappe.get_single("Mollie Settings")
        client = mollie_settings.get_mollie_client()

        print(f"API Mode: {'Test' if mollie_settings.test_mode else 'Live'}")
        print(f"Subscriptions Enabled: {getattr(mollie_settings, 'enable_subscriptions', False)}")
        print()

        # Get the payment
        payment = client.payments.get(payment_id)

        print("=== PAYMENT DETAILS ===")
        print(f"ID: {payment.id}")
        print(f"Status: {payment.status}")
        print(f"Amount: {payment.amount['value']} {payment.amount['currency']}")
        print(f"Description: {payment.description}")
        print(f"Created: {payment.created_at}")
        print(f"Method: {getattr(payment, 'method', 'N/A')}")
        print(f"Sequence Type: {getattr(payment, 'sequence_type', 'N/A')}")
        print(f"Customer ID: {getattr(payment, 'customer_id', 'N/A')}")
        print(f"Subscription ID: {getattr(payment, 'subscription_id', 'N/A')}")
        print()

        # Check if payment was successful
        is_paid = payment.is_paid()
        print(f"Payment Successful: {is_paid}")
        if is_paid:
            print(f"Paid At: {getattr(payment, 'paid_at', 'N/A')}")
        print()

        # Analyze the description (should contain metadata)
        description = payment.description
        print("=== DESCRIPTION ANALYSIS ===")
        print(f"Raw Description: '{description}'")

        try:
            if description.startswith("{"):
                metadata = json.loads(description)
                print("Parsed Metadata:")
                for key, value in metadata.items():
                    print(f"  {key}: {value}")

                payment_type = metadata.get("type")
                if payment_type == "recurring":
                    print("✅ Payment was intended for recurring subscription")
                    print(f"Interval: {metadata.get('interval', 'unknown')}")
                else:
                    print(f"⚠️ Payment type: {payment_type}")
            else:
                print("⚠️ Description is not JSON metadata")
        except:
            print("❌ Failed to parse description as JSON")
        print()

        # Check customer and subscriptions if customer_id exists
        customer_id = getattr(payment, "customer_id", None)
        if customer_id:
            print(f"=== CUSTOMER {customer_id} ANALYSIS ===")
            try:
                customer = client.customers.get(customer_id)
                print(f"Name: {customer.name}")
                print(f"Email: {customer.email}")

                # List subscriptions
                subscriptions = customer.subscriptions.list()
                sub_count = len(subscriptions) if hasattr(subscriptions, "__len__") else 0
                print(f"Subscriptions Count: {sub_count}")

                # Handle both list object and dict with 'data' key
                subscription_list = subscriptions if hasattr(subscriptions, "__iter__") else []
                if hasattr(subscriptions, "get") and "data" in subscriptions:
                    subscription_list = subscriptions["data"]

                for sub in subscription_list:
                    print(f"  Subscription {sub.id}:")
                    print(f"    Status: {sub.status}")
                    print(f"    Amount: {sub.amount['value']} {sub.amount['currency']}")
                    print(f"    Interval: {sub.interval}")
                    print(f"    Created: {sub.created_at}")
                    print(f"    Next Payment: {getattr(sub, 'next_payment_date', 'N/A')}")

                if sub_count == 0:
                    print("❌ NO SUBSCRIPTIONS FOUND - This is likely the problem!")

            except Exception as e:
                print(f"❌ Error getting customer details: {e}")
        else:
            print("❌ NO CUSTOMER ID - First payment should have customer_id")

        print()

        return {
            "payment_id": payment_id,
            "status": payment.status,
            "is_paid": is_paid,
            "sequence_type": getattr(payment, "sequence_type", None),
            "customer_id": customer_id,
            "description": description,
        }

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return None


def check_mollie_interval_support():
    """
    Check what intervals Mollie supports for subscriptions
    """
    print("=== MOLLIE SUBSCRIPTION INTERVALS ===")
    print("According to Mollie API documentation:")
    print("Supported intervals:")
    print("- ... days (minimum 1 day)")
    print("- ... weeks")
    print("- ... months")
    print("- ... years")
    print()
    print("Notes:")
    print("- Daily subscriptions (1 day) are supported")
    print("- Some payment methods may have restrictions")
    print("- Credit cards: generally support daily")
    print("- SEPA Direct Debit: may have minimum intervals")
    print("- iDEAL: typically one-time only, not suitable for recurring")
    print()


def analyze_subscription_workflow():
    """
    Analyze the expected workflow for subscription creation
    """
    print("=== EXPECTED SUBSCRIPTION WORKFLOW ===")
    print("1. User initiates recurring donation")
    print("2. Create Mollie customer")
    print("3. Create first payment with sequenceType: 'first'")
    print("4. User completes payment (establishes mandate)")
    print("5. Webhook fires when payment succeeds")
    print("6. Create subscription based on successful first payment")
    print("7. Future payments are automatically charged")
    print()
    print("POTENTIAL ISSUES:")
    print("- Step 6 might be failing")
    print("- 1-day interval might not be supported by payment method")
    print("- Webhook might not be creating subscription properly")
    print("- Customer creation might be failing")
    print()


if __name__ == "__main__":
    debug_specific_transaction()
    check_mollie_interval_support()
    analyze_subscription_workflow()
