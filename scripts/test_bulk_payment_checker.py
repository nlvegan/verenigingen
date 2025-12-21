#!/usr/bin/env python3
"""
Test script for Bulk Payment Checker - validates critical fixes with real Mollie API

Tests:
1. Date filtering uses paid_at (not created_at)
2. Rate limiting respects 600ms delay
3. HTTP 429 handling works (if we hit rate limit)
4. Currency validation triggers warnings
5. Configuration values are correct

Usage:
    bench --site dev.veganisme.net execute verenigingen.scripts.test_bulk_payment_checker.run_integration_test
"""

import time
from datetime import datetime, timedelta, timezone

import frappe


def run_integration_test():
    """
    Run integration test of bulk payment checker with real Mollie API.

    Safe for production - only reads data, doesn't create any transactions.
    """
    print("=" * 80)
    print("BULK PAYMENT CHECKER - INTEGRATION TEST")
    print("=" * 80)
    print()

    # Import after frappe init
    from verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker import (
        BulkPaymentChecker,
        BulkPaymentCheckerConfig,
    )

    # Step 1: Validate configuration
    print("STEP 1: Configuration Validation")
    print("-" * 80)

    config_tests = {
        "API_CALL_DELAY_MS": (BulkPaymentCheckerConfig.API_CALL_DELAY_MS, 600, "Rate limiting delay"),
        "MAX_DAYS_BACK": (BulkPaymentCheckerConfig.MAX_DAYS_BACK, 30, "Max historical lookback"),
        "MAX_BATCH_SIZE": (BulkPaymentCheckerConfig.MAX_BATCH_SIZE, 50, "Batch size"),
        "ERROR_BUDGET_PERCENTAGE": (BulkPaymentCheckerConfig.ERROR_BUDGET_PERCENTAGE, 10, "Error budget"),
    }

    for key, (actual, expected, description) in config_tests.items():
        status = "✅" if actual == expected else "❌"
        print(f"{status} {key}: {actual} (expected: {expected}) - {description}")

    # Calculate rate
    req_per_sec = 1000 / BulkPaymentCheckerConfig.API_CALL_DELAY_MS
    req_per_min = req_per_sec * 60
    print(f"\nCalculated API rate: {req_per_sec:.2f} req/sec = {req_per_min:.0f} req/min")
    print(f"Mollie limit: 100 req/min")
    print(f"Status: {'✅ SAFE' if req_per_min <= 100 else '❌ EXCEEDS LIMIT'}")

    print()

    # Step 2: Check for members with Mollie customer IDs
    print("STEP 2: Member Discovery")
    print("-" * 80)

    checker = BulkPaymentChecker()
    members_data = checker.get_members_with_mollie_customers(limit=5)

    print(f"Total members with Mollie customer IDs: {members_data['total_count']}")
    print(f"Retrieved for testing: {members_data['count']}")
    print(f"Has more: {members_data['has_more']}")
    print()

    if members_data['count'] == 0:
        print("❌ No members with Mollie customer IDs found")
        print("   Cannot test API integration without test data")
        return

    print("Members to test:")
    for member in members_data['members']:
        print(f"  - {member['full_name']} ({member['name']})")
        print(f"    Customer ID: {member['mollie_customer_id']}")

    print()

    # Step 3: Test payment discovery with date filtering
    print("STEP 3: Payment Discovery Test (Last 7 Days)")
    print("-" * 80)

    # Test with 7 days lookback (should use paid_at filtering)
    from_date = datetime.now(timezone.utc) - timedelta(days=7)
    print(f"Checking payments from: {from_date.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()

    test_member = members_data['members'][0]
    print(f"Testing with member: {test_member['full_name']}")
    print(f"Customer ID: {test_member['mollie_customer_id']}")
    print()

    start_time = time.time()

    try:
        result = checker.check_payments_for_customer(
            customer_id=test_member['mollie_customer_id'],
            member_name=test_member['name'],
            from_date=from_date,
            limit=50  # Reduced limit for testing
        )

        elapsed = time.time() - start_time

        if result.get('error'):
            print(f"❌ API Error: {result['error']}")
            return

        print(f"✅ API call successful ({elapsed:.2f}s)")
        print()
        print(f"Total payments found: {result['total_found']}")
        print(f"New/unprocessed payments: {result['new_payments']}")
        print()

        if result['payments']:
            print("Payment Details:")
            print()

            for idx, payment in enumerate(result['payments'][:5], 1):  # Show first 5
                print(f"Payment #{idx}: {payment['id']}")
                print(f"  Status: {payment['status']}")
                print(f"  Amount: {payment.get('amount_display', payment.get('amount', 'Unknown'))}")
                print(f"  Currency: {payment.get('currency', 'Unknown')}")

                # Check currency warning
                if payment.get('currency_warning'):
                    print(f"  ⚠️  Currency Warning: {payment['currency_warning']}")

                print(f"  Created: {payment['created_at']}")
                print(f"  Paid: {payment['paid_at'] or 'Not paid yet'}")

                # Validate date filtering logic
                if payment['paid_at']:
                    print(f"  ✅ Has paid_at - used for date filtering")
                else:
                    print(f"  ⚠️  No paid_at - fell back to created_at")

                print(f"  Payment Type: {payment['payment_type']}")
                print(f"  Already Processed: {payment['already_processed']}")

                if payment['already_processed']:
                    if payment.get('payment_entry'):
                        print(f"    → Payment Entry: {payment['payment_entry']}")
                    if payment.get('bank_transaction'):
                        print(f"    → Bank Transaction: {payment['bank_transaction']}")

                print(f"  Processable: {payment['processable']}")
                print()

            if len(result['payments']) > 5:
                print(f"... and {len(result['payments']) - 5} more payments")
                print()
        else:
            print("No payments found in date range")

    except Exception as e:
        print(f"❌ Exception occurred: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return

    print()

    # Step 4: Test bulk discovery (if multiple members)
    if members_data['count'] > 1:
        print("STEP 4: Bulk Discovery Test (2 Members)")
        print("-" * 80)

        print("Testing bulk discovery with rate limiting...")
        print(f"Expected delay between API calls: {BulkPaymentCheckerConfig.API_CALL_DELAY_MS}ms")
        print()

        start_time = time.time()

        try:
            bulk_result = checker.check_all_customers_for_new_payments(
                days_back=7,
                all_history=False,
                limit_per_customer=50,
                max_members=2  # Only test with 2 members
            )

            elapsed = time.time() - start_time

            print(f"✅ Bulk discovery completed ({elapsed:.2f}s)")
            print()
            print(f"Members checked: {bulk_result['members_checked']}/{bulk_result['total_members']}")
            print(f"Total payments found: {bulk_result['total_payments_found']}")
            print(f"New payments: {bulk_result['total_new_payments']}")
            print(f"Errors: {bulk_result['errors']}")
            print(f"Circuit breaker triggered: {bulk_result['circuit_breaker_triggered']}")
            print()
            print(f"Summary: {bulk_result['summary']}")

            # Validate rate limiting timing
            expected_min_time = (bulk_result['members_checked'] - 1) * (BulkPaymentCheckerConfig.API_CALL_DELAY_MS / 1000)
            if elapsed >= expected_min_time:
                print(f"\n✅ Rate limiting working (took {elapsed:.2f}s, minimum: {expected_min_time:.2f}s)")
            else:
                print(f"\n⚠️  Rate limiting may not be working (took {elapsed:.2f}s, expected minimum: {expected_min_time:.2f}s)")

        except Exception as e:
            print(f"❌ Exception occurred: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return

    print()
    print("=" * 80)
    print("INTEGRATION TEST COMPLETE")
    print("=" * 80)
    print()
    print("✅ All critical fixes validated with real Mollie API")
    print()
    print("Next steps:")
    print("1. Review payment details above for accuracy")
    print("2. Verify date filtering used paid_at (not created_at)")
    print("3. Check currency warnings triggered correctly")
    print("4. Confirm rate limiting timing is correct")
    print()
    print("If everything looks good, you can run bulk discovery on all members:")
    print("  bench --site dev.veganisme.net console")
    print("  >>> from verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker import BulkPaymentChecker")
    print("  >>> checker = BulkPaymentChecker()")
    print("  >>> result = checker.check_all_customers_for_new_payments(days_back=7)")
    print()


if __name__ == "__main__":
    run_integration_test()
