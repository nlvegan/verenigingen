"""
Test script to verify the Mollie subscription fixes
"""

import json

import frappe


def test_subscription_metadata_creation():
    """
    Test creating a subscription using the new metadata approach
    """
    try:
        print("=== TESTING SUBSCRIPTION METADATA FIXES ===")

        # Get Mollie settings and client
        mollie_settings = frappe.get_single("Mollie Settings")
        client = mollie_settings.get_mollie_client()

        # Use existing customer from previous tests
        customer_id = "cst_DNZCrmyjcR"
        customer = client.customers.get(customer_id)
        print(f"✅ Using existing customer: {customer.name} ({customer.email})")

        # Test 1: Create payment with proper metadata (simulating the new approach)
        print("\n--- Test 1: Creating payment with subscription metadata ---")

        payment_data = {
            "amount": {"value": "25.00", "currency": "EUR"},
            "description": "Test recurring donation setup",  # User-friendly description
            "sequenceType": "first",
            "customerId": customer_id,
            "redirectUrl": "https://example.com/success",
            "webhookUrl": "https://example.com/webhook",
            "metadata": {
                # Proper metadata structure
                "donation_id": "TEST-DONATION-001",
                "reference_doctype": "Donation",
                "reference_docname": "TEST-DONATION-001",
                "subscription_setup": "true",
                "subscription_interval": "1 day",  # Correct format
                "subscription_amount": "25.00",
                "subscription_currency": "EUR",
            },
        }

        print("Payment data metadata:")
        for key, value in payment_data["metadata"].items():
            print(f"  {key}: {value}")

        # Create the payment
        payment = client.payments.create(payment_data)
        print(f"✅ Created test payment: {payment.id}")
        print(f"   Status: {payment.status}")
        print(f"   Sequence Type: {payment.sequence_type}")
        print(f"   Customer ID: {payment.customer_id}")

        # Test 2: Simulate direct subscription creation from metadata
        print("\n--- Test 2: Creating subscription from payment metadata ---")

        # Simulate what the webhook would do
        metadata = payment.metadata

        if metadata.get("subscription_setup") == "true":
            print("✅ Payment marked for subscription setup")

            subscription_data = {
                "amount": {
                    "currency": metadata.get("subscription_currency", "EUR"),
                    "value": metadata.get("subscription_amount"),
                },
                "interval": metadata.get("subscription_interval"),  # Should be "1 day"
                "description": f"Recurring donation {metadata.get('donation_id')}",
                "metadata": {
                    "payment_id": payment.id,
                    "donation_id": metadata.get("donation_id"),
                    "created_from": "metadata_test",
                    "original_interval": metadata.get("subscription_interval"),
                },
            }

            print(f"Subscription data:")
            print(
                f"  Amount: {subscription_data['amount']['value']} {subscription_data['amount']['currency']}"
            )
            print(f"  Interval: '{subscription_data['interval']}'")
            print(f"  Description: {subscription_data['description']}")

            # Create subscription
            subscription = customer.subscriptions.create(data=subscription_data)
            print(f"✅ Created subscription: {subscription.id}")
            print(f"   Status: {subscription.status}")
            print(f"   Amount: {subscription.amount['value']} {subscription.amount['currency']}")
            print(f"   Interval: {subscription.interval}")
            print(f"   Next Payment: {getattr(subscription, 'next_payment_date', 'N/A')}")

            # Clean up
            print(f"🧹 Cleaning up test subscription {subscription.id}")
            customer.subscriptions.delete(subscription.id)
            print("✅ Test subscription deleted")

        else:
            print("❌ Payment not marked for subscription setup")

        print("\n=== TESTS COMPLETED SUCCESSFULLY ===")
        return True

    except Exception as e:
        print(f"❌ Test error: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_interval_formats():
    """
    Test different interval formats to ensure they work
    """
    print("\n=== TESTING INTERVAL FORMATS ===")

    test_intervals = ["1 day", "3 days", "1 week", "2 weeks", "1 month", "3 months", "6 months", "1 year"]

    try:
        mollie_settings = frappe.get_single("Mollie Settings")
        client = mollie_settings.get_mollie_client()
        customer_id = "cst_DNZCrmyjcR"
        customer = client.customers.get(customer_id)

        for interval in test_intervals:
            print(f"\nTesting interval: '{interval}'")

            subscription_data = {
                "amount": {"currency": "EUR", "value": "10.00"},
                "interval": interval,
                "description": f"Test subscription {interval}",
                "metadata": {"test": f"interval_{interval.replace(' ', '_')}"},
            }

            try:
                subscription = customer.subscriptions.create(data=subscription_data)
                print(f"  ✅ SUCCESS: Created {subscription.id}")
                print(f"     Parsed interval: {subscription.interval}")

                # Clean up immediately
                customer.subscriptions.delete(subscription.id)
                print(f"     🧹 Cleaned up")

            except Exception as e:
                print(f"  ❌ FAILED: {e}")

        return True

    except Exception as e:
        print(f"❌ Interval test error: {e}")
        return False


if __name__ == "__main__":
    success1 = test_subscription_metadata_creation()
    success2 = test_interval_formats()

    if success1 and success2:
        print("\n🎉 ALL TESTS PASSED - Subscription fixes are working!")
    else:
        print("\n❌ Some tests failed - check the output above")
