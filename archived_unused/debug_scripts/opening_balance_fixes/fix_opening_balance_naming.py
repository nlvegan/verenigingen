#!/usr/bin/env python3
"""
Fix opening balance naming to use proper OPB-YYYY-00001 format
"""

import frappe


@frappe.whitelist()
def fix_opening_balance_naming():
    """Fix the opening balance naming to use proper format"""

    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    with open(file_path, "r") as f:
        content = f.read()

    # Find the journal entry creation section and add proper naming
    old_je_creation = '''        # Create the journal entry
        je = frappe.new_doc("Journal Entry")
        je.company = company
        je.posting_date = posting_date
        je.title = f"Opening Balance as of {posting_date}"
        je.user_remark = f"E-Boekhouden Opening Balance Import - All accounts as of {posting_date}"
        je.voucher_type = "Opening Entry"
        je.eboekhouden_mutation_nr = "OPENING_BALANCE"
        je.eboekhouden_mutation_type = "0"'''

    new_je_creation = '''        # Create the journal entry
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

        je.title = f"Opening Balance as of {posting_date}"
        je.user_remark = "E-Boekhouden Opening Balance Import - All accounts as of {posting_date}"
        je.voucher_type = "Opening Entry"
        je.eboekhouden_mutation_nr = "OPENING_BALANCE"
        je.eboekhouden_mutation_type = "0"'''

    # Replace the journal entry creation
    content = content.replace(old_je_creation, new_je_creation)

    # Write back the fixed content
    with open(file_path, "w") as f:
        f.write(content)

    print("Successfully fixed opening balance naming:")
    print("1. Uses proper OPB-YYYY-00001 naming format")
    print("2. Automatically increments sequence numbers")
    print("3. Sets descriptive title and user remarks")
    print("4. No more naming after account numbers")

    return {"success": True}


if __name__ == "__main__":
    print("Fix opening balance naming")
