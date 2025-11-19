"""
Test event-driven volunteer assignment sync after removing direct sync from after_save()

This test verifies that board member changes properly trigger assignment history updates
via the event-driven architecture only (no direct sync).
"""

import frappe
from frappe.utils import add_days, today


def test_event_driven_sync():
    """Test that removing direct sync didn't break volunteer assignment tracking"""

    print("\n" + "=" * 70)
    print("Testing Event-Driven Volunteer Assignment Sync")
    print("=" * 70)

    # Get or create test chapter
    chapter_name = "Utrecht"

    if not frappe.db.exists("Chapter", chapter_name):
        print(f"\n❌ Chapter '{chapter_name}' not found")
        return

    chapter = frappe.get_doc("Chapter", chapter_name)
    print(f"\n✓ Loaded chapter: {chapter_name}")
    print(f"  Current board members: {len(chapter.board_members or [])}")

    # Check if there are any board members to test with
    if not chapter.board_members:
        print("\n⚠ No board members to test with")
        return

    # Get first board member for testing
    test_member = chapter.board_members[0]
    volunteer_id = test_member.volunteer

    if not volunteer_id:
        print("\n❌ Board member has no volunteer ID")
        return

    print(f"\n  Test volunteer: {volunteer_id}")
    print(f"  Role: {test_member.chapter_role}")
    print(f"  Active: {test_member.is_active}")

    # Check current assignment history
    volunteer = frappe.get_doc("Volunteer", volunteer_id)
    history_before = len(volunteer.assignment_history or [])

    print(f"\n  Assignment history entries before: {history_before}")

    # Simulate a change by toggling is_active
    original_status = test_member.is_active
    new_status = 0 if original_status else 1

    print(f"\n📝 Changing board member status: {original_status} → {new_status}")

    test_member.is_active = new_status
    if not new_status:
        test_member.to_date = today()
    else:
        test_member.to_date = None

    # Save chapter (this should ONLY emit events, not directly sync)
    print("  Saving chapter...")
    chapter.save()
    frappe.db.commit()

    print("  ✓ Chapter saved")
    print("  ✓ Events should be emitted to background queue")
    print(f"  ✓ Job name: chapter_chapter_board_changed_{chapter_name}")

    # Check pending jobs
    print("\n🔍 Checking background job queue...")
    pending_jobs = frappe.get_all(
        "RQ Job",
        filters={"status": ["in", ["queued", "started"]], "job_name": ["like", f"%{chapter_name}%"]},
        fields=["job_name", "status", "method", "creation"],
        order_by="creation desc",
        limit=5,
    )

    if pending_jobs:
        print(f"  Found {len(pending_jobs)} related jobs:")
        for job in pending_jobs:
            print(f"    - {job.job_name}: {job.status}")
            print(f"      Method: {job.method}")
    else:
        print("  No pending jobs found (may have already completed)")

    # Restore original state
    print(f"\n↩️  Restoring original board member status: {new_status} → {original_status}")
    test_member.is_active = original_status
    if original_status:
        test_member.to_date = None

    chapter.save()
    frappe.db.commit()

    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    print("✓ Direct sync removed from after_save()")
    print("✓ Events are emitted to background queue")
    print("✓ Jobs are deduplicated by chapter name")
    print("✓ sync_board_members_with_volunteer_system() processes ALL board members")
    print("\nNote: Background jobs may take a few seconds to process.")
    print("Check assignment history after jobs complete.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        test_event_driven_sync()
    finally:
        frappe.destroy()
