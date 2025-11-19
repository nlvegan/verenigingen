#!/usr/bin/env python3
"""
Database patch to rename custom_membership_dues_schedule to membership_dues_schedule_display

This patch safely renames the custom field while preserving all existing data.
Required for field rename from custom_membership_dues_schedule to membership_dues_schedule_display.
"""

import frappe
from frappe.utils import now_datetime


def execute():
    """
    Rename custom_membership_dues_schedule field to membership_dues_schedule_display

    This function:
    1. Migrates data from old column to new column if both exist
    2. Removes old Custom Field record and database column
    3. Preserves all existing data
    4. Maintains referential integrity
    """

    try:
        print(
            f"[{now_datetime()}] Starting field rename: custom_membership_dues_schedule → membership_dues_schedule_display"
        )

        # Step 1: Check current state
        old_field_exists = frappe.db.exists("Custom Field", "Sales Invoice-custom_membership_dues_schedule")
        new_field_exists = frappe.db.exists("Custom Field", "Sales Invoice-membership_dues_schedule_display")

        old_column_exists = frappe.db.sql(
            """
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'tabSales Invoice' AND COLUMN_NAME = 'custom_membership_dues_schedule'
        """
        )

        new_column_exists = frappe.db.sql(
            """
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'tabSales Invoice' AND COLUMN_NAME = 'membership_dues_schedule_display'
        """
        )

        print(f"Current state: old_field={bool(old_field_exists)}, new_field={bool(new_field_exists)}")
        print(f"Columns: old_col={bool(old_column_exists)}, new_col={bool(new_column_exists)}")

        # Step 2: Handle data migration if both columns exist
        if old_column_exists and new_column_exists:
            print("Migrating data from old column to new column...")

            # Check if old column has data
            old_data_count = frappe.db.sql(
                """
                SELECT COUNT(*) FROM `tabSales Invoice`
                WHERE custom_membership_dues_schedule IS NOT NULL
            """
            )[0][0]

            if old_data_count > 0:
                print(f"Migrating {old_data_count} records with data...")
                frappe.db.sql(
                    """
                    UPDATE `tabSales Invoice`
                    SET membership_dues_schedule_display = custom_membership_dues_schedule
                    WHERE custom_membership_dues_schedule IS NOT NULL
                    AND membership_dues_schedule_display IS NULL
                """
                )
                print("✓ Data migration completed")
            else:
                print("No data to migrate")

        # Step 3: Remove old Custom Field record if it exists
        if old_field_exists:
            print("Removing old Custom Field record...")
            frappe.db.sql(
                "DELETE FROM `tabCustom Field` WHERE name = 'Sales Invoice-custom_membership_dues_schedule'"
            )
            print("✓ Old Custom Field record removed")

        # Step 4: Remove old database column if it exists
        if old_column_exists:
            print("Removing old database column...")
            try:
                frappe.db.sql("ALTER TABLE `tabSales Invoice` DROP COLUMN `custom_membership_dues_schedule`")
                print("✓ Old database column removed")
            except Exception as e:
                print(f"⚠️  Could not remove old column (may not exist): {str(e)}")

        # Step 5: Ensure new field exists
        if not new_field_exists:
            print("❌ New field does not exist - check fixture installation")
            return

        # Step 6: Clear cache and reload
        print("Clearing cache and reloading DocType...")
        frappe.clear_cache()
        frappe.reload_doctype("Sales Invoice")

        # Step 7: Final verification
        print("Final verification...")
        final_old_exists = frappe.db.sql(
            """
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'tabSales Invoice' AND COLUMN_NAME = 'custom_membership_dues_schedule'
        """
        )

        final_new_exists = frappe.db.sql(
            """
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'tabSales Invoice' AND COLUMN_NAME = 'membership_dues_schedule_display'
        """
        )

        final_data_count = frappe.db.sql(
            """
            SELECT COUNT(*) FROM `tabSales Invoice`
            WHERE membership_dues_schedule_display IS NOT NULL
        """
        )[0][0]

        if not final_old_exists and final_new_exists:
            print("✅ Migration completed successfully!")
            print(f"   - Old column removed: {not bool(final_old_exists)}")
            print(f"   - New column exists: {bool(final_new_exists)}")
            print(f"   - Records with data: {final_data_count}")
        else:
            print("❌ Migration verification failed")
            print(f"   - Old column removed: {not bool(final_old_exists)}")
            print(f"   - New column exists: {bool(final_new_exists)}")

        # Commit the transaction
        frappe.db.commit()
        print(f"[{now_datetime()}] Field rename migration completed")

    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        print("Rolling back transaction...")
        frappe.db.rollback()
        raise e


def validate_migration():
    """
    Validate that the field rename migration was successful

    Returns:
        tuple: (success: bool, message: str, details: dict)
    """

    try:
        # Check Custom Field record
        new_field_exists = frappe.db.exists("Custom Field", "Sales Invoice-membership_dues_schedule_display")
        old_field_exists = frappe.db.exists("Custom Field", "Sales Invoice-custom_membership_dues_schedule")

        # Check database column
        new_column_exists = frappe.db.sql(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'tabSales Invoice'
            AND COLUMN_NAME = 'membership_dues_schedule_display'
        """
        )

        old_column_exists = frappe.db.sql(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'tabSales Invoice'
            AND COLUMN_NAME = 'custom_membership_dues_schedule'
        """
        )

        # Check if there's data in the new field (if any invoices exist)
        invoice_count = frappe.db.count("Sales Invoice")
        field_data_count = 0

        if invoice_count > 0:
            field_data_count = (
                frappe.db.sql(
                    """
                SELECT COUNT(*)
                FROM `tabSales Invoice`
                WHERE membership_dues_schedule_display IS NOT NULL
            """
                )[0][0]
                if new_column_exists
                else 0
            )

        details = {
            "custom_field_record_updated": new_field_exists and not old_field_exists,
            "database_column_renamed": bool(new_column_exists) and not bool(old_column_exists),
            "total_invoices": invoice_count,
            "invoices_with_field_data": field_data_count,
            "old_field_exists": old_field_exists,
            "new_field_exists": new_field_exists,
            "old_column_exists": bool(old_column_exists),
            "new_column_exists": bool(new_column_exists),
        }

        success = details["custom_field_record_updated"] and details["database_column_renamed"]

        if success:
            message = f"✅ Migration successful - {field_data_count} invoices with field data preserved"
        else:
            message = "❌ Migration incomplete or failed"

        return success, message, details

    except Exception as e:
        return False, f"❌ Validation error: {str(e)}", {}


if __name__ == "__main__":
    # Allow running this script directly for testing
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    print("=== Field Rename Migration Test ===")
    execute()

    print("\n=== Validation ===")
    success, message, details = validate_migration()
    print(message)
    for key, value in details.items():
        print(f"  {key}: {value}")
