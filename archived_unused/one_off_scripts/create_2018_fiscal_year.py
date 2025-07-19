#!/usr/bin/env python3
"""
Create 2018 fiscal year for opening balance
"""

import frappe


@frappe.whitelist()
def create_2018_fiscal_year():
    """Create 2018 fiscal year to accommodate opening balance"""

    # Check if 2018 fiscal year already exists
    existing_fy = frappe.db.exists("Fiscal Year", "2018")

    if existing_fy:
        print("2018 fiscal year already exists")
        return {"exists": True}

    try:
        # Create 2018 fiscal year
        fy = frappe.new_doc("Fiscal Year")
        fy.year = "2018"
        fy.year_start_date = "2018-01-01"
        fy.year_end_date = "2018-12-31"
        fy.disabled = 0
        fy.save(ignore_permissions=True)

        print("Successfully created 2018 fiscal year")
        return {
            "success": True,
            "fiscal_year": fy.name,
            "start_date": fy.year_start_date,
            "end_date": fy.year_end_date,
        }

    except Exception as e:
        print(f"Error creating 2018 fiscal year: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def fix_opening_balance_date():
    """Alternative fix: adjust opening balance date to 01-01-2019"""

    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    with open(file_path, "r") as f:
        content = f.read()

    # Find the opening balance date logic and force it to 01-01-2019
    old_logic = """# Get the date from the first opening balance entry or use fiscal year start
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

    new_logic = """# Force opening balance date to 01-01-2019 (start of first fiscal year)
        posting_date = "2019-01-01"
        local_debug.append(f"Using opening balance date: {posting_date} (start of first fiscal year)")

        je.posting_date = posting_date"""

    content = content.replace(old_logic, new_logic)

    with open(file_path, "w") as f:
        f.write(content)

    print("Fixed opening balance date to use 01-01-2019")
    return {"success": True}


if __name__ == "__main__":
    print("Create 2018 fiscal year or fix opening balance date")
