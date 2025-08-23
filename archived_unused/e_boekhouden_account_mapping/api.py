"""
E-Boekhouden Migration Configuration API
Handles staging, account mapping configuration, and step-by-step migration
"""

import json
from datetime import datetime

import frappe
from frappe import _


@frappe.whitelist()
def get_migration_config_status():
    """Get the current status of migration configuration"""
    try:
        # Check for staged data
        staged_data = get_staged_data_from_cache()
        staged_data_exists = staged_data is not None
        staged_count = len(staged_data.get("transactions", [])) if staged_data else 0

        # Get existing mappings
        mappings = frappe.get_all(
            "E-Boekhouden Account Mapping",
            fields=[
                "name",
                "account_code",
                "account_name",
                "document_type",
                "category",
                "confidence",
                "is_active",
            ],
        )

        # Get last staging date from cache
        last_staging_date = frappe.cache().get_value("ebh_last_staging_date")

        return {
            "staged_data_exists": staged_data_exists,
            "staged_count": staged_count,
            "staged_data": staged_data,
            "mappings": mappings,
            "mappings_count": len(mappings),
            "last_staging_date": last_staging_date,
        }
    except Exception as e:
        frappe.log_error(f"Error getting config status: {str(e)}", "E-Boekhouden Config")
        frappe.throw(_("Failed to get configuration status"))


@frappe.whitelist()
def stage_eboekhouden_data(from_date, to_date):
    """Stage E-Boekhouden data for configuration"""
    try:
        from verenigingen.utils.eboekhouden.eboekhouden_api import EBoekhoudenAPI

        settings = frappe.get_single("E-Boekhouden Settings")
        if not settings.api_token:
            frappe.throw(_("E-Boekhouden API not configured"))

        api = EBoekhoudenAPI(settings)

        # Fetch transactions
        transactions = []
        accounts = {}
        offset = 0
        limit = 100

        while True:
            params = {"from_date": from_date, "to_date": to_date, "limit": limit, "offset": offset}

            result = api.get_mutations(params)
            if not result["success"]:
                frappe.throw(_("Failed to fetch data from E-Boekhouden"))

            data = json.loads(result["data"])
            items = data.get("items", [])

            if not items:
                break

            transactions.extend(items)

            # Collect unique accounts
            for item in items:
                account_code = item.get("account", {}).get("code")
                if account_code and account_code not in accounts:
                    accounts[account_code] = {
                        "code": account_code,
                        "name": item.get("account", {}).get("name", ""),
                        "count": 0,
                        "total": 0,
                    }

                if account_code:
                    accounts[account_code]["count"] += 1
                    accounts[account_code]["total"] += float(item.get("amount", 0))

            offset += limit

            # Safety limit
            if offset > 10000:
                break

        # Store in cache for later processing
        staged_data = {
            "transactions": transactions,
            "accounts": list(accounts.values()),
            "from_date": from_date,
            "to_date": to_date,
            "staging_time": datetime.now().isoformat(),
        }

        # Store in cache with 24-hour expiry
        frappe.cache().set_value("ebh_staged_data", staged_data, expires_in_sec=86400)
        frappe.cache().set_value("ebh_last_staging_date", datetime.now().isoformat())

        return {
            "success": True,
            "transaction_count": len(transactions),
            "account_count": len(accounts),
            "from_date": from_date,
            "to_date": to_date,
            "data": staged_data,
        }

    except Exception as e:
        frappe.log_error(f"Error staging data: {str(e)}", "E-Boekhouden Staging")
        frappe.throw(str(e))


@frappe.whitelist()
def get_staged_data_summary():
    """Get summary of staged data for review"""
    try:
        staged_data = get_staged_data_from_cache()
        if not staged_data:
            frappe.throw(_("No staged data found. Please stage data first."))

        accounts = staged_data.get("accounts", [])
        transactions = staged_data.get("transactions", [])

        # Analyze transaction types
        transaction_types = {}
        for trans in transactions:
            desc = trans.get("description", "Unknown")
            # Simple categorization based on description
            if "btw" in desc.lower() or "vat" in desc.lower():
                trans_type = "Tax/VAT"
            elif "loon" in desc.lower() or "salaris" in desc.lower():
                trans_type = "Wages/Salary"
            elif "contributie" in desc.lower():
                trans_type = "Contribution"
            elif "donatie" in desc.lower():
                trans_type = "Donation"
            elif "bank" in desc.lower():
                trans_type = "Banking"
            else:
                trans_type = "Other"

            transaction_types[trans_type] = transaction_types.get(trans_type, 0) + 1

        # Suggest account types based on account codes
        for account in accounts:
            code = account["code"]
            suggested_type = suggest_account_type(code, account["name"])
            account["suggested_type"] = suggested_type

        return {
            "accounts": sorted(accounts, key=lambda x: x["code"]),
            "transaction_types": transaction_types,
            "total_transactions": len(transactions),
            "date_range": {"from": staged_data.get("from_date"), "to": staged_data.get("to_date")},
        }

    except Exception as e:
        frappe.log_error(f"Error getting staged data summary: {str(e)}", "E-Boekhouden")
        frappe.throw(str(e))


