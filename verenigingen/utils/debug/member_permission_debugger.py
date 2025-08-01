import frappe
from frappe import _
from frappe.permissions import has_permission


@frappe.whitelist()
def debug_member_permissions():
    """Debug why Foppe can see some records but not his own"""

    foppe_email = "foppe@veganisme.org"

    # Set user context to Foppe
    frappe.set_user(foppe_email)

    result = {"current_user": frappe.session.user, "tests": []}

    # Test 1: Check Foppe's own record
    foppe_member = frappe.db.get_value("Member", {"user": foppe_email}, ["name", "owner"], as_dict=True)
    if foppe_member:
        # Check owner field
        test1 = {
            "test": "Own record access",
            "member_id": foppe_member.name,
            "member_owner_field": foppe_member.owner,
            "current_user": foppe_email,
            "owner_matches": foppe_member.owner == foppe_email,
        }

        # Test permissions
        try:
            perm_check = has_permission("Member", doc=foppe_member.name, user=foppe_email)
            test1["has_permission_result"] = perm_check

            # Try to actually get the doc
            doc = frappe.get_doc("Member", foppe_member.name)
            test1["can_fetch_doc"] = True
            test1["doc_owner"] = doc.owner
        except frappe.PermissionError as e:
            test1["can_fetch_doc"] = False
            test1["error"] = str(e)

        result["tests"].append(test1)

    # Test 2: Check other members Foppe can see
    other_members = ["Gerben Zonderland", "test Sipkes"]

    for member_name in other_members:
        member_data = frappe.db.get_value(
            "Member", {"full_name": member_name}, ["name", "owner", "user"], as_dict=True
        )
        if member_data:
            test = {
                "test": f"Other member: {member_name}",
                "member_id": member_data.name,
                "member_owner": member_data.owner,
                "member_user": member_data.user,
            }

            try:
                perm_check = has_permission("Member", doc=member_data.name, user=foppe_email)
                test["has_permission_result"] = perm_check

                doc = frappe.get_doc("Member", member_data.name)
                test["can_fetch_doc"] = True
                test["why_can_access"] = "Checking permission rules..."

                # Check if there's a shared permission
                shared = frappe.db.get_value(
                    "DocShare",
                    {"share_doctype": "Member", "share_name": member_data.name, "user": foppe_email},
                    ["read", "write"],
                    as_dict=True,
                )

                if shared:
                    test["has_docshare"] = True
                    test["share_permissions"] = shared
                else:
                    test["has_docshare"] = False

            except frappe.PermissionError as e:
                test["can_fetch_doc"] = False
                test["error"] = str(e)

            result["tests"].append(test)

    # Test 3: Check permission rules
    frappe.set_user("Administrator")  # Switch back to admin to check rules

    perm_rules = frappe.get_all(
        "DocPerm", filters={"parent": "Member", "role": "Verenigingen Member"}, fields=["*"]
    )

    result["permission_rules"] = perm_rules

    # Check if there are any global permissions allowing read
    global_perms = frappe.get_all(
        "DocPerm", filters={"parent": "Member", "read": 1, "if_owner": 0, "permlevel": 0}, fields=["role"]
    )

    result["roles_with_global_read"] = [p.role for p in global_perms]

    return result
