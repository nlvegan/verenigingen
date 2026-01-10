"""
Fix notifications with conditions but missing condition_type.

When condition_type is NULL, Frappe's notification system skips condition evaluation,
causing all notifications with the same value_changed field to fire regardless of
their condition. This patch sets condition_type to 'Python' for all notifications
that have a condition defined.

Issue: Both "Member Application Approved" and "Member Application Rejected" emails
were sent simultaneously when application_status changed, because the conditions
were never evaluated.
"""

import frappe


def execute():
    """Set condition_type to 'Python' for notifications with conditions."""
    # Check if condition_type column exists (added in newer Frappe versions)
    columns = frappe.db.get_table_columns("Notification")
    if "condition_type" not in columns:
        # Column doesn't exist in this Frappe version - skip patch
        frappe.logger().info(
            "Skipping fix_notification_condition_type: condition_type column not present in this Frappe version"
        )
        return

    frappe.db.sql(
        """
        UPDATE `tabNotification`
        SET condition_type = 'Python'
        WHERE `condition` IS NOT NULL
        AND `condition` != ''
        AND (condition_type IS NULL OR condition_type = '')
        """,
    )

    # Clear notification cache so changes take effect immediately
    frappe.cache.delete_keys("notifications::")

    frappe.db.commit()