@frappe.whitelist()
def add_account_mapping(account_code, account_type, notes=None):
    """Add a manual account mapping"""
    try:
        # Check if mapping already exists
        existing = frappe.db.exists("E-Boekhouden Account Mapping", {"account_code": account_code})

        if existing:
            # Update existing mapping
            doc = frappe.get_doc("E-Boekhouden Account Mapping", existing)
            doc.target_account_type = account_type
            if notes:
                doc.description = notes
            doc.save()
        else:
            # Create new mapping
            doc = frappe.new_doc("E-Boekhouden Account Mapping")
            doc.account_code = account_code
            doc.target_account_type = account_type
            doc.priority = 100  # High priority for manual mappings
            if notes:
                doc.description = notes

            # Try to get account name from staged data
            staged_data = get_staged_data_from_cache()
            if staged_data:
                for account in staged_data.get("accounts", []):
                    if account["code"] == account_code:
                        doc.account_name = account["name"]
                        break

            doc.insert()

        return {
            "success": True,
            "mapping": {
                "id": doc.name,
                "account_code": doc.account_code,
                "account_type": doc.target_account_type,
                "notes": doc.description,
            },
        }

    except Exception as e:
        frappe.log_error(f"Error adding mapping: {str(e)}", "E-Boekhouden")
        frappe.throw(str(e))


@frappe.whitelist()
def remove_account_mapping(mapping_id):
    """Remove an account mapping"""
    try:
        frappe.delete_doc("E-Boekhouden Account Mapping", mapping_id)
        return {"success": True}
    except Exception as e:
        frappe.log_error(f"Error removing mapping: {str(e)}", "E-Boekhouden")
        frappe.throw(str(e))


@frappe.whitelist()
def preview_migration_impact():
    """Preview what will be created during migration"""
    try:
        staged_data = get_staged_data_from_cache()
        if not staged_data:
            frappe.throw(_("No staged data found. Please stage data first."))

        transactions = staged_data.get("transactions", [])

        # Get all mappings
        mappings = {}
        for mapping in frappe.get_all(
            "E-Boekhouden Account Mapping",
            fields=["account_code", "document_type", "category"],
        ):
            mappings[mapping["account_code"]] = mapping

        # Analyze impact
        journal_entries = 0
        purchase_invoices = 0
        unmapped_accounts = {}
        warnings = []

        for trans in transactions:
            account_code = trans.get("account", {}).get("code")
            mapping = mappings.get(account_code)

            if mapping and mapping.get("target_document_type") == "Purchase Invoice":
                purchase_invoices += 1
            else:
                journal_entries += 1

            if not mapping and account_code:
                if account_code not in unmapped_accounts:
                    unmapped_accounts[account_code] = {
                        "code": account_code,
                        "name": trans.get("account", {}).get("name", ""),
                        "count": 0,
                    }
                unmapped_accounts[account_code]["count"] += 1

        # Check for potential issues
        if len(unmapped_accounts) > 10:
            warnings.append(f"{len(unmapped_accounts)} accounts have no manual mappings configured")

        return {
            "journal_entries": journal_entries,
            "purchase_invoices": purchase_invoices,
            "unmapped_accounts": list(unmapped_accounts.values()),
            "warnings": warnings,
            "total_transactions": len(transactions),
        }

    except Exception as e:
        frappe.log_error(f"Error previewing impact: {str(e)}", "E-Boekhouden")
        frappe.throw(str(e))


