"""
Simple migration commands for Contribution Amendment Request
Run these commands in bench console: bench --site dev.veganisme.net console
"""


def check_migration_status():
    """Check if migration is needed"""
    import frappe

    # Check if old table exists
    old_table_exists = False
    old_count = 0

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

        if old_table_exists:
            old_count = frappe.db.sql(
                """
                SELECT COUNT(*) as count FROM `tabMembership Amendment Request`
            """,
                as_dict=True,
            )[0]["count"]
    except Exception as e:
        print(f"Error checking old table: {str(e)}")

    # Check if new table exists
    new_table_exists = False
    new_count = 0

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

        if new_table_exists:
            new_count = frappe.db.sql(
                """
                SELECT COUNT(*) as count FROM `tabContribution Amendment Request`
            """,
                as_dict=True,
            )[0]["count"]
    except Exception as e:
        print(f"Error checking new table: {str(e)}")

    print(f"Old table exists: {old_table_exists}, Records: {old_count}")
    print(f"New table exists: {new_table_exists}, Records: {new_count}")

    return {
        "old_table_exists": old_table_exists,
        "old_count": old_count,
        "new_table_exists": new_table_exists,
        "new_count": new_count,
    }


def migrate_data():
    """Migrate data from old to new table"""
    import frappe

    status = check_migration_status()

    if not status["old_table_exists"]:
        print("✅ No old table found - migration not needed")
        return

    if not status["new_table_exists"]:
        print("❌ New table doesn't exist - run 'bench migrate' first")
        return

    if status["old_count"] == 0:
        print("✅ No records to migrate in old table")
        return

    print(f"🔄 Migrating {status['old_count']} records...")

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

        for record in old_records:
            try:
                # Insert into new table with same data
                frappe.db.sql(
                    """
                    INSERT INTO `tabContribution Amendment Request`
                    (name, member, amendment_type, requested_amount, current_amount,
                     reason, status, effective_date, admin_notes, approved_by,
                     approved_on, processed_on, owner, creation, modified,
                     modified_by, docstatus)
                    VALUES (%(name)s, %(member)s, %(amendment_type)s, %(requested_amount)s,
                           %(current_amount)s, %(reason)s, %(status)s, %(effective_date)s,
                           %(admin_notes)s, %(approved_by)s, %(approved_on)s,
                           %(processed_on)s, %(owner)s, %(creation)s, %(modified)s,
                           %(modified_by)s, %(docstatus)s)
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
                        "admin_notes": record.get("admin_notes"),
                        "approved_by": record.get("approved_by"),
                        "approved_on": record.get("approved_on"),
                        "processed_on": record.get("processed_on"),
                        "owner": record.get("owner"),
                        "creation": record.get("creation"),
                        "modified": record.get("modified"),
                        "modified_by": record.get("modified_by"),
                        "docstatus": record.get("docstatus", 0),
                    },
                )

                migrated_count += 1
                print(f"  ✅ Migrated: {record.get('name')}")

            except Exception as e:
                print(f"  ❌ Failed to migrate {record.get('name')}: {str(e)}")

        frappe.db.commit()
        print(f"✅ Successfully migrated {migrated_count} records")

        # Clean up old table
        if migrated_count == len(old_records):
            print("🧹 Cleaning up old table...")
            frappe.db.sql("DROP TABLE IF EXISTS `tabMembership Amendment Request`")
            frappe.db.commit()
            print("✅ Old table removed")

        return True

    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        frappe.db.rollback()
        return False


# Instructions for manual execution
migration_instructions = """
To run the migration manually:

1. Open bench console:
   bench --site dev.veganisme.net console

2. Run these commands:
   exec(open('/home/frappe/frappe-bench/apps/verenigingen/migration_commands.py').read())
   check_migration_status()
   migrate_data()

3. Exit console:
   exit()
"""

if __name__ == "__main__":
    print(migration_instructions)
