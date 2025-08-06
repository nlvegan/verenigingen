import frappe


@frappe.whitelist()
def debug_jantje_chapter_assignment():
    """Debug Jantje's chapter assignment"""
    member_name = "Assoc-Member-2025-06-0005"

    # Get member document
    member = frappe.get_doc("Member", member_name)

    # Check chapter memberships in Chapter Member table
    chapter_members = frappe.get_all(
        "Chapter Member",
        filters={"member": member_name, "enabled": 1},
        fields=["parent as chapter", "chapter_join_date", "enabled"],
        order_by="chapter_join_date desc",
    )

    # Check board memberships
    board_members = frappe.get_all(
        "Verenigingen Chapter Board Member",
        filters={"member": member_name, "is_active": 1},
        fields=["parent as chapter", "chapter_role", "is_active"],
    )

    # Check current chapter display
    current_chapter_display = getattr(member, "current_chapter_display", "Not set")

    # Get optimized chapters
    try:
        optimized_chapters = member.get_current_chapters_optimized()
    except Exception as e:
        optimized_chapters = f"Error: {str(e)}"

    return {
        "member_name": member.full_name,
        "member_id": member_name,
        "chapter_members": chapter_members,
        "board_members": board_members,
        "current_chapter_display": current_chapter_display,
        "optimized_chapters": optimized_chapters,
        "chapter_management_enabled": frappe.db.get_single_value(
            "Verenigingen Settings", "enable_chapter_management"
        ),
    }


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    result = debug_jantje_chapter_assignment()
    print(result)
