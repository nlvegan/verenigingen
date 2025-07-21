"""
E-Boekhouden Migration Statistics and Redesign Functions
"""

import re

import frappe
from frappe import _


@frappe.whitelist()
def get_migration_statistics():
    """
    Get statistics about E-Boekhouden migrations

    Returns:
        Dict with statistics
    """
    if not frappe.has_permission("E-Boekhouden Migration", "read"):
        frappe.throw(_("Insufficient permissions"))

    try:
        stats = {
            "total_migrations": frappe.db.count("E-Boekhouden Migration"),
            "successful_migrations": 0,
            "failed_migrations": 0,
            "total_imported": {
                "sales_invoices": 0,
                "purchase_invoices": 0,
                "payments": 0,
                "journal_entries": 0,
            },
            "total_errors": 0,
            "common_errors": {},
        }

        # Get all migrations
        migrations = frappe.db.get_all(
            "E-Boekhouden Migration", fields=["name", "migration_status", "migration_summary"]
        )

        for migration in migrations:
            if migration.migration_status == "Completed":
                stats["successful_migrations"] += 1
            else:
                stats["failed_migrations"] += 1

            # Parse summary if available
            if migration.import_summary:
                try:
                    # Extract counts from summary
                    summary = migration.import_summary

                    # Sales invoices
                    match = re.search(r"sales.*?invoices.*?created.*?(\d+)", summary, re.IGNORECASE)
                    if match:
                        stats["total_imported"]["sales_invoices"] += int(match.group(1))

                    # Purchase invoices
                    match = re.search(r"purchase.*?invoices.*?created.*?(\d+)", summary, re.IGNORECASE)
                    if match:
                        stats["total_imported"]["purchase_invoices"] += int(match.group(1))

                    # Payments
                    match = re.search(r"payments.*?processed.*?(\d+)", summary, re.IGNORECASE)
                    if match:
                        stats["total_imported"]["payments"] += int(match.group(1))

                    # Journal entries
                    match = re.search(r"journal.*?entries.*?created.*?(\d+)", summary, re.IGNORECASE)
                    if match:
                        stats["total_imported"]["journal_entries"] += int(match.group(1))

                    # Errors
                    match = re.search(r"System Errors.*?(\d+)", summary)
                    if match:
                        stats["total_errors"] += int(match.group(1))

                except Exception:
                    pass

        return stats

    except Exception as e:
        frappe.log_error(f"Error getting migration statistics: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
def validate_migration_readiness():
    """
    Validate if the system is ready for E-Boekhouden migration

    Returns:
        Dict with validation results
    """
    if not frappe.has_permission("E-Boekhouden Migration", "read"):
        frappe.throw(_("Insufficient permissions"))

    validation = {"ready": True, "issues": [], "warnings": []}

    try:
        # Check E-Boekhouden settings
        settings = frappe.get_single("E-Boekhouden Settings")
        if not settings:
            validation["ready"] = False
            validation["issues"].append("E-Boekhouden Settings not configured")
            return validation

        # Check API credentials
        if not settings.username or not settings.password:
            validation["ready"] = False
            validation["issues"].append("E-Boekhouden API credentials not configured")

        # Check company
        if not settings.default_company:
            validation["ready"] = False
            validation["issues"].append("Default company not set in E-Boekhouden Settings")

        # Check if company exists
        if settings.default_company and not frappe.db.exists("Company", settings.default_company):
            validation["ready"] = False
            validation["issues"].append(f"Company '{settings.default_company}' does not exist")

        # Check for required accounts
        if settings.default_company:
            # Check for receivable accounts
            receivable_accounts = frappe.db.count(
                "Account", {"company": settings.default_company, "account_type": "Receivable", "is_group": 0}
            )

            if receivable_accounts == 0:
                validation["warnings"].append("No receivable accounts found")

            # Check for payable accounts
            payable_accounts = frappe.db.count(
                "Account", {"company": settings.default_company, "account_type": "Payable", "is_group": 0}
            )

            if payable_accounts == 0:
                validation["warnings"].append("No payable accounts found")

        # Check for missing customers/suppliers
        if settings.default_company:
            customers = frappe.db.count("Customer", {"company": settings.default_company})
            suppliers = frappe.db.count("Supplier", {"company": settings.default_company})

            if customers == 0:
                validation["warnings"].append("No customers found - they will be created during migration")

            if suppliers == 0:
                validation["warnings"].append("No suppliers found - they will be created during migration")

        # Check account types
        if settings.default_company:
            bank_accounts = frappe.db.count(
                "Account", {"company": settings.default_company, "account_type": "Bank", "is_group": 0}
            )

            if bank_accounts == 0:
                validation["warnings"].append("No bank accounts configured")

    except Exception as e:
        validation["ready"] = False
        validation["issues"].append(f"Validation error: {str(e)}")

    return validation
