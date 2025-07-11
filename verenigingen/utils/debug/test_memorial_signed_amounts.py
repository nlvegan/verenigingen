#!/usr/bin/env python3
"""
Test memorial booking logic with signed amounts
"""

import frappe


@frappe.whitelist()
def test_memorial_signed_amounts():
    """Test memorial booking logic with both positive and negative amounts"""

    print("Testing memorial booking logic with signed amounts...")

    # Test Case 1: Positive amount (normal memorial booking)
    # This should create: Credit to row account, Debit from main account
    print("\n=== Test Case 1: Positive Amount ===")
    print("Mutation 6353: +20000 from 05310 to 05320")

    je_6353 = frappe.db.get_value("Journal Entry", {"eboekhouden_mutation_nr": "6353"}, "name")
    if je_6353:
        je_doc = frappe.get_doc("Journal Entry", je_6353)
        print(f"Journal Entry: {je_6353}")

        for acc in je_doc.accounts:
            if "05310" in acc.account:
                print(
                    "  05310 (main): Debit={acc.debit_in_account_currency}, Credit={acc.credit_in_account_currency}"
                )
            elif "05320" in acc.account:
                print(
                    "  05320 (row): Debit={acc.debit_in_account_currency}, Credit={acc.credit_in_account_currency}"
                )
    else:
        print("  Journal entry not found")

    # Test Case 2: Negative amount (reverse memorial booking)
    # This should create: Debit to row account, Credit from main account
    print("\n=== Test Case 2: Negative Amount ===")
    print("Mutation 4595: -3329.41 from 99998 to 05000")

    je_4595 = frappe.db.get_value("Journal Entry", {"eboekhouden_mutation_nr": "4595"}, "name")
    if je_4595:
        je_doc = frappe.get_doc("Journal Entry", je_4595)
        print(f"Journal Entry: {je_4595}")

        for acc in je_doc.accounts:
            if "99998" in acc.account:
                print(
                    "  99998 (main): Debit={acc.debit_in_account_currency}, Credit={acc.credit_in_account_currency}"
                )
            elif "05000" in acc.account:
                print(
                    "  05000 (row): Debit={acc.debit_in_account_currency}, Credit={acc.credit_in_account_currency}"
                )
    else:
        print("  Journal entry not found")

    # Analysis
    print("\n=== Analysis ===")
    print("Expected behavior:")
    print("- Positive amounts: Row account credited, Main account debited")
    print("- Negative amounts: Row account debited, Main account credited")
    print()
    print("Current behavior for 4595 (if negative amount):")
    print("- Should show: 05000 debited, 99998 credited")
    print("- This would correctly reduce reserves and clear the loss")

    return {"success": True}


if __name__ == "__main__":
    test_memorial_signed_amounts()
