"""
E-Boekhouden Migration API Utilities

Conservative refactor: These API functions were moved from the main migration file
for better organization. All original logic is preserved exactly as-is.
"""

import json

import frappe


@frappe.whitelist()
def start_migration_api(migration_name, dry_run=1):
    """API method to start migration process"""
    try:
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
        if migration.migration_status != "Draft":
            return {"success": False, "error": "Migration must be in Draft status to start"}

        # Update migration settings and initialize counters
        migration.dry_run = int(dry_run)
        migration.migration_status = "In Progress"
        migration.start_time = frappe.utils.now_datetime()
        migration.current_operation = "Initializing migration..."
        migration.progress_percentage = 0

        # Initialize counters
        migration.total_records = 0
        migration.imported_records = 0
        migration.failed_records = 0

        migration.save()
        frappe.db.commit()

        # Start the actual migration in background
        frappe.enqueue(
            method="vereininggen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration.run_migration_background",
            queue="long",
            timeout=3600,
            migration_name=migration_name,
        )

        return {"success": True, "message": "Migration started successfully"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def start_migration(migration_name, setup_only=False):
    """Start migration with optional setup-only mode"""
    try:
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)

        if migration.migration_status not in ["Draft", "Setup Complete"]:
            return {"success": False, "error": "Migration must be in Draft or Setup Complete status"}

        # Update status
        migration.migration_status = "In Progress"
        migration.start_time = frappe.utils.now_datetime()
        migration.current_operation = "Starting migration process..."
        migration.progress_percentage = 0
        migration.save()
        frappe.db.commit()

        if setup_only:
            # Only run setup phase (accounts, cost centers)
            migration.current_operation = "Setup phase only - running chart of accounts import..."
            migration.save()
            frappe.db.commit()

            # Call the actual migration method
            migration.start_migration()

            migration.migration_status = "Setup Complete"
            migration.current_operation = "Setup completed - ready for transaction import"
            migration.save()
            frappe.db.commit()

            return {"success": True, "message": "Setup phase completed successfully"}
        else:
            # Run full migration
            migration.start_migration()
            return {"success": True, "message": "Migration completed successfully"}

    except Exception as e:
        frappe.logger().error(f"Migration failed: {str(e)}")
        return {"success": False, "error": str(e)}


def run_migration_background(migration_name, setup_only=False):
    """Background task to run migration"""
    try:
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
        migration.start_migration()

        migration.db_set(
            {
                "migration_status": "Completed",
                "end_time": frappe.utils.now_datetime(),
                "current_operation": "Migration completed successfully",
                "progress_percentage": 100,
            }
        )
        frappe.db.commit()

    except Exception as e:
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
        migration.db_set(
            {
                "migration_status": "Failed",
                "current_operation": f"Migration failed: {str(e)}",
                "end_time": frappe.utils.now_datetime(),
            }
        )
        frappe.db.commit()
        raise


@frappe.whitelist()
def get_staging_data_for_review(migration_name):
    """Get staged data for manual review and configuration"""
    try:
        migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)

        if not migration_doc.staging_data:
            return {"success": False, "error": "No staging data found. Please run data staging first."}

        staging_data = json.loads(migration_doc.staging_data)

        return {
            "success": True,
            "staging_data": staging_data,
            "migration_status": migration_doc.migration_status,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def create_manual_account_mapping(
    migration_name, eboekhouden_code, erpnext_account, account_type, notes=None
):
    """Create manual account mapping override"""
    try:
        # Check if mapping already exists
        existing = frappe.db.exists("E-Boekhouden Ledger Mapping", {"eboekhouden_code": eboekhouden_code})

        if existing:
            return {
                "success": False,
                "error": f"Mapping for E-Boekhouden code {eboekhouden_code} already exists",
            }

        # Create new mapping
        mapping = frappe.new_doc("E-Boekhouden Ledger Mapping")
        mapping.eboekhouden_code = eboekhouden_code
        mapping.erpnext_account = erpnext_account
        mapping.account_type = account_type
        mapping.notes = notes or f"Manual mapping created for migration {migration_name}"
        mapping.is_manual = 1
        mapping.save()

        return {"success": True, "message": f"Manual mapping created for code {eboekhouden_code}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def preview_mapping_impact(migration_name, account_mappings):
    """Preview the impact of proposed account mappings"""
    try:
        migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)

        if not migration_doc.staging_data:
            return {"success": False, "error": "No staging data available for impact analysis"}

        staging_data = json.loads(migration_doc.staging_data)

        # Analyze impact of proposed mappings
        impact_analysis = {
            "total_transactions_affected": 0,
            "accounts_mapped": len(account_mappings),
            "mapping_details": [],
            "potential_issues": [],
        }

        # Check each proposed mapping
        for mapping in account_mappings:
            eboekhouden_code = mapping.get("eboekhouden_code")
            erpnext_account = mapping.get("erpnext_account")

            # Count transactions that would be affected
            affected_count = 0
            for mutation in staging_data.get("sample_mutations", []):
                for line in mutation.get("MutatieRegels", []):
                    if line.get("TegenrekeningCode") == eboekhouden_code:
                        affected_count += 1

            impact_analysis["mapping_details"].append(
                {
                    "eboekhouden_code": eboekhouden_code,
                    "erpnext_account": erpnext_account,
                    "transactions_affected": affected_count,
                }
            )

            impact_analysis["total_transactions_affected"] += affected_count

            # Check if ERPNext account exists
            if not frappe.db.exists("Account", erpnext_account):
                impact_analysis["potential_issues"].append(
                    f"ERPNext account '{erpnext_account}' does not exist"
                )

        return {"success": True, "impact_analysis": impact_analysis}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def approve_and_continue_migration(migration_name):
    """Approve staging data and continue with full migration"""
    try:
        migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)

        if migration_doc.migration_status != "Data Staged":
            return {"success": False, "error": "Migration must be in 'Data Staged' status to continue"}

        # Update status to indicate approval
        migration_doc.migration_status = "Approved"
        migration_doc.current_operation = "Configuration approved - starting full migration..."
        migration_doc.progress_percentage = 45
        migration_doc.save()
        frappe.db.commit()

        # Start full migration process
        migration_doc.start_migration()

        return {"success": True, "message": "Migration approved and started successfully"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_current_account_mappings(company):
    """Get current account mappings for review"""
    mappings = frappe.get_all(
        "E-Boekhouden Ledger Mapping",
        fields=["eboekhouden_code", "erpnext_account", "account_type", "is_manual", "notes"],
        order_by="eboekhouden_code",
    )

    return mappings


def assess_configuration_status(company, staging_data):
    """Assess if configuration is ready for migration"""
    status = {"ready_for_migration": True, "issues": [], "recommendations": []}

    # Check if required mappings exist
    required_accounts = staging_data.get("mapping_analysis", {}).get("account_usage", {})

    for account_code in required_accounts.keys():
        mapping_exists = frappe.db.exists("E-Boekhouden Ledger Mapping", {"eboekhouden_code": account_code})

        if not mapping_exists:
            status["issues"].append(f"Missing mapping for E-Boekhouden account {account_code}")
            status["ready_for_migration"] = False

    # Check company configuration
    company_doc = frappe.get_doc("Company", company)
    if not company_doc.default_bank_account:
        status["issues"].append("Company default bank account not configured")
        status["ready_for_migration"] = False

    return status
