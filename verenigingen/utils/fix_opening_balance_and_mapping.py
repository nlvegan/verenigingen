#!/usr/bin/env python3
"""
Fix opening balance date handling and account type mapping
"""

import frappe
from frappe.utils import flt, getdate


@frappe.whitelist()
def fix_opening_balance_import():
    """Fix the opening balance import to use correct dates and better duplicate detection"""

    # Read the current file
    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    with open(file_path, "r") as f:
        content = f.read()

    # Fix 1: Update the opening balance date handling
    # Find the hardcoded date line
    old_date_line = 'je.posting_date = "2019-01-01"  # Opening balance date - use start of fiscal year'
    new_date_line = """# Get the date from the first opening balance entry or use fiscal year start
        posting_date = None
        if opening_entries:
            # Try to get date from first entry
            first_entry_date = opening_entries[0].get("date")
            if first_entry_date:
                posting_date = getdate(first_entry_date)
                local_debug.append(f"Using opening balance date from eBoekhouden: {posting_date}")
            else:
                # Fallback to previous fiscal year end
                fiscal_year_start = frappe.db.get_value("Fiscal Year",
                    {"company": company, "disabled": 0},
                    "year_start_date",
                    order_by="year_start_date desc")
                if fiscal_year_start:
                    # Use day before fiscal year start (typically Dec 31)
                    from datetime import timedelta
                    posting_date = getdate(fiscal_year_start) - timedelta(days=1)
                else:
                    posting_date = "2018-12-31"  # Default fallback
                local_debug.append(f"Using calculated opening balance date: {posting_date}")

        je.posting_date = posting_date"""

    content = content.replace(old_date_line, new_date_line)

    # Fix 2: Enhanced duplicate detection
    # Find the existing duplicate check
    old_duplicate_check = """# Check if opening balances have already been imported
        existing_opening_balance = frappe.db.get_value(
            "Journal Entry", {"eboekhouden_mutation_nr": "OPENING_BALANCE"}, "name"
        )

        if existing_opening_balance:
            debug_info.append(
                f"Opening balances already imported (Journal Entry: {existing_opening_balance}), skipping"
            )
            return {"imported": 0, "errors": [], "debug_info": []}"""

    new_duplicate_check = """# Enhanced duplicate detection for opening balances
        # Check multiple criteria to prevent duplicates
        existing_checks = [
            # Check by eBoekhouden mutation number
            frappe.db.get_value("Journal Entry",
                {"eboekhouden_mutation_nr": "OPENING_BALANCE", "docstatus": ["!=", 2]},
                "name"),
            # Check by title pattern
            frappe.db.get_value("Journal Entry",
                {"title": ["like", "%Opening Balance%"], "company": company, "docstatus": ["!=", 2]},
                "name"),
            # Check by voucher type and date range
            frappe.db.get_value("Journal Entry",
                {"voucher_type": "Opening Entry", "company": company, "docstatus": ["!=", 2],
                 "posting_date": ["between", ["2018-01-01", "2019-12-31"]]},
                "name")
        ]

        existing_opening_balance = None
        for check in existing_checks:
            if check:
                existing_opening_balance = check
                break

        if existing_opening_balance:
            debug_info.append(
                f"Opening balances already imported (Journal Entry: {existing_opening_balance}), skipping duplicate"
            )
            return {"imported": 0, "errors": [], "debug_info": []}"""

    content = content.replace(old_duplicate_check, new_duplicate_check)

    # Fix 3: Update the title to use dynamic date
    old_title = 'je.title = "eBoekhouden Opening Balance 2019"'
    new_title = (
        "je.title = f\"eBoekhouden Opening Balance {posting_date.year if posting_date else 'Import'}\""
    )
    content = content.replace(old_title, new_title)

    # Fix 4: Update user remark to use dynamic date
    old_remark = (
        'je.user_remark = "E-Boekhouden Opening Balance Import - All account balances as of 2019-01-01"'
    )
    new_remark = (
        'je.user_remark = "E-Boekhouden Opening Balance Import - All account balances as of {posting_date}"'
    )
    content = content.replace(old_remark, new_remark)

    # Write back the fixed content
    with open(file_path, "w") as f:
        f.write(content)

    print("Fixed opening balance import function:")
    print("1. Now uses actual date from eBoekhouden entries")
    print("2. Enhanced duplicate detection with multiple criteria")
    print("3. Dynamic title and remarks based on actual date")

    return {"success": True}


