#!/usr/bin/env python3
"""
Data migration script for Contribution Amendment Request rename
Migrates data from "Membership Amendment Request" to "Contribution Amendment Request"
"""

import sys

import frappe


def check_old_doctype_exists():
    """Check if the old DocType still exists in database"""
    return frappe.db.exists("DocType", "Membership Amendment Request")


def check_new_doctype_exists():
    """Check if the new DocType exists in database"""
    return frappe.db.exists("DocType", "Contribution Amendment Request")


def get_old_doctype_data():
    """Get all data from the old DocType"""
    if not check_old_doctype_exists():
        return []

    try:
        # Get all records from old doctype
        old_records = frappe.db.sql(
            """
            SELECT * FROM `tabMembership Amendment Request`
            ORDER BY creation
        """,
            as_dict=True,
        )

        return old_records
    except Exception as e:
        print(f"Error getting old doctype data: {str(e)}")
        return []


def migrate_single_record(old_record):
    """Migrate a single record from old to new doctype"""
    try:
        # Create new record with same data
        new_doc = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "name": old_record.get("name"),
                "member": old_record.get("member"),
                "amendment_type": old_record.get("amendment_type", "Fee Change"),
                "requested_amount": old_record.get("requested_amount"),
                "current_amount": old_record.get("current_amount"),
                "reason": old_record.get("reason"),
                "status": old_record.get("status", "Draft"),
                "effective_date": old_record.get("effective_date"),
                "admin_notes": old_record.get("admin_notes"),
                "approved_by": old_record.get("approved_by"),
                "approved_on": old_record.get("approved_on"),
                "processed_on": old_record.get("processed_on"),
                "owner": old_record.get("owner"),
                "creation": old_record.get("creation"),
                "modified": old_record.get("modified"),
                "modified_by": old_record.get("modified_by"),
                "docstatus": old_record.get("docstatus", 0),
            }
        )

        # Use flags to preserve timestamps and avoid validation issues
        new_doc.flags.ignore_permissions = True
        new_doc.flags.ignore_mandatory = True
        new_doc.flags.ignore_validate = True
        new_doc.flags.ignore_links = True

        # Insert the new record
        new_doc.insert()

        # If the old record was submitted, submit the new one too
        if old_record.get("docstatus") == 1:
            new_doc.submit()
        elif old_record.get("docstatus") == 2:
            new_doc.cancel()

        return True, new_doc.name

    except Exception as e:
        print(f"Error migrating record {old_record.get('name')}: {str(e)}")
        return False, str(e)


def update_member_links():
    """Update any Member DocType links to point to new DocType"""
    try:
        # Update Member JSON links (this should already be done by the rename script)
        print("Member DocType links should already be updated by rename script")
        return True
    except Exception as e:
        print(f"Error updating member links: {str(e)}")
        return False


def cleanup_old_doctype():
    """Remove the old DocType and its data after successful migration"""
    try:
        if not check_old_doctype_exists():
            print("Old DocType already removed")
            return True

        # Delete all old records first
        frappe.db.sql("DELETE FROM `tabMembership Amendment Request`")
        print("Deleted old records from tabMembership Amendment Request")

        # Remove the old DocType definition
        if frappe.db.exists("DocType", "Membership Amendment Request"):
            frappe.delete_doc("DocType", "Membership Amendment Request", force=True)
            print("Deleted old DocType: Membership Amendment Request")

        frappe.db.commit()
        return True

    except Exception as e:
        print(f"Error during cleanup: {str(e)}")
        return False


def main():
    """Main migration function"""
    print("🔄 Starting Contribution Amendment Request data migration...")
    print("=" * 70)

    # Initialize Frappe
    try:
        frappe.init(site="dev.veganisme.net")
        frappe.connect()
    except Exception as e:
        print(f"❌ Error connecting to Frappe: {str(e)}")
        return 1

    try:
        # Check if old DocType exists
        if not check_old_doctype_exists():
            print(
                "✅ Old DocType 'Membership Amendment Request' does not exist - migration may already be complete"
            )

            # Check if new DocType exists and has data
            if check_new_doctype_exists():
                new_count = frappe.db.count("Contribution Amendment Request")
                print(f"✅ New DocType 'Contribution Amendment Request' exists with {new_count} records")
                return 0
            else:
                print("❌ Neither old nor new DocType exists - something is wrong")
                return 1

        # Check if new DocType exists
        if not check_new_doctype_exists():
            print("❌ New DocType 'Contribution Amendment Request' does not exist")
            print("Please run 'bench migrate' first to create the new DocType")
            return 1

        # Get old data
        print("📊 Retrieving data from old DocType...")
        old_records = get_old_doctype_data()
        print(f"Found {len(old_records)} records to migrate")

        if not old_records:
            print("✅ No records to migrate")
            cleanup_old_doctype()
            return 0

        # Migrate each record
        print("\n🔄 Migrating records...")
        migrated_count = 0
        failed_count = 0

        for i, record in enumerate(old_records, 1):
            print(f"Migrating record {i}/{len(old_records)}: {record.get('name')}")
            success, result = migrate_single_record(record)

            if success:
                migrated_count += 1
                print(f"  ✅ Successfully migrated to {result}")
            else:
                failed_count += 1
                print(f"  ❌ Failed: {result}")

        print(f"\n📈 Migration Summary:")
        print(f"  • Total records: {len(old_records)}")
        print(f"  • Successfully migrated: {migrated_count}")
        print(f"  • Failed: {failed_count}")

        if failed_count == 0:
            print("\n🧹 Cleaning up old DocType...")
            if cleanup_old_doctype():
                print("✅ Old DocType cleaned up successfully")
            else:
                print("⚠️  Warning: Could not clean up old DocType completely")

            print("\n🎉 Data migration completed successfully!")
            print("\n📋 Next Steps:")
            print("  • Verify new records in 'Contribution Amendment Request'")
            print("  • Test fee adjustment workflow")
            print("  • Check member portal links")

            return 0
        else:
            print(f"\n⚠️  Migration completed with {failed_count} failures")
            print("Please review failed records before proceeding with cleanup")
            return 1

    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        import traceback

        print(f"Full traceback: {traceback.format_exc()}")
        return 1

    finally:
        try:
            frappe.destroy()
        except:
            pass


if __name__ == "__main__":
    sys.exit(main())
