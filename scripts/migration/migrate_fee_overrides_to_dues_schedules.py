#!/usr/bin/env python3
"""
DEPRECATED LEGACY MIGRATION SCRIPT - DO NOT USE
===============================================

⚠️  WARNING: This script is DEPRECATED and NON-FUNCTIONAL
⚠️  The referenced fields have been REMOVED from the Member DocType

This script was used to migrate legacy membership_fee_override data to the new 
Membership Dues Schedule architecture. The following fields no longer exist:
- membership_fee_override
- fee_override_reason  
- fee_override_date
- fee_override_by

This file is kept for historical reference only. Any attempt to run this script
will fail as the referenced database fields have been removed.

RECOMMENDATION: Remove this file from the repository.
"""

import frappe
from frappe.utils import today, getdate, flt
from datetime import datetime


def migrate_fee_overrides():
    """
    DEPRECATED FUNCTION - IMMEDIATELY EXITS
    
    This function is deprecated as the required database fields no longer exist.
    """
    frappe.throw("This migration script is deprecated. The required database fields (membership_fee_override, fee_override_reason, fee_override_date, fee_override_by) have been removed from the Member DocType.")
    
    # The rest of this function is kept for historical reference but will never execute


def _deprecated_migrate_fee_overrides():
    """
    Main migration function to convert all membership_fee_override data
    to Membership Dues Schedule records
    """
    print("Starting migration of membership fee overrides to dues schedules...")
    
    # Get all members with fee overrides
    # NOTE: membership_fee_override field was removed - this script is for legacy data migration only
    try:
        # NOTE: This query will fail as membership_fee_override was removed
        members_with_overrides = frappe.get_all(
            "Member",
            filters={
                "membership_fee_override": [">", 0]  # LEGACY: field removed, handled by exception
            },
            fields=[
                "name", "full_name", "membership_fee_override",  # LEGACY: field removed
                "fee_override_reason", "fee_override_date", "fee_override_by"
            ]
        )
    except Exception:
        print("membership_fee_override field no longer exists - this script is for legacy data only")
        return {"migrated": 0, "errors": 0, "total": 0}
    
    print(f"Found {len(members_with_overrides)} members with fee overrides")
    
    migrated_count = 0
    error_count = 0
    
    for member_data in members_with_overrides:
        try:
            migrate_member_override(member_data)
            migrated_count += 1
            print(f"✓ Migrated {member_data['full_name']} ({member_data['name']})")
        except Exception as e:
            error_count += 1
            print(f"✗ Error migrating {member_data['full_name']}: {str(e)}")
            frappe.log_error(f"Migration error for {member_data['name']}: {str(e)}", "Fee Override Migration")
    
    print(f"\nMigration completed:")
    print(f"  Successfully migrated: {migrated_count}")
    print(f"  Errors: {error_count}")
    
    return {
        "migrated": migrated_count,
        "errors": error_count,
        "total": len(members_with_overrides)
    }


def migrate_member_override(member_data):
    """
    Migrate a single member's fee override to a dues schedule
    """
    member_name = member_data["name"]
    override_amount = flt(member_data["membership_fee_override"])
    
    # Skip if no override amount
    if override_amount <= 0:
        return
    
    # Get or create active membership
    membership = get_or_create_membership(member_name)
    
    # Check if dues schedule already exists
    existing_schedule = frappe.db.get_value(
        "Membership Dues Schedule",
        {"member": member_name, "status": ["in", ["Active", "Pending"]]},
        "name"
    )
    
    if existing_schedule:
        print(f"  Warning: Dues schedule already exists for {member_name}, skipping...")
        return
    
    # Create new dues schedule from override data
    dues_schedule = frappe.new_doc("Membership Dues Schedule")
    dues_schedule.member = member_name
    dues_schedule.membership = membership.name
    dues_schedule.membership_type = membership.membership_type
    dues_schedule.contribution_mode = "Custom"
    dues_schedule.dues_rate = override_amount
    dues_schedule.uses_custom_amount = 1
    dues_schedule.custom_amount_approved = 1  # Assume existing overrides were approved
    dues_schedule.custom_amount_reason = member_data.get("fee_override_reason") or "Migrated from legacy fee override"
    dues_schedule.billing_frequency = "Monthly"  # Default frequency
    # Payment method will be determined dynamically based on member's payment setup
    dues_schedule.status = "Active"
    dues_schedule.auto_generate = 1
    dues_schedule.test_mode = 0
    
    # Set historical dates if available
    if member_data.get("fee_override_date"):
        dues_schedule.effective_date = member_data["fee_override_date"]
        dues_schedule.next_invoice_date = member_data["fee_override_date"]
    else:
        dues_schedule.effective_date = today()
        dues_schedule.next_invoice_date = today()
    
    # Set migration metadata
    dues_schedule.migration_source = "fee_override_migration"
    dues_schedule.migration_date = datetime.now()
    dues_schedule.migration_by = member_data.get("fee_override_by") or "System Migration"
    
    # Save the dues schedule
    dues_schedule.save()
    
    # Add migration comment
    dues_schedule.add_comment(
        text=f"Created from legacy fee override migration. Original amount: €{override_amount:.2f}"
    )
    
    print(f"  Created dues schedule {dues_schedule.name} with amount €{override_amount:.2f}")


