#!/usr/bin/env python3
"""
Revert to simple opening balance approach:
- One journal entry for everything
- Use company as party for receivables/payables
- Much simpler and more straightforward
"""

import frappe


@frappe.whitelist()
def revert_to_simple_opening_balance():
    """Replace the complex opening balance logic with simple journal entry approach"""

    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    with open(file_path, "r") as f:
        content = f.read()

    # Find the _import_opening_balances function and replace it entirely
    function_start = content.find("def _import_opening_balances(company, cost_center, debug_info):")
    if function_start == -1:
        return {"success": False, "error": "Could not find _import_opening_balances function"}

    # Find the end of the function
    function_end = content.find("\ndef ", function_start + 1)
    if function_end == -1:
        function_end = len(content)

    # Create the new simple function
    new_function = '''def _import_opening_balances(company, cost_center, debug_info):
    """Import opening balance entries as one simple journal entry"""
    try:
        # Check for existing opening balance
        existing_opening = frappe.db.get_value("Journal Entry",
            {"eboekhouden_mutation_nr": "OPENING_BALANCE", "docstatus": ["!=", 2]},
            "name")

        if existing_opening:
            debug_info.append(f"Opening balance already imported: {existing_opening}, skipping duplicate")
            return {"imported": 0, "errors": [], "debug_info": []}

        import requests
        from .eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()
        imported = 0
        errors = []
        local_debug = []

        local_debug.append("Fetching opening balance entries using list endpoint...")

        # Get opening balance entries
        url = "{iterator.base_url}/v1/mutation"
        params = {"type": 0}
        response = requests.get(url, headers=iterator._get_headers(), params=params, timeout=30)

        if response.status_code != 200:
            error_msg = f"Failed to fetch opening balances: {response.status_code}"
            errors.append(error_msg)
            return {"imported": 0, "errors": errors, "debug_info": local_debug}

        response_data = response.json()
        opening_entries = response_data.get("items", [])

        if not opening_entries:
            local_debug.append("No opening balance entries found")
            return {"imported": 0, "errors": [], "debug_info": local_debug}

        local_debug.append(f"Found {len(opening_entries)} opening balance entries")

        # Get opening balance date
        posting_date = "2018-12-31"
        if opening_entries:
            first_entry_date = opening_entries[0].get("date")
            if first_entry_date:
                posting_date = frappe.utils.getdate(first_entry_date)

        # Create the journal entry
        je = frappe.new_doc("Journal Entry")
        je.company = company
        je.posting_date = posting_date
        je.title = f"Opening Balance as of {posting_date}"
        je.user_remark = f"E-Boekhouden Opening Balance Import - All accounts as of {posting_date}"
        je.voucher_type = "Opening Entry"
        je.eboekhouden_mutation_nr = "OPENING_BALANCE"
        je.eboekhouden_mutation_type = "0"

        # Process each entry
        for entry in opening_entries:
            ledger_id = entry.get("ledgerId")
            amount = frappe.utils.flt(entry.get("amount", 0), 2)

            if amount == 0 or not ledger_id:
                continue

            # Get account mapping
            mapping_result = frappe.db.sql("""
                SELECT erpnext_account
                FROM `tabE-Boekhouden Ledger Mapping`
                WHERE ledger_id = %s
                LIMIT 1
            """, ledger_id)

            if not mapping_result:
                error_msg = f"No account mapping found for ledger ID {ledger_id}"
                errors.append(error_msg)
                continue

            erpnext_account = mapping_result[0][0]

            # Get account details
            account_details = frappe.db.get_value("Account", erpnext_account,
                ["account_name", "account_type", "root_type"], as_dict=True)

            if not account_details:
                error_msg = f"Account {erpnext_account} not found"
                errors.append(error_msg)
                continue

            # Skip stock accounts
            if account_details.account_type == "Stock":
                local_debug.append(f"Skipping stock account {erpnext_account} (amount: {amount})")
                continue

            # Determine debit/credit based on account type and amount
            if account_details.root_type in ["Asset", "Expense"]:
                debit_amount = amount if amount > 0 else 0
                credit_amount = abs(amount) if amount < 0 else 0
            else:
                debit_amount = abs(amount) if amount < 0 else 0
                credit_amount = amount if amount > 0 else 0

            # Create journal entry line
            entry_line = {
                "account": erpnext_account,
                "debit_in_account_currency": debit_amount,
                "credit_in_account_currency": credit_amount,
                "cost_center": cost_center,
                "user_remark": "Opening balance - Ledger {ledger_id} ({account_details.account_name})"
            }

            # Add party for receivables/payables
            if account_details.account_type in ["Receivable", "Payable"]:
                party_type = "Customer" if account_details.account_type == "Receivable" else "Supplier"

                # Use company as the party
                if party_type == "Customer":
                    # Get or create company as customer
                    company_name = frappe.db.get_value("Company", company, "company_name")
                    if not frappe.db.exists("Customer", company_name):
                        customer = frappe.new_doc("Customer")
                        customer.customer_name = company_name
                        customer.customer_type = "Company"
                        customer.customer_group = "All Customer Groups"
                        customer.territory = "All Territories"
                        customer.save(ignore_permissions=True)
                        local_debug.append(f"Created customer: {company_name}")

                    entry_line["party_type"] = "Customer"
                    entry_line["party"] = company_name

                else:  # Supplier
                    company_name = frappe.db.get_value("Company", company, "company_name")
                    if not frappe.db.exists("Supplier", company_name):
                        supplier = frappe.new_doc("Supplier")
                        supplier.supplier_name = company_name
                        supplier.supplier_type = "Company"
                        supplier.supplier_group = "All Supplier Groups"
                        supplier.save(ignore_permissions=True)
                        local_debug.append(f"Created supplier: {company_name}")

                    entry_line["party_type"] = "Supplier"
                    entry_line["party"] = company_name

            je.append("accounts", entry_line)

        # Save and submit the journal entry
        je.save(ignore_permissions=True)
        je.submit()

        imported = 1
        local_debug.append(f"Created opening balance journal entry: {je.name}")

        debug_info.extend(local_debug)
        return {"imported": imported, "errors": errors, "debug_info": local_debug}

    except Exception as e:
        import traceback
        error_msg = f"Opening balance import failed: {str(e)}"
        errors.append(error_msg)
        debug_info.append(error_msg)
        debug_info.append(traceback.format_exc())
        return {"imported": 0, "errors": errors, "debug_info": debug_info}

'''

    # Replace the function
    content = content[:function_start] + new_function + content[function_end:]

    # Remove the helper functions we don't need anymore
    helper_functions = [
        "_create_opening_invoices",
        "_create_opening_journal_entry",
        "_get_or_create_opening_item",
        "_get_or_create_generic_customer",
        "_get_or_create_generic_supplier",
    ]

    for func_name in helper_functions:
        # Find function start
        func_start = content.find("def {func_name}(")
        if func_start != -1:
            # Find function end (next function or end of file)
            func_end = content.find("\ndef ", func_start + 1)
            if func_end == -1:
                func_end = len(content)

            # Remove the function
            content = content[:func_start] + content[func_end:]

    # Write back the simplified content
    with open(file_path, "w") as f:
        f.write(content)

    print("Successfully reverted to simple opening balance approach:")
    print("1. One journal entry for all opening balance accounts")
    print("2. Uses company as party for receivables/payables")
    print("3. Much simpler and more straightforward")
    print("4. Removed complex Opening Invoice Creation Tool logic")
    print("5. Removed unnecessary helper functions")

    return {"success": True}


if __name__ == "__main__":
    print("Revert to simple opening balance approach")
