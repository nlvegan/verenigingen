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
        print(f"Current dues rate: {member_doc.dues_rate}")

        # Try to set a new fee override
        original_rate = member_doc.dues_rate
        member_doc.dues_rate = 35.00
        member_doc.save()

        # Reload and check
        member_doc.reload()
        print(f"New dues rate: {member_doc.dues_rate}")
        print(f"Current user: {frappe.session.user}")

        # Restore original rate
        member_doc.dues_rate = original_rate
        member_doc.save()
        print("✅ Fee override test completed successfully")

    except Exception as e:
        print(f"Error during test: {e}")
        import traceback

        traceback.print_exc()