@frappe.whitelist()
def fix_account_type_mapping():
    """Fix the smart account typing to properly use eBoekhouden category field"""

    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_smart_account_typing.py"
    )

    with open(file_path, "r") as f:
        content = f.read()

    # Update the category mapping to use proper 'FIN' type
    old_mapping = """category_mapping = {
            "DEB": ("Receivable", "Asset"),
            "CRED": ("Payable", "Liability"),
            "FIN": ("Bank", "Asset"),
            "KAS": ("Cash", "Asset"),
            "VW": ("Expense Account", "Expense"),  # Verbruiksrekeningen
            "BTW": ("Tax", "Liability"),
            "EIG": ("Equity", "Equity"),
            "BAL": ("Current Asset", "Asset"),  # Balance sheet - needs context
        }"""

    new_mapping = """category_mapping = {
            "DEB": ("Receivable", "Asset"),
            "CRED": ("Payable", "Liability"),
            "FIN": ("Bank", "Asset"),  # Financial accounts - usually banks
            "KAS": ("Cash", "Asset"),
            "VW": ("Expense Account", "Expense"),  # Verbruiksrekeningen
            "BTW": ("Tax", "Liability"),
            "EIG": ("Equity", "Equity"),  # Eigen vermogen
            "BAL": ("Current Asset", "Asset"),  # Balance sheet - needs context
        }"""

    content = content.replace(old_mapping, new_mapping)

    # Add special handling for equity accounts with FIN category
    # Find the equity account section
    old_equity_section = '''# Equity accounts
    elif code.startswith("5") or category == "EIG":
        return "Equity", "Equity"'''

    new_equity_section = '''# Equity accounts
    elif code.startswith("5"):
        # Check if it's incorrectly categorized as FIN in eBoekhouden
        # Equity accounts should never be Bank type
        if category == "FIN":
            # Log this mapping issue for review
            frappe.log_error(
                "Account {code} - {description} has FIN category but code suggests Equity account",
                "eBoekhouden Category Mismatch"
            )
        return "Equity", "Equity"
    elif category == "EIG":
        return "Equity", "Equity"'''

    content = content.replace(old_equity_section, new_equity_section)

    # Write back the fixed content
    with open(file_path, "w") as f:
        f.write(content)

    print("Fixed smart account typing:")
    print("1. Category 'FIN' properly documented as Financial/Bank accounts")
    print("2. Added detection for equity accounts miscategorized as FIN")
    print("3. Logging added for category mismatches")

    return {"success": True}


@frappe.whitelist()
def check_and_fix_duplicate_opening_entries():
    """Check for and optionally fix duplicate opening balance entries"""

    company = "Ned Ver Vegan"

    # Find all potential opening balance entries
    opening_entries = frappe.db.sql(
        """
        SELECT
            name,
            posting_date,
            title,
            creation,
            docstatus,
            eboekhouden_mutation_nr
        FROM `tabJournal Entry`
        WHERE (
            eboekhouden_mutation_nr = 'OPENING_BALANCE'
            OR title LIKE '%%Opening Balance%%'
            OR voucher_type = 'Opening Entry'
        )
        AND company = %s
        ORDER BY creation
    """,
        company,
        as_dict=True,
    )

    print(f"\nFound {len(opening_entries)} potential opening balance entries:")
    for entry in opening_entries:
        print(f"\n{entry.name}:")
        print(f"  Date: {entry.posting_date}")
        print(f"  Title: {entry.title}")
        print(f"  Created: {entry.creation}")
        print(
            "  Status: {'Submitted' if entry.docstatus == 1 else 'Draft' if entry.docstatus == 0 else 'Cancelled'}"
        )
        print(f"  eBoekhouden Nr: {entry.eboekhouden_mutation_nr}")

    if len(opening_entries) > 1:
        print("\nDUPLICATE OPENING ENTRIES DETECTED!")
        print("\nTo fix this issue:")
        print("1. Cancel and delete the duplicate entry")
        print("2. Keep only the earliest created entry")

        # Show GL impact of each
        for entry in opening_entries:
            if entry.docstatus == 1:  # Only submitted entries have GL impact
                gl_count = frappe.db.count("GL Entry", {"voucher_no": entry.name, "is_cancelled": 0})
                print(f"\n{entry.name} has {gl_count} GL entries")

    return {"opening_entries": opening_entries, "duplicate_found": len(opening_entries) > 1}


@frappe.whitelist()
def fix_account_05292_type():
    """Fix account 05292 from Bank to Equity type"""

    account_name = "05292 - Bestemmingsreserve Melk Je Kan Zonder - NVV"

    # Check current type
    current_type = frappe.db.get_value("Account", account_name, ["account_type", "root_type"], as_dict=True)

    if current_type:
        print(f"\nCurrent configuration for {account_name}:")
        print(f"  Account Type: {current_type.account_type}")
        print(f"  Root Type: {current_type.root_type}")

        if current_type.account_type != "Equity":
            # Fix the account type
            frappe.db.set_value("Account", account_name, {"account_type": "Equity", "root_type": "Equity"})

            print("\nFixed account type to Equity")

            # Clear cache
            frappe.clear_cache()

            return {"success": True, "fixed": True}
        else:
            print("\nAccount type is already correct")
            return {"success": True, "fixed": False}
    else:
        print(f"\nAccount {account_name} not found")
        return {"success": False, "error": "Account not found"}


if __name__ == "__main__":
    print("Fix opening balance and account mapping issues")
