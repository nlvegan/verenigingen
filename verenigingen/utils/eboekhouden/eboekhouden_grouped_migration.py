"""
Enhanced E-Boekhouden migration that properly groups mutations into balanced journal entries
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta

import frappe


@frappe.whitelist()
def migrate_mutations_grouped(migration_doc, settings):
    """
    Migrate mutations using native transaction types instead of creating journal entries for everything
    """
    try:
        from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

        from .eboekhouden_transaction_type_mapper import simplify_migration_process

        api = EBoekhoudenAPI(settings)
        company = settings.default_company

        if not company:
            return {"success": False, "error": "No default company set"}

        # Get cost center
        cost_center = frappe.db.get_value(
            "Cost Center",
            {"company": company, "is_group": 1, "parent_cost_center": ["in", ["", None]]},
            "name",
        )

        # Process transactions in batches
        all_mutations = []
        current_date = frappe.utils.getdate(migration_doc.date_from)
        end_date = frappe.utils.getdate(migration_doc.date_to)

        while current_date <= end_date:
            # Calculate month end
            if current_date.month == 12:
                month_end = current_date.replace(year=current_date.year + 1, month=1, day=1) - timedelta(
                    days=1
                )
            else:
                month_end = current_date.replace(month=current_date.month + 1, day=1) - timedelta(days=1)

            month_end = min(month_end, end_date)

            # Get mutations for this month
            params = {"dateFrom": current_date.strftime("%Y-%m-%d"), "dateTo": month_end.strftime("%Y-%m-%d")}

            result = api.get_mutations(params)
            if result["success"]:
                data = json.loads(result["data"])
                mutations = data.get("items", [])
                all_mutations.extend(mutations)

            # Move to next month
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1, day=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1, day=1)

        # Group mutations by document type using native E-boekhouden types
        mutations_by_doc_type = defaultdict(list)

        for mut in all_mutations:
            # Use the simplified mapper to determine document type
            mapping_result = simplify_migration_process(mut)
            doc_type = mapping_result["document_type"]

            # Add mapping info to mutation for later use
            mut["_mapping_info"] = mapping_result

            mutations_by_doc_type[doc_type].append(mut)

        # Import processing functions
        from .eboekhouden_unified_processor import (
            process_journal_entries_grouped,
            process_payment_entries,
            process_purchase_invoices,
            process_sales_invoices,
        )

        # Process mutations by document type
        stats = {
            "sales_invoices": 0,
            "purchase_invoices": 0,
            "payment_entries": 0,
            "journal_entries": 0,
            "failed": 0,
            "errors": [],
        }

        # Process each document type
        for doc_type, mutations in mutations_by_doc_type.items():
            if doc_type == "Sales Invoice":
                result = process_sales_invoices(mutations, company, cost_center, migration_doc)
                stats["sales_invoices"] += result.get("created", 0)
                stats["errors"].extend(result.get("errors", []))

            elif doc_type == "Purchase Invoice":
                result = process_purchase_invoices(mutations, company, cost_center, migration_doc)
                stats["purchase_invoices"] += result.get("created", 0)
                stats["errors"].extend(result.get("errors", []))

            elif doc_type == "Payment Entry":
                result = process_payment_entries(mutations, company, cost_center, migration_doc)
                stats["payment_entries"] += result.get("created", 0)
                stats["errors"].extend(result.get("errors", []))

            elif doc_type == "Journal Entry":
                # For journal entries, still group by entry number
                result = process_journal_entries_grouped(mutations, company, cost_center, migration_doc)
                stats["journal_entries"] += result.get("created", 0)
                stats["errors"].extend(result.get("errors", []))

            stats["failed"] += len(result.get("errors", []))

        total_created = (
            stats["sales_invoices"]
            + stats["purchase_invoices"]
            + stats["payment_entries"]
            + stats["journal_entries"]
        )

        return {
            "success": True,
            "created": total_created,
            "failed": stats["failed"],
            "total_mutations": len(all_mutations),
            "stats": stats,
            "message": "Created {total_created} documents using native transaction types",
        }

    except Exception as e:
        frappe.log_error(f"Grouped migration error: {str(e)}", "E-Boekhouden")
        return {"success": False, "error": str(e)}


def create_journal_entry_from_group(entry_num, mutations, company, cost_center, migration_doc, group_key):
    """
    Create a journal entry from a group of mutations
    """
    try:
        # Check if already exists using the composite key
        if frappe.db.exists("Journal Entry", {"eboekhouden_group_key": group_key}):
            return {"success": False, "reason": "skip", "message": "Already imported"}

        # Calculate totals
        total_debit = 0
        total_credit = 0
        accounts = []

        # Get the date from first mutation
        posting_date = None

        for mut in mutations:
            # Parse amount
            amount = float(mut.get("amount", 0) or 0)
            if amount == 0:
                continue

            # Get date
            if not posting_date and mut.get("date"):
                date_str = mut.get("date")
                if "T" in date_str:
                    posting_date = datetime.strptime(date_str.split("T")[0], "%Y-%m-%d").date()
                else:
                    posting_date = datetime.strptime(date_str, "%Y-%m-%d").date()

            # Get account
            ledger_id = mut.get("ledgerId")
            if not ledger_id:
                continue

            account_code = migration_doc.get_account_code_from_ledger_id(ledger_id)
            if not account_code:
                continue

            account = frappe.db.get_value(
                "Account",
                {"company": company, "account_number": account_code},
                ["name", "account_type"],
                as_dict=True,
            )

            if not account:
                continue

            # Skip stock accounts
            if account.account_type == "Stock":
                continue

            # Determine debit/credit based on mutation type
            # Type interpretation based on the data:
            # Type 0: appears to be debit
            # Type 1,2,3,4: appear to be different credit types
            mut_type = mut.get("type", 0)

            if mut_type == 0:  # Debit
                debit = amount
                credit = 0
                total_debit += amount
            else:  # Credit types
                debit = 0
                credit = amount
                total_credit += amount

            # Prepare account entry
            entry = {
                "account": account.name,
                "debit_in_account_currency": debit,
                "credit_in_account_currency": credit,
                "cost_center": cost_center,
                "user_remark": mut.get("description", ""),
            }

            # Add party if needed
            if account.account_type in ["Receivable", "Payable"]:
                if account.account_type == "Receivable":
                    entry["party_type"] = "Customer"
                    entry["party"] = "E-Boekhouden Import Customer"
                else:
                    entry["party_type"] = "Supplier"
                    entry["party"] = "E-Boekhouden Import Supplier"

            accounts.append(entry)

        # Check if we have valid entries
        if not accounts or not posting_date:
            return {"success": False, "reason": "skip", "message": "No valid entries"}

        # Balance the entry if needed
        diff = abs(total_debit - total_credit)
        if diff > 0.01:  # Not balanced
            # Add balancing entry to suspense account
            suspense = get_suspense_account(company)
            if suspense:
                if total_debit > total_credit:
                    accounts.append(
                        {
                            "account": suspense,
                            "credit_in_account_currency": diff,
                            "cost_center": cost_center,
                            "user_remark": "Balancing entry",
                        }
                    )
                else:
                    accounts.append(
                        {
                            "account": suspense,
                            "debit_in_account_currency": diff,
                            "cost_center": cost_center,
                            "user_remark": "Balancing entry",
                        }
                    )

        # Create journal entry
        je = frappe.new_doc("Journal Entry")
        je.company = company
        je.posting_date = posting_date
        je.user_remark = f"E-Boekhouden Entry: {entry_num}"
        je.eboekhouden_entry_number = entry_num
        je.eboekhouden_group_key = group_key

        for acc in accounts:
            je.append("accounts", acc)

        je.flags.ignore_mandatory = True
        je.insert(ignore_permissions=True)

        return {"success": True, "journal_entry": je.name}

    except Exception as e:
        return {"success": False, "reason": "error", "message": str(e)[:100]}


def create_journal_entry_from_single(mut, company, cost_center, migration_doc):
    """
    Create a journal entry from a single ungrouped mutation
    """
    try:
        # Similar to grouped but creates balanced entry with suspense account
        amount = float(mut.get("amount", 0) or 0)
        if amount == 0:
            return {"success": False, "reason": "skip", "message": "Zero amount"}

        # Get date
        date_str = mut.get("date")
        if not date_str:
            return {"success": False, "reason": "skip", "message": "No date"}

        if "T" in date_str:
            posting_date = datetime.strptime(date_str.split("T")[0], "%Y-%m-%d").date()
        else:
            posting_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        # Get account
        ledger_id = mut.get("ledgerId")
        if not ledger_id:
            return {"success": False, "reason": "skip", "message": "No ledger ID"}

        account_code = migration_doc.get_account_code_from_ledger_id(ledger_id)
        if not account_code:
            return {"success": False, "reason": "skip", "message": "No account code"}

        account = frappe.db.get_value(
            "Account",
            {"company": company, "account_number": account_code},
            ["name", "account_type"],
            as_dict=True,
        )

        if not account:
            return {"success": False, "reason": "skip", "message": "Account not found"}

        # Skip stock accounts
        if account.account_type == "Stock":
            return {"success": False, "reason": "skip", "message": "Stock account"}

        # Create balanced entry
        je = frappe.new_doc("Journal Entry")
        je.company = company
        je.posting_date = posting_date
        je.user_remark = f"E-Boekhouden Single Mutation: {mut.get('description', '')}"

        # Main entry
        mut_type = mut.get("type", 0)
        if mut_type == 0:  # Debit
            entry1 = {
                "account": account.name,
                "debit_in_account_currency": amount,
                "cost_center": cost_center,
            }
            # Balancing credit to suspense
            entry2 = {
                "account": get_suspense_account(company),
                "credit_in_account_currency": amount,
                "cost_center": cost_center,
            }
        else:  # Credit
            entry1 = {
                "account": account.name,
                "credit_in_account_currency": amount,
                "cost_center": cost_center,
            }
            # Balancing debit to suspense
            entry2 = {
                "account": get_suspense_account(company),
                "debit_in_account_currency": amount,
                "cost_center": cost_center,
            }

        # Add party if needed
        if account.account_type == "Receivable":
            entry1["party_type"] = "Customer"
            entry1["party"] = "E-Boekhouden Import Customer"
        elif account.account_type == "Payable":
            entry1["party_type"] = "Supplier"
            entry1["party"] = "E-Boekhouden Import Supplier"

        je.append("accounts", entry1)
        je.append("accounts", entry2)

        je.flags.ignore_mandatory = True
        je.insert(ignore_permissions=True)

        return {"success": True, "journal_entry": je.name}

    except Exception as e:
        return {"success": False, "reason": "error", "message": str(e)[:100]}


def get_suspense_account(company):
    """Get or create suspense account"""
    suspense = frappe.db.get_value(
        "Account", {"company": company, "account_name": "E-Boekhouden Suspense Account"}, "name"
    )

    if not suspense:
        parent = frappe.db.get_value(
            "Account", {"company": company, "root_type": "Asset", "is_group": 1}, "name"
        )

        if parent:
            acc = frappe.new_doc("Account")
            acc.account_name = "E-Boekhouden Suspense Account"
            acc.company = company
            acc.parent_account = parent
            acc.account_type = "Temporary"
            acc.root_type = "Asset"
            acc.insert(ignore_permissions=True)
            suspense = acc.name

    return suspense


@frappe.whitelist()
def add_entry_number_field():
    """Add custom fields to track entry numbers and group keys"""
    fields_added = []

    # Add entry number field
    if not frappe.db.has_column("Journal Entry", "eboekhouden_entry_number"):
        custom_field = frappe.new_doc("Custom Field")
        custom_field.dt = "Journal Entry"
        custom_field.label = "E-Boekhouden Entry Number"
        custom_field.fieldname = "eboekhouden_entry_number"
        custom_field.fieldtype = "Data"
        custom_field.no_copy = 1
        custom_field.insert_after = "eboekhouden_mutation_id"
        custom_field.insert(ignore_permissions=True)
        fields_added.append("eboekhouden_entry_number")

    # Add group key field for better duplicate detection
    if not frappe.db.has_column("Journal Entry", "eboekhouden_group_key"):
        custom_field = frappe.new_doc("Custom Field")
        custom_field.dt = "Journal Entry"
        custom_field.label = "E-Boekhouden Group Key"
        custom_field.fieldname = "eboekhouden_group_key"
        custom_field.fieldtype = "Data"
        custom_field.unique = 1
        custom_field.no_copy = 1
        custom_field.insert_after = "eboekhouden_entry_number"
        custom_field.insert(ignore_permissions=True)
        fields_added.append("eboekhouden_group_key")

    if fields_added:
        return {"success": True, "message": "Fields added: {', '.join(fields_added)}"}
    return {"success": True, "message": "All fields already exist"}
