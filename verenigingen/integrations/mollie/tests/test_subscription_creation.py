"""
Test script to reproduce the Mollie subscription creation issue
"""

import json
from decimal import Decimal

import frappe


def test_subscription_creation_with_1day_interval():
    """
    Test creating a subscription with 1 day interval to reproduce the issue
    """
    try:
        print("=== TESTING SUBSCRIPTION CREATION ===")

        # Get Mollie settings and client
        mollie_settings = frappe.get_single("Mollie Settings")
        client = mollie_settings.get_mollie_client()

        print("✅ Connected to Mollie API")

        # Use the existing customer from the failed transaction
        customer_id = "cst_DNZCrmyjcR"

        print(f"Testing with existing customer: {customer_id}")

        # Test 1: Try with "1 d" format (current broken format)
        print("\n--- Test 1: Using '1 d' interval format ---")
        subscription_data_bad = {
            "amount": {"currency": "EUR", "value": "25.00"},
            "interval": "1 d",  # This is the problem format
            "description": "Test subscription with 1d interval",
            "metadata": {"test": "1d_interval_format"},
        }

        try:
            customer = client.customers.get(customer_id)
            subscription = customer.subscriptions.create(data=subscription_data_bad)
            print(f"❌ UNEXPECTED: '1 d' format worked! Created subscription: {subscription.id}")
            # Clean up
            customer.subscriptions.delete(subscription.id)
        except Exception as e:
            print(f"✅ EXPECTED: '1 d' format failed: {e}")

        # Test 2: Try with "1 day" format (correct format)
        print("\n--- Test 2: Using '1 day' interval format ---")
        subscription_data_good = {
            "amount": {"currency": "EUR", "value": "25.00"},
            "interval": "1 day",  # Correct format
            "description": "Test subscription with 1 day interval",
            "metadata": {"test": "1day_interval_format"},
        }

        try:
            subscription = customer.subscriptions.create(data=subscription_data_good)
            print(f"✅ SUCCESS: '1 day' format worked! Created subscription: {subscription.id}")
            print(f"   Status: {subscription.status}")
            print(f"   Amount: {subscription.amount['value']} {subscription.amount['currency']}")
            print(f"   Interval: {subscription.interval}")
            print(f"   Next Payment: {getattr(subscription, 'next_payment_date', 'N/A')}")

            # Clean up the test subscription
            print(f"🧹 Cleaning up test subscription {subscription.id}")
            customer.subscriptions.delete(subscription.id)
            print("✅ Test subscription deleted")

        except Exception as e:
            print(f"❌ UNEXPECTED: '1 day' format failed: {e}")

        # Test 3: Check if iDEAL supports recurring payments
        print("\n--- Test 3: Check iDEAL compatibility with subscriptions ---")
        print("The original payment used iDEAL method")
        print("iDEAL is typically one-time only and may not support recurring subscriptions")
        print("This could be why the subscription creation failed even with correct format")

        return True

    except Exception as e:
        print(f"❌ Test error: {e}")
        import traceback

        traceback.print_exc()
        return False


def suggest_fixes():
    """
    Suggest fixes for the subscription creation issue
    """
    print("\n=== RECOMMENDED FIXES ===")
    print()
    print("1. **Fix Interval Format**:")
    print("   - Change '1 d' to '1 day' in the interval abbreviation logic")
    print("   - File: verenigingen/utils/payment_services/mollie_payment_service.py")
    print("   - Line 204: Update interval abbreviation to use full words for days")
    print()
    print("2. **Add iDEAL Compatibility Check**:")
    print("   - iDEAL payments are typically one-time only")
    print("   - Consider warning users or suggesting alternative payment methods")
    print("   - Credit card or SEPA Direct Debit work better for subscriptions")
    print()
    print("3. **Add Retry Logic**:")
    print("   - Add manual retry functionality for failed subscription creations")
    print("   - Store first payment details for later subscription setup")
    print()
    print("4. **Improve Error Handling**:")
    print("   - Better logging when subscription creation fails")
    print("   - Store failed attempts for debugging")


if __name__ == "__main__":
    test_subscription_creation_with_1day_interval()
    suggest_fixes()
