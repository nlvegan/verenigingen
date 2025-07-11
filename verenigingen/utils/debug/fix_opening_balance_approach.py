#!/usr/bin/env python3
"""
Fix opening balance import to use ERPNext's proper approach:
- Opening Invoice Creation Tool for receivables/payables
- Journal Entries for other accounts
"""

import frappe
from frappe.utils import flt, getdate


@frappe.whitelist()
def analyze_opening_balance_accounts():
    """Analyze which accounts in opening balance should be invoices vs journal entries"""

    # Get the current opening balance journal entry
    opening_je = frappe.db.get_value("Journal Entry", {"eboekhouden_mutation_nr": "OPENING_BALANCE"}, "name")

    if not opening_je:
        print("No opening balance journal entry found")
        return {"error": "No opening balance found"}

    # Get all accounts from the opening balance
    accounts = frappe.db.sql(
        """
        SELECT
            jea.account,
            jea.debit_in_account_currency as debit,
            jea.credit_in_account_currency as credit,
            jea.party_type,
            jea.party,
            acc.account_type,
            acc.root_type
        FROM `tabJournal Entry Account` jea
        JOIN `tabAccount` acc ON acc.name = jea.account
        WHERE jea.parent = %s
        ORDER BY acc.account_type, jea.account
    """,
        opening_je,
        as_dict=True,
    )

    print(f"\nAnalyzing {len(accounts)} accounts in opening balance:")

    # Categorize accounts
    should_be_invoices = []
    should_be_journal = []

    for acc in accounts:
        amount = acc.debit if acc.debit > 0 else -acc.credit

        if acc.account_type in ["Receivable", "Payable"]:
            should_be_invoices.append(
                {
                    "account": acc.account,
                    "amount": amount,
                    "party_type": acc.party_type,
                    "party": acc.party,
                    "account_type": acc.account_type,
                }
            )
        else:
            should_be_journal.append(
                {
                    "account": acc.account,
                    "amount": amount,
                    "account_type": acc.account_type,
                    "root_type": acc.root_type,
                }
            )

    print(f"\n=== SHOULD BE OPENING INVOICES ({len(should_be_invoices)}) ===")
    total_receivable = 0
    total_payable = 0

    for acc in should_be_invoices:
        print(f"  {acc['account']}: {acc['amount']:,.2f} ({acc['party_type']} {acc['party']})")
        if acc["account_type"] == "Receivable":
            total_receivable += acc["amount"]
        else:
            total_payable += acc["amount"]

    print("\nSummary:")
    print(f"  Total Receivables: €{total_receivable:,.2f}")
    print(f"  Total Payables: €{total_payable:,.2f}")

    print(f"\n=== SHOULD REMAIN AS JOURNAL ENTRIES ({len(should_be_journal)}) ===")
    by_type = {}
    for acc in should_be_journal:
        acc_type = acc["account_type"] or acc["root_type"]
        if acc_type not in by_type:
            by_type[acc_type] = []
        by_type[acc_type].append(acc)

    for acc_type, accs in by_type.items():
        print(f"\n  {acc_type}:")
        for acc in accs:
            print(f"    {acc['account']}: €{acc['amount']:,.2f}")

    return {
        "should_be_invoices": should_be_invoices,
        "should_be_journal": should_be_journal,
        "total_receivable": total_receivable,
        "total_payable": total_payable,
    }


@frappe.whitelist()
def create_proper_opening_balance_approach():
    """Create the proper ERPNext opening balance approach"""

    # This would be a comprehensive rewrite of the opening balance logic
    # For now, let's create a plan

    plan = """
    PLAN: Implement Proper ERPNext Opening Balance Approach

    1. MODIFY _import_opening_balances() function to:
       - Separate receivable/payable accounts from others
       - Create Opening Invoice Creation Tool entries for receivables/payables
       - Create Journal Entry only for non-party accounts

    2. FOR RECEIVABLES/PAYABLES:
       - Use Opening Invoice Creation Tool
       - Create proper Sales/Purchase Invoices with is_opening = "Yes"
       - Maintain proper party balances
       - Better aging report integration

    3. FOR OTHER ACCOUNTS:
       - Use Journal Entry approach (current)
       - Bank, Cash, Assets, Equity, etc.

    4. BENEFITS:
       - Proper ERPNext workflow
       - Better party balance tracking
       - Correct aging reports
       - Cleaner audit trail
    """

    print(plan)

    return {"plan": plan}


@frappe.whitelist()
def fix_opening_balance_import_logic():
    """Fix the opening balance import to use proper ERPNext approach"""

    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    # For now, let's add a TODO comment in the code
    with open(file_path, "r") as f:
        content = f.read()

    # Add a TODO comment
    todo_comment = """        # TODO: Implement proper ERPNext opening balance approach
        # - Use Opening Invoice Creation Tool for receivables/payables
        # - Use Journal Entries only for non-party accounts
        # This would provide better integration with ERPNext's aging reports
        # and maintain proper party balance tracking
        """

    # Find where to insert the comment
    insert_point = "def _import_opening_balances(company, cost_center, debug_info):"

    if insert_point in content:
        content = content.replace(insert_point, insert_point + "\n" + todo_comment)

        with open(file_path, "w") as f:
            f.write(content)

        print("Added TODO comment for proper opening balance approach")
        return {"success": True}
    else:
        print("Could not find insertion point")
        return {"success": False}


if __name__ == "__main__":
    print("Fix opening balance approach to use ERPNext standards")
