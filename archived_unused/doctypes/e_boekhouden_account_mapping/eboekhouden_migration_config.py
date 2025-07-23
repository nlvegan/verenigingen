"""
E-Boekhouden Migration Configuration Page
Provides a user interface for step-by-step migration with manual account mapping overrides
"""

import json

import frappe
from frappe import _


def get_context(context):
    """
    Setup context for the migration configuration page
    """
    # Check permissions
    if not frappe.has_permission("E-Boekhouden Migration", "read"):
        frappe.throw(_("You do not have permission to access this page"))

    # Get E-Boekhouden settings
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        if not settings.api_token:
            frappe.throw(_("E-Boekhouden Settings not configured. Please configure API token first."))
    except Exception:
        frappe.throw(_("E-Boekhouden Settings not found. Please configure the integration first."))

    # Set page context
    context.title = _("E-Boekhouden Migration Configuration")
    context.show_sidebar = True
    context.no_cache = 1

    # Get configuration status
    context.configuration_status = get_configuration_status()

    return context


@frappe.whitelist()
def get_configuration_status():
    """
    Get the current configuration status for the migration
    """
    try:
        settings = frappe.get_single("E-Boekhouden Settings")

        status = {
            "api_configured": bool(settings.api_token),
            "default_company": settings.default_company,
            "has_staged_data": False,
            "staging_data_date": None,
            "mapping_configurations": 0,
            "ready_for_migration": False,
        }

        # Check if we have staged data
        staging_data = frappe.db.get_value(
            "E-Boekhouden Migration", {"migration_status": "Staged"}, ["name", "modified"], as_dict=True
        )

        if staging_data:
            status["has_staged_data"] = True
            status["staging_data_date"] = staging_data.modified

        # Check mapping configurations
        mapping_count = frappe.db.count("E-Boekhouden Account Mapping")
        status["mapping_configurations"] = mapping_count

        # Determine if ready for migration
        status["ready_for_migration"] = (
            status["api_configured"]
            and status["default_company"]
            and (status["has_staged_data"] or mapping_count > 0)
        )

        return status

    except Exception as e:
        frappe.log_error(f"Error getting configuration status: {str(e)}")
        return {"api_configured": False, "ready_for_migration": False, "error": str(e)}


