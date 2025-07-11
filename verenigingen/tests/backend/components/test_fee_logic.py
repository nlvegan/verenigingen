#!/usr/bin/env python3
"""
Test script to verify the fee override logic works correctly for:
1. New member applications with custom amounts
2. Existing member fee adjustments
"""


import frappe
from frappe.utils import random_string

from verenigingen.tests.test_utils import mock_email_sending
from verenigingen.tests.test_utils import setup_test_environment as setup_test_env


def setup_test_environment():
    """Setup test environment"""
    setup_test_env()  # This sets up common test environment including email mocking
    print("🔧 Setting up test environment...")

    # Ensure we have a membership type
    if not frappe.db.exists("Membership Type", "Standard"):
        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Standard",
                "name": "Standard",
                "amount": 50.0,
                "currency": "EUR",
                "subscription_period": "year",
                "is_active": 1,
                "description": "Standard membership for testing",
            }
        )
        membership_type.insert(ignore_permissions=True)
        # Create subscription plan for the membership type
        membership_type.create_subscription_plan()
        print("✅ Created test membership type")
    else:
        print("✅ Test membership type exists")


def test_new_application_with_custom_amount():
    """Test 1: New member application with custom contribution amount"""
    print("\n🧪 TEST 1: New Member Application with Custom Amount")
    print("=" * 60)

    with mock_email_sending() as email_queue:
        try:
            # Create application data similar to what the form would send
            application_data = {
                "first_name": "Test",
                "last_name": "Member" + random_string(4),
                "email": f"test.member.{random_string(6)}@example.com",
                "contact_number": "+31612345678",
                "birth_date": "1990-01-01",
                "address_line1": "Test Street 123",
                "city": "Amsterdam",
                "postal_code": "1012AB",
                "country": "Netherlands",
                "selected_membership_type": "Standard",
                "membership_amount": 75.0,  # Custom amount higher than standard (50)
                "uses_custom_amount": True,
                "custom_amount_reason": "Supporter contribution",
                "payment_method": "SEPA Direct Debit",
                "terms": True,
            }

            print(f"📝 Creating member with custom amount: €{application_data['membership_amount']}")

            # Import and use the application helper
            from verenigingen.utils.application_helpers import (
                create_member_from_application,
                generate_application_id,
            )

            # Generate application ID
            app_id = generate_application_id()
            print(f"📋 Application ID: {app_id}")

            # Create member from application data
            member = create_member_from_application(application_data, app_id)
            print(f"✅ Member created: {member.name}")
            print(f"   - Full name: {member.full_name}")
            print(f"   - Email: {member.email}")
            print(f"   - Fee override: €{member.membership_fee_override}")
            print(f"   - Fee reason: {member.fee_override_reason}")
            print(f"   - Status: {member.status}")
            print(f"   - Application status: {member.application_status}")

            # Verify no pending fee change was created (this was the bug)
            if hasattr(member, "_pending_fee_change"):
                print("❌ ERROR: _pending_fee_change should not be set for new applications!")
                return False
            else:
                print("✅ Correctly skipped fee change tracking for new application")

            # Check that fee override fields are properly set
            if member.membership_fee_override == 75.0:
                print("✅ Custom fee amount set correctly")
            else:
                print(f"❌ Fee amount wrong: expected 75.0, got {member.membership_fee_override}")
                return False

            if member.fee_override_reason:
                print(f"✅ Fee override reason set: {member.fee_override_reason}")
            else:
                print("❌ Fee override reason missing")
                return False

            print("✅ TEST 1 PASSED: New application with custom amount works correctly")

            # Check that notification email was captured but not sent
            emails = email_queue.get_sent_emails(subject_contains="New Membership Application")
            print(f"📧 Captured {len(emails)} notification emails (not sent)")

            return True

        except Exception as e:
            print(f"❌ TEST 1 FAILED: {str(e)}")
            frappe.log_error(f"Test 1 failed: {str(e)}", "Fee Logic Test Error")
            return False


