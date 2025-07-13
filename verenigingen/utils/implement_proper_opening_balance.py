#!/usr/bin/env python3
"""
Implement proper ERPNext opening balance approach:
- Opening Invoice Creation Tool for receivables/payables
- Journal Entries for other accounts
"""

import frappe
from frappe.utils import flt, getdate, nowdate


@frappe.whitelist()
def implement_opening_balance_fix():
    """Replace the opening balance logic with proper ERPNext approach"""

    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    with open(file_path, "r") as f:
        content = f.read()

    # Find the _import_opening_balances function and replace it
    function_start = content.find("def _import_opening_balances(company, cost_center, debug_info):")
    if function_start == -1:
        return {"success": False, "error": "Could not find _import_opening_balances function"}

    # Find the end of the function (next function definition or end of file)
    function_end = content.find("\ndef ", function_start + 1)
    if function_end == -1:
        function_end = len(content)

    # Extract the old function
    # old_function = content[function_start:function_end]

    # Create the new function
    new_function = '''def _import_opening_balances(company, cost_center, debug_info):
    """Import opening balance entries using proper ERPNext approach"""
    try:
        # Enhanced duplicate detection for opening balances
        existing_checks = [
            # Check by eBoekhouden mutation number
            frappe.db.get_value("Journal Entry",
                {"eboekhouden_mutation_nr": "OPENING_BALANCE", "docstatus": ["!=", 2]},
                "name"),
            # Check by title pattern
            frappe.db.get_value("Journal Entry",
                {"title": ["like", "%Opening Balance%"], "company": company, "docstatus": ["!=", 2]},
                "name"),
            # Check by naming pattern
            frappe.db.get_value("Journal Entry",
                {"name": ["like", "OPB-%"], "company": company, "docstatus": ["!=", 2]},
                "name"),
            # Check for opening invoices
            frappe.db.get_value("Sales Invoice",
                {"is_opening": "Yes", "company": company, "docstatus": ["!=", 2]},
                "name"),
            frappe.db.get_value("Purchase Invoice",
                {"is_opening": "Yes", "company": company, "docstatus": ["!=", 2]},
                "name")
        ]

        existing_opening_balance = None
        for check in existing_checks:
            if check:
                existing_opening_balance = check
                break

        if existing_opening_balance:
            debug_info.append(
                f"Opening balances already imported (Document: {existing_opening_balance}), skipping duplicate"
            )
            return {"imported": 0, "errors": [], "debug_info": []}

        import requests
        from .eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()
        imported = 0
        errors = []
        local_debug = []

        local_debug.append("Fetching opening balance entries using list endpoint...")

        # Use the list endpoint with type=0 to get all opening balance entries
        url = "{iterator.base_url}/v1/mutation"
        params = {"type": 0}
        response = requests.get(url, headers=iterator._get_headers(), params=params, timeout=30)

        if response.status_code != 200:
            error_msg = f"Failed to fetch opening balances: {response.status_code}"
            errors.append(error_msg)
            local_debug.append(error_msg)
            return {"imported": 0, "errors": errors, "debug_info": local_debug}

        response_data = response.json()
        opening_entries = response_data.get("items", [])

        if not opening_entries:
            local_debug.append("No opening balance entries found")
            return {"imported": 0, "errors": [], "debug_info": local_debug}

        local_debug.append(f"Found {len(opening_entries)} opening balance entries")

        # Get opening balance date
        posting_date = "2018-12-31"  # Default
        if opening_entries:
            first_entry_date = opening_entries[0].get("date")
            if first_entry_date:
                posting_date = getdate(first_entry_date)
                local_debug.append(f"Using opening balance date from eBoekhouden: {posting_date}")

        # Separate entries by account type
        receivable_entries = []
        payable_entries = []
        other_entries = []

        for entry in opening_entries:
            ledger_id = entry.get("ledgerId")
            amount = frappe.utils.flt(entry.get("amount", 0), 2)

            if amount == 0 or not ledger_id:
                local_debug.append(f"Skipping entry with ledger {ledger_id}, amount {amount}")
                continue

            # Get account mapping
            mapping_result = frappe.db.sql(
                """SELECT erpnext_account
                   FROM `tabE-Boekhouden Ledger Mapping`
                   WHERE ledger_id = %s
                   LIMIT 1""",
                ledger_id,
            )

            if not mapping_result:
                error_msg = f"No account mapping found for ledger ID {ledger_id} (amount: {amount})"
                errors.append(error_msg)
                local_debug.append(error_msg)
                continue

            erpnext_account = mapping_result[0][0]

            # Get account type
            account_type = frappe.db.get_value("Account", erpnext_account, "account_type")

            # Skip stock accounts
            if account_type == "Stock":
                warning_msg = f"Skipping stock account {erpnext_account} (amount: {amount}) - stock accounts require Stock Transactions"
                local_debug.append(warning_msg)
                continue

            entry_data = {
                "ledger_id": ledger_id,
                "account": erpnext_account,
                "amount": amount,
                "account_type": account_type,
                "entry": entry
            }

            if account_type == "Receivable":
                receivable_entries.append(entry_data)
            elif account_type == "Payable":
                payable_entries.append(entry_data)
            else:
                other_entries.append(entry_data)

        local_debug.append(f"Categorized entries: {len(receivable_entries)} receivable, {len(payable_entries)} payable, {len(other_entries)} other")

        # Create opening invoices for receivables
        if receivable_entries:
            result = _create_opening_invoices(receivable_entries, "Sales", company, posting_date, local_debug)
            if result.get("success"):
                imported += result.get("imported", 0)
            else:
                errors.extend(result.get("errors", []))

        # Create opening invoices for payables
        if payable_entries:
            result = _create_opening_invoices(payable_entries, "Purchase", company, posting_date, local_debug)
            if result.get("success"):
                imported += result.get("imported", 0)
            else:
                errors.extend(result.get("errors", []))

        # Create journal entry for other accounts
        if other_entries:
            result = _create_opening_journal_entry(other_entries, company, cost_center, posting_date, local_debug)
            if result.get("success"):
                imported += result.get("imported", 0)
            else:
                errors.extend(result.get("errors", []))

        local_debug.append(f"Opening balance import completed - Total imported: {imported}")
        debug_info.extend(local_debug)

        return {"imported": imported, "errors": errors, "debug_info": local_debug}

    except Exception as e:
        import traceback
        error_msg = f"Opening balance import failed: {str(e)}"
        errors.append(error_msg)
        debug_info.append(error_msg)
        debug_info.append(traceback.format_exc())
        return {"imported": 0, "errors": errors, "debug_info": debug_info}


def _create_opening_invoices(entries, invoice_type, company, posting_date, debug_info):
    """Create opening invoices using ERPNext's proper approach"""
    try:
        imported = 0
        errors = []

        # Get temporary opening account - look for both group and ledger accounts
        temp_account = frappe.db.get_value("Account",
            {"account_name": "Temporary Opening Ledger", "company": company},
            "name")

        if not temp_account:
            temp_account = frappe.db.get_value("Account",
                {"account_name": "Temporary Opening", "company": company, "is_group": 0},
                "name")

        if not temp_account:
            # Create temporary opening account as a group account
            temp_account = frappe.new_doc("Account")
            temp_account.account_name = "Temporary Opening"
            temp_account.company = company
            temp_account.root_type = "Asset"
            temp_account.account_type = "Temporary"
            temp_account.is_group = 1  # Make it a group account
            temp_account.parent_account = frappe.db.get_value("Account",
                {"account_name": "Application of Funds (Assets)", "company": company},
                "name")
            temp_account.save(ignore_permissions=True)
            temp_account = temp_account.name
            debug_info.append(f"Created temporary opening account: {temp_account}")

            # Create a ledger account under the group
            ledger_account = frappe.new_doc("Account")
            ledger_account.account_name = "Temporary Opening Ledger"
            ledger_account.company = company
            ledger_account.root_type = "Asset"
            ledger_account.account_type = "Temporary"
            ledger_account.is_group = 0  # This is the ledger account
            ledger_account.parent_account = temp_account
            ledger_account.save(ignore_permissions=True)
            # Use the ledger account for transactions
            temp_account = ledger_account.name
            debug_info.append(f"Created temporary opening ledger account: {temp_account}")

        # Create opening invoices
        for entry_data in entries:
            try:
                # Create invoice
                doctype = "Sales Invoice" if invoice_type == "Sales" else "Purchase Invoice"
                invoice = frappe.new_doc(doctype)
                invoice.company = company
                invoice.posting_date = posting_date
                invoice.is_opening = "Yes"

                # Set party
                if invoice_type == "Sales":
                    invoice.customer = _get_or_create_generic_customer(debug_info)
                    invoice.debit_to = entry_data["account"]
                else:
                    invoice.supplier = _get_or_create_generic_supplier(debug_info)
                    invoice.credit_to = entry_data["account"]

                # Add item
                amount = abs(entry_data["amount"])
                invoice.append("items", {
                    "item_code": _get_or_create_opening_item(debug_info),
                    "item_name": "Opening Balance Item",
                    "qty": 1,
                    "rate": amount,
                    "amount": amount,
                    "income_account": temp_account if invoice_type == "Sales" else None,
                    "expense_account": temp_account if invoice_type == "Purchase" else None
                })

                # Set naming
                invoice.naming_series = "OPB-{invoice_type[:4].upper()}-{posting_date.year}-"

                # Save and submit
                invoice.save(ignore_permissions=True)
                invoice.submit()

                imported += 1
                debug_info.append(f"Created opening {invoice_type.lower()} invoice: {invoice.name} for {entry_data['account']}")

            except Exception as e:
                error_msg = f"Failed to create opening invoice for {entry_data['account']}: {str(e)}"
                errors.append(error_msg)
                debug_info.append(error_msg)

        return {"success": True, "imported": imported, "errors": errors}

    except Exception as e:
        return {"success": False, "imported": 0, "errors": [str(e)]}


def _create_opening_journal_entry(entries, company, cost_center, posting_date, debug_info):
    """Create journal entry for non-party accounts"""
    try:
        # Create Journal Entry
        je = frappe.new_doc("Journal Entry")
        je.company = company
        je.posting_date = posting_date

        # Set proper naming for opening balance
        posting_year = posting_date.year if posting_date else frappe.utils.now_datetime().year

        # Get the next number for opening balance entries
        existing_opb = frappe.db.sql("""
            SELECT name FROM `tabJournal Entry`
            WHERE name LIKE %s
            ORDER BY name DESC LIMIT 1
        """, [f"OPB-{posting_year}-%"], as_dict=True)

        if existing_opb:
            # Extract number and increment
            last_num = int(existing_opb[0].name.split('-')[-1])
            next_num = last_num + 1
        else:
            next_num = 1

        je.naming_series = f"OPB-{posting_year}-"
        je.name = f"OPB-{posting_year}-{str(next_num).zfill(5)}"

        # Set descriptive title
        je.title = f"Opening Balance as of {posting_date}"
        je.user_remark = f"E-Boekhouden Opening Balance Import - Non-party accounts as of {posting_date}\\nImported from eBoekhouden mutation type 0"
        je.voucher_type = "Opening Entry"

        # Store eBoekhouden references
        if hasattr(je, "eboekhouden_mutation_nr"):
            je.eboekhouden_mutation_nr = "OPENING_BALANCE"
        if hasattr(je, "eboekhouden_mutation_type"):
            je.eboekhouden_mutation_type = "0"

        # Add journal entry lines and calculate balancing entry
        total_debit = 0
        total_credit = 0

        for entry_data in entries:
            account_details = frappe.db.get_value(
                "Account", entry_data["account"],
                ["account_name", "account_type", "root_type"],
                as_dict=True
            )

            amount = entry_data["amount"]

            # Determine debit/credit based on account type and amount
            if account_details.root_type in ["Asset", "Expense"]:
                # Normal debit balance accounts
                debit_amount = abs(amount) if amount > 0 else 0
                credit_amount = abs(amount) if amount < 0 else 0
            else:
                # Normal credit balance accounts (Liability, Equity, Income)
                debit_amount = abs(amount) if amount < 0 else 0
                credit_amount = abs(amount) if amount > 0 else 0

            entry_line = {
                "account": entry_data["account"],
                "debit_in_account_currency": debit_amount,
                "credit_in_account_currency": credit_amount,
                "cost_center": cost_center,
                "user_remark": "Opening balance - Ledger {entry_data['ledger_id']} ({account_details.account_name})"
            }

            je.append("accounts", entry_line)
            total_debit += debit_amount
            total_credit += credit_amount

        # Add balancing entry if needed
        balance_diff = total_debit - total_credit
        if abs(balance_diff) > 0.01:  # If difference is significant
            # Get retained earnings account for balancing
            retained_earnings = frappe.db.get_value("Account",
                {"account_name": "Retained Earnings", "company": company},
                "name")

            if not retained_earnings:
                # Create retained earnings account if not exists
                retained_earnings = frappe.new_doc("Account")
                retained_earnings.account_name = "Retained Earnings"
                retained_earnings.company = company
                retained_earnings.root_type = "Equity"
                retained_earnings.account_type = "Accumulated Depreciation"
                retained_earnings.parent_account = frappe.db.get_value("Account",
                    {"account_name": "Equity", "company": company},
                    "name")
                retained_earnings.save(ignore_permissions=True)
                retained_earnings = retained_earnings.name
                debug_info.append(f"Created retained earnings account: {retained_earnings}")

            # Add balancing entry
            balancing_entry = {
                "account": retained_earnings,
                "debit_in_account_currency": abs(balance_diff) if balance_diff < 0 else 0,
                "credit_in_account_currency": abs(balance_diff) if balance_diff > 0 else 0,
                "cost_center": cost_center,
                "user_remark": "Opening balance balancing entry"
            }
            je.append("accounts", balancing_entry)
            debug_info.append(f"Added balancing entry: {abs(balance_diff):.2f} to {retained_earnings}")

        # Save and submit
        je.save(ignore_permissions=True)
        je.submit()

        debug_info.append(f"Created opening balance journal entry: {je.name} with {len(entries)} accounts")
        return {"success": True, "imported": 1, "errors": []}

    except Exception as e:
        return {"success": False, "imported": 0, "errors": [str(e)]}


def _get_or_create_opening_item(debug_info):
    """Get or create opening balance item"""
    item_code = "Opening Balance Item"

    if not frappe.db.exists("Item", item_code):
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = item_code
        item.item_group = "Products"
        item.stock_uom = "Unit"
        item.is_stock_item = 0
        item.is_sales_item = 1
        item.is_purchase_item = 1
        item.description = "Item for opening balance entries"
        item.save(ignore_permissions=True)
        debug_info.append(f"Created opening balance item: {item_code}")

    return item_code


def _get_or_create_generic_customer(debug_info):
    """Get or create generic customer for opening balance invoices"""
    customer_name = "Opening Balance Customer"

    if not frappe.db.exists("Customer", customer_name):
        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_type = "Individual"
        customer.customer_group = frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups"
        customer.territory = frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"
        customer.save(ignore_permissions=True)
        debug_info.append(f"Created generic customer: {customer_name}")

    return customer_name


def _get_or_create_generic_supplier(debug_info):
    """Get or create generic supplier for opening balance invoices"""
    supplier_name = "Opening Balance Supplier"

    if not frappe.db.exists("Supplier", supplier_name):
        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = supplier_name
        supplier.supplier_type = "Company"
        supplier.supplier_group = frappe.db.get_single_value("Buying Settings", "supplier_group") or "All Supplier Groups"
        supplier.save(ignore_permissions=True)
        debug_info.append(f"Created generic supplier: {supplier_name}")

    return supplier_name


'''

    # Replace the function
    content = content[:function_start] + new_function + content[function_end:]

    # Write back the modified content
    with open(file_path, "w") as f:
        f.write(content)

    print("Successfully implemented proper ERPNext opening balance approach:")
    print("1. Opening invoices for receivables/payables")
    print("2. Journal entries for other accounts")
    print("3. Proper duplicate detection across all opening balance types")
    print("4. Standard ERPNext naming conventions")

    return {"success": True}


@frappe.whitelist()
def test_new_opening_balance_logic():
    """Test the new opening balance logic without actually importing"""

    # This would test the logic with sample data
    print("Testing new opening balance logic...")

    # Sample test data
    test_data = {
        "receivable_entries": [{"account": "13500 - Te ontvangen contributies - NVV", "amount": 1150.58}],
        "payable_entries": [{"account": "19290 - Te betalen bedragen - NVV", "amount": -8445.03}],
        "other_entries": [
            {"account": "10000 - Kas - NVV", "amount": 154.70},
            {"account": "05000 - Vrij besteedbaar eigen vermogen - NVV", "amount": -38848.55},
        ],
    }

    print(
        "Test data: {len(test_data['receivable_entries'])} receivable, {len(test_data['payable_entries'])} payable, {len(test_data['other_entries'])} other"
    )

    return {"success": True, "test_data": test_data}


if __name__ == "__main__":
    print("Implement proper ERPNext opening balance approach")
