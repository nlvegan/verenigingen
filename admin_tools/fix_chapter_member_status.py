"""
Fix Chapter Member Status Migration Tool

This script fixes Chapter Member records where the member's status is Terminated, Deceased,
or Suspended but they are still marked as enabled=1 in the Chapter Member child table.

This issue occurred because the mijnrood CSV import was not properly setting enabled=0
and status='Inactive' for non-Active members when assigning them to chapters.

The underlying code issue has been fixed in member_manager.py, but this tool corrects
existing mismatched data.

Usage:
    # Dry run (safe - shows what would be changed)
    bench --site [sitename] console
    >>> from admin_tools.fix_chapter_member_status import fix_all_chapters
    >>> fix_all_chapters(dry_run=True)

    # Apply fixes
    >>> fix_all_chapters(dry_run=False)

    # Fix specific chapter
    >>> from admin_tools.fix_chapter_member_status import fix_specific_chapter
    >>> fix_specific_chapter('Utrecht', dry_run=True)
    >>> fix_specific_chapter('Utrecht', dry_run=False)

Or via command line:
    # Dry run all chapters
    bench --site [sitename] console < admin_tools/fix_chapter_member_status_dryrun.py

    # Apply fixes
    bench --site [sitename] console < admin_tools/fix_chapter_member_status_apply.py
"""

import frappe
from frappe.utils import now


def fix_all_chapters(dry_run=True):
    """
    Fix all Chapter Member records where member status doesn't match chapter enabled/status

    Args:
        dry_run: If True, only report what would be changed without making changes

    Returns:
        Dict with operation results
    """
    # Find all Chapter Member records where member is not Active but chapter member is enabled
    mismatched_records = frappe.db.sql(
        """
        SELECT
            cm.name as chapter_member_name,
            cm.parent as chapter_name,
            cm.member as member_id,
            m.full_name as member_name,
            m.status as member_status,
            cm.enabled as chapter_enabled,
            cm.status as chapter_status
        FROM `tabChapter Member` cm
        INNER JOIN `tabMember` m ON m.name = cm.member
        WHERE m.status != 'Active'
        AND cm.enabled = 1
        ORDER BY cm.parent, m.full_name
    """,
        as_dict=True,
    )

    if not mismatched_records:
        print("✓ No mismatched records found - all Chapter Member statuses are correct")
        return {"success": True, "dry_run": dry_run, "total_found": 0}

    # Group by chapter for reporting
    by_chapter = {}
    for record in mismatched_records:
        chapter = record["chapter_name"]
        if chapter not in by_chapter:
            by_chapter[chapter] = []
        by_chapter[chapter].append(record)

    # Report findings
    print(f"\n{'=' * 80}")
    print(f"Found {len(mismatched_records)} Chapter Member records with status mismatches")
    print(f"Affected chapters: {len(by_chapter)}")
    print(f"{'=' * 80}\n")

    for chapter_name, records in by_chapter.items():
        print(f"\n{chapter_name}: {len(records)} members")
        print(f"{'-' * 80}")
        for record in records[:10]:  # Show first 10 per chapter
            print(
                f"  • {record['member_name'][:40]:40} | Member status: {record['member_status']:12} | "
                f"Chapter enabled: {record['chapter_enabled']} | Chapter status: {record['chapter_status']}"
            )
        if len(records) > 10:
            print(f"  ... and {len(records) - 10} more")

    if dry_run:
        print(f"\n{'=' * 80}")
        print("DRY RUN MODE - No changes were made")
        print("Run with dry_run=False to apply fixes")
        print(f"{'=' * 80}\n")
        return {
            "success": True,
            "dry_run": True,
            "total_found": len(mismatched_records),
            "chapters_affected": len(by_chapter),
            "by_chapter": {k: len(v) for k, v in by_chapter.items()},
        }

    # Apply fixes
    print(f"\n{'=' * 80}")
    print("APPLYING FIXES...")
    print(f"{'=' * 80}\n")

    fixed_count = 0
    errors = []

    for record in mismatched_records:
        try:
            # Update the Chapter Member record directly
            frappe.db.sql(
                """
                UPDATE `tabChapter Member`
                SET enabled = 0,
                    status = 'Inactive',
                    modified = %s
                WHERE name = %s
            """,
                (now(), record["chapter_member_name"]),
            )

            fixed_count += 1
            if fixed_count <= 20:  # Show first 20 fixes
                print(f"✓ Fixed: {record['member_name'][:40]:40} in {record['chapter_name']}")
            elif fixed_count == 21:
                print(f"  ... fixing remaining {len(mismatched_records) - 20} records ...")

        except Exception as e:
            error_msg = f"✗ Error fixing {record['member_name']} in {record['chapter_name']}: {str(e)}"
            errors.append(error_msg)
            print(error_msg)

    # Commit all changes
    frappe.db.commit()

    # Summary
    print(f"\n{'=' * 80}")
    print("MIGRATION COMPLETE")
    print(f"{'=' * 80}")
    print(f"Total records found:    {len(mismatched_records)}")
    print(f"Successfully fixed:     {fixed_count}")
    print(f"Errors:                 {len(errors)}")
    print(f"{'=' * 80}\n")

    if errors:
        print("\nErrors encountered:")
        for error in errors[:10]:  # Show first 10 errors
            print(f"  {error}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more errors")

    return {
        "success": len(errors) == 0,
        "dry_run": False,
        "total_found": len(mismatched_records),
        "fixed": fixed_count,
        "errors": errors,
        "chapters_affected": len(by_chapter),
        "by_chapter": {k: len(v) for k, v in by_chapter.items()},
    }


