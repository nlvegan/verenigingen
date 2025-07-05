"""
Migration patch for renaming Membership Amendment Request to Contribution Amendment Request
"""

import frappe


def execute():
    """Execute the migration"""

    # Check if old table exists
    old_table_exists = False
    try:
        result = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
            AND table_name = 'tabMembership Amendment Request'
        """,
            as_dict=True,
        )

        old_table_exists = result[0]["count"] > 0 if result else False
    except Exception:
        old_table_exists = False

    if not old_table_exists:
        print("Old table 'tabMembership Amendment Request' does not exist - migration not needed")
        return

    # Check if new table exists
    new_table_exists = False
    try:
        result = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
            AND table_name = 'tabContribution Amendment Request'
        """,
            as_dict=True,
        )

        new_table_exists = result[0]["count"] > 0 if result else False
    except Exception:
        new_table_exists = False

    if not new_table_exists:
        print("New table 'tabContribution Amendment Request' does not exist - cannot migrate")
        return

    # Get count of records in old table
    try:
        old_count = frappe.db.sql(
            """
            SELECT COUNT(*) as count FROM `tabMembership Amendment Request`
        """,
            as_dict=True,
        )[0]["count"]
    except Exception:
        old_count = 0

    if old_count == 0:
        print("No records to migrate from old table")
        # Still clean up the empty old table
        try:
            frappe.db.sql("DROP TABLE IF EXISTS `tabMembership Amendment Request`")
            print("Removed empty old table")
        except Exception as e:
            print(f"Could not remove old table: {str(e)}")
        return

    print(
        f"Migrating {old_count} records from 'Membership Amendment Request' to 'Contribution Amendment Request'"
    )

    try:
        # Get all records from old table
        old_records = frappe.db.sql(
            """
            SELECT * FROM `tabMembership Amendment Request`
            ORDER BY creation
        """,
            as_dict=True,
        )

        migrated_count = 0
        failed_count = 0

        for record in old_records:
            try:
                # Check if record already exists in new table
                existing = frappe.db.sql(
                    """
                    SELECT name FROM `tabContribution Amendment Request`
                    WHERE name = %s
                """,
                    record.get("name"),
                )

                if existing:
                    print(f"Record {record.get('name')} already exists in new table, skipping")
                    continue

                # Insert into new table - map old columns to new structure
                frappe.db.sql(
                    """
                    INSERT INTO `tabContribution Amendment Request`
                    (name, member, amendment_type, requested_amount, current_amount,
                     reason, status, effective_date, approved_by, approved_date,
                     internal_notes, owner, creation, modified, modified_by, docstatus)
                    VALUES (%(name)s, %(member)s, %(amendment_type)s, %(requested_amount)s,
                           %(current_amount)s, %(reason)s, %(status)s, %(effective_date)s,
                           %(approved_by)s, %(approved_date)s, %(internal_notes)s,
                           %(owner)s, %(creation)s, %(modified)s, %(modified_by)s, %(docstatus)s)
                """,
                    {
                        "name": record.get("name"),
                        "member": record.get("member"),
                        "amendment_type": record.get("amendment_type", "Fee Change"),
                        "requested_amount": record.get("requested_amount"),
                        "current_amount": record.get("current_amount"),
                        "reason": record.get("reason"),
                        "status": record.get("status", "Draft"),
                        "effective_date": record.get("effective_date"),
                        "approved_by": record.get("approved_by"),
                        "approved_date": record.get("approved_on"),  # Map approved_on to approved_date
                        "internal_notes": record.get("admin_notes", ""),  # Map admin_notes to internal_notes
                        "owner": record.get("owner"),
                        "creation": record.get("creation"),
                        "modified": record.get("modified"),
                        "modified_by": record.get("modified_by"),
                        "docstatus": record.get("docstatus", 0),
                    },
                )

                migrated_count += 1

            except Exception as e:
                failed_count += 1
                print(f"Failed to migrate record {record.get('name')}: {str(e)}")

        print(f"Migration completed: {migrated_count} migrated, {failed_count} failed")

        # If all records migrated successfully, remove old table
        if failed_count == 0:
            try:
                frappe.db.sql("DROP TABLE IF EXISTS `tabMembership Amendment Request`")
                print("Successfully removed old table")
            except Exception as e:
                print(f"Could not remove old table: {str(e)}")
        else:
            print("Old table kept due to migration failures")

    except Exception as e:
        print(f"Migration failed: {str(e)}")
        raise
