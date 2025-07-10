#!/usr/bin/env python3
"""
Inspect specific journal entry and related memorial booking
"""

import frappe
from frappe.utils import flt


@frappe.whitelist()
def inspect_journal_entry(journal_entry_name):
    """Inspect specific journal entry details"""

    # Get the journal entry
    je = frappe.get_doc("Journal Entry", journal_entry_name)

    print(f"Journal Entry: {je.name}")
    print(f"Status: {je.docstatus}")
    print(f"Posting Date: {je.posting_date}")
    print(f"Title: {je.title}")
    print(f"User Remark: {je.user_remark}")
    print(
        "eBoekhouden Mutation Nr: {je.eboekhouden_mutation_nr if hasattr(je, 'eboekhouden_mutation_nr') else 'N/A'}"
    )
    print(f"Total Debit: {je.total_debit}")
    print(f"Total Credit: {je.total_credit}")

    print("\nAccounts:")
    for idx, acc in enumerate(je.accounts):
        print(f"\n  Entry {idx + 1}:")
        print(f"    Account: {acc.account}")
        print(f"    Debit: {acc.debit_in_account_currency}")
        print(f"    Credit: {acc.credit_in_account_currency}")
        print(f"    Remark: {acc.user_remark}")

    return {"journal_entry": je.as_dict()}


@frappe.whitelist()
def check_memorial_booking_logic():
    """Check memorial booking (type 7) import logic"""

    # Search for memorial bookings around the date
    memorial_entries = frappe.db.sql(
        """
        SELECT
            name,
            posting_date,
            title,
            total_debit,
            total_credit,
            eboekhouden_mutation_nr,
            eboekhouden_mutation_type
        FROM `tabJournal Entry`
        WHERE posting_date = '2024-12-31'
        AND (eboekhouden_mutation_type = '7' OR title LIKE '%Memorial%' OR title LIKE '%Memoriaal%')
        ORDER BY creation DESC
    """,
        as_dict=True,
    )

    print(f"Found {len(memorial_entries)} memorial entries on 2024-12-31:")

    for entry in memorial_entries:
        print(f"\n{entry.name}:")
        print(f"  Title: {entry.title}")
        print(f"  Mutation Nr: {entry.eboekhouden_mutation_nr}")
        print(f"  Total Debit: {entry.total_debit}")
        print(f"  Total Credit: {entry.total_credit}")

        # Get accounts involved
        accounts = frappe.db.sql(
            """
            SELECT
                account,
                debit_in_account_currency,
                credit_in_account_currency,
                user_remark
            FROM `tabJournal Entry Account`
            WHERE parent = %s
            AND (account LIKE '%%05310%%' OR account LIKE '%%05320%%')
        """,
            entry.name,
            as_dict=True,
        )

        if accounts:
            print("  Relevant accounts:")
            for acc in accounts:
                if acc.debit_in_account_currency > 0:
                    print(f"    {acc.account}: Debit {acc.debit_in_account_currency}")
                if acc.credit_in_account_currency > 0:
                    print(f"    {acc.account}: Credit {acc.credit_in_account_currency}")

    return {"entries": memorial_entries}


@frappe.whitelist()
def analyze_account_05320():
    """Analyze what happened with account 05320"""

    print("Analyzing account 05320 - Continuïteitsreserve Productie")

    # Get all GL entries for this account
    gl_entries = frappe.db.sql(
        """
        SELECT
            posting_date,
            voucher_type,
            voucher_no,
            account,
            debit,
            credit,
            remarks
        FROM `tabGL Entry`
        WHERE account = '05320 - Continuïteitsreserve Productie - NVV'
        AND is_cancelled = 0
        ORDER BY posting_date, creation
    """,
        as_dict=True,
    )

    print("\nGL Entries for account 05320:")
    running_balance = 0

    for entry in gl_entries:
        movement = entry.credit - entry.debit  # Credit increases equity, debit decreases
        running_balance += movement

        print(f"\n{entry.posting_date} - {entry.voucher_type} {entry.voucher_no}:")
        print(f"  Debit: {entry.debit}, Credit: {entry.credit}")
        print(f"  Movement: {movement:+.2f}")
        print(f"  Running Balance: {running_balance:.2f}")
        print(f"  Remarks: {entry.remarks}")

    # Check the specific memorial booking
    print("\n\nChecking memorial booking details from eBoekhouden data...")

    # Get the eBoekhouden mutation if it exists
    mutation_cache = frappe.db.sql(
        """
        SELECT mutation_data
        FROM `tabEBoekhouden REST Mutation Cache`
        WHERE mutation_data LIKE '%05320%'
        AND mutation_data LIKE '%05310%'
        AND mutation_data LIKE '%2024-12-31%'
        LIMIT 5
    """,
        as_dict=True,
    )

    if mutation_cache:
        import json

        for cache in mutation_cache:
            data = json.loads(cache.mutation_data)
            if data.get("date") == "2024-12-31":
                print("\nFound eBoekhouden mutation:")
                print(f"  ID: {data.get('id')}")
                print(f"  Type: {data.get('type')}")
                print(f"  Date: {data.get('date')}")
                print(f"  Description: {data.get('description')}")
                print(f"  Amount: {data.get('amount')}")
                print("  Lines:")
                for line in data.get("lines", []):
                    print(f"    Ledger {line.get('ledgerId')}: {line.get('amount')}")

    return {"gl_entries": gl_entries}


if __name__ == "__main__":
    print("Inspect journal entry")
