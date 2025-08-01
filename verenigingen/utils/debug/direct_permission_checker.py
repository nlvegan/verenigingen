import frappe
from frappe import _

from verenigingen.permissions import has_member_permission


@frappe.whitelist()
def test_direct_permission_check(user_email=None, member_names=None):
    """Test the permission function directly for any user and members

    Args:
        user_email: Email of user to test permissions for (default: current user)
        member_names: List of member names to test (default: gets sample members)
    """

    if not user_email:
        user_email = frappe.session.user

    results = {"user": user_email, "tests": []}

    # Get test members if not provided
    if not member_names:
        # Get a mix of members - some owned by user, some not
        user_owned_members = frappe.get_all(
            "Member", filters={"owner": user_email}, fields=["name", "first_name", "last_name"], limit=3
        )

        other_members = frappe.get_all(
            "Member",
            filters={"owner": ["!=", user_email]},
            fields=["name", "first_name", "last_name"],
            limit=3,
        )

        test_cases = []
        for member in user_owned_members:
            test_cases.append(
                {
                    "name": member.name,
                    "expected": True,
                    "description": f"User-owned: {member.first_name} {member.last_name or ''}",
                }
            )

        for member in other_members:
            test_cases.append(
                {
                    "name": member.name,
                    "expected": False,  # Assume no access to others unless special permissions
                    "description": f"Other user: {member.first_name} {member.last_name or ''}",
                }
            )
    else:
        # Use provided member names
        test_cases = []
        for name in member_names:
            if frappe.db.exists("Member", name):
                member = frappe.get_doc("Member", name)
                test_cases.append(
                    {"name": name, "expected": member.owner == user_email, "description": f"Member {name}"}
                )

    for test in test_cases:
        try:
            # Get the document
            doc = frappe.get_doc("Member", test["name"])

            # Test permission function directly
            has_perm = has_member_permission(doc, user=user_email, permission_type="read")

            results["tests"].append(
                {
                    "member": test["name"],
                    "description": test["description"],
                    "owner": doc.owner,
                    "expected_access": test["expected"],
                    "actual_access": has_perm,
                    "correct": has_perm == test["expected"],
                }
            )
        except Exception as e:
            results["tests"].append(
                {"member": test["name"], "description": test["description"], "error": str(e)}
            )

    return results


@frappe.whitelist()
def test_user_permissions_summary(user_email=None):
    """Get a summary of what a user can access

    Args:
        user_email: Email of user to test (default: current user)
    """
    if not user_email:
        user_email = frappe.session.user

    # Test permission check
    permission_test = test_direct_permission_check(user_email)

    # Get user roles
    user_roles = frappe.get_all("Has Role", filters={"parent": user_email}, fields=["role"])
    roles = [r.role for r in user_roles]

    # Count accessible members
    accessible_count = sum(1 for test in permission_test["tests"] if test.get("actual_access"))
    total_tested = len(permission_test["tests"])

    return {
        "user": user_email,
        "roles": roles,
        "permission_summary": {
            "accessible_members": accessible_count,
            "total_tested": total_tested,
            "access_rate": f"{accessible_count}/{total_tested}",
        },
        "detailed_tests": permission_test["tests"],
    }
