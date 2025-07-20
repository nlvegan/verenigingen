# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Rename 'amount' field to 'dues_rate' in Membership Dues Schedule table.
This aligns with our architectural decision to use dues schedules as the
source of truth for billing amounts.
"""

import frappe


def execute():
    """Rename amount column to dues_rate in Membership Dues Schedule"""

    # Check if the column exists
    columns = frappe.db.sql(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'tabMembership Dues Schedule'
        AND COLUMN_NAME IN ('amount', 'dues_rate')
    """,
        as_dict=True,
    )

    column_names = [col.COLUMN_NAME for col in columns]

    if "amount" in column_names and "dues_rate" not in column_names:
        try:
            # Rename the column
            frappe.db.sql(
                """
                ALTER TABLE `tabMembership Dues Schedule`
                CHANGE COLUMN `amount` `dues_rate` decimal(18,6) NOT NULL DEFAULT 0.000000
            """
            )

            frappe.db.commit()
            print("Successfully renamed 'amount' column to 'dues_rate'")

        except Exception as e:
            print(f"Error renaming column: {str(e)}")
            # If it fails, it might already be renamed or have a different structure
            pass
    elif "dues_rate" in column_names:
        print("Column 'dues_rate' already exists - migration may have already run")
    else:
        print("Neither 'amount' nor 'dues_rate' column found - check table structure")
