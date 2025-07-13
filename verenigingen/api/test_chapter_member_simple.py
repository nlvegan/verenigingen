"""Simple test for chapter member functionality"""

import frappe


@frappe.whitelist()
def test_chapter_member_simple():
    """Test simple chapter member addition"""
    try:
        # Create test member
        test_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "SimpleTest",
                "last_name": "Member",
                "email": f"simpletest_member@test.invalid",
                "birth_date": "1990-01-01",
                "status": "Active",
            }
        )
        test_member.insert()

        # Get an existing chapter
        chapters = frappe.get_all("Chapter", limit=1)
        if not chapters:
            return {"error": "No chapters found for testing"}

        chapter = frappe.get_doc("Chapter", chapters[0].name)

        # Try to add member
        result = chapter.add_member(test_member.name)

        # Clean up
        frappe.delete_doc("Member", test_member.name, force=True)

        return {"success": True, "result": result, "chapter": chapter.name, "member": test_member.name}

    except Exception as e:
        # Clean up on error
        try:
            if "test_member" in locals():
                frappe.delete_doc("Member", test_member.name, force=True)
        except:
            pass

        import traceback

        return {"error": str(e), "traceback": traceback.format_exc()}
