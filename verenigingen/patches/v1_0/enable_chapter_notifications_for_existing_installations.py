"""
Migration: Enable chapter assignment notifications for existing installations

This patch maintains backward compatibility by enabling the new
send_chapter_assignment_notifications setting for existing installations.

New installations will still default to OFF (safer for bulk operations),
but existing installations will preserve current notification behavior.
"""

import frappe


def execute():
    """Enable chapter assignment notifications for existing installations."""
    try:
        # Verify field exists before attempting to set it
        if not frappe.db.has_column("Verenigingen Settings", "send_chapter_assignment_notifications"):
            frappe.logger().warning(
                "send_chapter_assignment_notifications field not found in Verenigingen Settings - "
                "skipping migration (schema may not be synced yet)"
            )
            return

        # Check if this is an existing installation by looking for existing members
        existing_members_count = frappe.db.count("Member")

        if existing_members_count > 0:
            # This is an existing installation - preserve current behavior
            frappe.logger().info(
                f"Existing installation detected ({existing_members_count} members). "
                "Enabling chapter assignment notifications to maintain current behavior."
            )

            # Use raw SQL for idempotency and reliability
            frappe.db.sql(
                """
                UPDATE `tabVerenigingen Settings`
                SET send_chapter_assignment_notifications = 1
                WHERE name = 'Verenigingen Settings'
                AND IFNULL(send_chapter_assignment_notifications, 0) = 0
            """
            )
            frappe.db.commit()

            frappe.logger().info("✅ Chapter assignment notifications enabled for existing installation")
        else:
            # New installation - keep default (OFF)
            frappe.logger().info(
                "New installation detected. Chapter assignment notifications "
                "remain OFF (recommended for bulk operations)."
            )

    except Exception as e:
        frappe.log_error(
            f"Error in chapter notifications migration: {str(e)}",
            "Chapter Notifications Migration Error",
        )
        # Don't fail the migration - this is a non-critical setting
        frappe.logger().warning(f"Could not migrate chapter notification setting: {str(e)}")