@frappe.whitelist()
def start_configured_migration(use_staged_data=True, apply_mappings=True):
    """Start migration with current configuration"""
    try:
        staged_data = get_staged_data_from_cache() if use_staged_data else None

        if use_staged_data and not staged_data:
            frappe.throw(_("No staged data found. Please stage data first."))

        # Create migration document
        migration = frappe.new_doc("E-Boekhouden Migration")
        migration.migration_type = "Full Initial Migration"

        if staged_data:
            migration.from_date = staged_data.get("from_date")
            migration.to_date = staged_data.get("to_date")
        else:
            # Use defaults
            migration.from_date = frappe.utils.add_days(frappe.utils.today(), -90)
            migration.to_date = frappe.utils.today()

        migration.migrate_transactions = 1
        migration.migrate_customers = 1
        migration.migrate_suppliers = 1
        migration.use_account_mappings = 1 if apply_mappings else 0

        migration.insert()

        # Start the migration
        from verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration import (
            start_migration_api,
        )

        result = start_migration_api(migration.name, dry_run=0)

        if result.get("success"):
            return {"success": True, "migration_id": migration.name}
        else:
            frappe.throw(result.get("error", "Migration failed to start"))

    except Exception as e:
        frappe.log_error(f"Error starting migration: {str(e)}", "E-Boekhouden")
        frappe.throw(str(e))


@frappe.whitelist()
def export_migration_config():
    """Export current migration configuration"""
    try:
        # Get all mappings
        mappings = frappe.get_all(
            "E-Boekhouden Account Mapping",
            fields=[
                "account_code",
                "account_name",
                "document_type",
                "category",
                "confidence",
                "is_active",
                "usage_count",
            ],
        )

        # Get settings
        settings = frappe.get_doc("E-Boekhouden Settings")

        config = {
            "version": "1.0",
            "export_date": datetime.now().isoformat(),
            "mappings": mappings,
            "settings": {
                "default_company": settings.default_company,
                "default_cost_center": settings.default_cost_center,
            },
        }

        return config

    except Exception as e:
        frappe.log_error(f"Error exporting config: {str(e)}", "E-Boekhouden")
        frappe.throw(str(e))


@frappe.whitelist()
def import_migration_config(config):
    """Import migration configuration"""
    try:
        if isinstance(config, str):
            config = json.loads(config)

        imported_count = 0

        # Import mappings
        for mapping_data in config.get("mappings", []):
            # Check if mapping exists
            existing = frappe.db.exists(
                "E-Boekhouden Account Mapping", {"account_code": mapping_data.get("account_code")}
            )

            if existing:
                doc = frappe.get_doc("E-Boekhouden Account Mapping", existing)
            else:
                doc = frappe.new_doc("E-Boekhouden Account Mapping")

            # Update fields
            for field in [
                "account_code",
                "account_name",
                "target_account_type",
                "target_document_type",
                "transaction_category",
                "priority",
                "description",
                "account_code_start",
                "account_code_end",
                "description_pattern",
            ]:
                if field in mapping_data:
                    setattr(doc, field, mapping_data[field])

            doc.save()
            imported_count += 1

        return {"success": True, "imported_count": imported_count}

    except Exception as e:
        frappe.log_error(f"Error importing config: {str(e)}", "E-Boekhouden")
        frappe.throw(str(e))


@frappe.whitelist()
def clear_all_mappings():
    """Clear all account mappings"""
    try:
        mappings = frappe.get_all("E-Boekhouden Account Mapping")

        for mapping in mappings:
            frappe.delete_doc("E-Boekhouden Account Mapping", mapping.name)

        return {"success": True}

    except Exception as e:
        frappe.log_error(f"Error clearing mappings: {str(e)}", "E-Boekhouden")
        frappe.throw(str(e))


# Helper functions
def get_staged_data_from_cache():
    """Get staged data from cache"""
    return frappe.cache().get_value("ebh_staged_data")


def suggest_account_type(account_code, account_name):
    """Suggest account type based on account code and name"""
    code = str(account_code)
    name_lower = account_name.lower() if account_name else ""

    # Based on Dutch accounting standards
    if code.startswith("0"):
        return "Fixed Asset"
    elif code.startswith("1"):
        if code.startswith("10") or code.startswith("11"):
            return "Bank"
        elif code.startswith("13"):
            return "Receivable"
        else:
            return "Current Asset"
    elif code.startswith("2"):
        return "Liability"
    elif code.startswith("3"):
        return "Equity"
    elif code.startswith("4"):
        if "btw" in name_lower or "vat" in name_lower:
            return "Tax"
        else:
            return "Income"
    elif code.startswith("5") or code.startswith("6") or code.startswith("7"):
        return "Expense"
    elif code.startswith("8"):
        return "Income"
    elif code.startswith("9"):
        return "Expense"
    else:
        return None