def test_existing_member_fee_adjustment():
    """Test 2: Existing member fee adjustment"""
    print("\n🧪 TEST 2: Existing Member Fee Adjustment")
    print("=" * 50)

    with mock_email_sending() as email_queue:
        try:
            # First create a regular member
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": "Existing",
                    "last_name": "Member" + random_string(4),
                    "email": f"existing.member.{random_string(6)}@example.com",
                    "birth_date": "1985-06-15",
                    "status": "Active",
                }
            )
            member.insert(ignore_permissions=True)
            print(f"✅ Created existing member: {member.name} ({member.full_name})")

            # Now adjust their fee (this should trigger change tracking)
            print("📝 Adjusting fee from standard to €125.0")
            member.membership_fee_override = 125.0
            member.fee_override_reason = "Premium supporter upgrade"

            # Save the member (this should trigger fee change tracking)
            member.save(ignore_permissions=True)
            print("✅ Fee adjustment saved")

            # Check if change tracking was triggered correctly
            if hasattr(member, "_pending_fee_change"):
                pending_change = member._pending_fee_change
                print("✅ Fee change tracking was triggered correctly")
                print(f"   - Old amount: {pending_change.get('old_amount')}")
                print(f"   - New amount: {pending_change.get('new_amount')}")
                print(f"   - Reason: {pending_change.get('reason')}")
                print(f"   - Changed by: {pending_change.get('changed_by')}")

                # Verify the change data
                if pending_change.get("new_amount") == 125.0:
                    print("✅ New amount tracked correctly")
                else:
                    print(f"❌ Wrong new amount: expected 125.0, got {pending_change.get('new_amount')}")
                    return False
            else:
                print("❌ ERROR: Fee change tracking should have been triggered!")
                return False

            # Check current member state
            print(f"✅ Member fee override: €{member.membership_fee_override}")
            print(f"✅ Member fee reason: {member.fee_override_reason}")

            print("✅ TEST 2 PASSED: Existing member fee adjustment works correctly")
            return True

        except Exception as e:
            print(f"❌ TEST 2 FAILED: {str(e)}")
            frappe.log_error(f"Test 2 failed: {str(e)}", "Fee Logic Test Error")
            return False


def test_api_submission():
    """Test 3: API submission like the actual form would do"""
    print("\n🧪 TEST 3: API Submission (like real form)")
    print("=" * 45)

    try:
        # Test data that mimics what the form JavaScript would send
        form_data = {
            "first_name": "API",
            "last_name": "Test" + random_string(4),
            "email": f"api.test.{random_string(6)}@example.com",
            "contact_number": "+31687654321",
            "birth_date": "1992-03-15",
            "address_line1": "API Test Lane 456",
            "city": "Rotterdam",
            "postal_code": "3012KL",
            "country": "Netherlands",
            "selected_membership_type": "Standard",
            "membership_amount": 35.0,  # Reduced fee (student rate)
            "uses_custom_amount": True,
            "custom_amount_reason": "Student discount",
            "payment_method": "Bank Transfer",
            "iban": "NL91ABNA0417164300",
            "bic": "ABNANL2A",
            "bank_account_name": "API Test User",
            "terms": True,
            "newsletter": True,
        }

        print(f"📝 Submitting via API with custom amount: €{form_data['membership_amount']}")

        # Call the API method that the form uses
        result = frappe.call(
            "verenigingen.api.membership_application.submit_membership_application", data=form_data
        )

        if result and result.get("success"):
            print("✅ API submission successful")
            print(f"   - Application ID: {result.get('application_id')}")
            print(f"   - Member ID: {result.get('member_id')}")
            print(f"   - Message: {result.get('message', 'No message')}")

            # Verify the created member
            member_id = result.get("member_id")
            if member_id:
                member = frappe.get_doc("Member", member_id)
                print(f"✅ Created member verified: {member.full_name}")
                print(f"   - Fee override: €{member.membership_fee_override}")
                print(f"   - Status: {member.application_status}")

                # Check no pending fee change for new application
                if hasattr(member, "_pending_fee_change"):
                    print("❌ ERROR: API submission should not create pending fee change!")
                    return False
                else:
                    print("✅ No pending fee change (correct for new application)")

            print("✅ TEST 3 PASSED: API submission works correctly")
            return True
        else:
            print(f"❌ API submission failed: {result}")
            return False

    except Exception as e:
        print(f"❌ TEST 3 FAILED: {str(e)}")
        frappe.log_error(f"Test 3 failed: {str(e)}", "Fee Logic Test Error")
        return False


def run_all_tests():
    """Run all tests and report results"""
    print("🚀 STARTING FEE LOGIC COMPREHENSIVE TESTS")
    print("=" * 60)

    # Setup
    setup_test_environment()

    # Run tests
    results = []
    results.append(("New Application with Custom Amount", test_new_application_with_custom_amount()))
    results.append(("Existing Member Fee Adjustment", test_existing_member_fee_adjustment()))
    results.append(("API Submission Test", test_api_submission()))

    # Report results
    print("\n" + "=" * 60)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 60)

    passed = 0
    total = len(results)

    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status} {test_name}")
        if result:
            passed += 1

    print(f"\n🎯 OVERALL RESULT: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 ALL TESTS PASSED! Fee logic is working correctly.")
        return True
    else:
        print("⚠️  SOME TESTS FAILED! Check the output above for details.")
        return False


if __name__ == "__main__":
    try:
        success = run_all_tests()
        exit(0 if success else 1)
    except Exception as e:
        print(f"💥 FATAL ERROR: {str(e)}")
        frappe.log_error(f"Fatal test error: {str(e)}", "Fee Logic Test Fatal")
        exit(1)
