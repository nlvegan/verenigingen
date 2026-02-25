"""Rename member status 'Terminated' to 'Quit' across all relevant tables."""
import frappe


def execute():
    """Update all database records that store 'Terminated' status to 'Quit'."""
    # 1. Member.status
    frappe.db.sql(
        """
        UPDATE `tabMember`
        SET status = 'Quit'
        WHERE status = 'Terminated'
    """
    )

    # 2. Chapter Membership History.status
    frappe.db.sql(
        """
        UPDATE `tabChapter Membership History`
        SET status = 'Quit'
        WHERE status = 'Terminated'
    """
    )

    frappe.db.commit()