@frappe.whitelist()
def update_account_mapping(mapping_id, account_type, notes=None):
    """Update an existing account mapping"""
    try:
        doc = frappe.get_doc("E-Boekhouden Account Mapping", mapping_id)
        doc.target_account_type = account_type
        if notes is not None:
            doc.description = notes
        doc.save()

        return {
            "success": True,
            "mapping": {
                "id": doc.name,
                "account_code": doc.account_code,
                "account_type": doc.target_account_type,
                "notes": doc.description,
            },
        }
    except Exception as e:
        frappe.log_error(f"Error updating mapping: {str(e)}", "E-Boekhouden")
        frappe.throw(str(e))


@frappe.whitelist()
def bulk_update_mappings(updates):
    """Bulk update multiple mappings"""
    try:
        if isinstance(updates, str):
            updates = json.loads(updates)

        updated_count = 0
        for update in updates:
            try:
                doc = frappe.get_doc("E-Boekhouden Account Mapping", update["mapping_id"])

                if "account_type" in update and update["account_type"]:
                    doc.target_account_type = update["account_type"]

                if "priority" in update and update["priority"]:
                    doc.priority = int(update["priority"])

                doc.save()
                updated_count += 1
            except Exception as e:
                frappe.log_error(
                    f"Error updating mapping {update.get('mapping_id')}: {str(e)}", "E-Boekhouden"
                )

        return {"success": True, "updated_count": updated_count}
    except Exception as e:
        frappe.log_error(f"Error in bulk update: {str(e)}", "E-Boekhouden")
        frappe.throw(str(e))


@frappe.whitelist()
def suggest_account_mappings():
    """Analyze staged data and suggest account mappings"""
    try:
        staged_data = get_staged_data_from_cache()
        if not staged_data:
            frappe.throw(_("No staged data found. Please stage data first."))

        accounts = staged_data.get("accounts", [])
        existing_mappings = {
            m["account_code"]: m
            for m in frappe.get_all("E-Boekhouden Account Mapping", fields=["account_code"])
        }

        suggestions = []

        for account in accounts:
            # Skip if already mapped
            if account["code"] in existing_mappings:
                continue

            suggested_type = suggest_account_type(account["code"], account["name"])
            if suggested_type:
                # Determine confidence level
                confidence = "high"
                if account["code"].startswith("1") and not (
                    account["code"].startswith("10") or account["code"].startswith("11")
                ):
                    confidence = "medium"  # Current assets can be various types
                elif not account["code"][0].isdigit():
                    confidence = "low"

                suggestions.append(
                    {
                        "account_code": account["code"],
                        "account_name": account["name"],
                        "suggested_type": suggested_type,
                        "confidence": confidence,
                        "transaction_count": account.get("count", 0),
                    }
                )

        # Sort by transaction count (most used first)
        suggestions.sort(key=lambda x: x["transaction_count"], reverse=True)

        return {"success": True, "suggestions": suggestions[:50]}  # Limit to top 50
    except Exception as e:
        frappe.log_error(f"Error suggesting mappings: {str(e)}", "E-Boekhouden")
        frappe.throw(str(e))


@frappe.whitelist()
def apply_suggested_mappings(suggestions):
    """Apply selected mapping suggestions"""
    try:
        if isinstance(suggestions, str):
            suggestions = json.loads(suggestions)

        created_count = 0

        for suggestion in suggestions:
            # Check if mapping already exists
            if not frappe.db.exists(
                "E-Boekhouden Account Mapping", {"account_code": suggestion["account_code"]}
            ):
                doc = frappe.new_doc("E-Boekhouden Account Mapping")
                doc.account_code = suggestion["account_code"]
                doc.account_name = suggestion["account_name"]
                doc.target_account_type = suggestion["suggested_type"]
                doc.priority = 50  # Medium priority for auto-suggested
                doc.description = f"Auto-suggested with {suggestion['confidence']} confidence"
                doc.insert()
                created_count += 1

        return {"success": True, "created_count": created_count}
    except Exception as e:
        frappe.log_error(f"Error applying suggestions: {str(e)}", "E-Boekhouden")
        frappe.throw(str(e))
