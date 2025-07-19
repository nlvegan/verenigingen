#!/usr/bin/env python3
"""
Test script to verify the complete membership application submission process
"""

import frappe
from frappe.utils import random_string

from verenigingen.tests.test_utils import mock_email_sending, setup_test_environment


def test_application_submission():
    """Test complete application submission"""
    print("🧪 Testing complete application submission process...")

    # Set up test environment with email mocking
    setup_test_environment()

    with mock_email_sending() as email_queue:
        # Create test data that mimics form submission
        form_data = {
            "first_name": "TestApp",
            "last_name": "User" + random_string(4),
            "email": f"testapp.user.{random_string(6)}@example.com",
            "contact_number": "+31612345678",
            "birth_date": "1990-05-15",
            "address_line1": "Test Application Street 123",
            "city": "Amsterdam",
            "postal_code": "1012AB",
            "country": "Netherlands",
            "selected_membership_type": "Standard",
            "membership_amount": 65.0,  # Custom amount
            "uses_custom_amount": True,
            "custom_amount_reason": "Supporter contribution",
            "payment_method": "SEPA Direct Debit",
            "iban": "NL91ABNA0417164300",
            "bic": "ABNANL2A",
            "bank_account_name": "Test Application User",
            "terms": True,
            "newsletter": True,
        }

        print(f"📝 Submitting application for: {form_data['first_name']} {form_data['last_name']}")
        print(f"   Email: {form_data['email']}")
        print(f"   Custom amount: €{form_data['membership_amount']}")

        try:
            # Call the API method that handles form submissions
            result = frappe.call(
                "verenigingen.api.membership_application.submit_membership_application", data=form_data
            )

            if result and result.get("success"):
                print("✅ Application submission successful!")
                print(f"   Application ID: {result.get('application_id')}")
                print(f"   Member ID: {result.get('member_id')}")
                print(f"   Message: {result.get('message', 'No message')}")

                # Verify the created member
                member_id = result.get("member_id")
                if member_id:
                    member = frappe.get_doc("Member", member_id)
                    print("✅ Member created successfully:")
                    print(f"   Name: {member.full_name}")
                    print(f"   Email: {member.email}")
                    print(f"   Fee override: €{member.dues_rate}")
                    print(f"   Fee reason: {member.fee_override_reason}")
                    print(f"   Status: {member.application_status}")

                    # Most importantly - check that NO _pending_fee_change was created
                    if hasattr(member, "_pending_fee_change"):
                        print("❌ ERROR: New application should not create _pending_fee_change!")
                        return False
                    else:
                        print("✅ Correctly skipped fee change tracking for new application")

                    # Verify all fields are set correctly
                    assert (
                        member.dues_rate == 65.0
                    ), f"Fee override wrong: {member.dues_rate}"
                    assert member.fee_override_reason, f"Fee reason missing: {member.fee_override_reason}"
                    assert (
                        member.application_status == "Pending"
                    ), f"Status wrong: {member.application_status}"

                    print("✅ All member fields verified correctly")

                    # Check that notification emails were captured but not sent
                    emails = email_queue.get_sent_emails(subject_contains="New Membership Application")
                    print(f"📧 Captured {len(emails)} notification emails (not sent)")

                    return True
                else:
                    print("❌ No member ID returned")
                    return False
            else:
                print(f"❌ Application submission failed: {result}")
                return False

        except Exception as e:
            print(f"❌ Application submission error: {str(e)}")
            import traceback

            traceback.print_exc()
            return False


def test_backend_fee_adjustment():
    """Test backend fee adjustment for existing member"""
    print("\n🧪 Testing backend fee adjustment for existing member...")

    with mock_email_sending() as email_queue:
        # Create an existing member first
        existing_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Backend",
                "last_name": "TestMember" + random_string(4),
                "email": f"backend.test.{random_string(6)}@example.com",
                "birth_date": "1985-03-10",
                "status": "Active",
                "application_status": "Active",
            }
        )
        existing_member.insert(ignore_permissions=True)

        print(f"✅ Created existing member: {existing_member.name} ({existing_member.full_name})")
        print(f"   Initial fee override: {existing_member.dues_rate}")

        # Now adjust their fee (this should trigger change tracking)
        print("📝 Adjusting fee from None to €150.0...")
        existing_member.dues_rate = 150.0
        existing_member.fee_override_reason = "Backend adjustment - Premium supporter"
        existing_member.save(ignore_permissions=True)

        # Check if change tracking was triggered
        if hasattr(existing_member, "_pending_fee_change"):
            print("✅ Backend fee adjustment correctly triggered change tracking")
            pending = existing_member._pending_fee_change
            print(f"   Old amount: {pending.get('old_amount')}")
            print(f"   New amount: {pending.get('new_amount')}")
            print(f"   Reason: {pending.get('reason')}")

            # Verify the change data
            assert pending.get("new_amount") == 150.0, f"New amount wrong: {pending.get('new_amount')}"
            assert (
                pending.get("old_amount") is None
            ), f"Old amount should be None: {pending.get('old_amount')}"

            print("✅ Backend fee adjustment working correctly")
            return True
        else:
            print("❌ Backend fee adjustment did not trigger change tracking!")
            return False


if __name__ == "__main__":
    # Connect to Frappe
    import frappe

    frappe.connect()

    print("=" * 70)
    print("🚀 MEMBERSHIP APPLICATION FEE OVERRIDE TEST SUITE")
    print("=" * 70)

    # Run tests
    test1_result = test_application_submission()
    test2_result = test_backend_fee_adjustment()

    # Summary
    print("\n" + "=" * 50)
    print("📊 TEST SUMMARY:")
    print(f"   Application submission test: {'✅ PASSED' if test1_result else '❌ FAILED'}")
    print(f"   Backend fee adjustment test: {'✅ PASSED' if test2_result else '❌ FAILED'}")
    print("=" * 50)

    # Clean up test data
    print("\n🧹 Cleaning up test data...")
    frappe.db.rollback()
