# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Remove UNIQUE constraint on member field in Membership Dues Schedule table.

This allows multiple dues schedules per member with different statuses
(e.g., Active, Cancelled, Expired) for better history tracking.

The uniqueness validation for active schedules is already handled in Python.
"""

import frappe


def execute():
    """Remove unique constraint on member field"""

    # Check if the constraint exists
    constraints = frappe.db.sql(
        """
        SELECT CONSTRAINT_NAME
        FROM information_schema.TABLE_CONSTRAINTS
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'tabMembership Dues Schedule'
        AND CONSTRAINT_TYPE = 'UNIQUE'
        AND CONSTRAINT_NAME = 'member'
    """
    )

    if constraints:
        try:
            # Drop the unique constraint
            frappe.db.sql(
                """
                ALTER TABLE `tabMembership Dues Schedule`
                DROP INDEX `member`
            """
            )

            frappe.db.commit()
            print("Successfully removed UNIQUE constraint on member field")

        except Exception as e:
            print(f"Error removing constraint: {str(e)}")
            # If it fails, it might already be removed or have a different name
            pass
    else:
        print("UNIQUE constraint on member field not found - may already be removed")

    # Add a regular index on member field for performance
    # Check if index already exists
    indexes = frappe.db.sql(
        """
        SELECT INDEX_NAME
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'tabMembership Dues Schedule'
        AND INDEX_NAME = 'idx_member'
    """
    )

    if not indexes:
        try:
            frappe.db.sql(
                """
                ALTER TABLE `tabMembership Dues Schedule`
                ADD INDEX idx_member (member)
            """
            )

            frappe.db.commit()
            print("Added regular index on member field for performance")

        except Exception as e:
            print(f"Error adding index: {str(e)}")
            pass

    # Add composite index for active schedule lookups
    composite_indexes = frappe.db.sql(
        """
        SELECT INDEX_NAME
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'tabMembership Dues Schedule'
        AND INDEX_NAME = 'idx_member_status'
    """
    )

    if not composite_indexes:
        try:
            frappe.db.sql(
                """
                ALTER TABLE `tabMembership Dues Schedule`
                ADD INDEX idx_member_status (member, status)
            """
            )

            frappe.db.commit()
            print("Added composite index on member and status fields")

        except Exception as e:
            print(f"Error adding composite index: {str(e)}")
            pass
