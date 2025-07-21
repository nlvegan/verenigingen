"""
Cleanup utility for orphaned Chapter Member records
"""

import frappe


@frappe.whitelist()
def cleanup_orphaned_chapter_members():
    """Clean up chapter member records pointing to non-existent members"""

    results = {
        "chapters_processed": 0,
        "orphaned_records_found": 0,
        "orphaned_records_cleaned": 0,
        "errors": [],
    }

    try:
        # Get all chapters
        chapters = frappe.get_all("Chapter", fields=["name"])

        for chapter_info in chapters:
            chapter_name = chapter_info["name"]
            results["chapters_processed"] += 1

            try:
                chapter_doc = frappe.get_doc("Chapter", chapter_name)

                # Find orphaned records
                members_to_remove = []
                for i, cm in enumerate(chapter_doc.members):
                    if cm.member and not frappe.db.exists("Member", cm.member):
                        members_to_remove.append((i, cm.member))
                        results["orphaned_records_found"] += 1

                if members_to_remove:
                    # Remove orphaned records in reverse order
                    for i, member_name in reversed(members_to_remove):
                        chapter_doc.remove(chapter_doc.members[i])
                        results["orphaned_records_cleaned"] += 1

                    # Save the chapter document
                    chapter_doc.flags.ignore_permissions = True
                    chapter_doc.save(ignore_permissions=True)

                    frappe.logger().info(
                        f"Cleaned {len(members_to_remove)} orphaned records from chapter {chapter_name}"
                    )

            except Exception as e:
                error_msg = f"Error processing chapter {chapter_name}: {str(e)}"
                results["errors"].append(error_msg)
                frappe.logger().error(error_msg)

        return results

    except Exception as e:
        results["errors"].append(f"General error: {str(e)}")
        return results


@frappe.whitelist()
def test_specific_chapter_cleanup(chapter_name):
    """Test cleanup for a specific chapter"""

    try:
        chapter_doc = frappe.get_doc("Chapter", chapter_name)

        result = {
            "chapter": chapter_name,
            "current_members": [],
            "orphaned_members": [],
            "cleanup_performed": False,
        }

        # Check all members
        for i, cm in enumerate(chapter_doc.members):
            member_info = {
                "index": i,
                "member_name": cm.member,
                "exists": bool(frappe.db.exists("Member", cm.member)) if cm.member else False,
                "status": cm.status,
            }
            result["current_members"].append(member_info)

            if cm.member and not frappe.db.exists("Member", cm.member):
                result["orphaned_members"].append(member_info)

        # Perform cleanup if orphaned records found
        if result["orphaned_members"]:
            members_to_remove = []
            for i, cm in enumerate(chapter_doc.members):
                if cm.member and not frappe.db.exists("Member", cm.member):
                    members_to_remove.append(i)

            # Remove in reverse order
            for i in reversed(members_to_remove):
                chapter_doc.remove(chapter_doc.members[i])

            # Save with elevated permissions
            chapter_doc.flags.ignore_permissions = True
            chapter_doc.save(ignore_permissions=True)

            result["cleanup_performed"] = True
            result["records_removed"] = len(members_to_remove)

        return result

    except Exception as e:
        return {"error": str(e), "error_type": str(type(e).__name__)}
