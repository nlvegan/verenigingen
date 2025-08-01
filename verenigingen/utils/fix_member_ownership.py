import frappe
from frappe import _


@frappe.whitelist()
def fix_member_ownership():
    """Fix member ownership so members own their own records"""

    fixes = []

    # Fix Foppe's record - he should own his own record
    foppe_email = "foppe@veganisme.org"
    foppe_member = frappe.db.get_value("Member", {"user": foppe_email}, "name")

    if foppe_member:
        # Set Foppe as owner of his own record
        frappe.db.set_value("Member", foppe_member, "owner", foppe_email)
        fixes.append(f"Fixed: {foppe_member} owner set to {foppe_email}")

    # Fix other members - they should NOT be owned by Foppe
    wrong_owner_members = frappe.db.get_all(
        "Member",
        filters={"owner": foppe_email, "user": ["!=", foppe_email]},
        fields=["name", "user", "full_name"],
    )

    for member in wrong_owner_members:
        # Set owner to the linked user if exists, otherwise Administrator
        new_owner = member.user if member.user else "Administrator"
        frappe.db.set_value("Member", member.name, "owner", new_owner)
        fixes.append(
            f"Fixed: {member.name} ({member.full_name}) owner changed from {foppe_email} to {new_owner}"
        )

    # Commit changes
    frappe.db.commit()

    # Verify the fix
    verification = []

    # Check Foppe's record
    foppe_check = frappe.db.get_value("Member", {"user": foppe_email}, ["name", "owner"], as_dict=True)
    if foppe_check:
        verification.append(
            {
                "member": foppe_check.name,
                "owner": foppe_check.owner,
                "correct": foppe_check.owner == foppe_email,
            }
        )

    # Check previously wrong records
    for member in wrong_owner_members:
        check = frappe.db.get_value("Member", member.name, ["name", "owner", "user"], as_dict=True)
        verification.append(
            {
                "member": check.name,
                "owner": check.owner,
                "user": check.user,
                "correct": check.owner != foppe_email,
            }
        )

    return {"fixes_applied": fixes, "verification": verification, "total_fixed": len(fixes)}
