"""
Quick test to verify fee override permission system
"""

import frappe

# Test fee override permissions
print("Testing Fee Override Permission System...")

# Find existing member to test with
members = frappe.get_all("Member", filters={"status": "Active"}, limit=1)
if not members:
    print("No active members found for testing")
else:
    member_name = members[0].name
    print(f"Testing with member: {member_name}")

    try:
        # Test as Administrator
        member_doc = frappe.get_doc("Member", member_name)
        print(f"Current fee override: {member_doc.membership_fee_override}")
        print(f"Override set by: {member_doc.fee_override_by}")

        # Try to set a new fee override
        member_doc.membership_fee_override = 35.00
        member_doc.fee_override_reason = "Testing permission system"
        member_doc.save()

        # Reload and check
        member_doc.reload()
        print(f"New fee override: {member_doc.membership_fee_override}")
        print(f"Override set by: {member_doc.fee_override_by}")
        print(f"Current user: {frappe.session.user}")

        if member_doc.fee_override_by == frappe.session.user:
            print("✅ Override Set By correctly shows current user")
        else:
            print(
                f"❌ Override Set By issue: shows {member_doc.fee_override_by}, expected {frappe.session.user}"
            )

    except Exception as e:
        print(f"Error during test: {e}")
        import traceback

        traceback.print_exc()