def fix_specific_chapter(chapter_name, dry_run=True):
    """
    Fix Chapter Member records for a specific chapter

    Args:
        chapter_name: Name of the chapter to fix
        dry_run: If True, only report what would be changed without making changes

    Returns:
        Dict with operation results
    """
    # Verify chapter exists
    if not frappe.db.exists("Chapter", chapter_name):
        print(f"✗ Error: Chapter '{chapter_name}' not found")
        return {"success": False, "error": "Chapter not found"}

    # Find mismatched records for this chapter
    mismatched_records = frappe.db.sql(
        """
        SELECT
            cm.name as chapter_member_name,
            cm.parent as chapter_name,
            cm.member as member_id,
            m.full_name as member_name,
            m.status as member_status,
            cm.enabled as chapter_enabled,
            cm.status as chapter_status
        FROM `tabChapter Member` cm
        INNER JOIN `tabMember` m ON m.name = cm.member
        WHERE cm.parent = %(chapter_name)s
        AND m.status != 'Active'
        AND cm.enabled = 1
        ORDER BY m.full_name
    """,
        {"chapter_name": chapter_name},
        as_dict=True,
    )

    if not mismatched_records:
        print(f"✓ No mismatched records found for chapter '{chapter_name}'")
        return {"success": True, "dry_run": dry_run, "chapter_name": chapter_name, "total_found": 0}

    # Report findings
    print(f"\n{'=' * 80}")
    print(f"Chapter: {chapter_name}")
    print(f"Found {len(mismatched_records)} mismatched records")
    print(f"{'=' * 80}\n")

    for record in mismatched_records:
        print(
            f"  • {record['member_name'][:40]:40} | Member status: {record['member_status']:12} | "
            f"Chapter enabled: {record['chapter_enabled']} | Chapter status: {record['chapter_status']}"
        )

    if dry_run:
        print(f"\n{'=' * 80}")
        print("DRY RUN MODE - No changes were made")
        print("Run with dry_run=False to apply fixes")
        print(f"{'=' * 80}\n")
        return {
            "success": True,
            "dry_run": True,
            "chapter_name": chapter_name,
            "total_found": len(mismatched_records),
        }

    # Apply fixes
    print(f"\n{'=' * 80}")
    print("APPLYING FIXES...")
    print(f"{'=' * 80}\n")

    fixed_count = 0
    errors = []

    for record in mismatched_records:
        try:
            frappe.db.sql(
                """
                UPDATE `tabChapter Member`
                SET enabled = 0,
                    status = 'Inactive',
                    modified = %s
                WHERE name = %s
            """,
                (now(), record["chapter_member_name"]),
            )

            fixed_count += 1
            print(f"✓ Fixed: {record['member_name']}")

        except Exception as e:
            error_msg = f"✗ Error fixing {record['member_name']}: {str(e)}"
            errors.append(error_msg)
            print(error_msg)

    # Commit changes
    frappe.db.commit()

    # Summary
    print(f"\n{'=' * 80}")
    print(f"MIGRATION COMPLETE - {chapter_name}")
    print(f"{'=' * 80}")
    print(f"Total records found:    {len(mismatched_records)}")
    print(f"Successfully fixed:     {fixed_count}")
    print(f"Errors:                 {len(errors)}")
    print(f"{'=' * 80}\n")

    return {
        "success": len(errors) == 0,
        "dry_run": False,
        "chapter_name": chapter_name,
        "total_found": len(mismatched_records),
        "fixed": fixed_count,
        "errors": errors,
    }


def get_mismatch_summary():
    """
    Get a quick summary of mismatched records without making changes

    Returns:
        Dict with summary statistics
    """
    mismatched_records = frappe.db.sql(
        """
        SELECT
            cm.parent as chapter_name,
            COUNT(*) as count
        FROM `tabChapter Member` cm
        INNER JOIN `tabMember` m ON m.name = cm.member
        WHERE m.status != 'Active'
        AND cm.enabled = 1
        GROUP BY cm.parent
        ORDER BY count DESC
    """,
        as_dict=True,
    )

    total = sum(r["count"] for r in mismatched_records)

    if not mismatched_records:
        print("✓ No mismatched records found")
        return {"total": 0, "chapters": []}

    print("\nMismatch Summary:")
    print(f"{'=' * 60}")
    print(f"Total mismatched records: {total}")
    print(f"Affected chapters: {len(mismatched_records)}")
    print(f"{'=' * 60}")

    for record in mismatched_records:
        print(f"  {record['chapter_name'][:45]:45} : {record['count']:3} records")

    return {"total": total, "chapters": mismatched_records}