@frappe.whitelist()
def stage_data_for_configuration():
    """
    Stage E-Boekhouden data for manual configuration
    """
    try:
        settings = frappe.get_single("E-Boekhouden Settings")

        # Create a staging migration document
        migration = frappe.new_doc("E-Boekhouden Migration")
        migration.migration_name = f"Configuration Staging {frappe.utils.now()}"
        migration.migration_type = "Data Staging"
        migration.company = settings.default_company
        migration.migration_status = "Staging"
        migration.insert(ignore_permissions=True)

        # Call the staging function from the main migration
        from verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration import (
            stage_eboekhouden_data,
        )

        result = stage_eboekhouden_data(migration, settings)

        if result.get("success"):
            migration.db_set("migration_status", "Staged")
            migration.db_set("migration_log", json.dumps(result.get("staging_summary", {}), indent=2))
            frappe.db.commit()

            return {
                "success": True,
                "migration_id": migration.name,
                "staging_summary": result.get("staging_summary", {}),
                "message": "Data staged successfully for configuration",
            }
        else:
            migration.db_set("migration_status", "Failed")
            migration.db_set("error_log", result.get("error", "Unknown error"))
            frappe.db.commit()

            return {"success": False, "error": result.get("error", "Failed to stage data")}

    except Exception as e:
        frappe.log_error(f"Error staging data: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_staging_data():
    """
    Get staged data for configuration review
    """
    try:
        # Find the most recent staged migration
        migration = frappe.db.get_value(
            "E-Boekhouden Migration",
            {"migration_status": "Staged"},
            ["name", "error_log"],
            as_dict=True,
            order_by="creation desc",
        )

        if not migration:
            return {"success": False, "error": "No staged data found. Please stage data first."}

        # Get the staging data from the migration
        from verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration import (
            get_staging_data_for_review,
        )

        staging_data = get_staging_data_for_review(migration.name)

        return {"success": True, "migration_id": migration.name, "staging_data": staging_data}

    except Exception as e:
        frappe.log_error(f"Error getting staging data: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def create_account_mapping(account_code, account_type, confidence_level="manual", notes=""):
    """
    Create a manual account mapping override
    """
    try:
        # Check if mapping already exists
        existing = frappe.db.exists("E-Boekhouden Account Mapping", {"account_code": account_code})

        if existing:
            # Update existing mapping
            mapping = frappe.get_doc("E-Boekhouden Account Mapping", existing)
            mapping.account_type = account_type
            mapping.confidence_level = confidence_level
            mapping.notes = notes
            mapping.save(ignore_permissions=True)
            action = "updated"
        else:
            # Create new mapping
            mapping = frappe.new_doc("E-Boekhouden Account Mapping")
            mapping.account_code = account_code
            mapping.account_type = account_type
            mapping.confidence_level = confidence_level
            mapping.notes = notes
            mapping.insert(ignore_permissions=True)
            action = "created"

        frappe.db.commit()

        return {
            "success": True,
            "mapping_id": mapping.name,
            "action": action,
            "message": f"Account mapping {action} successfully",
        }

    except Exception as e:
        frappe.log_error(f"Error creating account mapping: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_account_mappings():
    """
    Get all existing account mappings
    """
    try:
        mappings = frappe.get_all(
            "E-Boekhouden Account Mapping",
            fields=[
                "name",
                "account_code",
                "account_name",
                "account_type",
                "confidence_level",
                "notes",
                "creation",
                "modified",
            ],
            order_by="account_code",
        )

        return {"success": True, "mappings": mappings, "total": len(mappings)}

    except Exception as e:
        frappe.log_error(f"Error getting account mappings: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def delete_account_mapping(mapping_id):
    """
    Delete an account mapping
    """
    try:
        frappe.delete_doc("E-Boekhouden Account Mapping", mapping_id, ignore_permissions=True)
        frappe.db.commit()

        return {"success": True, "message": "Account mapping deleted successfully"}

    except Exception as e:
        frappe.log_error(f"Error deleting account mapping: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def preview_migration_impact():
    """
    Preview what will be created with current configuration
    """
    try:
        # Find the most recent staged migration
        migration = frappe.db.get_value(
            "E-Boekhouden Migration", {"migration_status": "Staged"}, "name", order_by="creation desc"
        )

        if not migration:
            return {"success": False, "error": "No staged data found. Please stage data first."}

        # Get preview from the migration
        from verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration import (
            preview_mapping_impact,
        )

        preview = preview_mapping_impact(migration)

        return {"success": True, "migration_id": migration, "preview": preview}

    except Exception as e:
        frappe.log_error(f"Error previewing migration impact: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def start_configured_migration():
    """
    Start migration with current configuration
    """
    try:
        # Find the most recent staged migration
        migration_name = frappe.db.get_value(
            "E-Boekhouden Migration", {"migration_status": "Staged"}, "name", order_by="creation desc"
        )

        if not migration_name:
            return {"success": False, "error": "No staged data found. Please stage data first."}

        # Update migration status and start
        migration = frappe.get_doc("E-Boekhouden Migration", migration_name)
        migration.migration_status = "Ready"
        migration.save(ignore_permissions=True)

        # Start the migration
        from verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration import (
            approve_and_continue_migration,
        )

        result = approve_and_continue_migration(migration_name)

        if result.get("success"):
            return {
                "success": True,
                "migration_id": migration_name,
                "message": "Migration started successfully",
            }
        else:
            return {"success": False, "error": result.get("error", "Failed to start migration")}

    except Exception as e:
        frappe.log_error(f"Error starting configured migration: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_migration_progress(migration_id):
    """
    Get migration progress for a specific migration
    """
    try:
        migration = frappe.get_doc("E-Boekhouden Migration", migration_id)

        return {
            "success": True,
            "migration_status": migration.migration_status,
            "progress_percentage": migration.progress_percentage or 0,
            "current_operation": migration.current_operation or "",
            "imported_records": migration.imported_records or 0,
            "failed_records": migration.failed_records or 0,
            "start_time": migration.start_time,
            "end_time": migration.end_time,
        }

    except Exception as e:
        frappe.log_error(f"Error getting migration progress: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def export_configuration():
    """
    Export current configuration for backup/sharing
    """
    try:
        mappings = frappe.get_all(
            "E-Boekhouden Account Mapping",
            fields=["account_code", "account_name", "account_type", "confidence_level", "notes"],
        )

        config = {"export_date": frappe.utils.now(), "mappings": mappings, "total_mappings": len(mappings)}

        return {
            "success": True,
            "configuration": config,
            "filename": f"eboekhouden_config_{frappe.utils.today()}.json",
        }

    except Exception as e:
        frappe.log_error(f"Error exporting configuration: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def import_configuration(config_json):
    """
    Import configuration from exported JSON
    """
    try:
        config = json.loads(config_json) if isinstance(config_json, str) else config_json

        imported_count = 0
        errors = []

        for mapping_data in config.get("mappings", []):
            try:
                result = create_account_mapping(
                    mapping_data["account_code"],
                    mapping_data["account_type"],
                    mapping_data.get("confidence_level", "imported"),
                    mapping_data.get("notes", ""),
                )

                if result["success"]:
                    imported_count += 1
                else:
                    errors.append(f"Account {mapping_data['account_code']}: {result['error']}")

            except Exception as e:
                errors.append(f"Account {mapping_data.get('account_code', 'unknown')}: {str(e)}")

        return {
            "success": len(errors) == 0,
            "imported_count": imported_count,
            "errors": errors,
            "message": f"Imported {imported_count} mappings"
            + (f" with {len(errors)} errors" if errors else ""),
        }

    except Exception as e:
        frappe.log_error(f"Error importing configuration: {str(e)}")
        return {"success": False, "error": str(e)}
