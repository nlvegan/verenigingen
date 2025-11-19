#!/usr/bin/env python3
"""
Production Schema Validation Script
Validates that all database schema changes are properly applied and production-ready.
"""

import frappe
from frappe.utils import now_datetime


@frappe.whitelist()
def validate_production_schema():
    """Comprehensive validation of production schema readiness"""
    
    print("=== Production Schema Validation ===")
    
    results = []
    errors = []
    
    try:
        # 1. Validate Contribution Amendment Request DocType
        print("\n--- Validating Contribution Amendment Request DocType ---")
        
        doctype = frappe.get_doc("DocType", "Contribution Amendment Request")
        
        # Check required new fields
        required_fields = [
            "new_dues_schedule",
            "current_dues_schedule",
            "current_amount",
            "current_billing_interval",
            "legacy_data_migrated",
            "processing_notes"
        ]
        
        existing_fields = [field.fieldname for field in doctype.fields]
        
        for field in required_fields:
            if field in existing_fields:
                results.append(f"✓ Field '{field}' exists in Contribution Amendment Request")
            else:
                errors.append(f"❌ Field '{field}' missing from Contribution Amendment Request")
        
        # Check field properties
        for field in doctype.fields:
            if field.fieldname == "new_dues_schedule":
                if field.fieldtype == "Link" and field.options == "Membership Dues Schedule":
                    results.append("✓ new_dues_schedule field properly configured")
                else:
                    errors.append(f"❌ new_dues_schedule field configuration incorrect: {field.fieldtype}, {field.options}")
            
            if field.fieldname == "current_dues_schedule":
                if field.fieldtype == "Link" and field.options == "Membership Dues Schedule":
                    results.append("✓ current_dues_schedule field properly configured")
                else:
                    errors.append(f"❌ current_dues_schedule field configuration incorrect: {field.fieldtype}, {field.options}")
        
        # 2. Validate Membership Dues Schedule DocType
        print("\n--- Validating Membership Dues Schedule DocType ---")
        
        if frappe.db.exists("DocType", "Membership Dues Schedule"):
            results.append("✓ Membership Dues Schedule DocType exists")
            
            mds_doctype = frappe.get_doc("DocType", "Membership Dues Schedule")
            
            # Check required fields
            mds_required_fields = [
                "member",
                "membership",
                "membership_type",
                "amount",
                "contribution_mode",
                "status",
                "uses_custom_amount",
                "custom_amount_approved",
                "custom_amount_reason",
                "effective_date",
                "billing_frequency",
                "payment_method"
            ]
            
            mds_existing_fields = [field.fieldname for field in mds_doctype.fields]
            
            for field in mds_required_fields:
                if field in mds_existing_fields:
                    results.append(f"✓ Field '{field}' exists in Membership Dues Schedule")
                else:
                    errors.append(f"❌ Field '{field}' missing from Membership Dues Schedule")
        else:
            errors.append("❌ Membership Dues Schedule DocType does not exist")
        
        # 3. Validate Database Tables
        print("\n--- Validating Database Tables ---")
        
        # Check if tables exist
        tables_to_check = [
            "tabContribution Amendment Request",
            "tabMembership Dues Schedule"
        ]
        
        for table in tables_to_check:
            if frappe.db.table_exists(table):
                results.append(f"✓ Database table '{table}' exists")
            else:
                errors.append(f"❌ Database table '{table}' does not exist")
        
        # 4. Validate Database Columns
        print("\n--- Validating Database Columns ---")
        
        # Check Contribution Amendment Request table columns
        try:
            columns = frappe.db.sql("""
                SHOW COLUMNS FROM `tabContribution Amendment Request` 
                WHERE Field IN ('new_dues_schedule', 'current_dues_schedule', 'current_amount')
            """, as_dict=True)
            
            column_names = [col['Field'] for col in columns]
            
            if 'new_dues_schedule' in column_names:
                results.append("✓ Database column 'new_dues_schedule' exists")
            else:
                errors.append("❌ Database column 'new_dues_schedule' missing")
            
            if 'current_dues_schedule' in column_names:
                results.append("✓ Database column 'current_dues_schedule' exists")
            else:
                errors.append("❌ Database column 'current_dues_schedule' missing")
            
            if 'current_amount' in column_names:
                results.append("✓ Database column 'current_amount' exists")
            else:
                errors.append("❌ Database column 'current_amount' missing")
                
        except Exception as e:
            errors.append(f"❌ Error checking database columns: {str(e)}")
        
        # 5. Validate Permissions
        print("\n--- Validating Permissions ---")
        
        # Check if required roles can access the doctypes
        roles_to_check = ["System Manager", "Verenigingen Administrator"]
        
        for role in roles_to_check:
            # Check Contribution Amendment Request permissions
            car_perms = frappe.db.get_all("DocPerm", 
                filters={"parent": "Contribution Amendment Request", "role": role},
                fields=["read", "write", "create", "delete"])
            
            if car_perms:
                results.append(f"✓ Role '{role}' has permissions for Contribution Amendment Request")
            else:
                errors.append(f"❌ Role '{role}' missing permissions for Contribution Amendment Request")
            
            # Check Membership Dues Schedule permissions
            mds_perms = frappe.db.get_all("DocPerm",
                filters={"parent": "Membership Dues Schedule", "role": role},
                fields=["read", "write", "create", "delete"])
            
            if mds_perms:
                results.append(f"✓ Role '{role}' has permissions for Membership Dues Schedule")
            else:
                errors.append(f"❌ Role '{role}' missing permissions for Membership Dues Schedule")
        
        # 6. Validate Custom Methods
        print("\n--- Validating Custom Methods ---")
        
        # Check if custom methods exist on the class
        test_doc = frappe.new_doc("Contribution Amendment Request")
        
        methods_to_check = [
            "create_dues_schedule_for_amendment",
            "set_current_details",
            "apply_fee_change",
            "get_current_amount"
        ]
        
        for method in methods_to_check:
            if hasattr(test_doc, method):
                results.append(f"✓ Method '{method}' exists on Contribution Amendment Request")
            else:
                errors.append(f"❌ Method '{method}' missing from Contribution Amendment Request")
        
        # 7. Validate API Endpoints
        print("\n--- Validating API Endpoints ---")
        
        # Check if whitelisted functions exist (updated for dues schedule system)
        whitelisted_functions = [
            "verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request.test_enhanced_approval_workflows",
            "verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request.process_pending_amendments",
            "verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request.create_fee_change_amendment"
        ]
        
        for func in whitelisted_functions:
            try:
                frappe.get_attr(func)
                results.append(f"✓ Whitelisted function '{func}' exists")
            except AttributeError:
                errors.append(f"❌ Whitelisted function '{func}' missing")
            except Exception as e:
                errors.append(f"❌ Error checking function '{func}': {str(e)}")
        
        # 8. Validate Data Integrity
        print("\n--- Validating Data Integrity ---")
        
        # Check if there are any existing records and validate their structure
        car_count = frappe.db.count("Contribution Amendment Request")
        mds_count = frappe.db.count("Membership Dues Schedule")
        
        results.append(f"✓ Found {car_count} Contribution Amendment Request records")
        results.append(f"✓ Found {mds_count} Membership Dues Schedule records")
        
        # Check for orphaned records
        orphaned_car = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabContribution Amendment Request` car
            LEFT JOIN `tabMembership` m ON car.membership = m.name
            WHERE m.name IS NULL AND car.membership IS NOT NULL
        """, as_dict=True)
        
        if orphaned_car[0]['count'] == 0:
            results.append("✓ No orphaned Contribution Amendment Request records")
        else:
            errors.append(f"❌ Found {orphaned_car[0]['count']} orphaned Contribution Amendment Request records")
        
        # 9. Validate Indexes
        print("\n--- Validating Database Indexes ---")
        
        # Check if important indexes exist
        indexes_to_check = [
            ("tabContribution Amendment Request", "member"),
            ("tabContribution Amendment Request", "membership"),
            ("tabContribution Amendment Request", "status"),
            ("tabMembership Dues Schedule", "member"),
            ("tabMembership Dues Schedule", "membership"),
            ("tabMembership Dues Schedule", "status")
        ]
        
        for table, column in indexes_to_check:
            indexes = frappe.db.sql(f"""
                SHOW INDEX FROM `{table}` WHERE Column_name = '{column}'
            """, as_dict=True)
            
            if indexes:
                results.append(f"✓ Index exists for {table}.{column}")
            else:
                results.append(f"! Index missing for {table}.{column} (may impact performance)")
        
        # 10. Summary
        print("\n=== Validation Summary ===")
        
        print(f"✅ Successful validations: {len(results)}")
        print(f"❌ Errors found: {len(errors)}")
        
        if errors:
            print("\n🚨 ERRORS THAT MUST BE FIXED:")
            for error in errors:
                print(f"  {error}")
        
        print("\n✅ SUCCESSFUL VALIDATIONS:")
        for result in results:
            print(f"  {result}")
        
        # Return results
        return {
            "success": len(errors) == 0,
            "total_checks": len(results) + len(errors),
            "successful_checks": len(results),
            "errors": len(errors),
            "error_details": errors,
            "results": results,
            "ready_for_production": len(errors) == 0
        }
        
    except Exception as e:
        error_msg = f"Fatal error during validation: {str(e)}"
        print(f"❌ {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "ready_for_production": False
        }


@frappe.whitelist()
def create_production_indexes():
    """Create recommended database indexes for production performance"""
    
    print("=== Creating Production Indexes ===")
    
    indexes_to_create = [
        ("tabContribution Amendment Request", "member", "idx_car_member"),
        ("tabContribution Amendment Request", "membership", "idx_car_membership"),
        ("tabContribution Amendment Request", "status", "idx_car_status"),
        ("tabContribution Amendment Request", "effective_date", "idx_car_effective_date"),
        ("tabMembership Dues Schedule", "member", "idx_mds_member"),
        ("tabMembership Dues Schedule", "membership", "idx_mds_membership"),
        ("tabMembership Dues Schedule", "status", "idx_mds_status"),
        ("tabMembership Dues Schedule", "effective_date", "idx_mds_effective_date")
    ]
    
    created_indexes = []
    errors = []
    
    for table, column, index_name in indexes_to_create:
        try:
            # Check if index already exists
            existing_indexes = frappe.db.sql(f"""
                SHOW INDEX FROM `{table}` WHERE Column_name = '{column}'
            """, as_dict=True)
            
            if not existing_indexes:
                # Create index
                frappe.db.sql(f"""
                    CREATE INDEX `{index_name}` ON `{table}` (`{column}`)
                """)
                created_indexes.append(f"✓ Created index {index_name} on {table}.{column}")
                print(f"✓ Created index {index_name} on {table}.{column}")
            else:
                created_indexes.append(f"✓ Index already exists on {table}.{column}")
                print(f"✓ Index already exists on {table}.{column}")
                
        except Exception as e:
            error_msg = f"❌ Error creating index {index_name}: {str(e)}"
            errors.append(error_msg)
            print(error_msg)
    
    return {
        "success": len(errors) == 0,
        "created_indexes": created_indexes,
        "errors": errors
    }


@frappe.whitelist()
def validate_production_data():
    """Validate existing data integrity for production readiness"""
    
    print("=== Production Data Validation ===")
    
    results = []
    errors = []
    
    try:
        # 1. Check for data consistency
        print("\n--- Checking Data Consistency ---")
        
        # Check for members with dues schedules
        members_with_dues = frappe.db.sql("""
            SELECT COUNT(DISTINCT m.name) as count
            FROM `tabMember` m
            INNER JOIN `tabMembership Dues Schedule` mds ON m.name = mds.member
            WHERE mds.status = 'Active'
        """, as_dict=True)
        
        total_active_members = frappe.db.count("Member", {"status": "Active"})
        
        results.append(f"✓ Found {members_with_dues[0]['count']} members with active dues schedules")
        results.append(f"✓ Total active members: {total_active_members}")
        
        # Check for members with legacy override fields (deprecated)
        members_with_overrides = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabMember`
            WHERE dues_rate IS NOT NULL AND dues_rate > 0
        """, as_dict=True)
        
        results.append(f"✓ Found {members_with_overrides[0]['count']} members with legacy override fields (deprecated system)")
        
        # 2. Check for invalid amounts
        print("\n--- Checking for Invalid Amounts ---")
        
        invalid_amounts = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabMembership Dues Schedule`
            WHERE amount < 0
        """, as_dict=True)
        
        if invalid_amounts[0]['count'] == 0:
            results.append("✓ No invalid negative amounts found")
        else:
            errors.append(f"❌ Found {invalid_amounts[0]['count']} dues schedules with negative amounts")
        
        # 3. Check for orphaned records
        print("\n--- Checking for Orphaned Records ---")
        
        # Orphaned dues schedules
        orphaned_dues = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabMembership Dues Schedule` mds
            LEFT JOIN `tabMember` m ON mds.member = m.name
            WHERE m.name IS NULL
        """, as_dict=True)
        
        if orphaned_dues[0]['count'] == 0:
            results.append("✓ No orphaned dues schedules found")
        else:
            errors.append(f"❌ Found {orphaned_dues[0]['count']} orphaned dues schedules")
        
        # 4. Check for duplicate active dues schedules
        print("\n--- Checking for Duplicate Active Dues Schedules ---")
        
        duplicate_active = frappe.db.sql("""
            SELECT member, COUNT(*) as count
            FROM `tabMembership Dues Schedule`
            WHERE status = 'Active'
            GROUP BY member
            HAVING count > 1
        """, as_dict=True)
        
        if not duplicate_active:
            results.append("✓ No duplicate active dues schedules found")
        else:
            errors.append(f"❌ Found {len(duplicate_active)} members with multiple active dues schedules")
        
        # 5. Check for missing required fields
        print("\n--- Checking for Missing Required Fields ---")
        
        missing_member_fields = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM `tabMembership Dues Schedule`
            WHERE member IS NULL OR member = ''
        """, as_dict=True)
        
        if missing_member_fields[0]['count'] == 0:
            results.append("✓ All dues schedules have member references")
        else:
            errors.append(f"❌ Found {missing_member_fields[0]['count']} dues schedules without member references")
        
        # Summary
        print("\n=== Data Validation Summary ===")
        
        print(f"✅ Successful validations: {len(results)}")
        print(f"❌ Errors found: {len(errors)}")
        
        if errors:
            print("\n🚨 DATA ERRORS THAT MUST BE FIXED:")
            for error in errors:
                print(f"  {error}")
        
        return {
            "success": len(errors) == 0,
            "results": results,
            "errors": errors,
            "data_ready_for_production": len(errors) == 0
        }
        
    except Exception as e:
        error_msg = f"Fatal error during data validation: {str(e)}"
        print(f"❌ {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "data_ready_for_production": False
        }


if __name__ == "__main__":
    # Run validation when script is executed directly
    print("Running production schema validation...")
    result = validate_production_schema()
    
    if result["success"]:
        print("\n🎉 Schema validation passed! System is ready for production.")
    else:
        print("\n🚨 Schema validation failed! Please fix errors before production deployment.")
        exit(1)