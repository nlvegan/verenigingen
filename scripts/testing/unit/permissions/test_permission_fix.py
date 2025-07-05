#!/usr/bin/env python3
"""
Test the fixed permission query
Run with: bench --site dev.veganisme.net execute verenigingen.test_permission_fix.test_parko_permissions
"""

import frappe


def test_parko_permissions():
    """Test Parko's permissions after the fix"""

    print("🧪 Testing Parko's chapter permissions...")

    try:
        # Test Parko's user
        parko_user = "parko@vrijwilligers.veganisme.org"

        # Import the fixed function
        from verenigingen.verenigingen.doctype.chapter.chapter import get_chapter_permission_query_conditions

        print(f"Testing permissions for user: {parko_user}")

        # Test the permission query
        result = get_chapter_permission_query_conditions(user=parko_user)
        print(f"Permission query result: {result}")

        # Test if he can access his member record
        member = frappe.db.get_value("Member", {"user": parko_user}, "name")
        print(f"Member record: {member}")

        # Test if he has a volunteer record
        if member:
            volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
            print(f"Volunteer record: {volunteer}")

            # Test board memberships
            if volunteer:
                board_memberships = frappe.get_all(
                    "Chapter Board Member",
                    filters={"volunteer": volunteer, "is_active": 1},
                    fields=["parent", "chapter_role"],
                )
                print(f"Board memberships: {board_memberships}")

        # Test chapter access
        chapters = frappe.get_all(
            "Chapter", filters=eval(result) if result and result != '""' else {}, fields=["name", "region"]
        )
        print(f"Accessible chapters: {chapters}")

        return {"success": True, "permission_query": result, "accessible_chapters": len(chapters)}

    except Exception as e:
        print(f"❌ Error testing permissions: {e}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e)}
