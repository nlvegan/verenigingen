"""Debug list view permissions for Member DocType"""

import json

import frappe


@frappe.whitelist()
def check_workspace_restrictions():
    """Check if workspace is restricting Member access"""
    try:
        workspace = frappe.get_doc("Workspace", "Verenigingen")
        member_links = [link for link in workspace.links if link.link_to == "Member"]

        result = {"workspace_name": workspace.name, "workspace_public": workspace.public, "member_links": []}

        for link in member_links:
            result["member_links"].append(
                {
                    "link_type": link.link_type,
                    "label": link.label,
                    "only_for": link.only_for,
                    "hidden": link.hidden,
                }
            )

        return result
    except Exception as e:
        return {"error": str(e)}


def debug_member_list_permissions():
    """Debug why list view buttons are missing"""
    user = frappe.session.user

    result = {"user": user, "roles": frappe.get_roles(user), "tests": []}

    # Test 1: Check DocType permissions
    test1 = {"name": "DocType permissions"}
    meta = frappe.get_meta("Member")
    test1["permissions"] = meta.get_permissions()
    result["tests"].append(test1)

    # Test 2: Check has_permission for list operations
    test2 = {"name": "has_permission checks"}
    test2["create"] = frappe.has_permission("Member", "create")
    test2["delete"] = frappe.has_permission("Member", "delete")
    test2["read"] = frappe.has_permission("Member", "read")
    test2["write"] = frappe.has_permission("Member", "write")
    result["tests"].append(test2)

    # Test 3: Call custom permission function directly
    test3 = {"name": "Custom has_member_permission function"}
    try:
        from verenigingen.permissions import has_member_permission

        # With None (list view scenario)
        test3["with_none"] = has_member_permission(None, user, "create")

        # With a real member if one exists
        members = frappe.get_all("Member", limit=1)
        if members:
            test3["with_doc"] = has_member_permission(members[0].name, user, "read")
        else:
            test3["with_doc"] = "No members to test"

    except Exception as e:
        test3["error"] = str(e)
        import traceback

        test3["traceback"] = traceback.format_exc()

    result["tests"].append(test3)

    # Test 4: Check if list settings are hiding buttons
    test4 = {"name": "List View Settings"}
    list_settings = frappe.db.get_value("List View Settings", {"name": "Member-" + user}, "*", as_dict=True)
    test4["settings"] = list_settings
    result["tests"].append(test4)

    print(json.dumps(result, indent=2, default=str))
    return result
