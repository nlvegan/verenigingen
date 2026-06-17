"""
E-Boekhouden REST API Full Migration
Fetches ALL mutations by iterating through IDs and caches them
"""

import json

import frappe
import requests
from frappe import _
from frappe.utils import getdate

from verenigingen.e_boekhouden.utils.consolidated.cost_center_utils import (
    get_default_cost_center,
)
from verenigingen.e_boekhouden.utils.eboekhouden_payment_naming import (
    enhance_journal_entry_fields,
    get_journal_entry_title,
)
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api

# eBoekhouden mutation type labels (singular form — for individual transaction display)
MUTATION_TYPE_SINGULAR = {
    0: "Opening Balance",
    1: "Purchase Invoice",
    2: "Sales Invoice",
    3: "Customer Payment",
    4: "Supplier Payment",
    5: "Money Received",
    6: "Money Paid",
    7: "Memorial Booking",
    8: "Bank Import",
    9: "Manual Entry",
    10: "Stock Mutation",
}

# eBoekhouden mutation type labels (plural form — for batch summaries/logs)
MUTATION_TYPE_PLURAL = {
    0: "Opening Balances",
    1: "Purchase Invoices",
    2: "Sales Invoices",
    3: "Customer Payments",
    4: "Supplier Payments",
    5: "Money Received",
    6: "Money Paid",
    7: "Memorial Bookings",
    8: "Bank Import",
    9: "Manual Entry",
    10: "Stock Mutations",
}


def ensure_account_type_is_correct(account_name, expected_type, debug_info=None, auto_fix=False):
    """
    Check if an account has the correct account_type, optionally auto-correcting.

    By default (auto_fix=False), this function only reports mismatches without modifying data.
    Set auto_fix=True explicitly when you want to correct account types (e.g., during migration).

    IMPORTANT: This function does NOT commit the transaction. Callers are responsible for
    committing when appropriate. This preserves atomicity when called within atomic migration
    operations or other transactional contexts.

    Args:
        account_name: Full account name (e.g., "1350 - Te ontvangen bedragen - NVV")
        expected_type: Expected account type ("Receivable" or "Payable")
        debug_info: Optional list to append debug messages
        auto_fix: If True, automatically correct mismatched account types (default: False)

    Returns:
        bool: True if account type is correct (or was corrected when auto_fix=True),
              False if account doesn't exist or type is wrong (and auto_fix=False)
    """
    if debug_info is None:
        debug_info = []

    try:
        # Check if account exists
        if not frappe.db.exists("Account", account_name):
            debug_info.append(f"Account {account_name} does not exist")
            return False

        # Get current account type
        current_type = frappe.db.get_value("Account", account_name, "account_type")

        # If already correct, nothing to do
        if current_type == expected_type:
            debug_info.append(f"Account {account_name} already has correct type: {expected_type}")
            return True

        # Type mismatch - report it
        debug_info.append(
            f"Account {account_name} has type '{current_type}' but expected '{expected_type}'. "
            f"auto_fix={auto_fix}"
        )

        if not auto_fix:
            # Report only, do not modify
            return False

        # Auto-correct the account type (only when explicitly requested)
        # NOTE: No commit here - caller controls transaction boundaries
        frappe.db.set_value("Account", account_name, "account_type", expected_type)

        # Create visible audit trail in Error Log (shows in Desk)
        # Use defensive access to session.user for background jobs/CLI contexts
        current_user = getattr(frappe.session, "user", None) if getattr(frappe, "session", None) else None
        frappe.log_error(
            title=_("E-Boekhouden Migration - Account Type Auto-Corrected"),
            message=(
                f"Account type automatically corrected during migration:\n\n"
                f"Account: {account_name}\n"
                f"Previous type: {current_type}\n"
                f"New type: {expected_type}\n"
                f"User: {current_user or 'unknown (background/CLI)'}"
            ),
        )

        debug_info.append(
            f"Auto-corrected account type: {account_name} from '{current_type}' to '{expected_type}'"
        )
        frappe.logger().info(
            f"E-Boekhouden: Auto-corrected account {account_name} type from '{current_type}' to '{expected_type}'"
        )

        return True

    except Exception as e:
        debug_info.append(f"ERROR: Failed to ensure account type for {account_name}: {str(e)}")
        frappe.logger().error(f"Failed to ensure account type for {account_name}: {str(e)}")
        return False


