"""
Backfill Chapter Membership History
Migration to add missing chapter membership history records for existing Chapter Members
"""

import frappe
from frappe.utils import today


def execute():
    """Execute the chapter membership history backfill migration"""
    print("Starting Chapter Membership History Backfill Migration...")

    # Track statistics
    stats = {"processed": 0, "added": 0, "skipped": 0, "errors": 0}

    try:
        # Get all Chapter Member records
        chapter_members = frappe.db.sql(
            """
            SELECT
                cm.name,
                cm.parent as chapter_name,
                cm.member,
                cm.chapter_join_date,
                cm.enabled,
                cm.leave_reason,
                m.full_name as member_name
            FROM `tabChapter Member` cm
            INNER JOIN `tabMember` m ON cm.member = m.name
            ORDER BY cm.chapter_join_date ASC, cm.creation ASC
        """,
            as_dict=True,
        )

        print(f"Found {len(chapter_members)} Chapter Member records to process")

        for cm in chapter_members:
            stats["processed"] += 1

            try:
                # Check if history already exists for this membership
                existing_history = frappe.db.exists(
                    "Chapter Membership History",
                    {
                        "parent": cm.member,
                        "chapter_name": cm.chapter_name,
                        "assignment_type": "Member",
                        "start_date": cm.chapter_join_date or today(),
                    },
                )

                if existing_history:
                    stats["skipped"] += 1
                    continue

                # Determine status based on enabled flag
                if cm.enabled:
                    status = "Active"
                    end_date = None
                    reason = f"Active member of {cm.chapter_name}"
                else:
                    status = "Completed"
                    end_date = today()  # We don't have the actual end date, use today
                    reason = cm.leave_reason or f"Disabled in {cm.chapter_name}"

                # Add membership history
                member_doc = frappe.get_doc("Member", cm.member)

                # Check if member has chapter_membership_history table
                if not hasattr(member_doc, "chapter_membership_history"):
                    print(f"Warning: Member {cm.member} does not have chapter_membership_history table")
                    continue

                member_doc.append(
                    "chapter_membership_history",
                    {
                        "chapter_name": cm.chapter_name,
                        "assignment_type": "Member",
                        "start_date": cm.chapter_join_date or today(),
                        "end_date": end_date,
                        "status": status,
                        "reason": reason,
                    },
                )

                member_doc.save(ignore_permissions=True)
                stats["added"] += 1

                if stats["added"] % 50 == 0:
                    print(f"Progress: {stats['added']} history records added...")
                    frappe.db.commit()

            except Exception as e:
                stats["errors"] += 1
                print(f"Error processing Chapter Member {cm.name}: {str(e)}")
                frappe.log_error(
                    f"Chapter Membership History Backfill Error for {cm.name}: {str(e)}",
                    "Chapter Membership History Backfill",
                )
                continue

        # Final commit
        frappe.db.commit()

        # Print summary
        print(
            """
Chapter Membership History Backfill Complete!

Statistics:
- Total Chapter Members processed: {stats['processed']}
- History records added: {stats['added']}
- Records skipped (already had history): {stats['skipped']}
- Errors encountered: {stats['errors']}
        """
        )

        # Log completion
        frappe.log_error(
            f"Chapter Membership History Backfill completed. Added {stats['added']} records, {stats['errors']} errors.",
            "Chapter Membership History Backfill Complete",
        )

    except Exception as e:
        print(f"Critical error in backfill migration: {str(e)}")
        frappe.log_error(
            f"Critical error in Chapter Membership History Backfill: {str(e)}",
            "Chapter Membership History Backfill Critical Error",
        )
        raise


def validate_backfill():
    """Validate that the backfill was successful"""
    print("Validating Chapter Membership History Backfill...")

    # Count Chapter Members
    chapter_member_count = frappe.db.count("Chapter Member")

    # Count Chapter Membership History records
    history_count = frappe.db.sql(
        """
        SELECT COUNT(*) as count
        FROM `tabChapter Membership History` cmh
        INNER JOIN `tabMember` m ON cmh.parent = m.name
        WHERE cmh.assignment_type = 'Member'
    """
    )[0][0]

    print(f"Chapter Members: {chapter_member_count}")
    print(f"Chapter Membership History records (Member type): {history_count}")

    if history_count >= chapter_member_count:
        print("✅ Validation successful: History records >= Chapter Members")
    else:
        print(f"⚠️ Validation warning: Missing {chapter_member_count - history_count} history records")

    # Check for members without any chapter history
    members_without_history = frappe.db.sql(
        """
        SELECT m.name, m.full_name
        FROM `tabMember` m
        LEFT JOIN `tabChapter Membership History` cmh ON m.name = cmh.parent
            AND cmh.assignment_type = 'Member'
        WHERE cmh.name IS NULL
        AND EXISTS (
            SELECT 1 FROM `tabChapter Member` cm WHERE cm.member = m.name
        )
        LIMIT 10
    """,
        as_dict=True,
    )

    if members_without_history:
        print(f"⚠️ Found {len(members_without_history)} members with Chapter Member records but no history:")
        for member in members_without_history:
            print(f"  - {member.name}: {member.full_name}")


if __name__ == "__main__":
    # Allow running this script directly for testing
    execute()
    validate_backfill()
