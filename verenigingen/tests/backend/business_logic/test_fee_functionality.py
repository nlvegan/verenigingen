import frappe
from frappe.utils import random_string


def test_new_member_fee_logic():
    """Test that new members with custom fees don't trigger change tracking"""
    print("🧪 Testing new member fee logic...")

    # Create a new member with custom fee
    member = frappe.get_doc(
        {
            "doctype": "Member",
            "first_name": "Test",
            "last_name": "NewMember" + random_string(4),
            "email": f"test.new.{random_string(6)}@example.com",
            "birth_date": "1990-01-01",
            "dues_rate": 75.0,
            "fee_override_reason": "Custom contribution during application",
            "status": "Pending",
            "application_status": "Pending",
        }
    )

    # Insert (this will trigger validation including handle_fee_override_changes)
    member.insert(ignore_permissions=True)

    # Check results
    if hasattr(member, "_pending_fee_change"):
        print("❌ ERROR: New member should not have _pending_fee_change!")
        print(f"   Member: {member.name}")
        print(f"   Pending change: {member._pending_fee_change}")
        return False
    else:
        print("✅ New member correctly skips fee change tracking")
        print(f"   Member: {member.name}")
        print(f"   Fee override: €{member.dues_rate}")
        return True


def test_existing_member_fee_change():
    """Test that existing members with fee changes do trigger tracking"""
    print("\n🧪 Testing existing member fee change...")

    # First create a member without fee override
    member = frappe.get_doc(
        {
            "doctype": "Member",
            "first_name": "Test",
            "last_name": "ExistingMember" + random_string(4),
            "email": f"test.existing.{random_string(6)}@example.com",
            "birth_date": "1985-01-01",
            "status": "Active",
        }
    )
    member.insert(ignore_permissions=True)
    print(f"✅ Created existing member: {member.name}")

    # Now update their fee (this should trigger change tracking)
    member.dues_rate = 125.0
    member.fee_override_reason = "Premium supporter upgrade"
    member.save(ignore_permissions=True)

    # Check if change tracking was triggered
    if hasattr(member, "_pending_fee_change"):
        print("✅ Existing member correctly triggers fee change tracking")
        pending = member._pending_fee_change
        print(f"   Old amount: {pending.get('old_amount')}")
        print(f"   New amount: {pending.get('new_amount')}")
        print(f"   Reason: {pending.get('reason')}")
        return True
    else:
        print("❌ ERROR: Existing member should have _pending_fee_change!")
        return False


def run_fee_tests():
    """Run all fee logic tests"""
    frappe.set_user("Administrator")

    print("🚀 Starting fee logic tests...")
    print("=" * 50)

    test1_result = test_new_member_fee_logic()
    test2_result = test_existing_member_fee_change()

    print("\n" + "=" * 50)
    print("📊 TEST RESULTS:")
    print(f"   New member test: {'✅ PASSED' if test1_result else '❌ FAILED'}")
    print(f"   Existing member test: {'✅ PASSED' if test2_result else '❌ FAILED'}")

    if test1_result and test2_result:
        print("🎉 ALL TESTS PASSED! Fee logic is working correctly.")
        return True
    else:
        print("⚠️ SOME TESTS FAILED!")
        return False
