import frappe
from frappe import _
from frappe.permissions import has_permission


@frappe.whitelist()
def check_specific_member_access():
    """Check why Foppe can access specific members"""

    foppe_email = "foppe@veganisme.org"
    frappe.set_user(foppe_email)

    # Clear cache
    frappe.clear_cache(user=foppe_email)

    results = {"user": foppe_email, "checks": []}

    # Check specific members
    test_members = [
        {"name": "Gerben Zonderland", "id": "Assoc-Member-2025-07-4218"},
        {"name": "test Sipkes", "id": "Assoc-Member-2025-07-4062"},
    ]

    for member_info in test_members:
        check = {"member": member_info["name"], "member_id": member_info["id"]}

        # Check DocShare
        docshare = frappe.db.get_value(
            "DocShare",
            {"share_doctype": "Member", "share_name": member_info["id"], "user": foppe_email},
            ["read", "write", "share", "everyone"],
            as_dict=True,
        )

        check["has_docshare"] = bool(docshare)
        if docshare:
            check["docshare_details"] = docshare

        # Check if member is in same chapter
        foppe_chapters = frappe.db.sql(
            """
            SELECT parent FROM `tabChapter Member`
            WHERE member = %s
        """,
            ("Assoc-Member-2025-07-0030",),
            as_dict=True,
        )

        member_chapters = frappe.db.sql(
            """
            SELECT parent FROM `tabChapter Member`
            WHERE member = %s
        """,
            (member_info["id"],),
            as_dict=True,
        )

        check["foppe_chapters"] = [c.parent for c in foppe_chapters]
        check["member_chapters"] = [c.parent for c in member_chapters]
        check["shared_chapters"] = list(set(check["foppe_chapters"]) & set(check["member_chapters"]))

        # Check team memberships
        foppe_teams = frappe.db.sql(
            """
            SELECT t.parent FROM `tabTeam Member` t
            JOIN `tabVolunteer` v ON t.volunteer = v.name
            WHERE v.member = %s
        """,
            ("Assoc-Member-2025-07-0030",),
            as_dict=True,
        )

        member_teams = frappe.db.sql(
            """
            SELECT t.parent FROM `tabTeam Member` t
            JOIN `tabVolunteer` v ON t.volunteer = v.name
            WHERE v.member = %s
        """,
            (member_info["id"],),
            as_dict=True,
        )

        check["foppe_teams"] = [t.parent for t in foppe_teams]
        check["member_teams"] = [t.parent for t in member_teams]
        check["shared_teams"] = list(set(check["foppe_teams"]) & set(check["member_teams"]))

        # Check if there's any special relationship
        check["member_details"] = frappe.db.get_value(
            "Member", member_info["id"], ["owner", "modified_by", "creation"], as_dict=True
        )

        results["checks"].append(check)

    return results
