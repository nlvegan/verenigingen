"""
Test per-membership-type minimum period enforcement
"""

import frappe
from frappe.utils import add_months, getdate, today


@frappe.whitelist()
def test_per_type_minimum_period():
    """Test that minimum period enforcement works per membership type"""

    frappe.db.rollback()  # Start fresh

    print("=" * 60)
    print("PER-TYPE MINIMUM PERIOD ENFORCEMENT TEST")
    print("=" * 60)

    # Create test member
    member = frappe.get_doc(
        {
            "doctype": "Member",
            "email": "test_per_type@example.com",
            "first_name": "Test",
            "last_name": "PerType",
            "status": "Active"}
    )
    member.insert(ignore_permissions=True)
    print(f"\n✓ Created test member: {member.email}")

    # Create membership type WITH enforcement
    mt_enforced = frappe.get_doc(
        {
            "doctype": "Membership Type",
            "membership_type_name": "Test Monthly Enforced",
            "amount": 25.0,
            "currency": "EUR",
            "subscription_period": "Monthly",
            "is_active": 1,
            "enforce_minimum_period": 1,  # Enforcement enabled
        }
    )
    mt_enforced.insert(ignore_permissions=True)
    print(f"\n✓ Created membership type WITH enforcement: {mt_enforced.name}")

    # Create membership type WITHOUT enforcement
    mt_not_enforced = frappe.get_doc(
        {
            "doctype": "Membership Type",
            "membership_type_name": "Test Monthly Not Enforced",
            "amount": 25.0,
            "currency": "EUR",
            "subscription_period": "Monthly",
            "is_active": 1,
            "enforce_minimum_period": 0,  # Enforcement disabled
        }
    )
    mt_not_enforced.insert(ignore_permissions=True)
    print(f"✓ Created membership type WITHOUT enforcement: {mt_not_enforced.name}")

    # Test 1: Membership with enforcement
    print("\n" + "-" * 40)
    print("TEST 1: Monthly membership WITH enforcement")
    print("-" * 40)

    membership1 = frappe.get_doc(
        {
            "doctype": "Membership",
            "member": member.name,
            "membership_type": mt_enforced.name,
            "start_date": today()}
    )
    membership1.insert()

    days_to_renewal_1 = (getdate(membership1.renewal_date) - getdate(membership1.start_date)).days
    print(f"Renewal date: {membership1.renewal_date}")
    print(f"Days until renewal: {days_to_renewal_1}")
    print("Expected: ~365 days (1 year minimum enforced)")
    print(f"✓ Enforcement working: {'YES' if days_to_renewal_1 >= 365 else 'NO'}")

    # Test 2: Membership without enforcement
    print("\n" + "-" * 40)
    print("TEST 2: Monthly membership WITHOUT enforcement")
    print("-" * 40)

    # Create another member for second test
    member2 = frappe.get_doc(
        {
            "doctype": "Member",
            "email": "test_per_type2@example.com",
            "first_name": "Test2",
            "last_name": "PerType2",
            "status": "Active"}
    )
    member2.insert(ignore_permissions=True)

    membership2 = frappe.get_doc(
        {
            "doctype": "Membership",
            "member": member2.name,
            "membership_type": mt_not_enforced.name,
            "start_date": today()}
    )
    membership2.insert()

    days_to_renewal_2 = (getdate(membership2.renewal_date) - getdate(membership2.start_date)).days
    print(f"Renewal date: {membership2.renewal_date}")
    print(f"Days until renewal: {days_to_renewal_2}")
    print("Expected: Could be less than 365 days")
    print(f"✓ No enforcement working: {'YES' if days_to_renewal_2 < 365 else 'MAYBE (check implementation)'}")

    # Test 3: Cancellation behavior
    print("\n" + "-" * 40)
    print("TEST 3: Early cancellation behavior")
    print("-" * 40)

    # Submit both memberships
    membership1.submit()
    membership2.submit()

    # Try to cancel membership with enforcement early
    print("\nTrying to cancel enforced membership early...")
    try:
        membership1.cancellation_date = add_months(today(), 3)
        membership1.cancellation_reason = "Testing early cancellation"
        membership1.save()
        print("❌ Early cancellation should have failed but didn't!")
    except frappe.ValidationError as e:
        print("✓ Early cancellation blocked as expected")
        print(f"  Error: {str(e)}")

    # Try to cancel membership without enforcement early
    print("\nTrying to cancel non-enforced membership early...")
    try:
        membership2.cancellation_date = add_months(today(), 3)
        membership2.cancellation_reason = "Testing early cancellation"
        membership2.save()
        print("✓ Early cancellation allowed (no enforcement)")
    except frappe.ValidationError as e:
        print("❌ Early cancellation blocked unexpectedly")
        print(f"  Error: {str(e)}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("\nThe 'enforce_minimum_period' setting is now PER MEMBERSHIP TYPE:")
    print("- Each membership type can have its own enforcement setting")
    print("- When enabled: 1-year minimum period is enforced")
    print("- When disabled: Membership follows its natural period")
    print("\nTest Results:")
    print(f"- Per-type enforcement: {'WORKING' if days_to_renewal_1 != days_to_renewal_2 else 'NOT WORKING'}")
    print(f"- Enforced type gets 1 year: {'YES' if days_to_renewal_1 >= 365 else 'NO'}")

    # Cleanup
    print("\n" + "-" * 40)
    print("Cleaning up test data...")
    frappe.db.rollback()
    print("✓ Test data rolled back")


if __name__ == "__main__":
    frappe.connect(site="dev.veganisme.net")
    frappe.set_user("Administrator")

    try:
        test_per_type_minimum_period()
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.db.rollback()
