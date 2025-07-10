#!/usr/bin/env python3
"""
Fix orphaned GL entries from deleted Journal Entries
"""

import frappe


@frappe.whitelist()
def fix_orphaned_gl_entries():
    """Find and fix orphaned GL entries"""

    # Find GL entries where the voucher doesn't exist
    orphaned_gl = frappe.db.sql(
        """
        SELECT DISTINCT
            gle.voucher_no,
            gle.voucher_type,
            COUNT(*) as entry_count,
            SUM(gle.debit) as total_debit,
            SUM(gle.credit) as total_credit
        FROM `tabGL Entry` gle
        LEFT JOIN `tabJournal Entry` je ON je.name = gle.voucher_no
        WHERE gle.voucher_type = 'Journal Entry'
        AND je.name IS NULL
        AND gle.is_cancelled = 0
        GROUP BY gle.voucher_no, gle.voucher_type
    """,
        as_dict=True,
    )

    if orphaned_gl:
        print(f"\nFound {len(orphaned_gl)} orphaned GL entry groups:")
        for entry in orphaned_gl:
            print(f"\n{entry.voucher_no}:")
            print(f"  Entries: {entry.entry_count}")
            print(f"  Total Debit: {entry.total_debit}")
            print(f"  Total Credit: {entry.total_credit}")

            # Get details of these entries
            details = frappe.db.sql(
                """
                SELECT account, debit, credit, posting_date
                FROM `tabGL Entry`
                WHERE voucher_no = %s
                AND is_cancelled = 0
                LIMIT 5
            """,
                entry.voucher_no,
                as_dict=True,
            )

            for detail in details:
                print(f"    {detail.account}: Dr {detail.debit} Cr {detail.credit}")
    else:
        print("No orphaned GL entries found")

    # Specifically check ACC-JV-2025-72051
    print("\n\nChecking ACC-JV-2025-72051 specifically:")

    gl_entries = frappe.db.sql(
        """
        SELECT
            name,
            account,
            debit,
            credit,
            posting_date,
            is_cancelled,
            creation
        FROM `tabGL Entry`
        WHERE voucher_no = 'ACC-JV-2025-72051'
        ORDER BY idx
    """,
        as_dict=True,
    )

    if gl_entries:
        print(f"Found {len(gl_entries)} GL entries for ACC-JV-2025-72051")
        for gle in gl_entries:
            print(f"  {gle.account}: Dr {gle.debit} Cr {gle.credit} (Cancelled: {gle.is_cancelled})")

        # Check if Journal Entry exists
        je_exists = frappe.db.exists("Journal Entry", "ACC-JV-2025-72051")
        print(f"\nJournal Entry ACC-JV-2025-72051 exists: {je_exists}")

        if not je_exists and gl_entries:
            print("\nThis is an ORPHANED GL entry set - Journal Entry was deleted but GL entries remain!")
            print("These GL entries should be cancelled to fix the balance.")

            # Cancel the orphaned GL entries
            return cancel_orphaned_gl_entries("ACC-JV-2025-72051")

    return {"orphaned_found": len(orphaned_gl)}


@frappe.whitelist()
def cancel_orphaned_gl_entries(voucher_no):
    """Cancel orphaned GL entries for a specific voucher"""

    # Safety check - make sure the Journal Entry really doesn't exist
    if frappe.db.exists("Journal Entry", voucher_no):
        frappe.throw(f"Journal Entry {voucher_no} exists! Cannot cancel its GL entries.")

    # Get all GL entries for this voucher
    gl_entries = frappe.db.sql(
        """
        SELECT name
        FROM `tabGL Entry`
        WHERE voucher_no = %s
        AND is_cancelled = 0
    """,
        voucher_no,
        as_dict=True,
    )

    if not gl_entries:
        print(f"No active GL entries found for {voucher_no}")
        return {"cancelled": 0}

    print(f"\nCancelling {len(gl_entries)} orphaned GL entries for {voucher_no}...")

    # Cancel each GL entry
    cancelled = 0
    for gle in gl_entries:
        frappe.db.set_value("GL Entry", gle.name, "is_cancelled", 1)
        cancelled += 1

    frappe.db.commit()
    print(f"Successfully cancelled {cancelled} GL entries")

    # Clear cache
    frappe.clear_cache()

    return {"cancelled": cancelled}


@frappe.whitelist()
def verify_fix():
    """Verify the fix worked"""

    account = "05000 - Vrij besteedbaar eigen vermogen - NVV"

    # Get current balance
    balance = frappe.db.sql(
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

    print(f"\nCurrent balance for {account}:")
    print(f"  Total Debit: €{balance.total_debit:,.2f}")
    print(f"  Total Credit: €{balance.total_credit:,.2f}")
    print(f"  Net Balance: €{balance.balance:,.2f} Cr")

    # Expected balance from eBoekhouden
    expected = 52933.81
    difference = abs(balance.balance - expected)

    print(f"\nExpected balance (eBoekhouden): €{expected:,.2f} Cr")
    print(f"Difference: €{difference:,.2f}")

    if difference < 0.01:
        print("\n✓ Balance now matches eBoekhouden!")
    else:
        print("\n✗ Balance still doesn't match")

    return {
        "current_balance": balance.balance,
        "expected_balance": expected,
        "difference": difference,
        "matches": difference < 0.01,
    }


if __name__ == "__main__":
    print("Fix orphaned GL entries")
