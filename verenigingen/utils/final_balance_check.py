#!/usr/bin/env python3
"""
Final balance check and reconciliation
"""

import frappe
from frappe.utils import flt


@frappe.whitelist()
def final_reconciliation():
    """Final reconciliation after fixing orphaned entries"""

    # Your eBoekhouden transaction list with amounts
    eb_transactions = [
        {"date": "31-12-2018", "mutation": "opening", "debit": 0, "credit": 38848.55},
        {"date": "31-12-2019", "mutation": "1340", "debit": 412.20, "credit": 0},
        {"date": "31-12-2019", "mutation": "1344", "debit": 0, "credit": 4339.54},
        {"date": "31-12-2019", "mutation": "1345", "debit": 19525.95, "credit": 0},
        {"date": "31-12-2019", "mutation": "1346", "debit": 0, "credit": 0},  # Missing
        {"date": "01-01-2020", "mutation": "2255", "debit": 0, "credit": 31.41},
        {"date": "31-12-2019", "mutation": "2461", "debit": 0, "credit": 61.71},
        {"date": "31-12-2020", "mutation": "3697", "debit": 18889.36, "credit": 0},
        {"date": "31-12-2020", "mutation": "2457", "debit": 0, "credit": 21.64},
        {"date": "31-12-2020", "mutation": "2458", "debit": 0, "credit": 849.03},
        {"date": "31-12-2020", "mutation": "2465", "debit": 315.20, "credit": 0},
        {"date": "31-12-2021", "mutation": "3688", "debit": 0.51, "credit": 0},
        {"date": "31-12-2021", "mutation": "3689", "debit": 659.55, "credit": 0},
        {"date": "31-12-2021", "mutation": "3178", "debit": 0, "credit": 1911.87},
        {"date": "31-12-2021", "mutation": "3698", "debit": 7676.07, "credit": 0},
        {"date": "31-12-2022", "mutation": "4595", "debit": 0, "credit": 3329.41},
        {"date": "31-12-2022", "mutation": "4596", "debit": 741.44, "credit": 0},
        {"date": "31-12-2023", "mutation": "5383", "debit": 0, "credit": 532.46},
        {"date": "31-12-2023", "mutation": "5426-1", "debit": 59.97, "credit": 0},
        {"date": "31-12-2023", "mutation": "5426-2", "debit": 0, "credit": 1890.89},
        {"date": "31-12-2024", "mutation": "6334", "debit": 1.25, "credit": 0},
        {"date": "31-12-2024", "mutation": "6352", "debit": 0, "credit": 1112.82},
        {"date": "31-12-2024", "mutation": "6738", "debit": 0, "credit": 20178.28},
    ]

    # Calculate eBoekhouden totals
    eb_total_debit = sum(t["debit"] for t in eb_transactions)
    eb_total_credit = sum(t["credit"] for t in eb_transactions)
    eb_balance = eb_total_credit - eb_total_debit

    print("=== EBOEKHOUDEN DATA ===")
    print(f"Total Debits: €{eb_total_debit:,.2f}")
    print(f"Total Credits: €{eb_total_credit:,.2f}")
    print(f"Balance: €{eb_balance:,.2f} Cr")

    # Get ERPNext current state
    account = "05000 - Vrij besteedbaar eigen vermogen - NVV"
    erp_totals = frappe.db.sql(
        """
        SELECT
            SUM(debit) as total_debit,
            SUM(credit) as total_credit,
            SUM(credit - debit) as balance
        FROM `tabGL Entry`
        WHERE account = %s
        AND is_cancelled = 0
    """,
        account,
        as_dict=True,
    )[0]

    print("\n=== ERPNEXT DATA ===")
    print(f"Total Debits: €{erp_totals.total_debit:,.2f}")
    print(f"Total Credits: €{erp_totals.total_credit:,.2f}")
    print(f"Balance: €{erp_totals.balance:,.2f} Cr")

    print("\n=== COMPARISON ===")
    print(f"Debit Difference: €{abs(erp_totals.total_debit - eb_total_debit):,.2f}")
    print(f"Credit Difference: €{abs(erp_totals.total_credit - eb_total_credit):,.2f}")
    print(f"Balance Difference: €{abs(erp_totals.balance - eb_balance):,.2f}")

    # The issue is the opening balance in eBoekhouden includes the opening balance in the total
    # But the calculated balance (52,933.81) already includes the opening balance
    # So we need to subtract it from the total credits

    # eb_balance_without_opening = eb_total_credit - 38848.55 - eb_total_debit + 38848.55
    print("\n=== CORRECTED CALCULATION ===")
    print("eBoekhouden balance (from your list): €52,933.81 Cr")
    print(f"ERPNext current balance: €{erp_totals.balance:,.2f} Cr")
    print(f"Difference: €{abs(erp_totals.balance - 52933.81):,.2f}")

    # Check for mutation 1346
    mutation_1346 = frappe.db.get_value(
        "Journal Entry", {"eboekhouden_mutation_nr": "1346"}, ["name", "posting_date"], as_dict=True
    )

    if mutation_1346:
        print(f"\nMutation 1346 found: {mutation_1346.name} dated {mutation_1346.posting_date}")
    else:
        print("\nMutation 1346 is MISSING - this could be part of the difference")

    return {
        "eb_balance": 52933.81,
        "erp_balance": erp_totals.balance,
        "difference": abs(erp_totals.balance - 52933.81),
        "mutation_1346_missing": not bool(mutation_1346),
    }


if __name__ == "__main__":
    print("Final balance reconciliation")