def should_skip_mutation(mutation, debug_info=None):
    """
    Check if a mutation should be skipped (e.g., system notifications, zero-amount automations).

    NOTE: This function is intentionally kept in the migration module rather than centralized,
    because:
    1. It's only used within the REST full migration flow
    2. Other processors have domain-specific skip logic (e.g., payment_processor has
       _is_payment_gateway_adjustment() for Mollie fee corrections)
    3. Centralizing would add unnecessary abstraction for a simple function

    Skip rules:
    - Invoice mutations (types 1, 2) with "system notification" or "status update" in description
    - Does NOT skip zero-amount invoices (they're valid in ERPNext)

    Args:
        mutation: E-Boekhouden mutation dict with 'id', 'type', 'amount', 'description'
        debug_info: Optional list to append debug messages

    Returns:
        bool: True if mutation should be skipped
    """
    if debug_info is None:
        debug_info = []

    mutation_id = mutation.get("id")
    amount = float(mutation.get("amount", 0) or 0)
    description = mutation.get("description", "").lower()
    mutation_type = mutation.get("type", 0)

    # Only skip automated system imports and notifications
    # Allow all zero-amount invoices to be imported (they're valid in ERPNext)
    if mutation_type in [1, 2]:  # Sales Invoice or Purchase Invoice
        # Only skip automated system imports that are clearly not real invoices
        # Note: WooCommerce invoices are legitimate customer transactions and should be imported
        system_patterns = [
            "system notification",
            "status update",
        ]

        for pattern in system_patterns:
            if pattern in description:
                debug_info.append(f"Skipping mutation {mutation_id}: Automated system import ({pattern})")
                return True

    # Log zero-amount transactions for monitoring
    if amount == 0:
        debug_info.append(
            f"Processing zero-amount transaction (mutation {mutation_id}, type {mutation_type}): {description[:100]}"
        )

    return False


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def export_unprocessed_mutations_csv(export_path="/tmp/unprocessed_mutations.csv"):
    """Export unprocessed mutations to CSV for easy analysis"""
    try:
        # Get unprocessed data (reuse logic from JSON export)
        result = export_unprocessed_mutations("/tmp/temp_unprocessed.json")
        if not result["success"]:
            return result

        # Read the temp JSON file
        with open("/tmp/temp_unprocessed.json", "r") as f:
            data = json.load(f)

        unprocessed = data["unprocessed_mutations"]

        # Create CSV data
        import csv

        with open(export_path, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = [
                "mutation_id",
                "mutation_type",
                "mutation_date",
                "invoice_number",
                "description",
                "amount",
                "relation_id",
                "ledger_id",
                "issues",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for mutation in unprocessed:
                writer.writerow(
                    {
                        "mutation_id": mutation.get("mutation_id", ""),
                        "mutation_type": mutation.get("mutation_type", ""),
                        "mutation_date": mutation.get("mutation_date", ""),
                        "invoice_number": mutation.get("invoice_number", ""),
                        "description": mutation.get("description", "")[:100],  # Truncate for CSV
                        "amount": mutation.get("amount", ""),
                        "relation_id": mutation.get("relation_id", ""),
                        "ledger_id": mutation.get("ledger_id", ""),
                        "issues": "; ".join(mutation.get("issues", [])),
                    }
                )

        # Clean up temp file
        import os

        if os.path.exists("/tmp/temp_unprocessed.json"):
            os.remove("/tmp/temp_unprocessed.json")

        return {
            "success": True,
            "export_path": export_path,
            "total_unprocessed": len(unprocessed),
            "file_size_kb": round(os.path.getsize(export_path) / 1024, 2),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def export_unprocessed_mutations(export_path="/tmp/unprocessed_mutations.json"):
    """Export all unprocessed mutations to a local file for analysis"""
    try:
        # Get all cached mutations
        cached_mutations = frappe.get_all(
            "EBoekhouden REST Mutation Cache",
            fields=["mutation_id", "mutation_data", "mutation_type", "mutation_date"],
            limit_page_length=0,
            order_by="mutation_id",
        )

        # Get all successfully imported mutation IDs
        imported_journal_entries = frappe.get_all(
            "Journal Entry",
            filters={"eboekhouden_mutation_nr": ["!=", ""]},
            fields=["eboekhouden_mutation_nr"],
            limit_page_length=0,
        )

        imported_payment_entries = frappe.get_all(
            "Payment Entry",
            filters={"eboekhouden_mutation_nr": ["!=", ""]},
            fields=["eboekhouden_mutation_nr"],
            limit_page_length=0,
        )

        imported_sales_invoices = frappe.get_all(
            "Sales Invoice",
            filters={"eboekhouden_mutation_nr": ["!=", ""]},
            fields=["eboekhouden_mutation_nr"],
            limit_page_length=0,
        )

        imported_purchase_invoices = frappe.get_all(
            "Purchase Invoice",
            filters={"eboekhouden_mutation_nr": ["!=", ""]},
            fields=["eboekhouden_mutation_nr"],
            limit_page_length=0,
        )

        # Create set of imported IDs for fast lookup
        imported_ids = set()
        for doc_list in [
            imported_journal_entries,
            imported_payment_entries,
            imported_sales_invoices,
            imported_purchase_invoices,
        ]:
            for doc in doc_list:
                if doc.get("eboekhouden_mutation_nr"):
                    imported_ids.add(int(doc["eboekhouden_mutation_nr"]))

        # Find unprocessed mutations
        unprocessed_mutations = []

        for cached in cached_mutations:
            mutation_id = cached.get("mutation_id")
            if mutation_id and int(mutation_id) not in imported_ids:
                # Parse mutation data to extract key fields
                try:
                    mutation_data = json.loads(cached.get("mutation_data", "{}"))
                    unprocessed_mutations.append(
                        {
                            "mutation_id": mutation_id,
                            "mutation_type": mutation_data.get("type"),
                            "mutation_date": mutation_data.get("date"),
                            "invoice_number": mutation_data.get("invoiceNumber"),
                            "description": mutation_data.get("description", "")[:200],  # Truncate
                            "amount": mutation_data.get("amount"),
                            "relation_id": mutation_data.get("relationId"),
                            "ledger_id": mutation_data.get("ledgerId"),
                            "row_count": len(mutation_data.get("rows", [])),
                            "issues": [],  # Can be populated with specific issues later
                        }
                    )
                except Exception as e:
                    unprocessed_mutations.append(
                        {
                            "mutation_id": mutation_id,
                            "mutation_type": "UNKNOWN",
                            "issues": [f"Failed to parse cached data: {str(e)}"],
                        }
                    )

        # Create summary data
        export_data = {
            "export_timestamp": frappe.utils.now_datetime().isoformat(),
            "total_cached": len(cached_mutations),
            "total_imported": len(imported_ids),
            "total_unprocessed": len(unprocessed_mutations),
            "unprocessed_mutations": unprocessed_mutations,
            "summary": {
                "by_type": {},
                "by_month": {},
                "with_issues": len([m for m in unprocessed_mutations if m.get("issues")]),
            },
        }

        # Add type and month analysis
        for mutation in unprocessed_mutations:
            mut_type = mutation.get("mutation_type", "UNKNOWN")
            export_data["summary"]["by_type"][mut_type] = (
                export_data["summary"]["by_type"].get(mut_type, 0) + 1
            )

            mut_date = mutation.get("mutation_date", "")
            if mut_date:
                try:
                    month_key = mut_date[:7]  # YYYY-MM
                    export_data["summary"]["by_month"][month_key] = (
                        export_data["summary"]["by_month"].get(month_key, 0) + 1
                    )
                except:
                    pass

        # Write to file
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        # Calculate file size
        import os

        file_size_kb = round(os.path.getsize(export_path) / 1024, 2)

        return {
            "success": True,
            "export_path": export_path,
            "total_cached": len(cached_mutations),
            "total_imported": len(imported_ids),
            "total_unprocessed": len(unprocessed_mutations),
            "file_size_kb": file_size_kb,
            "summary": export_data["summary"],
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def migration_status_summary(company=None):
    """Get a summary of migration status across all data types"""
    try:
        if not company:
            # Get default company from settings
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

        if not company:
            return {"success": False, "error": "No company specified and no default company in settings"}

        summary = {"company": company, "data_types": {}}

        # Accounts
        account_count = frappe.db.count("Account", {"company": company, "is_group": 0})
        eb_account_count = frappe.db.count(
            "Account", {"company": company, "is_group": 0, "eboekhouden_grootboek_nummer": ["!=", ""]}
        )
        summary["data_types"]["accounts"] = {
            "total": account_count,
            "from_eboekhouden": eb_account_count,
            "percentage": round((eb_account_count / account_count * 100) if account_count > 0 else 0, 1),
        }

        # Cost Centers
        cc_count = frappe.db.count("Cost Center", {"company": company, "is_group": 0})
        # The eBoekhouden kostenplaats-id tag is an optional custom field that is not
        # shipped on every site. Guard the filtered count so the whole status report
        # does not die with a 1054 (unknown column) when the field is absent.
        if frappe.get_meta("Cost Center").has_field("eboekhouden_kostenplaats_id"):
            eb_cc_count = frappe.db.count(
                "Cost Center",
                {"company": company, "is_group": 0, "eboekhouden_kostenplaats_id": ["!=", ""]},
            )
        else:
            eb_cc_count = 0
        summary["data_types"]["cost_centers"] = {
            "total": cc_count,
            "from_eboekhouden": eb_cc_count,
            "percentage": round((eb_cc_count / cc_count * 100) if cc_count > 0 else 0, 1),
        }

        # Transactions (Journal Entries from eBoekhouden)
        je_count = frappe.db.count("Journal Entry", {"company": company})
        eb_je_count = frappe.db.count(
            "Journal Entry", {"company": company, "eboekhouden_mutation_nr": ["!=", ""]}
        )
        summary["data_types"]["journal_entries"] = {
            "total": je_count,
            "from_eboekhouden": eb_je_count,
            "percentage": round((eb_je_count / je_count * 100) if je_count > 0 else 0, 1),
        }

        # Payment Entries
        pe_count = frappe.db.count("Payment Entry", {"company": company})
        eb_pe_count = frappe.db.count(
            "Payment Entry", {"company": company, "eboekhouden_mutation_nr": ["!=", ""]}
        )
        summary["data_types"]["payment_entries"] = {
            "total": pe_count,
            "from_eboekhouden": eb_pe_count,
            "percentage": round((eb_pe_count / pe_count * 100) if pe_count > 0 else 0, 1),
        }

        # Sales Invoices
        si_count = frappe.db.count("Sales Invoice", {"company": company})
        eb_si_count = frappe.db.count(
            "Sales Invoice", {"company": company, "eboekhouden_mutation_nr": ["!=", ""]}
        )
        summary["data_types"]["sales_invoices"] = {
            "total": si_count,
            "from_eboekhouden": eb_si_count,
            "percentage": round((eb_si_count / si_count * 100) if si_count > 0 else 0, 1),
        }

        # Purchase Invoices
        pi_count = frappe.db.count("Purchase Invoice", {"company": company})
        eb_pi_count = frappe.db.count(
            "Purchase Invoice", {"company": company, "eboekhouden_mutation_nr": ["!=", ""]}
        )
        summary["data_types"]["purchase_invoices"] = {
            "total": pi_count,
            "from_eboekhouden": eb_pi_count,
            "percentage": round((eb_pi_count / pi_count * 100) if pi_count > 0 else 0, 1),
        }

        # Cache status. The "EBoekhouden REST Mutation Cache" doctype is not shipped
        # (no JSON / table on any site), so guard the count to keep the status report
        # alive. See the flagged follow-up about the dangling cache references.
        if frappe.db.table_exists("EBoekhouden REST Mutation Cache"):
            cache_count = frappe.db.count("EBoekhouden REST Mutation Cache")
        else:
            cache_count = 0
        summary["cache_status"] = {"total_mutations_cached": cache_count}

        # Calculate overall migration percentage
        total_eb_records = (
            eb_account_count + eb_cc_count + eb_je_count + eb_pe_count + eb_si_count + eb_pi_count
        )
        total_records = account_count + cc_count + je_count + pe_count + si_count + pi_count
        summary["overall_percentage"] = round(
            (total_eb_records / total_records * 100) if total_records > 0 else 0, 1
        )

        return {"success": True, "summary": summary}

    except Exception as e:
        return {"success": False, "error": str(e)}


def _check_if_already_imported(mutation_id, doctype):
    """Check if a mutation has already been imported"""
    existing = frappe.db.get_value(doctype, {"eboekhouden_mutation_nr": str(mutation_id)}, "name")
    return existing


def _check_if_invoice_number_exists(invoice_number, doctype):
    """Check if an invoice number already exists in the specified doctype"""
    if not invoice_number:
        return None

    existing = frappe.db.get_value(doctype, {"eboekhouden_invoice_number": str(invoice_number)}, "name")
    return existing


# Removed: _check_if_invoice_number_exists_for_party - E-Boekhouden handles duplicate detection


def create_invoice_line_for_tegenrekening(
    tegenrekening_code=None, amount=0, description="", transaction_type="purchase"
):
    """
    Enhanced invoice line creation with smart tegenrekening account mapping
    """
    # Use the smart tegenrekening mapper which now raises errors instead of using fallbacks
    from verenigingen.e_boekhouden.utils.smart_tegenrekening_mapper import (
        create_invoice_line_for_tegenrekening as smart_create_line,
    )

    # Delegate to the smart mapper
    return smart_create_line(tegenrekening_code, amount, description, transaction_type)


def _cache_all_mutations(settings):
    """Cache all mutations from eBoekhouden REST API by iterating through IDs"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI()

        # Try to get highest mutation ID to determine range
        # We'll iterate from 1 up to a reasonable limit or until we hit consecutive failures
        max_id = 50000  # Conservative upper bound
        batch_size = 100
        consecutive_failures = 0
        max_consecutive_failures = 50  # Stop after 50 consecutive failures

        total_cached = 0
        total_new = 0

        # Get existing cached IDs for quick lookup
        existing_ids = set()
        existing_cache = frappe.get_all(
            "EBoekhouden REST Mutation Cache", fields=["mutation_id"], limit_page_length=0
        )
        for cache in existing_cache:
            existing_ids.add(int(cache["mutation_id"]))

        for start_id in range(1, max_id + 1, batch_size):
            end_id = min(start_id + batch_size - 1, max_id)
            batch_new = 0
            batch_failures = 0

            for mutation_id in range(start_id, end_id + 1):
                # Skip if already cached
                if mutation_id in existing_ids:
                    total_cached += 1
                    continue

                # Fetch from API
                result = api.make_request(f"v1/mutation/{mutation_id}")

                if result and result.get("success") and result.get("status_code") == 200:
                    # Parse mutation data
                    try:
                        mutation_data = json.loads(result.get("data", "{}"))

                        # Create cache entry
                        cache_doc = frappe.new_doc("EBoekhouden REST Mutation Cache")
                        cache_doc.mutation_id = str(mutation_id)
                        cache_doc.mutation_data = result.get("data")
                        cache_doc.mutation_type = mutation_data.get("type", 0)
                        cache_doc.mutation_date = mutation_data.get("date")
                        cache_doc.save()

                        batch_new += 1
                        total_new += 1
                        consecutive_failures = 0

                    except Exception as e:
                        frappe.logger().error(f"Failed to cache mutation {mutation_id}: {str(e)}")
                        batch_failures += 1
                        consecutive_failures += 1
                else:
                    batch_failures += 1
                    consecutive_failures += 1

                # Stop if too many consecutive failures
                if consecutive_failures >= max_consecutive_failures:
                    frappe.logger().info(
                        f"Stopping cache process at mutation {mutation_id} due to {consecutive_failures} consecutive failures"
                    )
                    break

            # Commit batch
            if batch_new > 0:
                frappe.db.commit()

            # Progress update
            frappe.publish_realtime(
                "cache_progress",
                {
                    "operation": "Caching mutations from eBoekhouden",
                    "progress_percentage": min(80, (end_id / max_id) * 80),  # Leave 20% for processing
                    "current_id": end_id,
                    "total_new": total_new,
                    "total_cached": total_cached,
                },
                user=frappe.session.user,
            )

            # Break if we've hit too many consecutive failures
            if consecutive_failures >= max_consecutive_failures:
                break

        return total_cached, total_new

    except Exception as e:
        frappe.logger().error(f"Error in _cache_all_mutations: {str(e)}")
        return 0, 0


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_progress_info():
    """Get real-time progress information for the migration"""
    # This will be called by frontend to get progress updates
    return {"status": "running", "message": "Migration in progress..."}


def _resolve_account_mapping(ledger_id, debug_info):
    """Resolve account mapping from eBoekhouden ledger ID"""
    if not ledger_id:
        return None

    mapping_result = frappe.db.sql(
        """SELECT erpnext_account FROM `tabE-Boekhouden Ledger Mapping`
           WHERE ledger_id = %s LIMIT 1""",
        ledger_id,
    )

    if mapping_result:
        return {
            "erpnext_account": mapping_result[0][0],
            "ledger_id": ledger_id,
        }

    debug_info.append(f"No mapping found for ledger ID {ledger_id}")
    return None


def _resolve_money_source_account(mutation, company, debug_info):
    """Resolve source account for money received (Type 5)"""
    # For money received, we need to determine where the money came from
    # This could be from various sources like cash, other banks, income, etc.

    # Check if there's a relation (customer/supplier) that suggests the source
    relation_id = mutation.get("relationId")
    if relation_id:
        # Money from a customer or external party - use appropriate receivable/income account
        return _get_appropriate_income_account(company, debug_info)

    # No relation - likely internal transfer from cash or other bank account
    return _get_appropriate_payment_account(company, debug_info)


def _resolve_money_destination_account(mutation, company, debug_info):
    """Resolve destination account for money paid (Type 6)"""
    # For money paid, we need to determine where the money went
    # This could be to cash, other banks, expenses, etc.

    # Check if there's a relation (supplier) that suggests the destination
    relation_id = mutation.get("relationId")
    if relation_id:
        # Money to a supplier or external party - use appropriate payable/expense account
        return _get_appropriate_expense_account(company, debug_info)

    # No relation - likely internal transfer to cash or other bank account
    return _get_appropriate_payment_account(company, debug_info)


def _get_appropriate_income_account(company, debug_info):
    """Get appropriate income account from explicit payment mappings"""
    # Import here to avoid circular imports
    from .eboekhouden_payment_mapping import get_payment_account_mappings

    try:
        payment_mappings = get_payment_account_mappings(company)

        # Check for explicit income account mapping
        if "income_account" in payment_mappings:
            account_name = payment_mappings["income_account"]
            debug_info.append(f"Using configured income account: {account_name}")
            return {"erpnext_account": account_name, "account_name": account_name, "account_type": "Income"}

        # Check for sales income mapping as fallback
        if "sales_income_account" in payment_mappings:
            account_name = payment_mappings["sales_income_account"]
            debug_info.append(f"Using sales income account: {account_name}")
            return {"erpnext_account": account_name, "account_name": account_name, "account_type": "Income"}

    except Exception as e:
        debug_info.append(f"Error accessing payment mappings: {str(e)}")

    frappe.throw(
        f"Income account must be explicitly configured in payment mappings for company {company}. "
        "Implicit account lookup by type has been disabled for data safety."
    )


def _get_appropriate_expense_account(company, debug_info):
    """Get appropriate expense account from explicit payment mappings"""
    # Import here to avoid circular imports
    from .eboekhouden_payment_mapping import get_payment_account_mappings

    try:
        payment_mappings = get_payment_account_mappings(company)

        # Check for explicit expense account mapping
        if "expense_account" in payment_mappings:
            account_name = payment_mappings["expense_account"]
            debug_info.append(f"Using configured expense account: {account_name}")
            return {"erpnext_account": account_name, "account_name": account_name, "account_type": "Expense"}

        # Check for general expense mapping as fallback
        if "general_expense_account" in payment_mappings:
            account_name = payment_mappings["general_expense_account"]
            debug_info.append(f"Using general expense account: {account_name}")
            return {"erpnext_account": account_name, "account_name": account_name, "account_type": "Expense"}

    except Exception as e:
        debug_info.append(f"Error accessing payment mappings: {str(e)}")

    frappe.throw(
        f"Expense account must be explicitly configured in payment mappings for company {company}. "
        "Implicit account lookup by type has been disabled for data safety."
    )


def _get_appropriate_payment_account(company, debug_info):
    """Get appropriate payment account (cash or bank) from explicit payment mappings"""
    # Import here to avoid circular imports
    from .eboekhouden_payment_mapping import get_payment_account_mappings

    try:
        payment_mappings = get_payment_account_mappings(company)

        # Check for explicit cash account mapping
        if "cash_account" in payment_mappings:
            account_name = payment_mappings["cash_account"]
            debug_info.append(f"Using configured cash account: {account_name}")
            return {"erpnext_account": account_name, "account_name": account_name, "account_type": "Cash"}

        # Check for bank account mapping as fallback
        if "bank_account" in payment_mappings:
            account_name = payment_mappings["bank_account"]
            debug_info.append(f"Using bank account as cash fallback: {account_name}")
            return {"erpnext_account": account_name, "account_name": account_name, "account_type": "Bank"}

    except Exception as e:
        debug_info.append(f"Error accessing payment mappings: {str(e)}")

    frappe.throw(
        f"Cash/Bank account must be explicitly configured in payment mappings for company {company}. "
        "Implicit account lookup by type has been disabled for data safety."
    )


def _process_money_transfer_mutation(
    mutation, company, cost_center, from_account_mapping, to_account_mapping, debug_info
):
    """Process a money transfer mutation (type 5 or 6) with enhanced party extraction"""
    mutation_id = mutation.get("id")
    description = mutation.get("description", f"Money Transfer {mutation_id}")

    # Always calculate amount from rows (rows are source of truth)
    top_level_amount = abs(frappe.utils.flt(mutation.get("amount", 0), 2))

    if mutation.get("rows"):
        row_amounts = [abs(frappe.utils.flt(row.get("amount", 0), 2)) for row in mutation.get("rows", [])]
        amount = sum(row_amounts)
        debug_info.append(
            f"Money transfer calculated amount {amount} from {len(mutation.get('rows', []))} rows"
        )

        # Validate top-level amount matches rows (if non-zero)
        if top_level_amount > 0 and abs(top_level_amount - amount) > 0.01:
            debug_info.append(
                f"WARNING: Money transfer top-level amount ({top_level_amount}) doesn't match row total ({amount})"
            )
    else:
        # Fallback to top-level amount only if no rows exist
        amount = top_level_amount
        debug_info.append(f"Money transfer no rows found, using top-level amount: {amount}")

    mutation_type = mutation.get("type", 5)
    debug_info.append(f"Processing money transfer: ID={mutation_id}, Type={mutation_type}, Amount={amount}")

    # Extract party information from mutation description
    try:
        from verenigingen.e_boekhouden.utils.party_extractor import EBoekhoudenPartyExtractor

        party_extractor = EBoekhoudenPartyExtractor(company)
        party_info = party_extractor.extract_party_from_mutation(mutation)

        if party_info:
            debug_info.append(
                f"Extracted party: {party_info['party_name']} ({party_info['party_type']}) via {party_info['extraction_method']}"
            )
        else:
            debug_info.append("No party information extracted from mutation")

    except Exception as e:
        debug_info.append(f"Party extraction failed: {str(e)}")
        party_info = None
        party_extractor = None

    # Create Journal Entry for money transfer
    je = frappe.new_doc("Journal Entry")
    je.company = company
    je.posting_date = mutation.get("date")
    je.voucher_type = "Bank Entry"  # More appropriate for money transfers
    je.eboekhouden_mutation_nr = str(mutation_id)
    je.user_remark = description

    # Set descriptive name and title using enhanced naming functions
    type_name = "Money Received" if mutation_type == 5 else "Money Paid"
    je.name = f"EBH-{type_name}-{mutation_id}"
    je.title = get_journal_entry_title(mutation, mutation_type)

    # Enhance journal entry fields for better identification
    je = enhance_journal_entry_fields(je, mutation, type_name)

    from_account = from_account_mapping["erpnext_account"]
    to_account = to_account_mapping["erpnext_account"]

    debug_info.append(f"Transfer: {amount} from {from_account} to {to_account}")

    # From account (credit - money going out) with party assignment
    from_entry = {
        "account": from_account,
        "credit_in_account_currency": amount,
        "cost_center": cost_center,
        "user_remark": f"{description} - From",
    }

    # Try to assign party to from_account if appropriate
    if party_extractor and party_info:
        party_assignment = party_extractor.resolve_party_for_journal_entry(party_info, from_account)
        if party_assignment:
            from_entry["party_type"] = party_assignment[0]
            from_entry["party"] = party_assignment[1]
            debug_info.append(
                f"Assigned {party_assignment[0]} '{party_assignment[1]}' to from_account {from_account}"
            )

    je.append("accounts", from_entry)

    # To account (debit - money coming in) with party assignment
    to_entry = {
        "account": to_account,
        "debit_in_account_currency": amount,
        "cost_center": cost_center,
        "user_remark": f"{description} - To",
    }

    # Try to assign party to to_account if appropriate
    if party_extractor and party_info:
        party_assignment = party_extractor.resolve_party_for_journal_entry(party_info, to_account)
        if party_assignment:
            to_entry["party_type"] = party_assignment[0]
            to_entry["party"] = party_assignment[1]
            debug_info.append(
                f"Assigned {party_assignment[0]} '{party_assignment[1]}' to to_account {to_account}"
            )

    je.append("accounts", to_entry)

    try:
        je.save()
        je.submit()
        debug_info.append(f"Successfully created money transfer Journal Entry {je.name}")
        return je
    except Exception as e:
        debug_info.append(f"Failed to create money transfer Journal Entry: {str(e)}")
        raise


def _get_or_create_customer(relation_id, debug_info):
    """Get or create customer from eBoekhouden relation ID using party resolver"""
    try:
        # Use the robust party resolver instead of custom logic
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        resolver = EBoekhoudenPartyResolver()
        customer_name = resolver.resolve_customer(relation_id, debug_info)

        if customer_name:
            debug_info.append(f"Party resolver returned customer: {customer_name}")
            return customer_name
        else:
            debug_info.append(f"Party resolver failed for relation {relation_id}")
            return None

    except Exception as e:
        debug_info.append(f"Error resolving customer for relation {relation_id}: {str(e)}")
        return None


def _get_or_create_supplier(relation_id, description, debug_info):
    """Get or create supplier from eBoekhouden relation ID using party resolver"""
    try:
        # Use the robust party resolver instead of custom logic
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        resolver = EBoekhoudenPartyResolver()
        supplier_name = resolver.resolve_supplier(relation_id, debug_info)

        if supplier_name:
            debug_info.append(f"Party resolver returned supplier: {supplier_name}")
            return supplier_name
        else:
            debug_info.append(f"Party resolver failed for relation {relation_id}")
            return None

    except Exception as e:
        debug_info.append(f"Error resolving supplier for relation {relation_id}: {str(e)}")
        return None


def _get_or_create_generic_party(party_type, description, debug_info):
    """
    Create customer or supplier with improved description-based naming.

    Uses centralized BankTransactionParser for party creation to ensure
    consistent matching and creation logic across the codebase.

    Args:
        party_type: "Customer" or "Supplier"
        description: Raw description for naming
        debug_info: List to append debug messages to
    """
    try:
        from verenigingen.e_boekhouden.utils.bank_transaction_parser import BankTransactionParser

        from .eboekhouden_payment_naming import get_meaningful_description

        clean_description = get_meaningful_description(description) if description else ""

        if clean_description and len(clean_description) >= 5:
            party_name_candidate = f"{clean_description[:40]} (eBoekhouden Import)"
        else:
            party_name_candidate = f"eBoekhouden Import {party_type}"

        parser = BankTransactionParser()
        party_name, created = parser.find_or_create_party(
            party_name=party_name_candidate,
            party_type=party_type,
            iban=None,
        )

        if created:
            try:
                updates = {}
                if frappe.get_meta(party_type).has_field("custom_import_source"):
                    updates["custom_import_source"] = "eBoekhouden"
                if frappe.get_meta(party_type).has_field("custom_needs_review"):
                    updates["custom_needs_review"] = 1
                if updates:
                    frappe.db.set_value(party_type, party_name, updates)
            except Exception:
                pass  # Fields might not exist

            debug_info.append(f"Created improved import {party_type.lower()}: {party_name}")
        else:
            debug_info.append(f"Found existing import {party_type.lower()}: {party_name}")

        return party_name

    except Exception as e:
        debug_info.append(f"Error creating import {party_type.lower()}: {str(e)}")
        return f"Default {party_type}"


def _get_or_create_generic_customer(description, debug_info):
    """Create customer with improved description-based naming."""
    return _get_or_create_generic_party("Customer", description, debug_info)


def _get_or_create_generic_supplier(description, debug_info):
    """Create supplier with improved description-based naming."""
    return _get_or_create_generic_party("Supplier", description, debug_info)


def _get_or_create_company_party(party_type, company, debug_info):
    """
    Get or create the company as a customer or supplier for internal transactions.

    Uses centralized BankTransactionParser for party creation to ensure
    consistent matching and creation logic across the codebase.

    Args:
        party_type: "Customer" or "Supplier"
        company: Company name
        debug_info: List to append debug messages to
    """
    try:
        from verenigingen.e_boekhouden.utils.bank_transaction_parser import BankTransactionParser

        party_label = party_type.lower()
        internal_name = f"{company} (Internal)"

        parser = BankTransactionParser()
        party_name, created = parser.find_or_create_party(
            party_name=internal_name,
            party_type=party_type,
            iban=None,
        )

        action = "Created" if created else "Found existing"
        debug_info.append(f"{action} company {party_label}: {party_name}")

        return party_name

    except Exception as e:
        debug_info.append(f"Error creating company {party_type.lower()}: {str(e)}")
        return None


def _get_or_create_company_as_customer(company, debug_info):
    """Get or create the company as a customer for internal transactions."""
    return _get_or_create_company_party("Customer", company, debug_info)


def _get_or_create_company_as_supplier(company, debug_info):
    """Get or create the company as a supplier for internal transactions."""
    return _get_or_create_company_party("Supplier", company, debug_info)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def analyze_import_failures():
    """Analyze recent import failures and categorize them"""
    try:
        # Get recent error logs
        errors = frappe.db.sql(
            """
            SELECT error FROM `tabError Log`
            WHERE creation > DATE_SUB(NOW(), INTERVAL 90 DAY)
            AND error LIKE '%Books have been closed%'
            LIMIT 3
        """,
            as_dict=True,
        )

        results = {"closed_book_errors": len(errors), "sample_errors": []}

        for error in errors:
            # Extract mutation data from error
            error_text = error["error"]
            if '"date":' in error_text:
                import re

                date_match = re.search(r'"date": "([^"]+)"', error_text)
                id_match = re.search(r'"id": (\d+)', error_text)
                type_match = re.search(r'"type": (\d+)', error_text)

                results["sample_errors"].append(
                    {
                        "date": date_match.group(1) if date_match else "unknown",
                        "id": id_match.group(1) if id_match else "unknown",
                        "type": type_match.group(1) if type_match else "unknown",
                    }
                )

        return results

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def debug_single_mutation(mutation_id):
    """Debug a single mutation by ID - useful for investigating import failures"""
    try:
        # Get company and cost center
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.company
        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

        if not cost_center:
            return {"success": False, "error": "No cost center found"}

        # Fetch the mutation from cache or API
        mutation_cache = frappe.cache().get_value("eboekhouden_mutations")
        if not mutation_cache:
            return {"success": False, "error": "No mutations cached. Run a full import first."}

        # Find the specific mutation
        mutation = None
        for cached_mutation in mutation_cache:
            if cached_mutation.get("id") == int(mutation_id):
                mutation = cached_mutation
                break

        if not mutation:
            return {"success": False, "error": f"Mutation {mutation_id} not in cache"}

        # Process the single mutation
        debug_info = []
        try:
            result = _process_single_mutation(mutation, company, cost_center, debug_info)
            return {
                "success": True,
                "mutation": mutation,
                "result": result.name if result else None,
                "debug_info": debug_info,
            }
        except Exception as e:
            return {"success": False, "mutation": mutation, "error": str(e), "debug_info": debug_info}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_mutation_gap_report():
    """Generate a report of missing mutations in the sequence"""
    try:
        # Get all imported mutation IDs
        journal_mutations = frappe.db.sql(
            """
            SELECT CAST(eboekhouden_mutation_nr AS UNSIGNED) as mutation_id
            FROM `tabJournal Entry`
            WHERE eboekhouden_mutation_nr != ''
            AND eboekhouden_mutation_nr REGEXP '^[0-9]+$'
            ORDER BY mutation_id
        """,
            as_dict=True,
        )

        payment_mutations = frappe.db.sql(
            """
            SELECT CAST(eboekhouden_mutation_nr AS UNSIGNED) as mutation_id
            FROM `tabPayment Entry`
            WHERE eboekhouden_mutation_nr != ''
            AND eboekhouden_mutation_nr REGEXP '^[0-9]+$'
            ORDER BY mutation_id
        """,
            as_dict=True,
        )

        invoice_mutations = frappe.db.sql(
            """
            SELECT CAST(eboekhouden_mutation_nr AS UNSIGNED) as mutation_id
            FROM `tabSales Invoice`
            WHERE eboekhouden_mutation_nr != ''
            AND eboekhouden_mutation_nr REGEXP '^[0-9]+$'
            UNION
            SELECT CAST(eboekhouden_mutation_nr AS UNSIGNED) as mutation_id
            FROM `tabPurchase Invoice`
            WHERE eboekhouden_mutation_nr != ''
            AND eboekhouden_mutation_nr REGEXP '^[0-9]+$'
            ORDER BY mutation_id
        """,
            as_dict=True,
        )

        # Combine all mutation IDs
        all_imported = set()
        for mutations_list in [journal_mutations, payment_mutations, invoice_mutations]:
            for mut in mutations_list:
                all_imported.add(mut["mutation_id"])

        if not all_imported:
            return {"success": True, "gaps": [], "message": "No mutations found"}

        # Find gaps in the sequence
        min_id = min(all_imported)
        max_id = max(all_imported)
        gaps = []

        for i in range(min_id, max_id + 1):
            if i not in all_imported:
                gaps.append(i)

        return {
            "success": True,
            "gaps": gaps,
            "total_imported": len(all_imported),
            "min_mutation": min_id,
            "max_mutation": max_id,
            "total_gaps": len(gaps),
            "coverage_percentage": round(
                ((max_id - min_id + 1 - len(gaps)) / (max_id - min_id + 1)) * 100, 2
            ),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def _classify_opening_balance_account(account, company, debug_info):
    """
    Classify an account for opening balance import: determine if it's valid,
    what party it needs, and whether to skip it.

    Returns:
        dict with keys:
        - skip: bool (True if account should be skipped)
        - skip_reason: str (why it was skipped: 'pnl', 'stock', 'not_found', 'error', 'party_error')
        - root_type: str or None
        - account_type: str or None
        - party_type: str or None
        - party: str or None
    """
    result = {
        "skip": False,
        "skip_reason": None,
        "root_type": None,
        "account_type": None,
        "party_type": None,
        "party": None,
    }

    try:
        account_doc = frappe.get_doc("Account", account)
        result["root_type"] = account_doc.root_type
        result["account_type"] = account_doc.account_type
    except frappe.DoesNotExistError:
        debug_info.append(f"Account {account} was not found, skipping")
        result["skip"] = True
        result["skip_reason"] = "not_found"
        return result
    except Exception as e:
        debug_info.append(f"Error accessing account {account}: {str(e)}, skipping")
        result["skip"] = True
        result["skip_reason"] = "error"
        return result

    # Skip P&L accounts — only Balance Sheet accounts allowed in opening entries
    if result["root_type"] in ["Income", "Expense"]:
        debug_info.append(f"Skipping P&L account {account} (type: {result['root_type']})")
        result["skip"] = True
        result["skip_reason"] = "pnl"
        return result

    # Stock accounts handled via Stock Reconciliation
    if result["account_type"] == "Stock":
        debug_info.append(f"Stock account {account} will be handled via Stock Reconciliation")
        result["skip"] = True
        result["skip_reason"] = "stock"
        return result

    # Assign party for Receivable/Payable accounts
    if result["account_type"] == "Receivable":
        result["party_type"] = "Customer"
        result["party"] = _get_or_create_company_as_customer(company, debug_info)
        if not result["party"]:
            debug_info.append(
                f"ERROR: Failed to get/create customer for Receivable account {account}, skipping"
            )
            result["skip"] = True
            result["skip_reason"] = "party_error"
            return result
    elif result["account_type"] == "Payable":
        result["party_type"] = "Supplier"
        result["party"] = _get_or_create_company_as_supplier(company, debug_info)
        if not result["party"]:
            debug_info.append(f"ERROR: Failed to get/create supplier for Payable account {account}, skipping")
            result["skip"] = True
            result["skip_reason"] = "party_error"
            return result

    return result


def _calculate_opening_balance_debit_credit(amount, root_type):
    """
    Calculate debit/credit amounts for an opening balance line based on the account's
    natural balance (Assets = debit, Liabilities/Equity = credit).

    Returns:
        tuple: (debit_amount, credit_amount)
    """
    if root_type == "Asset":
        return (
            frappe.utils.flt(amount if amount > 0 else 0, 2),
            frappe.utils.flt(-amount if amount < 0 else 0, 2),
        )
    else:  # Liability or Equity
        return (
            frappe.utils.flt(-amount if amount < 0 else 0, 2),
            frappe.utils.flt(amount if amount > 0 else 0, 2),
        )


def _add_opening_balance_balancing_entry(je, total_debit, total_credit, company, cost_center, debug_info):
    """
    Add a balancing entry to a temporary difference account if the opening balance
    journal entry has a debit/credit mismatch.
    """
    balance_diff = total_debit - total_credit
    if abs(balance_diff) <= 0.01:
        return

    debug_info.append(f"Balancing entry required: {balance_diff}")
    temp_diff_account = _get_or_create_temporary_diff_account(company, debug_info)

    if balance_diff > 0:
        balancing_entry = {
            "account": temp_diff_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": balance_diff,
            "cost_center": cost_center,
            "user_remark": "Balancing entry for opening balances",
        }
    else:
        balancing_entry = {
            "account": temp_diff_account,
            "debit_in_account_currency": abs(balance_diff),
            "credit_in_account_currency": 0,
            "cost_center": cost_center,
            "user_remark": "Balancing entry for opening balances",
        }

    je.append("accounts", balancing_entry)
    debug_info.append(f"Added balancing entry: {temp_diff_account} = {balance_diff}")


def _build_opening_balance_je(
    mutations_data,
    company,
    cost_center,
    debug_info,
    amount_field="amount",
    je_title="eBoekhouden Opening Balances",
    je_user_remark="Opening balances imported from eBoekhouden",
    track_skip_reasons=False,
):
    """Build a Journal Entry from opening balance mutation data.

    Shared core logic used by both _import_opening_balances (API fetch path)
    and _import_opening_balances_from_data (pre-filtered path).

    Returns dict with keys:
        - "je", "processed_accounts", "skipped_accounts" on success
        - "success", "message" on early return (no valid entries)
    """
    # Determine opening balance date from mutations
    opening_date = None
    for mutation in mutations_data:
        if isinstance(mutation, dict) and mutation.get("date"):
            opening_date = getdate(mutation.get("date"))
            break

    if not opening_date:
        opening_date = getdate("2018-01-01")
        debug_info.append(f"WARNING: No date found in mutations, using fallback date: {opening_date}")
    else:
        debug_info.append(f"Using opening balance date from mutations: {opening_date}")

    # Ensure fiscal year exists
    try:
        from .invoice_helpers import ensure_fiscal_year_exists

        fiscal_year = ensure_fiscal_year_exists(opening_date, company, debug_info)
        debug_info.append(f"Fiscal year {fiscal_year} verified/created for opening balance date")
    except Exception as fy_error:
        debug_info.append(f"WARNING: Could not ensure fiscal year for {opening_date}: {str(fy_error)}")

    # Create Journal Entry
    je = frappe.new_doc("Journal Entry")
    je.company = company
    je.posting_date = opening_date
    je.voucher_type = "Opening Entry"
    je.title = je_title
    je.user_remark = je_user_remark
    je.eboekhouden_mutation_nr = "OPENING_BALANCE"

    total_debit = 0
    total_credit = 0
    processed_accounts = set()
    skipped_accounts = {"stock": [], "pnl": [], "errors": []}

    for mutation in mutations_data:
        if isinstance(mutation, list):
            debug_info.append(f"WARNING: Mutation is a list, not dict: {mutation}")
            continue

        ledger_id = mutation.get("ledgerId")
        amount = frappe.utils.flt(mutation.get(amount_field, 0), 2)
        description = mutation.get("description", "Opening Balance")

        debug_info.append(
            f"Processing opening balance: ID={mutation.get('id')}, Ledger={ledger_id}, Amount={amount}"
        )

        if amount == 0:
            debug_info.append(f"Skipping zero amount opening balance for ledger {ledger_id}")
            continue

        account = get_erpnext_account_from_ledger_id(ledger_id, company, debug_info, auto_create=True)
        if not account:
            debug_info.append(f"Failed to resolve or create mapping for ledger {ledger_id}, skipping")
            continue

        if account in processed_accounts:
            debug_info.append(f"Account {account} already processed, skipping duplicate")
            continue
        processed_accounts.add(account)

        classification = _classify_opening_balance_account(account, company, debug_info)
        if classification["skip"]:
            if track_skip_reasons:
                reason = classification["skip_reason"]
                if reason == "pnl":
                    skipped_accounts["pnl"].append({"account": account, "type": classification["root_type"]})
                elif reason == "stock":
                    skipped_accounts["stock"].append({"account": account, "balance": amount})
                elif reason == "party_error":
                    skipped_accounts["errors"].append(
                        {
                            "account": account,
                            "error": f"Failed to create party for {classification['account_type']} account",
                        }
                    )
            continue

        debit_amount, credit_amount = _calculate_opening_balance_debit_credit(
            amount, classification["root_type"]
        )

        entry_line = {
            "account": account,
            "debit_in_account_currency": debit_amount,
            "credit_in_account_currency": credit_amount,
            "cost_center": cost_center,
            "user_remark": f"Opening balance: {description}" if track_skip_reasons else description,
        }

        if classification["party_type"] and classification["party"]:
            entry_line["party_type"] = classification["party_type"]
            entry_line["party"] = classification["party"]

        je.append("accounts", entry_line)
        total_debit += debit_amount
        total_credit += credit_amount

        debug_info.append(
            f"Added opening balance entry: {account}, Debit: {debit_amount}, Credit: {credit_amount}"
        )

    _add_opening_balance_balancing_entry(je, total_debit, total_credit, company, cost_center, debug_info)

    if not je.accounts:
        debug_info.append("No valid opening balance entries found after filtering")
        if track_skip_reasons:
            debug_info.append(
                f"Summary: {len(skipped_accounts['pnl'])} P&L accounts skipped, "
                f"{len(skipped_accounts['stock'])} stock accounts skipped, "
                f"{len(skipped_accounts['errors'])} error accounts"
            )
        return {
            "success": True,
            "message": "No valid opening balance entries found",
            "journal_entry": None,
        }

    return {
        "je": je,
        "processed_accounts": processed_accounts,
        "skipped_accounts": skipped_accounts,
    }


def _import_opening_balances(company, cost_center, debug_info, dry_run=False, force=False):
    """Import opening balances from eBoekhouden using REST API"""
    try:
        # Check if opening balances have already been imported
        existing_opening_balance = frappe.db.exists(
            "Journal Entry",
            {
                "company": company,
                "eboekhouden_mutation_nr": "OPENING_BALANCE",
                "voucher_type": "Opening Entry",
            },
        )

        if existing_opening_balance:
            if force:
                # Force re-import: delete existing opening balance entry
                debug_info.append(
                    f"Force mode: deleting existing opening balance Journal Entry {existing_opening_balance}"
                )
                try:
                    je_doc = frappe.get_doc("Journal Entry", existing_opening_balance)
                    if je_doc.docstatus == 1:
                        je_doc.cancel()
                        debug_info.append(f"Cancelled Journal Entry {existing_opening_balance}")
                    frappe.delete_doc("Journal Entry", existing_opening_balance, force=True)
                    debug_info.append(f"Deleted Journal Entry {existing_opening_balance}")
                    frappe.db.commit()
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Failed to delete existing opening balance {existing_opening_balance}: {str(e)}. Cancel it manually first.",
                    }
            else:
                # Opening balances already imported
                return {
                    "success": True,
                    "message": "Opening balances already imported",
                    "journal_entry": existing_opening_balance,
                }

        from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI()

        # Get opening balances from eBoekhouden
        result = api.make_request("v1/mutation", method="GET", params={"type": 0})

        if not result or not result.get("success") or result.get("status_code") != 200:
            return {
                "success": False,
                "error": f"Failed to fetch opening balances: {result.get('error', 'Unknown error')}",
            }

        mutations_data = json.loads(result.get("data", "[]"))

        # Debug: Check data structure
        debug_info.append(f"mutations_data type: {type(mutations_data)}")

        # Handle if mutations_data is a dict instead of list
        if isinstance(mutations_data, dict):
            debug_info.append(f"mutations_data is dict with keys: {list(mutations_data.keys())[:5]}")
            # If it has 'items' key, use that (standard API response format)
            if "items" in mutations_data:
                mutations_data = mutations_data["items"]
            else:
                # Otherwise convert dict values to list
                mutations_data = list(mutations_data.values())

        debug_info.append(f"Found {len(mutations_data)} opening balance mutations")

        if not mutations_data:
            return {"success": True, "message": "No opening balances found", "journal_entry": None}

        # Build JE using shared helper (API path uses "amount" field, tracks skip reasons)
        result = _build_opening_balance_je(
            mutations_data,
            company,
            cost_center,
            debug_info,
            amount_field="amount",
            track_skip_reasons=True,
        )
        if "success" in result:
            return result  # Early return (no valid entries)

        je = result["je"]
        processed_accounts = result["processed_accounts"]
        skipped_accounts = result["skipped_accounts"]

        # Save and submit journal entry (unless dry run)
        if dry_run:
            debug_info.append("DRY RUN: Would create opening balance journal entry")
            debug_info.append(f"Number of accounts: {len(je.accounts)}")
            return {
                "success": True,
                "journal_entry": "DRY-RUN-PREVIEW",
                "message": "Opening balances preview completed (no changes made)",
            }
        else:
            try:
                je.save()
                je.submit()
                debug_info.append(f"Successfully created opening balance journal entry: {je.name}")

                # Handle stock accounts via Stock Reconciliation
                stock_reconciliations = []
                if skipped_accounts["stock"]:
                    debug_info.append(
                        f"Creating Stock Reconciliations for {len(skipped_accounts['stock'])} stock accounts"
                    )

                    try:
                        from verenigingen.e_boekhouden.utils.stock_opening_balance_handler import (
                            create_stock_reconciliation_for_opening_balance,
                        )

                        stock_result = create_stock_reconciliation_for_opening_balance(
                            skipped_accounts["stock"], company, debug_info
                        )

                        if stock_result.get("success"):
                            stock_reconciliations = stock_result.get("created_reconciliations", [])
                            debug_info.append(
                                f"Created {len(stock_reconciliations)} Stock Reconciliation entries"
                            )
                        else:
                            debug_info.append(
                                f"Stock reconciliation failed: {stock_result.get('error', 'Unknown error')}"
                            )

                    except Exception as e:
                        debug_info.append(f"Error importing stock reconciliations: {str(e)}")

                # Add summary of what was processed
                total_skipped = len(skipped_accounts["pnl"]) + len(skipped_accounts["errors"])
                total_stock_processed = len(stock_reconciliations)

                if total_skipped > 0 or total_stock_processed > 0:
                    summary_parts = []
                    if total_stock_processed > 0:
                        summary_parts.append(
                            f"{total_stock_processed} stock accounts via Stock Reconciliation"
                        )
                    if len(skipped_accounts["pnl"]) > 0:
                        summary_parts.append(f"{len(skipped_accounts['pnl'])} P&L accounts skipped")
                    if len(skipped_accounts["errors"]) > 0:
                        summary_parts.append(f"{len(skipped_accounts['errors'])} error accounts skipped")

                    debug_info.append(f"Additional processing: {', '.join(summary_parts)}")

                return {
                    "success": True,
                    "journal_entry": je.name,
                    "stock_reconciliations": stock_reconciliations,
                    "message": "Opening balances imported successfully",
                    "skipped_accounts": skipped_accounts,
                    "accounts_processed": len(processed_accounts),
                }
            except Exception as e:
                debug_info.append(f"Failed to save opening balance journal entry: {str(e)}")
                return {"success": False, "error": f"Failed to create journal entry: {str(e)}"}

    except Exception as e:
        import traceback

        debug_info.append(f"Error in _import_opening_balances: {str(e)}")
        debug_info.append(f"Traceback: {traceback.format_exc()}")
        return {"success": False, "error": str(e)}


def _import_opening_balances_from_data(mutations_data, company, cost_center, debug_info, dry_run=False):
    """Import opening balances from provided data (used by stock account handler).

    Delegates to _build_opening_balance_je() for shared processing logic.
    """
    try:
        # Check if opening balances have already been imported
        existing_opening_balance = frappe.db.exists(
            "Journal Entry",
            {
                "company": company,
                "eboekhouden_mutation_nr": "OPENING_BALANCE",
                "voucher_type": "Opening Entry",
            },
        )

        if existing_opening_balance:
            return {
                "success": True,
                "message": "Opening balances already imported",
                "journal_entry": existing_opening_balance,
            }

        if not mutations_data:
            return {"success": True, "message": "No opening balances found", "journal_entry": None}

        # Build JE using shared helper (stock-filtered path uses "balance" field)
        result = _build_opening_balance_je(
            mutations_data,
            company,
            cost_center,
            debug_info,
            amount_field="balance",
            je_title="eBoekhouden Opening Balances (Stock Filtered)",
            je_user_remark="Opening balances imported from eBoekhouden with stock account filtering",
        )
        if "success" in result:
            return result  # Early return (no valid entries)

        je = result["je"]
        processed_accounts = result["processed_accounts"]

        if dry_run:
            debug_info.append("Dry run mode - not saving journal entry")
            return {
                "success": True,
                "message": "Opening balances validated (dry run)",
                "journal_entry": None,
                "accounts_processed": len(processed_accounts),
            }

        try:
            je.save()
            je.submit()
            debug_info.append(f"Created and submitted Journal Entry {je.name}")
            return {
                "success": True,
                "journal_entry": je.name,
                "message": "Opening balances imported successfully",
                "accounts_processed": len(processed_accounts),
            }
        except Exception as e:
            debug_info.append(f"Failed to save opening balance journal entry: {str(e)}")
            return {"success": False, "error": f"Failed to create journal entry: {str(e)}"}

    except Exception as e:
        import traceback

        debug_info.append(f"Error in _import_opening_balances_from_data: {str(e)}")
        debug_info.append(f"Traceback: {traceback.format_exc()}")
        return {"success": False, "error": str(e)}


def _get_or_create_temporary_diff_account(company, debug_info):
    """Get or create a temporary difference account for balancing opening balances"""

    # PRIORITY 1: Look for existing temporary accounts instead of creating new ones
    # First check if there's already a "Temporary Differences" account for this company
    existing_temp_accounts = frappe.db.sql(
        """
        SELECT name, account_name
        FROM `tabAccount`
        WHERE company = %s
        AND account_type = 'Temporary'
        AND root_type = 'Equity'
        AND (account_name = 'Temporary Differences'
             OR account_name LIKE '%%Temporary%%Difference%%'
             OR account_name LIKE '%%Difference%%')
        ORDER BY
            CASE WHEN account_name = 'Temporary Differences' THEN 1 ELSE 2 END,
            name
        LIMIT 1
    """,
        company,
        as_dict=True,
    )

    if existing_temp_accounts:
        account_name = existing_temp_accounts[0].name
        debug_info.append(f"Using existing temporary account: {account_name}")
        return account_name

    # PRIORITY 2: Look for any temporary account under Equity
    any_equity_temp = frappe.db.sql(
        """
        SELECT name, account_name
        FROM `tabAccount`
        WHERE company = %s
        AND account_type = 'Temporary'
        AND root_type = 'Equity'
        ORDER BY name
        LIMIT 1
    """,
        company,
        as_dict=True,
    )

    if any_equity_temp:
        account_name = any_equity_temp[0].name
        debug_info.append(f"Using existing equity temporary account: {account_name}")
        return account_name

    # PRIORITY 3: Look for any temporary account (regardless of root type)
    any_temp = frappe.db.sql(
        """
        SELECT name, account_name, root_type
        FROM `tabAccount`
        WHERE company = %s
        AND account_type = 'Temporary'
        ORDER BY
            CASE WHEN root_type = 'Equity' THEN 1 ELSE 2 END,
            name
        LIMIT 1
    """,
        company,
        as_dict=True,
    )

    if any_temp:
        account_name = any_temp[0].name
        debug_info.append(f"Using existing temporary account (root: {any_temp[0].root_type}): {account_name}")
        return account_name

    # PRIORITY 4: Only try to create if no temporary accounts exist at all
    account_name = f"Temporary Differences - {company}"
    if frappe.db.exists("Account", account_name):
        return account_name

    # Create the account under Equity as last resort
    try:
        # Find equity parent account
        equity_accounts = frappe.db.sql(
            """SELECT name FROM `tabAccount`
               WHERE company = %s
               AND root_type = 'Equity'
               AND is_group = 1
               LIMIT 1""",
            company,
        )

        if equity_accounts:
            parent_account = equity_accounts[0][0]
        else:
            parent_account = f"Capital Stock - {company}"

        account = frappe.new_doc("Account")
        account.account_name = "Temporary Differences"
        account.parent_account = parent_account
        account.company = company
        account.account_type = "Temporary"  # Use Temporary account type
        account.root_type = "Equity"
        account.is_group = 0
        account.insert()

        debug_info.append(f"Created temporary difference account: {account.name}")
        return account.name

    except Exception as e:
        debug_info.append(f"Failed to create temporary difference account: {str(e)}")

        # FINAL FALLBACK: Find any account that can be used for balancing
        # Look for any Equity account that's not a group
        fallback_equity = frappe.db.sql(
            """
            SELECT name FROM `tabAccount`
            WHERE company = %s
            AND root_type = 'Equity'
            AND is_group = 0
            ORDER BY
                CASE WHEN account_type = 'Temporary' THEN 1
                     WHEN account_name LIKE '%%Capital%%' THEN 2
                     WHEN account_name LIKE '%%Reserve%%' THEN 3
                     ELSE 4 END,
                name
            LIMIT 1
        """,
            company,
            as_dict=True,
        )

        if fallback_equity:
            fallback_account = fallback_equity[0].name
            debug_info.append(f"FALLBACK: Using equity account for balancing: {fallback_account}")
            return fallback_account

        # Absolute last resort - this should never happen in a properly configured system
        debug_info.append("ERROR: No suitable account found for opening balance balancing")
        raise Exception("No temporary or equity accounts available for opening balance balancing")


def _get_or_create_stock_temporary_account(company, debug_info):
    """Get or create a temporary account for stock balances during opening balance import"""
    # Look up by (account_name, company), NOT a constructed "<name> - <company>"
    # string. ERPNext autonames accounts "<account_name> - <company_abbr>", so the
    # old f"... - {company}" lookup never matched the account this function creates
    # (the abbr differs from the full company name). That made it non-idempotent:
    # every re-call hit the create path, the duplicate insert() threw, and it
    # silently fell back to the wrong (temp-diff) account.
    existing = frappe.db.get_value(
        "Account",
        {"account_name": "Stock Opening Balance (Temporary)", "company": company},
        "name",
    )
    if existing:
        return existing

    # Create the account under Assets
    try:
        # Find current assets parent account
        current_assets_accounts = frappe.db.sql(
            """SELECT name FROM `tabAccount`
               WHERE company = %s
               AND root_type = 'Asset'
               AND is_group = 1
               AND account_name LIKE '%%Current%%'
               LIMIT 1""",
            company,
        )

        if current_assets_accounts:
            parent_account = current_assets_accounts[0][0]
        else:
            # Fallback to any Asset group
            asset_accounts = frappe.db.sql(
                """SELECT name FROM `tabAccount`
                   WHERE company = %s
                   AND root_type = 'Asset'
                   AND is_group = 1
                   LIMIT 1""",
                company,
            )
            parent_account = (
                asset_accounts[0][0] if asset_accounts else f"Application of Funds (Assets) - {company}"
            )

        account = frappe.new_doc("Account")
        account.account_name = "Stock Opening Balance (Temporary)"
        account.parent_account = parent_account
        account.company = company
        account.account_type = "Temporary"  # Use Temporary account type
        account.root_type = "Asset"
        account.is_group = 0
        account.insert()

        debug_info.append(f"Created temporary stock account: {account.name}")
        return account.name

    except Exception as e:
        debug_info.append(f"Failed to create temporary stock account: {str(e)}")
        # Fallback to general temporary account
        return _get_or_create_temporary_diff_account(company, debug_info)


def _process_single_mutation(mutation, company, cost_center, debug_info):
    """Process a single mutation and return the created document"""
    try:
        mutation_id = mutation.get("id")
        mutation_type = mutation.get("type", 0)
        # mutation.get("description", "eBoekhouden Import {mutation_id}")
        amount = frappe.utils.flt(mutation.get("amount", 0), 2)
        # mutation.get("relationId")
        # mutation.get("invoiceNumber")
        # mutation.get("ledgerId")
        # mutation.get("rows", [])

        debug_info.append(f"Processing single mutation {mutation_id}: type={mutation_type}, amount={amount}")

        # Check if already imported
        existing_je = _check_if_already_imported(mutation_id, "Journal Entry")
        existing_pe = _check_if_already_imported(mutation_id, "Payment Entry")
        existing_si = _check_if_already_imported(mutation_id, "Sales Invoice")
        existing_pi = _check_if_already_imported(mutation_id, "Purchase Invoice")

        if existing_je or existing_pe or existing_si or existing_pi:
            existing_doc = existing_je or existing_pe or existing_si or existing_pi
            # Mutation already imported
            return frappe.get_doc(
                (
                    "Journal Entry"
                    if existing_je
                    else (
                        "Payment Entry"
                        if existing_pe
                        else "Sales Invoice"
                        if existing_si
                        else "Purchase Invoice"
                    )
                ),
                existing_doc,
            )

        # CRITICAL: Fetch full mutation details for complete data
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        mutation_detail = iterator.fetch_mutation_detail(mutation_id)
        if not mutation_detail:
            debug_info.append(f"Could not fetch detailed data for mutation {mutation_id}, using summary data")
            mutation_detail = mutation  # Fallback to summary data
        else:
            # Count line items from both possible fields
            regels_count = len(mutation_detail.get("Regels", []))
            rows_count = len(mutation_detail.get("rows", []))
            total_items = regels_count or rows_count
            debug_info.append(
                f"Fetched detailed data for mutation {mutation_id} with {total_items} line items (Regels: {regels_count}, rows: {rows_count})"
            )

        # REMOVED: Duplicate detection - E-Boekhouden already enforces this perfectly

        # Handle different mutation types with detailed data
        if mutation_type == 1:  # Purchase Invoice (Invoice received)
            return _create_purchase_invoice(mutation_detail, company, cost_center, debug_info)
        elif mutation_type == 2:  # Sales Invoice (Invoice sent)
            return _create_sales_invoice(mutation_detail, company, cost_center, debug_info)
        elif mutation_type in [3, 4]:  # Customer/Supplier Payment types
            # Check if this is a credit note refund (negative amount with invoice reference)
            raw_amount = mutation_detail.get("amount", 0) or 0
            has_rows = bool(mutation_detail.get("rows"))
            row_amount = mutation_detail["rows"][0].get("amount", 0) if has_rows else 0
            is_negative = (raw_amount < 0) or (row_amount < 0)
            has_invoice_ref = bool(mutation_detail.get("invoiceNumber"))

            if is_negative and has_invoice_ref:
                debug_info.append(
                    f"Type {mutation_type} with negative amount and invoice ref - creating Journal Entry for credit note refund"
                )
                return _create_journal_entry(mutation_detail, company, cost_center, debug_info)
            else:
                return _create_payment_entry(mutation_detail, company, cost_center, debug_info)
        elif mutation_type in [5, 6]:  # Money Received/Money Paid - better as Payment Entries
            return _create_money_transfer_payment_entry(mutation_detail, company, cost_center, debug_info)
        else:
            # Create Journal Entry for other types (0, 7, 8, 9, 10, etc.)
            return _create_journal_entry(mutation_detail, company, cost_center, debug_info)

    except Exception as e:
        debug_info.append(f"Error processing single mutation {mutation.get('id')}: {str(e)}")
        raise


def _resolve_party_account(mutation_detail, account_type, company, debug_info):
    """
    Resolve a party account (Receivable or Payable) from eBoekhouden ledger mapping.

    For Receivable accounts, also handles the WooCommerce/FactuurSturen special case
    (uses "Te Ontvangen Bedragen" account).

    Args:
        mutation_detail: Mutation data dictionary
        account_type: "Receivable" or "Payable"
        company: Company name
        debug_info: List to append debug messages

    Returns:
        Account name if resolved, None if no suitable account found (ERPNext default will be used)
    """
    account_type_lower = account_type.lower()
    ledger_id = mutation_detail.get("ledgerId")
    if not ledger_id:
        debug_info.append(
            f"WARNING: No ledgerID found in mutation data, ERPNext will use default {account_type_lower} account selection"
        )
        return None

    # WooCommerce/FactuurSturen receivables use a special account
    if account_type == "Receivable":
        special_account = _check_woocommerce_factuursturen_account(mutation_detail, company, debug_info)
        if special_account:
            return special_account

    # Standard ledger mapping
    account_mapping = _resolve_account_mapping(ledger_id, debug_info)
    if not account_mapping or not account_mapping.get("erpnext_account"):
        debug_info.append(f"WARNING: No account mapping found for ledger ID {ledger_id}")
        return None

    party_account = account_mapping["erpnext_account"]

    # Group/control accounts cannot be used in invoices
    is_group = frappe.db.get_value("Account", party_account, "is_group")
    if is_group:
        debug_info.append(
            f"WARNING: Ledger {ledger_id} maps to group/control account '{party_account}'. "
            f"Cannot use control accounts in invoices - will use party default {account_type_lower} account instead."
        )
        return None

    ensure_account_type_is_correct(party_account, account_type, debug_info, auto_fix=True)
    debug_info.append(f"Set {account_type_lower} account from ledger mapping: {party_account}")
    return party_account


def _check_woocommerce_factuursturen_account(mutation_detail, company, debug_info):
    """Check if mutation is from WooCommerce/FactuurSturen and return special account if so."""
    description = mutation_detail.get("description", "")
    description_lower = description.lower()

    if "woocommerce" not in description_lower and "factuursturen" not in description_lower:
        return None

    debug_info.append("Found WooCommerce/FactuurSturen in description, using Te Ontvangen Bedragen account")
    te_ontvangen_account = frappe.db.get_value(
        "Account",
        {"account_name": ["like", "%Te Ontvangen Bedragen%"], "company": company, "is_group": 0},
        "name",
    )
    if te_ontvangen_account:
        ensure_account_type_is_correct(te_ontvangen_account, "Receivable", debug_info, auto_fix=True)
        debug_info.append(f"Set receivable account to: {te_ontvangen_account}")
        return te_ontvangen_account

    debug_info.append("WARNING: Te Ontvangen Bedragen account not found, falling back to ledger mapping")
    return None


def _resolve_receivable_account(mutation_detail, company, debug_info):
    """Resolve the receivable account for a sales invoice."""
    return _resolve_party_account(mutation_detail, "Receivable", company, debug_info)


def _process_invoice_line_items(
    invoice, mutation_detail, cost_center, is_credit_note, invoice_number, description, company, debug_info
):
    """
    Process line items for a sales invoice: handles credit note conversion,
    adds line items or fallback, enhances title, and consolidates mixed invoices.
    """
    from .invoice_helpers import (
        add_tax_lines,
        create_single_line_fallback,
        process_line_items,
    )

    regels = mutation_detail.get("Regels", []) or mutation_detail.get("rows", [])
    if regels:
        if is_credit_note:
            regels = _convert_regels_for_sales_credit_note(regels, debug_info)

        success = process_line_items(invoice, regels, "sales", cost_center, debug_info)
        if success:
            add_tax_lines(invoice, regels, "sales", debug_info)
        else:
            create_single_line_fallback(invoice, mutation_detail, cost_center, debug_info)
    else:
        debug_info.append("No Regels found, creating single line fallback")
        if is_credit_note:
            mutation_detail = _convert_mutation_detail_amount(mutation_detail, debug_info)
        create_single_line_fallback(invoice, mutation_detail, cost_center, debug_info)

    _enhance_sales_invoice_title(invoice, invoice_number, description, debug_info)

    # Consolidate mixed invoices with negative total into single line
    _consolidate_mixed_invoice_if_needed(invoice, cost_center, company, debug_info)


def _consolidate_mixed_invoice_if_needed(invoice, cost_center, company, debug_info):
    """
    If an invoice has both positive and negative line items resulting in a negative total,
    consolidate into a single line and mark as credit note. This handles edge cases from
    eBoekhouden where partial refunds are mixed into the same mutation.
    """
    calculated_total = sum(item.qty * item.rate for item in invoice.items)
    if calculated_total >= 0:
        return

    has_positive_qty = any(item.qty > 0 for item in invoice.items)
    has_negative_qty = any(item.qty < 0 for item in invoice.items)
    is_mixed = has_positive_qty and has_negative_qty

    if is_mixed:
        debug_info.append(
            f"Mixed invoice with negative total ({calculated_total}). "
            f"Consolidating {len(invoice.items)} line items into single net amount."
        )
        item_descriptions = [f"{item.description} ({item.qty} x {item.rate})" for item in invoice.items]
        consolidated_desc = "CONSOLIDATED MIXED INVOICE: " + "; ".join(item_descriptions)

        from .eboekhouden_improved_item_naming import get_or_create_generic_item

        generic_item = get_or_create_generic_item(company)
        invoice.items = []
        invoice.append(
            "items",
            {
                "item_code": generic_item,
                "item_name": "Consolidated E-Boekhouden Item",
                "description": consolidated_desc[:500],
                "qty": -1 if calculated_total < 0 else 1,
                "rate": abs(calculated_total),
                "uom": "Unit",
                "cost_center": cost_center,
            },
        )
        invoice.is_return = 1
        invoice.update_stock = 0
        debug_info.append(
            f"Consolidated to single line: qty={invoice.items[0].qty}, "
            f"rate={invoice.items[0].rate}, net={calculated_total}"
        )
    else:
        debug_info.append(
            f"Pure credit note with negative total ({calculated_total}). is_return already set."
        )


def _setup_invoice_common(doc, mutation_detail, company, debug_info):
    """Set up common fields shared between sales and purchase invoices.

    Handles: company, posting_date, currency, payment terms, remarks,
    credit note detection, custom tracking fields.

    Args:
        doc: The invoice document (Sales Invoice or Purchase Invoice)
        mutation_detail: eBoekhouden mutation data
        company: Company name
        debug_info: Debug message list

    Returns:
        tuple: (is_credit_note, effective_total_amount) or None if credit note detection fails
    """
    from frappe.utils import add_days

    from .invoice_helpers import get_or_create_payment_terms

    mutation_id = mutation_detail.get("id")
    description = mutation_detail.get("description", f"eBoekhouden Import {mutation_id}")
    invoice_number = mutation_detail.get("invoiceNumber")

    # Basic fields
    doc.company = company
    doc.posting_date = mutation_detail.get("date")
    doc.set_posting_time = 1

    # Currency
    company_currency = frappe.db.get_value("Company", company, "default_currency") or "EUR"
    doc.currency = company_currency
    doc.conversion_rate = 1.0

    # Payment terms and due date
    payment_days = mutation_detail.get("Betalingstermijn", 30)
    if payment_days:
        try:
            payment_terms = get_or_create_payment_terms(payment_days)
            if payment_terms:
                doc.payment_terms_template = payment_terms
            doc.due_date = add_days(doc.posting_date, payment_days)
        except Exception as e:
            debug_info.append(f"Warning: Failed to create payment terms for {payment_days} days: {str(e)}")
            doc.due_date = add_days(doc.posting_date, payment_days)

    # Description
    doc.remarks = description

    # Credit note detection
    credit_note_result = _detect_credit_note_improved(mutation_detail, debug_info)
    if credit_note_result is None:
        debug_info.append("ERROR: Credit note detection returned None - skipping invoice creation")
        return None

    is_credit_note, effective_total_amount = credit_note_result
    doc.is_return = is_credit_note

    if is_credit_note:
        debug_info.append(
            f"Processing as credit note (effective amount: {effective_total_amount}), will convert amounts to positive"
        )

    # Custom tracking fields
    doc.eboekhouden_mutation_nr = str(mutation_id)
    if invoice_number:
        doc.eboekhouden_invoice_number = invoice_number

    return is_credit_note, effective_total_amount


def _save_and_submit_invoice(doc, company, debug_info):
    """Save and submit an invoice with fiscal year handling.

    Args:
        doc: The invoice document (Sales Invoice or Purchase Invoice)
        company: Company name
        debug_info: Debug message list
    """
    invoice_type = doc.doctype

    try:
        doc.save()
        debug_info.append(f"Saved {invoice_type} draft: {doc.name}")
    except Exception as save_error:
        debug_info.append(f"ERROR: Failed to save {invoice_type}: {str(save_error)}")
        raise

    from .invoice_helpers import ensure_fiscal_year_exists

    try:
        ensure_fiscal_year_exists(doc.posting_date, company, debug_info)
    except Exception as fy_error:
        debug_info.append(f"WARNING: Could not ensure fiscal year: {str(fy_error)}")

    try:
        doc.submit()
        debug_info.append(f"Submitted {invoice_type}: {doc.name}")
    except Exception as submit_error:
        debug_info.append(f"ERROR: Failed to submit {invoice_type} {doc.name}: {str(submit_error)}")
        debug_info.append(f"Submit error type: {type(submit_error).__name__}")
        raise

    debug_info.append(f"Created enhanced {invoice_type} {doc.name} with {len(doc.items)} line items")


def _create_sales_invoice(mutation_detail, company, cost_center, debug_info):
    """Create Sales Invoice with ALL available fields from detailed mutation data"""
    from .party_resolver import resolve_customer

    mutation_id = mutation_detail.get("id")
    description = mutation_detail.get("description", f"eBoekhouden Import {mutation_id}")
    invoice_number = mutation_detail.get("invoiceNumber")
    relation_id = mutation_detail.get("relationId")

    debug_info.append(f"Creating Sales Invoice for mutation {mutation_id}")

    si = frappe.new_doc("Sales Invoice")

    # Common setup (company, currency, payment terms, credit note detection, tracking fields)
    result = _setup_invoice_common(si, mutation_detail, company, debug_info)
    if result is None:
        return None
    is_credit_note, _effective_total_amount = result

    # Sales-specific fields
    customer = resolve_customer(relation_id, debug_info)
    si.customer = customer

    if mutation_detail.get("Referentie"):
        si.po_no = mutation_detail.get("Referentie")

    receivable_account = _resolve_receivable_account(mutation_detail, company, debug_info)
    if receivable_account:
        si.debit_to = receivable_account

    # Process line items, handle credit notes, and consolidate mixed invoices
    _process_invoice_line_items(
        si, mutation_detail, cost_center, is_credit_note, invoice_number, description, company, debug_info
    )

    _save_and_submit_invoice(si, company, debug_info)
    return si


def _enhance_sales_invoice_title(sales_invoice, invoice_number, description, debug_info):
    """
    Enhance Sales Invoice title to include invoice number for better identification

    Args:
        sales_invoice: The Sales Invoice document
        invoice_number: The eBoekhouden invoice number (factuurnummer)
        description: The transaction description
        debug_info: List to append debug messages to
    """
    if not invoice_number:
        debug_info.append("No invoice number available for title enhancement")
        return

    try:
        # Extract customer name for context
        customer_name = sales_invoice.customer_name or sales_invoice.customer

        # For all invoices, use clean format: Customer - Factuur Number
        invoice_num = str(invoice_number).replace("/", "-").replace("\\", "-")
        sales_invoice.title = f"{customer_name} - Factuur {invoice_num}"
        debug_info.append(f"Enhanced sales invoice title: {sales_invoice.title}")

    except Exception as e:
        debug_info.append(f"Warning: Failed to enhance sales invoice title: {str(e)}")


def _detect_credit_note_improved(mutation_detail, debug_info):
    """
    Improved credit note detection that checks both main amount and line item amounts.

    Returns tuple: (is_credit_note, effective_total_amount)
    """
    # First check main amount field
    main_amount = frappe.utils.flt(mutation_detail.get("amount", 0))

    # If main amount is negative, it's definitely a credit note
    if main_amount < 0:
        debug_info.append(f"Credit note detected from main amount: {main_amount}")
        return True, main_amount

    # If main amount is positive and non-zero, it's definitely not a credit note
    if main_amount > 0:
        debug_info.append(f"Not a credit note - main amount is positive: {main_amount}")
        return False, main_amount

    # Main amount is 0 or None - check line items
    regels = mutation_detail.get("Regels", []) or mutation_detail.get("rows", [])
    if not regels:
        debug_info.append("No line items to check for credit note detection")
        return False, main_amount

    # Calculate total from line items
    line_item_total = 0
    negative_items = 0
    positive_items = 0

    for regel in regels:
        # Handle both Dutch (SOAP) and English (REST) field names
        amount_field = "amount" if "amount" in regel else "Prijs"
        quantity_field = "quantity" if "quantity" in regel else "Aantal"

        item_amount = frappe.utils.flt(regel.get(amount_field, 0))
        item_quantity = frappe.utils.flt(regel.get(quantity_field, 1))

        # Calculate total amount for this line item
        total_item_amount = item_amount * item_quantity
        line_item_total += total_item_amount

        if total_item_amount < 0:
            negative_items += 1
        elif total_item_amount > 0:
            positive_items += 1

    debug_info.append(
        f"Line item analysis: total={line_item_total}, negative_items={negative_items}, positive_items={positive_items}"
    )

    # Determine if it's a credit note based on line item analysis
    # CRITICAL: Only treat as credit note if ALL items are negative (pure credit note)
    # Mixed invoices (some positive, some negative) should NOT be treated as credit notes
    # ERPNext's is_return expects ALL items to be credits, not a mix
    if negative_items > 0 and positive_items == 0:
        # All items are negative - this is a pure credit note
        debug_info.append(
            f"Credit note detected - all {negative_items} line items are negative (total: {line_item_total})"
        )
        return True, line_item_total
    elif negative_items > 0 and positive_items > 0:
        # Mixed invoice with both debits and credits
        debug_info.append(
            f"Mixed invoice detected: {positive_items} positive items, {negative_items} negative items (net: {line_item_total}). "
            f"NOT treating as credit note - will preserve individual item signs."
        )
        return False, line_item_total
    else:
        # All other cases: not a credit note
        # This handles:
        # - All positive items (normal invoice)
        # - Zero total
        # - Any edge cases
        debug_info.append(f"Not a credit note based on line item analysis (total: {line_item_total})")
        return False, line_item_total


def _get_ledger_code_from_id(ledger_id, company, debug_info):
    """Get the ledger code (account number) from ledger ID via mapping table"""
    if not ledger_id:
        return None

    mapping_result = frappe.db.sql(
        """SELECT ledger_code FROM `tabE-Boekhouden Ledger Mapping` WHERE ledger_id = %s LIMIT 1""",
        str(ledger_id),
    )

    if mapping_result:
        ledger_code = mapping_result[0][0]
        debug_info.append(f"Resolved ledger_id {ledger_id} to ledger_code {ledger_code}")
        return ledger_code
    else:
        debug_info.append(f"No mapping found for ledger_id {ledger_id}")
        # Try to fetch missing mapping from E-Boekhouden API before failing
        try:
            _fetch_and_create_missing_ledger_mapping(ledger_id, company, debug_info)
            # Retry the lookup after creating mapping
            retry_result = frappe.db.sql(
                """SELECT ledger_code FROM `tabE-Boekhouden Ledger Mapping` WHERE ledger_id = %s LIMIT 1""",
                str(ledger_id),
            )
            if retry_result:
                ledger_code = retry_result[0][0]
                debug_info.append(
                    f"Created missing mapping and resolved ledger_id {ledger_id} to ledger_code {ledger_code}"
                )
                return ledger_code
        except Exception as e:
            debug_info.append(f"Failed to create missing ledger mapping: {str(e)}")

        # If all else fails, raise an error instead of returning invalid data
        error_msg = f"No account mapping found for E-Boekhouden ledger ID {ledger_id}. Please configure the ledger mapping or run the Chart of Accounts import to create missing mappings."
        frappe.throw(error_msg, title="Missing Account Mapping")


def get_erpnext_account_from_ledger_id(ledger_id, company, debug_info, auto_create=True):
    """
    Get ERPNext account name from E-Boekhouden ledger ID.

    Args:
        ledger_id: E-Boekhouden ledger ID
        company: Company name for account lookup
        debug_info: List to append debug messages to
        auto_create: If True, attempt to fetch and create missing mappings from API

    Returns:
        ERPNext account name or None if not found/created
    """
    if not ledger_id:
        return None

    # First try to get existing mapping
    mapping_result = frappe.db.sql(
        """SELECT erpnext_account
           FROM `tabE-Boekhouden Ledger Mapping`
           WHERE ledger_id = %s
           LIMIT 1""",
        ledger_id,
    )

    if mapping_result:
        return mapping_result[0][0]

    # No existing mapping found
    if not auto_create:
        debug_info.append(f"No mapping found for ledger {ledger_id} (auto_create=False)")
        return None

    # Try to fetch and create missing mapping
    debug_info.append(f"No mapping found for ledger {ledger_id}, attempting to fetch from API")
    return _fetch_and_create_missing_ledger_mapping(ledger_id, company, debug_info)


def _fetch_and_create_missing_ledger_mapping(ledger_id, company, debug_info):
    """
    Fetch ledger details from E-Boekhouden API and create mapping if missing.

    Args:
        ledger_id: E-Boekhouden ledger ID to fetch
        company: Company name for account lookup
        debug_info: List to append debug messages to

    Returns:
        ERPNext account name or None if not found
    """
    try:
        from .eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()
        session_token = iterator._get_session_token()

        if not session_token:
            debug_info.append(f"Failed to get session token for ledger {ledger_id}")
            return None

        headers = {"Authorization": session_token, "Accept": "application/json"}
        ledger_url = f"{iterator.base_url}/v1/ledger/{ledger_id}"

        response = requests.get(ledger_url, headers=headers, timeout=30)

        if response.status_code == 200:
            ledger_data = response.json()
            ledger_code = ledger_data.get("code")
            ledger_name = ledger_data.get("description", "")

            if ledger_code:
                # Check if account exists with this code - try multiple lookup methods
                # 1. First try by eboekhouden_grootboek_nummer (custom field)
                account_name = frappe.db.get_value(
                    "Account",
                    {"company": company, "eboekhouden_grootboek_nummer": ledger_code},
                    "name",
                )

                # 2. If not found, try by account_number (standard field from CoA import)
                if not account_name:
                    account_name = frappe.db.get_value(
                        "Account",
                        {"company": company, "account_number": ledger_code},
                        "name",
                    )
                    if account_name:
                        debug_info.append(f"Found account by account_number: {ledger_code} -> {account_name}")

                # 3. If still not found, try by name pattern (e.g., "1101 - Name - ABBR")
                if not account_name:
                    company_abbr = frappe.db.get_value("Company", company, "abbr")
                    if company_abbr:
                        name_pattern = f"{ledger_code} - % - {company_abbr}"
                        result = frappe.db.get_value(
                            "Account",
                            {"company": company, "name": ("like", name_pattern)},
                            "name",
                        )
                        if result:
                            account_name = result
                            debug_info.append(
                                f"Found account by name pattern: {name_pattern} -> {account_name}"
                            )

                if account_name:
                    # Check if mapping was created by another concurrent call
                    existing = frappe.db.get_value(
                        "E-Boekhouden Ledger Mapping", {"ledger_id": str(ledger_id)}, "erpnext_account"
                    )

                    if existing:
                        debug_info.append(
                            f"Mapping already exists (created by concurrent call): {ledger_id} -> {existing}"
                        )
                        return existing

                    # Create ledger mapping only if still missing
                    try:
                        mapping = frappe.new_doc("E-Boekhouden Ledger Mapping")
                        mapping.ledger_id = str(ledger_id)
                        mapping.ledger_code = ledger_code
                        mapping.ledger_name = ledger_name
                        mapping.erpnext_account = account_name
                        mapping.insert()

                        debug_info.append(f"Created ledger mapping: {ledger_id} -> {account_name}")
                        return account_name
                    except frappe.exceptions.DuplicateEntryError:
                        # Another process created it between our check and insert
                        debug_info.append(f"Mapping created by concurrent call during insert: {ledger_id}")
                        return frappe.db.get_value(
                            "E-Boekhouden Ledger Mapping", {"ledger_id": str(ledger_id)}, "erpnext_account"
                        )
                else:
                    debug_info.append(
                        f"No account found for ledger code {ledger_code} (name: {ledger_name}) "
                        f"in company {company}. Searched by eboekhouden_grootboek_nummer, "
                        f"account_number, and name pattern."
                    )

        else:
            debug_info.append(f"API error fetching ledger {ledger_id}: {response.status_code}")

    except Exception as e:
        debug_info.append(f"Error fetching ledger {ledger_id}: {str(e)}")

    return None


def _convert_negative_amounts_to_positive(regels, debug_info):
    """Convert negative amounts in line items to positive values for credit notes (Purchase Invoices)"""
    return _convert_regels_for_credit_note(regels, "purchase", debug_info)


def _convert_regels_for_sales_credit_note(regels, debug_info):
    """Convert line items for Sales Invoice credit notes - amounts positive, quantities negative"""
    return _convert_regels_for_credit_note(regels, "sales", debug_info)


def _convert_regels_for_credit_note(regels, invoice_type, debug_info):
    """
    Convert line items for credit notes with proper quantity/amount handling.

    For ALL Returns (both Sales and Purchase Invoices with is_return=True):
    - Amounts: Convert to positive (ERPNext handles the math)
    - Quantities: MUST be negative (ERPNext validation requirement)

    ERPNext validates in status_updater.py:243-244:
    if d.qty > 0 and self.get("is_return"):
        throw("quantity must be negative number")
    """
    if not regels:
        return regels

    converted_regels = []
    for regel in regels:
        converted_regel = regel.copy()  # Create a copy to avoid modifying original

        # Handle both Dutch (SOAP) and English (REST) field names
        amount_field = "amount" if "amount" in regel else "Prijs"
        quantity_field = "quantity" if "quantity" in regel else "Aantal"

        # Convert amounts to positive (both sales and purchase)
        if amount_field in regel:
            original_amount = frappe.utils.flt(regel[amount_field])
            if original_amount < 0:
                converted_regel[amount_field] = abs(original_amount)
                debug_info.append(
                    f"Converted negative amount {original_amount} to positive {abs(original_amount)}"
                )

        # Handle quantities based on invoice type
        # For eBoekhouden data, quantity field might not exist, defaulting to 1
        if quantity_field in regel:
            original_quantity = frappe.utils.flt(regel[quantity_field])
        else:
            # Default quantity when field doesn't exist
            original_quantity = 1.0

        if original_quantity != 0:
            # For ALL Returns (both Sales and Purchase), quantities MUST be negative
            # ERPNext validation: if is_return and qty > 0 → error
            if original_quantity > 0:
                converted_regel[quantity_field] = -abs(original_quantity)
                debug_info.append(
                    f"{invoice_type.title()} credit note: converted positive quantity {original_quantity} to negative {-abs(original_quantity)}"
                )
            else:
                # Already negative, keep it
                converted_regel[quantity_field] = original_quantity
                debug_info.append(
                    f"{invoice_type.title()} credit note: kept negative quantity {original_quantity}"
                )

        converted_regels.append(converted_regel)

    return converted_regels


def _convert_mutation_detail_amount(mutation_detail, debug_info):
    """Convert negative amount in mutation detail to positive for credit notes"""
    if not mutation_detail:
        return mutation_detail

    converted_detail = mutation_detail.copy()

    # Handle both Dutch (SOAP) and English (REST) field names
    amount_field = "amount" if "amount" in mutation_detail else "Bedrag"

    if amount_field in mutation_detail:
        original_amount = frappe.utils.flt(mutation_detail[amount_field])
        if original_amount < 0:
            converted_detail[amount_field] = abs(original_amount)
            debug_info.append(
                f"Converted mutation detail amount {original_amount} to positive {abs(original_amount)}"
            )

    return converted_detail


def _resolve_payable_account(mutation_detail, company, debug_info):
    """Resolve the payable account for a purchase invoice."""
    return _resolve_party_account(mutation_detail, "Payable", company, debug_info)


def _run_parallel_credit_note_validation(
    mutation_id, mutation_detail, is_credit_note, effective_total_amount, debug_info
):
    """
    Run the new invoice classifier in parallel with the old credit note detection logic,
    logging any mismatches. Uses old logic for actual processing (safe fallback).
    """
    from verenigingen.e_boekhouden.utils.invoice_classifier import ProcessingStrategy, get_invoice_classifier

    try:
        classifier = get_invoice_classifier()
        new_classification = classifier.classify(mutation_detail, debug_info)

        new_is_credit_note = new_classification.processing_strategy == ProcessingStrategy.CREDIT_NOTE

        if is_credit_note != new_is_credit_note:
            frappe.log_error(
                title=f"Classification Mismatch - Mutation {mutation_id}",
                message=(
                    f"OLD vs NEW classifier disagreement for mutation {mutation_id}\n\n"
                    f"OLD Logic:\n"
                    f"  is_credit_note: {is_credit_note}\n"
                    f"  effective_total: {effective_total_amount}\n\n"
                    f"NEW Classifier:\n"
                    f"  invoice_type: {new_classification.invoice_type.value}\n"
                    f"  processing_strategy: {new_classification.processing_strategy.value}\n"
                    f"  net_amount: {new_classification.net_amount}\n"
                    f"  positive_items: {new_classification.positive_item_count}\n"
                    f"  negative_items: {new_classification.negative_item_count}\n"
                    f"  reasoning: {new_classification.reasoning}\n\n"
                    f"Using OLD logic for safety.\n\n"
                    f"Debug info:\n{frappe.as_json(debug_info, indent=2)}"
                ),
            )
            debug_info.append(
                f"CLASSIFICATION MISMATCH: Old={is_credit_note}, New={new_is_credit_note}. Using old logic."
            )

        debug_info.append(
            f"Parallel validation: Old logic={'credit_note' if is_credit_note else 'normal'}, "
            f"New logic={new_classification.processing_strategy.value}, "
            f"Match={'yes' if is_credit_note == new_is_credit_note else 'no'}"
        )
    except Exception as classifier_error:
        frappe.log_error(
            title=f"New Classifier Failed - Mutation {mutation_id}",
            message=f"Error running new classifier:\n{str(classifier_error)}\n\n{frappe.get_traceback()}",
        )
        debug_info.append(f"New classifier failed: {str(classifier_error)}. Using old logic.")


def _process_purchase_invoice_line_items(
    invoice, mutation_detail, cost_center, is_credit_note, company, debug_info
):
    """
    Process line items for a purchase invoice: handles credit note conversion,
    adds line items or fallback, consolidates mixed invoices, and saves the document.
    """
    from .invoice_helpers import (
        add_tax_lines,
        create_single_line_fallback,
        process_line_items,
    )

    regels = mutation_detail.get("Regels", []) or mutation_detail.get("rows", [])
    if regels:
        if is_credit_note:
            regels = _convert_negative_amounts_to_positive(regels, debug_info)

        success = process_line_items(invoice, regels, "purchase", cost_center, debug_info)
        if success:
            add_tax_lines(invoice, regels, "purchase", debug_info)
        else:
            create_single_line_fallback(invoice, mutation_detail, cost_center, debug_info)
    else:
        debug_info.append("No Regels found, creating single line fallback")
        if is_credit_note:
            mutation_detail = _convert_mutation_detail_amount(mutation_detail, debug_info)
        create_single_line_fallback(invoice, mutation_detail, cost_center, debug_info)

    # Consolidate mixed invoices and handle pure credit notes before saving
    _consolidate_purchase_invoice_and_save(invoice, cost_center, company, debug_info)


def _consolidate_purchase_invoice_and_save(invoice, cost_center, company, debug_info):
    """
    For purchase invoices: detect negative totals from mixed line items,
    consolidate if needed, set credit note flags, and save the document.
    """
    calculated_total = sum(item.qty * item.rate for item in invoice.items)

    if calculated_total < 0:
        has_positive_qty = any(item.qty > 0 for item in invoice.items)
        has_negative_qty = any(item.qty < 0 for item in invoice.items)
        is_mixed = has_positive_qty and has_negative_qty

        if is_mixed:
            debug_info.append(
                f"Mixed invoice with negative total ({calculated_total}). "
                f"Consolidating {len(invoice.items)} line items into single net amount."
            )
            _consolidate_mixed_invoice_if_needed(invoice, cost_center, company, debug_info)
        else:
            debug_info.append(
                f"Pure credit note detected ({calculated_total}). Setting is_return=True (debit note) "
                f"and disabling stock updates."
            )
            invoice.is_return = 1
            invoice.update_stock = 0

    invoice.save()


def _create_purchase_invoice(mutation_detail, company, cost_center, debug_info):
    """Create Purchase Invoice with ALL available fields from detailed mutation data"""
    from .party_resolver import resolve_supplier

    mutation_id = mutation_detail.get("id")
    invoice_number = mutation_detail.get("invoiceNumber")
    relation_id = mutation_detail.get("relationId")

    debug_info.append(f"Creating Purchase Invoice for mutation {mutation_id}")

    pi = frappe.new_doc("Purchase Invoice")

    # Common setup (company, currency, payment terms, credit note detection, tracking fields)
    result = _setup_invoice_common(pi, mutation_detail, company, debug_info)
    if result is None:
        return None
    is_credit_note, effective_total_amount = result

    # Purchase-specific fields
    supplier = resolve_supplier(relation_id, debug_info)
    pi.supplier = supplier

    if invoice_number:
        pi.bill_no = invoice_number
    if mutation_detail.get("Referentie"):
        pi.supplier_invoice_no = mutation_detail.get("Referentie")

    # Parallel credit note validation (purchase only)
    _run_parallel_credit_note_validation(
        mutation_id, mutation_detail, is_credit_note, effective_total_amount, debug_info
    )

    payable_account = _resolve_payable_account(mutation_detail, company, debug_info)
    if payable_account:
        pi.credit_to = payable_account

    # Process line items, handle credit notes, and consolidate mixed invoices
    _process_purchase_invoice_line_items(
        pi, mutation_detail, cost_center, is_credit_note, company, debug_info
    )

    _save_and_submit_invoice(pi, company, debug_info)
    return pi


def _create_payment_entry(mutation, company, cost_center, debug_info):
    """
    Create Payment Entry from mutation.

    This function now uses the enhanced PaymentEntryHandler for:
    - Proper bank account mapping from ledger IDs
    - Multi-invoice payment support
    - Automatic payment reconciliation
    """
    # Use enhanced payment handler (single code path)
    from verenigingen.e_boekhouden.utils.eboekhouden_payment_import import create_payment_entry

    payment_name = create_payment_entry(mutation, company, cost_center, debug_info)
    if payment_name:
        return frappe.get_doc("Payment Entry", payment_name)
    else:
        # Enhanced handler failed - this is a critical error that should be investigated
        error_msg = f"Enhanced payment handler failed for mutation {mutation.get('id')}. Check debug logs for details."
        debug_info.append(f"ERROR: {error_msg}")
        raise frappe.ValidationError(error_msg)


def _create_import_log_entry(mutation, company, debug_info):
    """Create a comprehensive log entry for zero-amount transactions that can't be imported as financial documents"""
    mutation_id = mutation.get("id")
    mutation_type = mutation.get("type", 0)
    description = mutation.get("description", f"eBoekhouden Import {mutation_id}")
    posting_date = mutation.get("date")
    ledger_id = mutation.get("ledgerId")
    rows = mutation.get("rows", [])

    # Build detailed log content
    type_name = MUTATION_TYPE_SINGULAR.get(mutation_type, f"Type {mutation_type}")

    log_content = f"""ZERO-AMOUNT EBOEKHOUDEN TRANSACTION IMPORTED

Mutation ID: {mutation_id}
Type: {type_name} ({mutation_type})
Date: {posting_date}
Description: {description}
Main Ledger ID: {ledger_id}

This transaction had zero financial impact and was logged for audit purposes only.
No ERPNext financial document was created due to zero amount.

Row Details:"""

    for i, row in enumerate(rows):
        row_amount = frappe.utils.flt(row.get("amount", 0), 2)
        row_ledger = row.get("ledgerId")
        row_desc = row.get("description", "")
        log_content += f"\n  Row {i + 1}: Amount €{row_amount}, Ledger {row_ledger}, {row_desc}"

    try:
        # Create error log entry for better tracking
        error_log = frappe.new_doc("Error Log")
        error_log.method = "eBoekhouden Zero-Amount Import"
        error_log.error = log_content
        error_log.save()

        debug_info.append(
            f"Created comprehensive log entry {error_log.name} for zero-amount mutation {mutation_id}"
        )

        # Return the Error Log document directly so it has .doctype and .name attributes
        return error_log

    except Exception as e:
        debug_info.append(f"Failed to create log entry: {str(e)}")
        # Fallback to simple comment
        try:
            comment = frappe.new_doc("Comment")
            comment.comment_type = "Info"
            comment.reference_doctype = "Company"
            comment.reference_name = company
            comment.content = f"Zero-amount eBoekhouden transaction {mutation_id}: {description}"
            comment.save()

            debug_info.append(f"Created fallback comment {comment.name} for mutation {mutation_id}")
            return comment
        except Exception as e2:
            debug_info.append(f"Both log entry and comment creation failed: {str(e2)}")
            # Return None to indicate failure
            return None


def _create_money_transfer_payment_entry(mutation, company, cost_center, debug_info):
    """
    Create Journal Entry for Money Received (type 5) or Money Paid (type 6).

    Delegates to PaymentProcessor._process_money_transfer() which provides:
    - Multi-row support (one JE line per row, not just the first row)
    - Party extraction from mutation description/relation
    - Bank Transaction creation for reconciliation
    - Duplicate handling (idempotent insert)
    - PII-masked error logging

    Note: The old implementation raised ValueError for Receivable/Payable accounts.
    PaymentProcessor handles these correctly by extracting and assigning parties.
    """
    from verenigingen.e_boekhouden.utils.processors.payment_processor import PaymentProcessor

    # Normalize Dutch "Regels" key to "rows" for PaymentProcessor compatibility
    if "Regels" in mutation and "rows" not in mutation:
        mutation["rows"] = mutation["Regels"]

    processor = PaymentProcessor(company, cost_center)
    result = processor._process_money_transfer(mutation)

    # Copy debug info from processor to caller's debug_info list
    processor_debug = processor.get_debug_info()
    if processor_debug:
        debug_info.extend(processor_debug)

    return result


def _process_journal_entry_rows(
    je, mutation, rows, main_ledger_id, company, cost_center, description, debug_info
):
    """
    Process all rows for a journal entry: resolve accounts, calculate debit/credit amounts,
    assign parties, and add the memorial balancing entry for type 7 bookings.

    Returns:
        tuple: (total_debit, total_credit) accumulated from all rows including balancing entry
    """
    mutation_id = mutation.get("id")
    mutation_type = mutation.get("type", 0)
    relation_id = mutation.get("relationId")
    is_memorial_booking = mutation_type == 7
    total_debit = 0
    total_credit = 0

    for row in rows:
        row_amount = frappe.utils.flt(row.get("amount", 0), 2)
        row_ledger_id = row.get("ledgerId")
        row_description = row.get("description", description)

        if row_amount == 0:
            continue

        row_account = _resolve_journal_row_account(
            row_ledger_id, row_amount, row_description, mutation, company, debug_info
        )

        if is_memorial_booking:
            row_debit, row_credit, _unused1, _unused2 = _get_memorial_booking_amounts(
                row_ledger_id, main_ledger_id, row_amount, debug_info
            )
            entry_line = {
                "account": row_account,
                "debit_in_account_currency": frappe.utils.flt(row_debit, 2),
                "credit_in_account_currency": frappe.utils.flt(row_credit, 2),
                "cost_center": cost_center,
                "user_remark": row_description,
                "is_advance": "No",
            }
            debug_info.append(
                f"Memorial row: {row_account} Dr={row_debit} Cr={row_credit} (from amount={row_amount})"
            )
        else:
            entry_line = {
                "account": row_account,
                "debit_in_account_currency": frappe.utils.flt(row_amount if row_amount > 0 else 0, 2),
                "credit_in_account_currency": frappe.utils.flt(-row_amount if row_amount < 0 else 0, 2),
                "cost_center": cost_center,
                "user_remark": row_description,
                "is_advance": "No",
            }

        # Add party for receivable/payable accounts
        _assign_party_to_entry(
            entry_line, row_account, mutation_type, relation_id, company, description, debug_info
        )

        debug_info.append(f"Appending entry_line: {entry_line}")
        je.append("accounts", entry_line)
        total_debit += entry_line["debit_in_account_currency"]
        total_credit += entry_line["credit_in_account_currency"]

    # For memorial bookings, add ONE balancing entry to main ledger for the net effect
    if is_memorial_booking and main_ledger_id and rows:
        main_line = _build_memorial_balancing_entry(
            mutation_id,
            rows,
            main_ledger_id,
            total_debit,
            total_credit,
            company,
            cost_center,
            description,
            debug_info,
        )
        if main_line:
            _assign_party_to_entry(
                main_line, main_line["account"], mutation_type, None, company, description, debug_info
            )
            debug_info.append(f"Appending main_line: {main_line}")
            je.append("accounts", main_line)
            total_debit += main_line["debit_in_account_currency"]
            total_credit += main_line["credit_in_account_currency"]

    return total_debit, total_credit


def _resolve_journal_row_account(row_ledger_id, row_amount, row_description, mutation, company, debug_info):
    """Resolve ERPNext account for a journal entry row, falling back to tegenrekening mapping."""
    row_account = get_erpnext_account_from_ledger_id(row_ledger_id, company, debug_info, auto_create=True)
    if row_account:
        return row_account

    ledger_code = _get_ledger_code_from_id(row_ledger_id, company, debug_info) if row_ledger_id else None
    line_dict = create_invoice_line_for_tegenrekening(
        tegenrekening_code=ledger_code,
        amount=abs(row_amount),
        description=row_description,
        transaction_type="purchase",
    )
    row_account = line_dict.get("expense_account")
    if not row_account:
        raise ValueError(
            f"No expense account mapping found for mutation {mutation.get('ID', 'unknown')} "
            f"row with ledger_id {row_ledger_id}. Account mapping required for proper financial reporting."
        )
    return row_account


def _assign_party_to_entry(entry_line, account, mutation_type, relation_id, company, description, debug_info):
    """Add party_type and party to a journal entry line if the account is Receivable or Payable."""
    account_type = frappe.db.get_value("Account", account, "account_type")
    if account_type == "Receivable":
        entry_line["party_type"] = "Customer"
        if mutation_type == 7:
            entry_line["party"] = _get_or_create_company_as_customer(company, debug_info)
        elif relation_id:
            entry_line["party"] = _get_or_create_customer(relation_id, debug_info)
    elif account_type == "Payable":
        entry_line["party_type"] = "Supplier"
        if mutation_type == 7:
            entry_line["party"] = _get_or_create_company_as_supplier(company, debug_info)
        elif relation_id:
            entry_line["party"] = _get_or_create_supplier(relation_id, description, debug_info)


def _build_memorial_balancing_entry(
    mutation_id,
    rows,
    main_ledger_id,
    total_debit,
    total_credit,
    company,
    cost_center,
    description,
    debug_info,
):
    """
    Build the balancing entry for the main ledger in a memorial booking.
    For single-row bookings, uses _get_memorial_booking_amounts for precise calculation.
    For multi-row bookings, calculates the net imbalance to balance the journal entry.

    Returns:
        dict or None: The balancing entry line, or None if no balancing is needed.
    """
    main_account = get_erpnext_account_from_ledger_id(main_ledger_id, company, debug_info, auto_create=True)
    if not main_account:
        raise ValueError(f"Memorial booking {mutation_id}: No mapping found for main ledger {main_ledger_id}")

    if len(rows) == 1:
        row = rows[0]
        row_amount = frappe.utils.flt(row.get("amount", 0), 2)
        row_ledger_id = row.get("ledgerId")
        main_result = _get_memorial_booking_amounts(row_ledger_id, main_ledger_id, row_amount, debug_info)
        row_d, row_c, main_debit, main_credit = main_result
        debug_info.append(
            f"Main balance calculation returned: row_d={row_d}, row_c={row_c}, main_d={main_debit}, main_c={main_credit}"
        )
        debug_info.append(f"Memorial balance (single row): {main_account} Dr={main_debit} Cr={main_credit}")
    else:
        row_net = total_debit - total_credit
        if abs(row_net) <= 0.01:
            return None  # No balancing needed
        main_debit = -row_net if row_net < 0 else 0
        main_credit = row_net if row_net > 0 else 0
        debug_info.append(
            f"Memorial balance (multi-row): {main_account} Dr={main_debit} Cr={main_credit} (balances {row_net})"
        )

    return {
        "account": main_account,
        "debit_in_account_currency": frappe.utils.flt(main_debit, 2),
        "credit_in_account_currency": frappe.utils.flt(main_credit, 2),
        "cost_center": cost_center,
        "user_remark": f"Memorial booking balance: {description}",
        "is_advance": "No",
    }


def _validate_memorial_booking(
    je, mutation, rows, amount, total_debit, total_credit, company, cost_center, debug_info
):
    """
    Validate memorial booking: check that rows sum to expected net amount
    and that the journal entry is balanced (ERPNext requirement).
    """
    from .processors.base_processor import BaseTransactionProcessor

    mutation_id = mutation.get("id")

    temp_processor = type(
        "TempProcessor",
        (BaseTransactionProcessor,),
        {
            "can_process": lambda self, m: True,
            "process": lambda self, m: None,
        },
    )(company, cost_center)

    is_valid, error_msg, amount_diff = temp_processor.validate_row_amounts(
        mutation, rows, amount, use_net_amount=True
    )

    if not is_valid:
        debug_info.append(f"Memorial booking row validation failed: {error_msg}")
        debug_info.extend(temp_processor.get_debug_info())
        raise Exception(error_msg)

    debug_info.extend(temp_processor.get_debug_info())

    if abs(total_debit - total_credit) > 0.01:
        error_msg = (
            f"Memorial booking {mutation_id} journal entry is not balanced: "
            f"Debit={total_debit}, Credit={total_credit}, "
            f"Difference={abs(total_debit - total_credit)}"
        )
        debug_info.append(f"Balance error: {error_msg}")
        raise Exception(error_msg)

    debug_info.append(
        f"Memorial booking journal entry is balanced: Debit={total_debit}, Credit={total_credit}"
    )


def _add_payment_offset_entry(
    je, mutation, ledger_id, company, cost_center, total_debit, total_credit, description, debug_info
):
    """
    For Type 3/4 payment mutations, add the offsetting main ledger entry (usually bank account)
    to balance the Journal Entry.

    NOTE: This creates a Journal Entry instead of Payment Entry for credit note refunds.
    Journal Entries don't auto-update invoice outstanding — manual reconciliation needed.
    """
    main_account = get_erpnext_account_from_ledger_id(ledger_id, company, debug_info, auto_create=True)
    if not main_account:
        raise ValueError(
            f"Payment mutation {mutation.get('ID', 'unknown')}: No mapping found for main ledger {ledger_id} (bank account)"
        )

    net_row_amount = total_credit - total_debit
    abs_amount = abs(net_row_amount)

    if net_row_amount > 0:
        main_debit, main_credit = abs_amount, 0
        debug_info.append(f"Payment: {abs_amount} debited to {main_account} (bank/cash account)")
    else:
        main_debit, main_credit = 0, abs_amount
        debug_info.append(f"Payment: {abs_amount} credited to {main_account} (bank/cash account)")

    main_line = {
        "account": main_account,
        "debit_in_account_currency": frappe.utils.flt(main_debit, 2),
        "credit_in_account_currency": frappe.utils.flt(main_credit, 2),
        "cost_center": cost_center,
        "user_remark": f"Payment transaction: {description}",
    }

    # Add party for main account if needed (unlikely for bank accounts, but check anyway)
    _assign_party_to_entry(
        main_line, main_account, mutation.get("type", 0), None, company, description, debug_info
    )

    je.append("accounts", main_line)
    debug_info.append(f"Added main ledger entry: {main_account} - Debit: {main_debit}, Credit: {main_credit}")


def _create_journal_entry(mutation, company, cost_center, debug_info):
    """Create Journal Entry from mutation"""
    mutation_id = mutation.get("id")
    mutation_type = mutation.get("type", 0)
    description = mutation.get("description", "eBoekhouden Import {mutation_id}")

    # Handle both detailed data format ("Regels") and summary data format ("rows")
    rows = mutation.get("Regels", []) or mutation.get("rows", [])

    # For Type 7 (memorial bookings), the E-Boekhouden REST API does NOT provide a top-level amount field
    # We need to calculate the expected net amount from the rows themselves
    if mutation_type == 7:
        # Calculate net amount from rows (sum of signed amounts)
        amount = sum(frappe.utils.flt(row.get("amount", 0), 2) for row in rows)
        debug_info.append(
            f"Memorial booking {mutation_id}: Calculated amount from {len(rows)} rows = {amount}"
        )
    else:
        # For other mutation types, try to extract amount from top-level fields
        amount = frappe.utils.flt(
            mutation.get("amount") or mutation.get("bedrag") or mutation.get("Bedrag") or 0, 2
        )

    relation_id = mutation.get("relationId")
    invoice_number = mutation.get("invoiceNumber")
    ledger_id = mutation.get("ledgerId")

    # Check if this is a zero-amount transaction
    row_amounts = [abs(frappe.utils.flt(row.get("amount", 0), 2)) for row in rows]
    total_row_amount = sum(row_amounts)
    is_zero_amount = total_row_amount == 0 and abs(amount) == 0

    # For zero-amount transactions, create a log entry instead of Journal Entry
    # This avoids ERPNext's validation that prevents zero-amount Journal Entry rows
    if is_zero_amount:
        debug_info.append(
            f"Zero-amount transaction detected for mutation {mutation_id}, creating log entry instead of financial document"
        )
        return _create_import_log_entry(mutation, company, debug_info)

    # Continue with regular Journal Entry creation for non-zero amounts

    je = frappe.new_doc("Journal Entry")
    je.company = company
    je.posting_date = mutation.get("date")
    je.voucher_type = "Journal Entry"
    je.eboekhouden_mutation_nr = str(mutation_id)
    je.eboekhouden_main_ledger_id = str(ledger_id) if ledger_id else ""
    je.user_remark = description

    # Store invoice number for manual reconciliation (Type 3/4 refunds)
    if invoice_number:
        je.eboekhouden_invoice_number = invoice_number

    # Set descriptive name and title using enhanced naming functions
    if invoice_number:
        clean_invoice = str(invoice_number).replace("/", "-").replace("\\", "-").replace(" ", "-")
        je.name = f"EBH-{clean_invoice}"
        je.title = get_journal_entry_title(mutation, mutation_type)
    else:
        type_name = MUTATION_TYPE_SINGULAR.get(mutation_type, f"Type {mutation_type}")
        je.name = f"EBH-{type_name}-{mutation_id}"
        je.title = get_journal_entry_title(mutation, mutation_type)

    # Enhance journal entry fields for better identification
    je = enhance_journal_entry_fields(je, mutation, type_name if "type_name" in locals() else None)

    if len(rows) > 0:
        # Multi-line journal entry: process rows, add memorial balancing, validate, and add payment offset
        is_memorial_booking = mutation_type == 7
        total_debit, total_credit = _process_journal_entry_rows(
            je, mutation, rows, ledger_id, company, cost_center, description, debug_info
        )

        if is_memorial_booking and rows:
            _validate_memorial_booking(
                je, mutation, rows, amount, total_debit, total_credit, company, cost_center, debug_info
            )

        if mutation_type in [3, 4] and ledger_id and not is_memorial_booking:
            _add_payment_offset_entry(
                je,
                mutation,
                ledger_id,
                company,
                cost_center,
                total_debit,
                total_credit,
                description,
                debug_info,
            )

    else:
        # Simple journal entry with main amount
        # Get main account mapping (with auto-create if missing)
        main_account = get_erpnext_account_from_ledger_id(ledger_id, company, debug_info, auto_create=True)

        if not main_account:
            # Get ledger code instead of ledger ID
            ledger_code = _get_ledger_code_from_id(ledger_id, company, debug_info) if ledger_id else None

            line_dict = create_invoice_line_for_tegenrekening(
                tegenrekening_code=ledger_code,
                amount=abs(amount),
                description=description,
                transaction_type="purchase",
            )
            main_account = line_dict.get("expense_account")
            if not main_account:
                raise ValueError(
                    f"No expense account mapping found for mutation {mutation.get('ID', 'unknown')} with ledger_id {ledger_id}. Account mapping required for proper financial reporting."
                )

        je.append(
            "accounts",
            {
                "account": main_account,
                "debit_in_account_currency": frappe.utils.flt(amount if amount > 0 else 0, 2),
                "credit_in_account_currency": frappe.utils.flt(-amount if amount < 0 else 0, 2),
                "cost_center": cost_center,
                "user_remark": description,
            },
        )

        # No automatic balancing - let journal entry validation handle unbalanced entries

    # Note: Types 5 & 6 (Money Received/Paid) should probably be Payment Entries, not Journal Entries
    # Journal Entries require manual balancing, but Payment Entries handle bank transfers automatically

    # Check for stock accounts before saving
    stock_accounts_found = []
    for account_entry in je.accounts:
        if account_entry.account:
            account_type = frappe.db.get_value("Account", account_entry.account, "account_type")
            if account_type == "Stock":
                stock_accounts_found.append(account_entry.account)

    if stock_accounts_found:
        error_msg = f"Cannot create Journal Entry: Stock accounts {', '.join(stock_accounts_found)} can only be updated via Stock Transactions"
        debug_info.append(error_msg)
        debug_info.append(
            "Skipping this mutation as it involves stock accounts which require Stock Entry instead of Journal Entry"
        )
        raise Exception(error_msg)

    try:
        je.save()
        je.submit()
        debug_info.append(f"Created Journal Entry {je.name}")
        return je
    except Exception as e:
        error_msg = f"Failed to create Journal Entry: {str(e)}"
        debug_info.append(error_msg)
        debug_info.append("This may indicate unbalanced entries or other data issues.")
        raise Exception(error_msg)


def _get_memorial_booking_amounts(row_ledger_id, main_ledger_id, row_amount, debug_info):
    """
    Calculate proper debit/credit amounts for memorial bookings based on E-Boekhouden account categories.

    This function fixes the memorial booking debit/credit logic by using E-Boekhouden account categories
    instead of simple amount-based rules that were causing inverted postings.

    Args:
        row_ledger_id: E-Boekhouden ledger ID for the row account
        main_ledger_id: E-Boekhouden ledger ID for the main account
        row_amount: Amount from E-Boekhouden (positive or negative)
        debug_info: List to append debug messages to

    Convention (verified against actual E-Boekhouden transactions): the "amount"
    field is the CREDIT side, so a POSITIVE row amount CREDITS the row account and
    DEBITS the offsetting main account; a negative amount reverses it.
      - Mutation 1334: Row=Kruisposten, Main=Te betalen, Amount=+8445.03
        → Credit Kruisposten, Debit Te betalen (zeroing an opening balance)

    Returns:
        tuple: (row_debit, row_credit, main_debit, main_credit)
    """
    debug_info.append(
        f"_get_memorial_booking_amounts: row_ledger={row_ledger_id}, main_ledger={main_ledger_id}, amount={row_amount}"
    )

    # NOTE: a prior version fetched E-Boekhouden ledger "categories" via the API but
    # never used them (the logic is purely amount-based), and its except-fallback
    # used the OPPOSITE debit/credit convention. That meant memorial bookings
    # imported WITHOUT API credentials (CI, or a transient token failure mid-import)
    # silently landed on the wrong side of the ledger. The dead API call was removed
    # and the single verified convention below is used everywhere.
    abs_amount = abs(row_amount)
    if row_amount > 0:
        # Positive amount: credit the row, debit the main.
        row_debit, row_credit = 0, abs_amount
        main_debit, main_credit = abs_amount, 0
    else:
        # Negative amount: debit the row, credit the main.
        row_debit, row_credit = abs_amount, 0
        main_debit, main_credit = 0, abs_amount

    debug_info.append(
        f"Memorial amounts - Row: Dr {row_debit}, Cr {row_credit} | Main: Dr {main_debit}, Cr {main_credit}"
    )
    return row_debit, row_credit, main_debit, main_credit


def start_full_rest_import(migration_name, mutation_types=None):
    """
    Start full REST import for a migration document.

    This function was restored from git history to fix the missing import error.
    Uses the simpler REST iterator approach with enhanced error handling for new fields.

    Args:
        migration_name: Name of the E-Boekhouden Migration document
        mutation_types: Optional list of mutation type integers to import (e.g., [1, 2, 4])
                       If None, imports all types (1-7) plus type 0 for full migrations

    Returns:
        dict: Migration result with success status and stats
    """
    try:
        # Get the migration document to extract parameters
        migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_name)

        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")
        if not settings.get_password("api_token"):
            return {
                "success": False,
                "error": "REST API token not configured in E-Boekhouden Settings",
            }

        # Extract migration parameters with defaults
        company = getattr(migration_doc, "company", None) or settings.default_company
        date_from = getattr(migration_doc, "date_from", None)
        date_to = getattr(migration_doc, "date_to", None)
        migrate_transactions = getattr(migration_doc, "migrate_transactions", 1)

        if not company:
            return {"success": False, "error": "No company specified"}

        # Update migration document with progress
        migration_doc.db_set("current_operation", "Starting REST API import...")
        migration_doc.db_set("progress_percentage", 5)
        frappe.db.commit()

        # Use the simpler REST iterator approach
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Determine which mutation types to import
        if mutation_types is None:
            # Default: Import all mutation types (Sales, Purchase, Payments, Money Transfers, Memorial)
            mutation_types = [1, 2, 3, 4, 5, 6, 7]
        elif not isinstance(mutation_types, list):
            # If mutation_types is not a list, convert to list or use default
            frappe.log_error(
                f"Invalid mutation_types parameter: {mutation_types}. Using default types.",
                "eBoekhouden Import - Invalid Parameter",
            )
            mutation_types = [1, 2, 3, 4, 5, 6, 7]
        else:
            # User provided specific types - use them
            # Filter to valid types (0-10) and ensure unique
            mutation_types = sorted(list(set([t for t in mutation_types if 0 <= t <= 10])))
            frappe.log_error(
                f"Using user-specified mutation types: {mutation_types}", "eBoekhouden Import - Custom Types"
            )

        # Add opening balances (type 0) if not already included and this is a full migration
        # Opening balances should be imported when:
        # 1. No date_from is specified (import all transactions)
        # 2. date_from is set to 2019-01-01 or earlier (includes 2018-12-31 opening balances)
        # getdate already imported at top of file

        is_full_import = migrate_transactions and (
            not date_from
            or (
                date_from and getdate(date_from) <= getdate("2019-01-01")
            )  # Cutoff for "full" import (includes 2018-12-31 opening balances)
        )

        # Only auto-add type 0 if user didn't explicitly specify types
        # (mutation_types parameter was None)
        if is_full_import and 0 not in mutation_types and mutation_types == [1, 2, 3, 4, 5, 6, 7]:
            mutation_types.insert(0, 0)  # Add type 0 at the beginning
            frappe.log_error(
                f"Including opening balances (type 0) in migration. Date from: {date_from}",
                "eBoekhouden Import",
            )
        total_imported = 0
        total_failed = 0
        total_skipped = 0
        errors = []

        for i, mutation_type in enumerate(mutation_types):
            try:
                # Update progress dynamically based on total mutation types
                total_types = len(mutation_types)
                progress_step = (
                    80 / total_types
                )  # Use 80% for mutation processing (10% for setup, 10% for completion)
                progress = 10 + (i * progress_step)  # Start at 10%, increment dynamically

                # Get descriptive type name
                type_name = MUTATION_TYPE_PLURAL.get(mutation_type, f"Type {mutation_type}")

                migration_doc.db_set("current_operation", f"Processing {type_name} (type {mutation_type})...")
                migration_doc.db_set("progress_percentage", int(progress))
                frappe.db.commit()

                # Fetch all mutations of this type
                mutations = iterator.fetch_mutations_by_type(mutation_type=mutation_type, limit=500)

                # Filter by date if specified (but not for opening balances - type 0)
                if (date_from or date_to) and mutation_type != 0:
                    filtered_mutations = []
                    for mutation in mutations:
                        mutation_date = mutation.get("date")
                        if mutation_date:
                            mut_date = getdate(mutation_date)
                            include = True

                            if date_from and mut_date < getdate(date_from):
                                include = False
                            if date_to and mut_date > getdate(date_to):
                                include = False

                            if include:
                                filtered_mutations.append(mutation)
                    mutations = filtered_mutations

                if mutations:
                    # Special handling for opening balances (type 0)
                    if mutation_type == 0:
                        # Use the specialized opening balance import function
                        debug_info = []
                        company = settings.default_company
                        cost_center = get_default_cost_center(company)

                        # Call the advanced opening balance import function
                        result = _import_opening_balances(company, cost_center, debug_info, dry_run=False)

                        # Convert result to batch result format
                        if result.get("success"):
                            batch_result = {
                                "imported": 1 if result.get("journal_entry") else 0,
                                "failed": 0,
                                "skipped": 0,
                                "errors": [],
                            }
                        else:
                            batch_result = {
                                "imported": 0,
                                "failed": len(mutations),  # All mutations failed
                                "skipped": 0,
                                "errors": [result.get("error", "Opening balance import failed")],
                            }

                        # Create summary log for opening balances
                        summary_title = "eBoekhouden REST Import - Opening Balances Complete"
                        summary_content = "BATCH SUMMARY for Opening Balances:\n"
                        summary_content += f"• Processed: {len(mutations)} mutations\n"
                        summary_content += f"• Imported: {batch_result['imported']}\n"
                        summary_content += f"• Failed: {batch_result['failed']}\n"
                        summary_content += f"• Skipped: {batch_result['skipped']}\n"
                        summary_content += f"• Total Errors: {len(batch_result['errors'])}\n"
                        frappe.log_error(summary_content, summary_title)

                        # Log detailed error information for opening balances when there are failures
                        if batch_result["errors"]:
                            detailed_error_content = "DETAILED ERROR REPORT for Opening Balances:\n\n"
                            for i, error in enumerate(batch_result["errors"], 1):
                                detailed_error_content += f"{i}. {error}\n\n"

                            detailed_title = "eBoekhouden REST Import - Opening Balances - Detailed Errors"
                            frappe.log_error(detailed_error_content, detailed_title)
                    else:
                        # Process other mutations using the batch import with enhanced error handling
                        batch_result = _import_rest_mutations_batch_enhanced(
                            migration_name, mutations, settings, mutation_type
                        )

                    total_imported += batch_result.get("imported", 0)
                    total_failed += batch_result.get("failed", 0)
                    total_skipped += batch_result.get("skipped", 0)
                    errors.extend(batch_result.get("errors", []))
                else:
                    # Create summary log even when no mutations found
                    type_name = MUTATION_TYPE_PLURAL.get(mutation_type, f"Type {mutation_type}")

                    debug_info = [f"No {type_name.lower()} mutations found in the specified date range"]
                    frappe.log_error(
                        "ENHANCED BATCH Log:\n" + "\n".join(debug_info),
                        f"eBoekhouden Import - {type_name} - No Data Found",
                    )

                    # Update running totals in the migration document
                    current_total = total_imported + total_failed + total_skipped
                    migration_doc.db_set("imported_records", total_imported)
                    migration_doc.db_set("failed_records", total_failed)
                    migration_doc.db_set("total_records", current_total)
                    frappe.db.commit()

            except Exception as e:
                errors.append(f"Error importing mutation type {mutation_type}: {str(e)}")
                total_failed += 1

        # Final progress update
        total_records = total_imported + total_failed + total_skipped
        migration_doc.db_set("current_operation", "Import completed")
        migration_doc.db_set("progress_percentage", 100)
        migration_doc.db_set("imported_records", total_imported)
        migration_doc.db_set("failed_records", total_failed)
        migration_doc.db_set("total_records", total_records)
        frappe.db.commit()

        # Return results in expected format
        return {
            "success": True,
            "stats": {
                "total_mutations": total_imported + total_failed + total_skipped,
                "invoices_created": total_imported,  # Simplified - actual breakdown would need more detail
                "payments_processed": 0,  # Would need to track separately
                "journal_entries_created": 0,  # Would need to track separately
                "skipped_existing": total_skipped,
                "errors": errors,
            },
        }

    except Exception as e:
        frappe.log_error(f"Error in start_full_rest_import: {str(e)}", "E-Boekhouden Migration")
        return {"success": False, "error": str(e)}


def _process_mutation_with_coordinator(
    mutation, mutation_id, mutation_type, coordinator, company, cost_center, debug_info
):
    """
    Process a single mutation using the coordinator (new processors) with legacy fallback.

    Returns:
        dict with keys:
        - action: 'success' | 'failed' | 'skip' | 'error'
        - method: 'new_processors' | 'legacy' (only for success)
        - error_msg: str (only for error)
        - is_stock_error: bool (only for error)
    """
    try:
        debug_info.append(f"Processing mutation {mutation_id}")
        doc = None
        processing_method = "legacy"

        if coordinator:
            try:
                doc = coordinator.process_mutation(mutation)
                if doc:
                    processing_method = "new_processors"
                    processor_debug = coordinator.last_processor_debug_info
                    if processor_debug:
                        debug_info.extend(processor_debug)
                else:
                    processor_debug = coordinator.last_processor_debug_info

                    # Check if this was a legitimate skip (gateway adjustment, etc.)
                    skip_indicators = [
                        "Skipping payment gateway adjustment",
                        "already detected in can_process",
                        "SKIPPING",
                    ]
                    is_legitimate_skip = processor_debug and any(
                        any(indicator in line for indicator in skip_indicators) for line in processor_debug
                    )

                    if is_legitimate_skip:
                        debug_info.append(
                            f"New processors intentionally skipped mutation {mutation_id} (Type {mutation_type})"
                        )
                        if processor_debug:
                            debug_info.extend(processor_debug)
                        return {"action": "skip"}
                    else:
                        debug_info.append(
                            f"New processors returned None for mutation {mutation_id} (Type {mutation_type}), falling back to legacy"
                        )
                        if processor_debug:
                            debug_info.extend(processor_debug)
                        frappe.log_error(
                            title=f"New Processor Returned None - Mutation {mutation_id} (Type {mutation_type})",
                            message=f"Mutation ID: {mutation_id}\nType: {mutation_type}\nDescription: {mutation.get('description', 'N/A')}\n\nDebug Info:\n"
                            + "\n".join(processor_debug if processor_debug else ["No debug info"]),
                        )
            except Exception as proc_error:
                debug_info.append(
                    f"New processor failed for mutation {mutation_id} (Type {mutation_type}): {str(proc_error)}, using legacy"
                )
                processor_debug = coordinator.last_processor_debug_info
                if processor_debug:
                    debug_info.extend(processor_debug)
                doc = None

        # Fallback to legacy if new processors didn't work
        if not doc:
            doc = _process_single_mutation(mutation, company, cost_center, debug_info)
            processing_method = "legacy"

        if doc:
            debug_info.append(
                f"Successfully imported mutation {mutation_id} as {doc.doctype} {doc.name} (via {processing_method})"
            )
            return {"action": "success", "method": processing_method}
        else:
            debug_info.append(f"Failed to process mutation {mutation_id} - no document returned")
            return {"action": "failed"}

    except Exception as processing_error:
        error_str = str(processing_error)
        is_stock = "Stock accounts" in error_str and "can only be updated via Stock Transactions" in error_str
        if is_stock:
            debug_info.append(f"STOCK ACCOUNT SKIP - Skipped mutation {mutation_id}: {error_str}")
        else:
            debug_info.append(f"PROCESSING ERROR - Error processing mutation {mutation_id}: {error_str}")
        return {
            "action": "error",
            "is_stock_error": is_stock,
            "error_msg": f"{'Skipped' if is_stock else 'Error processing'} mutation {mutation_id}: {error_str}",
        }


def _categorize_batch_errors(errors):
    """Group batch import errors into categories for summary logging."""
    error_categories = {}
    for error in errors:
        if "Stock accounts" in error and "can only be updated via Stock Transactions" in error:
            category = "Stock Account Updates (Fixed - now creates Stock Reconciliations)"
        elif "already been fully paid" in error or "cannot be greater than outstanding amount" in error:
            category = "Payment Allocation Issues"
        elif "Could not find" in error:
            category = "Missing References"
        elif "already exists" in error:
            category = "Duplicate Entries"
        else:
            category = "Other Errors"

        if category not in error_categories:
            error_categories[category] = []
        error_categories[category].append(error)

    return error_categories


def _log_batch_summary(
    mutations,
    type_name,
    imported,
    failed,
    skipped,
    errors,
    processed_with_new,
    processed_with_legacy,
    error_categories,
):
    """Build and log the batch import summary to Error Log. Returns the summary content string."""
    import re

    summary_title = f"eBoekhouden REST Import - {type_name} Complete"
    summary_content = f"BATCH SUMMARY for {type_name}:\n"
    summary_content += f"Processed: {len(mutations) if mutations else 0} mutations\n"
    summary_content += f"Imported: {imported}\n"
    summary_content += f"Failed: {failed}\n"
    summary_content += f"Skipped: {skipped}\n"
    summary_content += f"Total Errors: {len(errors)}\n\n"

    total_processed = processed_with_new + processed_with_legacy
    if total_processed > 0:
        summary_content += "PROCESSING METHOD BREAKDOWN:\n"
        summary_content += (
            f"New Processors: {processed_with_new} ({processed_with_new * 100 / total_processed:.1f}%)\n"
        )
        summary_content += f"Legacy Processing: {processed_with_legacy} ({processed_with_legacy * 100 / total_processed:.1f}%)\n\n"

    # Bank Transaction statistics for payment types
    if (
        type_name in ["Customer Payments", "Supplier Payments", "Money Received", "Money Paid"]
        and imported > 0
    ):
        summary_content += _get_bank_transaction_stats(mutations, type_name)

    if error_categories:
        summary_content += "ERROR CATEGORIES:\n"
        for category, category_errors in error_categories.items():
            summary_content += f"\n{category} ({len(category_errors)} errors):\n"
            for error in category_errors[:5]:
                mutation_match = re.search(r"mutation (\d+)", error)
                if mutation_match:
                    summary_content += f"  - Mutation {mutation_match.group(1)}\n"
                else:
                    summary_content += f"  - {error[:100]}{'...' if len(error) > 100 else ''}\n"
            if len(category_errors) > 5:
                summary_content += f"  ... and {len(category_errors) - 5} more\n"

    frappe.log_error(summary_content, summary_title)

    if errors:
        detailed_content = f"DETAILED ERROR REPORT for {type_name}:\n\n"
        for category, category_errors in error_categories.items():
            detailed_content += f"{category} ({len(category_errors)} errors):\n"
            for i, error in enumerate(category_errors, 1):
                detailed_content += f"\n{i}. {error}\n"
            detailed_content += "\n" + "=" * 80 + "\n\n"
        frappe.log_error(detailed_content, f"eBoekhouden REST Import - {type_name} - Detailed Errors")

    return summary_content


def _get_bank_transaction_stats(mutations, type_name):
    """Build bank transaction statistics string for payment type batches. Returns the stats block."""
    try:
        mutation_ids = [str(m.get("id")) for m in mutations] if mutations else []
        if not mutation_ids:
            return ""

        placeholders = ", ".join(["%s"] * len(mutation_ids))
        bank_tx_stats = frappe.db.sql(
            f"""
            SELECT
                COUNT(DISTINCT pe.name) as total_pes,
                COUNT(DISTINCT btp.parent) as with_bank_tx
            FROM `tabPayment Entry` pe
            LEFT JOIN `tabBank Transaction Payments` btp ON btp.payment_entry = pe.name
            WHERE pe.eboekhouden_mutation_nr IN ({placeholders})
        """,
            tuple(mutation_ids),
            as_dict=True,
        )

        if not bank_tx_stats or not bank_tx_stats[0]:
            return ""

        stats = bank_tx_stats[0]
        total = stats.total_pes
        with_bt = stats.with_bank_tx
        without_bt = total - with_bt
        success_rate = (with_bt / total * 100) if total > 0 else 0

        result = ""
        if total == 0:
            result += "PAYMENT ENTRY STATUS:\n"
            result += f"No Payment Entries created ({len(mutations)} mutations processed)\n"
            result += f"All {len(mutations)} mutations created as Journal Entries instead\n"
            result += "This is expected for type 5/6 (Money Received/Paid) transactions\n\n"
        else:
            je_count = len(mutations) - total
            result += "BANK TRANSACTION STATUS:\n"
            result += f"Payment Entries in batch: {total} (of {len(mutations)} mutations)\n"
            if je_count > 0:
                result += f"  - Created as Payment Entry: {total}\n"
                result += f"  - Created as Journal Entry instead: {je_count}\n"
            result += f"With Bank Transactions: {with_bt} ({success_rate:.1f}%)\n"
            result += f"WITHOUT Bank Transactions: {without_bt}\n"
            if without_bt > 0:
                result += f"  WARNING: {without_bt} Payment Entries missing Bank Transactions!\n"
            result += "\n"
        return result
    except Exception as bt_stats_error:
        return f"BANK TRANSACTION STATISTICS: Error collecting stats - {str(bt_stats_error)}\n\n"


def _retry_transient_failures(migration_name, errors, failed, imported, debug_info):
    """
    Retry failed mutations that had transient errors (deadlocks, timeouts, connection issues).

    Returns:
        dict with updated imported/failed/errors counts and optional retry_summary string.
    """
    import re

    transient_error_patterns = [
        "has been modified after you have opened it",
        "Deadlock found",
        "Lock wait timeout exceeded",
        "Connection reset",
        "Connection timed out",
        "Lost connection to MySQL server",
    ]

    retry_summary = None

    if failed > 0 and errors:
        failed_mutation_ids = []
        for error in errors:
            is_transient = any(pattern in error for pattern in transient_error_patterns)
            if is_transient:
                mutation_match = re.search(r"mutation (\d+)", error)
                if mutation_match:
                    failed_mutation_ids.append(mutation_match.group(1))

        if failed_mutation_ids:
            debug_info.append(
                f"\nRETRY PHASE: Retrying {len(failed_mutation_ids)} mutations with transient errors"
            )

            from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
                import_single_mutation,
            )

            retry_success = 0
            retry_failed = 0

            for mutation_id in failed_mutation_ids:
                try:
                    debug_info.append(f"  Retrying mutation {mutation_id}...")
                    result = import_single_mutation(migration_name, mutation_id, overwrite_existing=False)

                    if result.get("success"):
                        retry_success += 1
                        errors = [e for e in errors if f"mutation {mutation_id}" not in e]
                        imported += 1
                        failed -= 1
                        debug_info.append(f"  Retry successful for mutation {mutation_id}")
                    else:
                        retry_failed += 1
                        debug_info.append(
                            f"  Retry failed for mutation {mutation_id}: {result.get('error', 'Unknown error')}"
                        )
                except Exception as retry_error:
                    retry_failed += 1
                    debug_info.append(f"  Retry exception for mutation {mutation_id}: {str(retry_error)}")

            retry_summary = f"\nRETRY SUMMARY:\n"
            retry_summary += f"Attempted: {len(failed_mutation_ids)} mutations\n"
            retry_summary += f"Successful: {retry_success}\n"
            retry_summary += f"Failed: {retry_failed}\n"
            debug_info.append(retry_summary)

    return {
        "imported": imported,
        "failed": failed,
        "errors": errors,
        "retry_summary": retry_summary,
    }


def _finalize_mutation_savepoint(savepoint_name, succeeded, debug_info):
    """Release a per-mutation savepoint, rolling back first if the mutation
    did not succeed.

    Tolerates the savepoint having been dropped (e.g. by a stray commit deeper
    in the call stack): a missing savepoint is logged to debug_info but must
    not abort the whole batch.
    """
    try:
        if not succeeded:
            frappe.db.rollback(save_point=savepoint_name)
        frappe.db.release_savepoint(savepoint_name)
    except Exception as savepoint_error:
        debug_info.append(f"SAVEPOINT WARNING - could not finalize {savepoint_name}: {savepoint_error}")


def _import_rest_mutations_batch_enhanced(migration_name, mutations, settings, mutation_type=None):
    """
    Enhanced batch import that handles new fields gracefully.

    This version includes better error handling for newly added fields like payment_terms
    that might not exist in all mutations or might cause processing issues.

    PHASE 2: Now uses new processor architecture with legacy fallback for validation.
    """
    imported = 0
    failed = 0
    skipped = 0
    errors = []
    debug_info = []

    # Phase 2 metrics
    processed_with_new = 0
    processed_with_legacy = 0

    # Get descriptive mutation type name
    type_name = (
        MUTATION_TYPE_PLURAL.get(mutation_type, f"Type {mutation_type}") if mutation_type else "Mixed Types"
    )

    debug_info.append(
        f"Starting enhanced batch import with {len(mutations) if mutations else 0} mutations of {type_name}"
    )

    if not mutations:
        debug_info.append("No mutations provided, returning early")
        frappe.log_error(
            "ENHANCED BATCH Log:\n" + "\n".join(debug_info),
            f"eBoekhouden Import - {type_name} - No Mutations",
        )
        return {"imported": 0, "failed": 0, "skipped": 0, "errors": []}

    company = settings.default_company
    debug_info.append(f"Company: {company}")

    # Get cost center
    cost_center = get_default_cost_center(company)
    debug_info.append(f"Cost center found: {cost_center}")

    if not cost_center:
        errors.append("No cost center found")
        debug_info.append("ERROR - No cost center found")
        frappe.log_error(
            "ENHANCED BATCH Log:\n" + "\n".join(debug_info),
            f"eBoekhouden Import - {type_name} - Cost Center Error",
        )
        return {"imported": 0, "failed": len(mutations), "skipped": 0, "errors": errors}

    # PHASE 2: Initialize TransactionCoordinator for new processor architecture
    use_new_processors = frappe.conf.get("eboekhouden_use_new_processors", True)
    coordinator = None

    if use_new_processors:
        try:
            from verenigingen.e_boekhouden.utils.processors.transaction_coordinator import (
                TransactionCoordinator,
            )

            # Pass mutation_type to filter relevant processors for this batch
            coordinator = TransactionCoordinator(company, cost_center, mutation_type=mutation_type)
            debug_info.append(
                f"✅ Phase 2: TransactionCoordinator initialized for {type_name} "
                f"(filtered to {len(coordinator.processors)} relevant processor(s))"
            )
        except Exception as coord_error:
            debug_info.append(f"⚠️ Failed to initialize TransactionCoordinator: {str(coord_error)}")
            debug_info.append("Falling back to legacy processing for entire batch")
            coordinator = None

    for i, mutation in enumerate(mutations):
        # Process each mutation inside its own savepoint: a mutation can create
        # several documents, so a failure partway through must roll back its
        # partial writes instead of leaving an orphaned half-record to be
        # committed at the type-batch boundary. _process_mutation_with_coordinator
        # catches its own errors and returns a result dict, so the savepoint is
        # rolled back whenever the mutation did not succeed — not only on an
        # uncaught exception.
        savepoint_name = f"eb_mut_{frappe.generate_hash(length=10)}"
        frappe.db.savepoint(savepoint_name)
        mutation_succeeded = False
        try:
            # Skip if already imported
            mutation_id = mutation.get("id")
            mutation_type = mutation.get("type", 0)

            if not mutation_id:
                errors.append("Mutation missing ID, skipping")
                debug_info.append("ERROR - Mutation missing ID")
                failed += 1
                continue

            # Check for existing documents
            existing_je = _check_if_already_imported(mutation_id, "Journal Entry")
            existing_pe = _check_if_already_imported(mutation_id, "Payment Entry")
            existing_si = _check_if_already_imported(mutation_id, "Sales Invoice")
            existing_pi = _check_if_already_imported(mutation_id, "Purchase Invoice")

            if existing_je or existing_pe or existing_si or existing_pi:
                skipped += 1
                continue

            # Check if this mutation should be skipped (e.g., zero-amount system notifications)
            if should_skip_mutation(mutation, debug_info):
                skipped += 1
                continue

            # Process the mutation with coordinator + legacy fallback
            result = _process_mutation_with_coordinator(
                mutation, mutation_id, mutation_type, coordinator, company, cost_center, debug_info
            )

            if result["action"] == "skip":
                skipped += 1
                continue
            elif result["action"] == "success":
                imported += 1
                mutation_succeeded = True
                if result.get("method") == "new_processors":
                    processed_with_new += 1
                else:
                    processed_with_legacy += 1
            elif result["action"] == "failed":
                failed += 1
            elif result["action"] == "error":
                if result.get("is_stock_error"):
                    skipped += 1
                else:
                    failed += 1
                    errors.append(result["error_msg"])

        except Exception as e:
            failed += 1
            error_msg = f"Error in batch processing loop for mutation {i}: {str(e)}"
            errors.append(error_msg)
            debug_info.append(f"LOOP ERROR - {error_msg}")
        finally:
            # Roll back unless the mutation fully succeeded — a failed/errored
            # mutation reaches here without an exception (its error was caught
            # in _process_mutation_with_coordinator), so its partial writes
            # must still be undone.
            _finalize_mutation_savepoint(savepoint_name, mutation_succeeded, debug_info)

    # Post-processing: categorize errors, log summary, retry transient failures
    error_categories = _categorize_batch_errors(errors)

    summary_content = _log_batch_summary(
        mutations,
        type_name,
        imported,
        failed,
        skipped,
        errors,
        processed_with_new,
        processed_with_legacy,
        error_categories,
    )

    retry_result = _retry_transient_failures(migration_name, errors, failed, imported, debug_info)
    imported = retry_result["imported"]
    failed = retry_result["failed"]
    errors = retry_result["errors"]
    if retry_result.get("retry_summary"):
        frappe.log_error(
            summary_content + retry_result["retry_summary"],
            f"eBoekhouden REST Import - {type_name} Complete (with retries)",
        )

    return {"imported": imported, "failed": failed, "skipped": skipped, "errors": errors}