def get_or_create_membership(member_name):
    """
    Get active membership or create one if it doesn't exist
    """
    # Try to find active membership
    membership = frappe.db.get_value(
        "Membership",
        {"member": member_name, "status": "Active"},
        ["name", "membership_type"],
        as_dict=True
    )
    
    if membership:
        return frappe.get_doc("Membership", membership.name)
    
    # Create new membership if none exists
    member = frappe.get_doc("Member", member_name)
    
    # Get default membership type
    default_membership_type = frappe.db.get_value(
        "Membership Type",
        {"is_active": 1},
        "name",
        order_by="creation"
    )
    
    if not default_membership_type:
        raise Exception(f"No active membership type found for creating membership for {member_name}")
    
    membership = frappe.new_doc("Membership")
    membership.member = member_name
    membership.membership_type = default_membership_type
    membership.start_date = member.member_since or today()
    membership.status = "Active"
    membership.save()
    
    print(f"  Created new membership {membership.name} for {member_name}")
    return membership


def validate_migration():
    """
    Validate that the migration was successful by comparing data
    """
    print("\nValidating migration...")
    
    # Get members with overrides
    # NOTE: membership_fee_override field was removed - this is for legacy data validation only
    try:
        # NOTE: This query will fail as membership_fee_override was removed
        members_with_overrides = frappe.get_all(
            "Member",
            filters={"membership_fee_override": [">", 0]},  # LEGACY: field removed, handled by exception
            fields=["name", "membership_fee_override"]  # LEGACY: field removed
        )
    except Exception:
        print("membership_fee_override field no longer exists - validation skipped")
        return {"matches": 0, "mismatches": 0, "missing": 0}
    
    validation_results = {"matches": 0, "mismatches": 0, "missing": 0}
    
    for member_data in members_with_overrides:
        member_name = member_data["name"]
        override_amount = flt(member_data["membership_fee_override"])
        
        # Check if dues schedule exists
        dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "status": "Active"},
            ["name", "dues_rate"],
            as_dict=True
        )
        
        if not dues_schedule:
            validation_results["missing"] += 1
            print(f"  Missing dues schedule for {member_name}")
        elif flt(dues_schedule.dues_rate) != override_amount:
            validation_results["mismatches"] += 1
            print(f"  Amount mismatch for {member_name}: Override €{override_amount:.2f} vs Schedule €{dues_schedule.dues_rate:.2f}")
        else:
            validation_results["matches"] += 1
    
    print(f"\nValidation results:")
    print(f"  Matches: {validation_results['matches']}")
    print(f"  Mismatches: {validation_results['mismatches']}")
    print(f"  Missing: {validation_results['missing']}")
    
    return validation_results


def create_migration_report():
    """
    Create a detailed migration report
    """
    print("\nGenerating migration report...")
    
    # NOTE: membership_fee_override field was removed - this is for legacy reporting only
    try:
        # NOTE: These queries will fail as membership_fee_override was removed
        total_members_with_overrides = frappe.db.count("Member", {"membership_fee_override": [">", 0]})
        total_override_amount = frappe.db.sql("""
            SELECT SUM(membership_fee_override) 
            FROM `tabMember` 
            WHERE membership_fee_override > 0
        """)[0][0] or 0
    except Exception:
        print("membership_fee_override field no longer exists - reporting legacy data as 0")
        total_members_with_overrides = 0
        total_override_amount = 0
    
    report_data = {
        "migration_date": datetime.now(),
        "total_members_with_overrides": total_members_with_overrides,
        "total_dues_schedules_created": frappe.db.count("Membership Dues Schedule", {"migration_source": "fee_override_migration"}),
        "total_override_amount": total_override_amount,
        "total_migrated_amount": frappe.db.sql("""
            SELECT SUM(dues_rate) 
            FROM `tabMembership Dues Schedule` 
            WHERE migration_source = 'fee_override_migration'
        """)[0][0] or 0
    }
    
    print(f"Migration Report:")
    print(f"  Migration Date: {report_data['migration_date']}")
    print(f"  Members with Overrides: {report_data['total_members_with_overrides']}")
    print(f"  Dues Schedules Created: {report_data['total_dues_schedules_created']}")
    print(f"  Total Override Amount: €{report_data['total_override_amount']:.2f}")
    print(f"  Total Migrated Amount: €{report_data['total_migrated_amount']:.2f}")
    
    # Save report to file
    report_file = f"/tmp/fee_override_migration_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, 'w') as f:
        import json
        json.dump(report_data, f, indent=2, default=str)
    
    print(f"  Report saved to: {report_file}")
    
    return report_data


if __name__ == "__main__":
    # Execute migration
    try:
        # Connect to Frappe
        frappe.init()
        frappe.connect()
        
        # Run migration
        migration_results = migrate_fee_overrides()
        
        # Validate migration
        validation_results = validate_migration()
        
        # Create report
        report_data = create_migration_report()
        
        print(f"\nMigration completed successfully!")
        print(f"Total migrated: {migration_results['migrated']}")
        print(f"Total errors: {migration_results['errors']}")
        
    except Exception as e:
        print(f"Migration failed: {str(e)}")
        frappe.log_error(f"Fee override migration failed: {str(e)}", "Migration Error")
    finally:
        frappe.destroy()