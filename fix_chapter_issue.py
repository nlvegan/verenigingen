#!/usr/bin/env python3

import frappe


def fix_invalid_chapter_references():
    """Fix invalid chapter references for member Assoc-Member-2025-07-0870"""

    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        # Direct database cleanup - remove invalid chapter references
        print("Cleaning up invalid chapter references...")

        result = frappe.db.sql(
            """
            DELETE FROM `tabChapter Membership History`
            WHERE parent = 'Assoc-Member-2025-07-0870'
            AND chapter_name = 'Test Amsterdam Chapter'
        """
        )

        print(f"Deleted {frappe.db.sql('SELECT ROW_COUNT()')[0][0]} invalid chapter references")

        # Commit the changes
        frappe.db.commit()

        # Reload and verify the member can be saved
        member = frappe.get_doc("Member", "Assoc-Member-2025-07-0870")
        print(
            f"Chapter history count after cleanup: {len(member.chapter_membership_history) if member.chapter_membership_history else 0}"
        )

        # Test save
        member.save()
        print("Member saved successfully after cleanup!")

        # Test financial history save
        print("Testing financial history save...")

        # Try importing and using the financial history manager
        try:
            from vereinigingen.utils.member_financial_history_manager import MemberFinancialHistoryManager

            manager = MemberFinancialHistoryManager(member)
            result = manager.update_payment_history()
            print(f"Financial history update result: {result}")
        except Exception as e:
            print(f"Financial history manager error: {str(e)}")

        print("Cleanup completed successfully!")

    except Exception as e:
        print(f"Error during cleanup: {str(e)}")
        frappe.db.rollback()
    finally:
        frappe.destroy()


if __name__ == "__main__":
    fix_invalid_chapter_references()
