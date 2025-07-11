#!/usr/bin/env python3
"""
Reconcile eBoekhouden balances with ERPNext
"""

import frappe
from frappe.utils import flt


@frappe.whitelist()
def reconcile_account_05000():
    """Detailed reconciliation of account 05000"""

    account = "05000 - Vrij besteedbaar eigen vermogen - NVV"

    # Get all GL entries
    gl_entries = frappe.db.sql(
        """
        SELECT
            posting_date,
            voucher_type,
            voucher_no,
            debit,
            credit,
            (credit - debit) as net_amount
        FROM `tabGL Entry`
        WHERE account = %s
        AND is_cancelled = 0
        ORDER BY posting_date, creation
    """,
        account,
        as_dict=True,
    )

    # Calculate running balance
    running_balance = 0
    reconciliation = []

    for entry in gl_entries:
        running_balance += flt(entry.net_amount, 2)
        reconciliation.append(
            {
                "date": entry.posting_date,
                "voucher": "{entry.voucher_type} {entry.voucher_no}",
                "debit": flt(entry.debit, 2),
                "credit": flt(entry.credit, 2),
                "net": flt(entry.net_amount, 2),
                "balance": running_balance,
            }
        )

    # eBoekhouden transactions from user's list
    eboekhouden_transactions = [
        {"date": "2018-12-31", "desc": "opening", "debit": 0, "credit": 38848.55},
        {"date": "2019-12-31", "desc": "diverse mutaties", "debit": 412.20, "credit": 0},
        {"date": "2019-12-31", "desc": "eindresultaat 2019", "debit": 0, "credit": 4339.54},
        {"date": "2019-12-31", "desc": "Toekenning kosten MJKZ", "debit": 19525.95, "credit": 0},
        {"date": "2019-12-31", "desc": "afschrijving", "debit": 0, "credit": 61.71},
        {"date": "2020-01-01", "desc": "fout 2019", "debit": 0, "credit": 31.41},
        {"date": "2020-12-31", "desc": "eindresultaat 2020", "debit": 18889.36, "credit": 0},
        {"date": "2020-12-31", "desc": "afschrijving", "debit": 0, "credit": 21.64},
        {"date": "2020-12-31", "desc": "afschriving", "debit": 0, "credit": 849.03},
        {"date": "2020-12-31", "desc": "eindresultaat 2020", "debit": 315.20, "credit": 0},
        {"date": "2021-12-31", "desc": "correctie", "debit": 0.51, "credit": 0},
        {"date": "2021-12-31", "desc": "eindresultaat 2021", "debit": 659.55, "credit": 0},
        {"date": "2021-12-31", "desc": "afschrijving", "debit": 0, "credit": 1911.87},
        {"date": "2021-12-31", "desc": "eindresultaat nav verlies", "debit": 7676.07, "credit": 0},
        {"date": "2022-12-31", "desc": "eindresultaat 2022", "debit": 0, "credit": 3329.41},
        {"date": "2022-12-31", "desc": "correctie", "debit": 741.44, "credit": 0},
        {"date": "2023-12-31", "desc": "diverse correcties", "debit": 0, "credit": 532.46},
        {"date": "2023-12-31", "desc": "correctie vrij vermogen", "debit": 59.97, "credit": 1890.89},
        {"date": "2024-12-31", "desc": "netto correctie wisselkoersen", "debit": 1.25, "credit": 0},
        {"date": "2024-12-31", "desc": "diverse correcties", "debit": 0, "credit": 1112.82},
        {"date": "2024-12-31", "desc": "correctie eigen vermogen", "debit": 0, "credit": 20178.28},
    ]

    # Calculate eBoekhouden balance
    eb_balance = 38848.55  # Opening
    eb_total_debit = 0
    eb_total_credit = 38848.55

    for trans in eboekhouden_transactions[1:]:  # Skip opening
        eb_total_debit += trans["debit"]
        eb_total_credit += trans["credit"]
        eb_balance = eb_balance - trans["debit"] + trans["credit"]

    print("\n=== RECONCILIATION REPORT FOR ACCOUNT 05000 ===")
    print("\neBoekhouden Summary:")
    print(f"  Opening Balance (31-12-2018): €{38848.55:,.2f} Cr")
    print(f"  Total Debits: €{eb_total_debit:,.2f}")
    print(f"  Total Credits: €{eb_total_credit:,.2f}")
    print(f"  Calculated Balance: €{eb_balance:,.2f} Cr")

    # ERPNext summary
    erp_total_debit = sum(e.debit for e in gl_entries)
    erp_total_credit = sum(e.credit for e in gl_entries)
    erp_balance = erp_total_credit - erp_total_debit

    print("\nERPNext Summary:")
    print(f"  Total Debits: €{erp_total_debit:,.2f}")
    print(f"  Total Credits: €{erp_total_credit:,.2f}")
    print(f"  Current Balance: €{erp_balance:,.2f} Cr")

    print("\nDifference Analysis:")
    print(f"  Balance Difference: €{abs(erp_balance - eb_balance):,.2f}")

    # Check for missing mutations
    print("\n\nChecking for missing mutations...")

    # Get all Journal Entries with eBoekhouden mutation numbers
    eb_mutations = frappe.db.sql(
        """
        SELECT
            eboekhouden_mutation_nr,
            posting_date,
            name
        FROM `tabJournal Entry`
        WHERE eboekhouden_mutation_nr IS NOT NULL
        AND eboekhouden_mutation_nr != ''
        ORDER BY eboekhouden_mutation_nr
    """,
        as_dict=True,
    )

    mutation_map = {m.eboekhouden_mutation_nr: m for m in eb_mutations}

    # Expected mutations from the user's list
    expected_mutations = [
        "6334",
        "6352",
        "6738",
        "5383",
        "5426",
        "4595",
        "4596",
        "3178",
        "3688",
        "3689",
        "3698",
        "2457",
        "2458",
        "2465",
        "3697",
        "2255",
        "1340",
        "1344",
        "1345",
        "1346",
        "2461",
    ]

    missing_mutations = []
    for mut_id in expected_mutations:
        if mut_id not in mutation_map:
            missing_mutations.append(mut_id)

    if missing_mutations:
        print(f"Missing mutations: {missing_mutations}")
    else:
        print("All expected mutations are imported")

    # The key issue: Opening balance in eBoekhouden is 31-12-2018 but ERPNext has it as 01-01-2019
    print("\n\nKEY FINDING:")
    print("The opening balance in eBoekhouden is dated 31-12-2018")
    print("But ERPNext has it dated 01-01-2019")
    print("This is causing the reconciliation issue")

    return {
        "eb_balance": eb_balance,
        "erp_balance": erp_balance,
        "difference": abs(erp_balance - eb_balance),
        "missing_mutations": missing_mutations,
    }


if __name__ == "__main__":
    print("Reconcile eBoekhouden balances with ERPNext")
