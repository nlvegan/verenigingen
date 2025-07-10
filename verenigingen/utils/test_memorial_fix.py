#!/usr/bin/env python3
"""
Test the memorial booking fix
"""

import frappe


@frappe.whitelist()
def test_memorial_booking_fix():
    """Test that memorial booking logic creates correct debit/credit entries"""

    # Check current journal entry if it exists
    je = frappe.db.get_value("Journal Entry", {"eboekhouden_mutation_nr": "6353"}, "name")
    if je:
        je_doc = frappe.get_doc("Journal Entry", je)

        print(f"\nExisting Journal Entry: {je}")
        print(f"Total Debit: {je_doc.total_debit}")
        print(f"Total Credit: {je_doc.total_credit}")

        print("\nAccount entries:")
        for acc in je_doc.accounts:
            if acc.debit_in_account_currency > 0:
                print(f"  DEBIT: {acc.account} - €{acc.debit_in_account_currency:,.2f}")
            if acc.credit_in_account_currency > 0:
                print(f"  CREDIT: {acc.account} - €{acc.credit_in_account_currency:,.2f}")

        # Verify the logic
        account_05310 = None
        account_05320 = None

        for acc in je_doc.accounts:
            if "05310" in acc.account:
                account_05310 = acc
            elif "05320" in acc.account:
                account_05320 = acc

        print("\nVerification:")
        if account_05310:
            print(
                "05310 (Continuïteitsreserve): Debit={account_05310.debit_in_account_currency}, Credit={account_05310.credit_in_account_currency}"
            )
        if account_05320:
            print(
                "05320 (Continuïteitsreserve Productie): Debit={account_05320.debit_in_account_currency}, Credit={account_05320.credit_in_account_currency}"
            )

        # Check if this is correct
        if (
            account_05310
            and account_05310.debit_in_account_currency == 20000
            and account_05320
            and account_05320.credit_in_account_currency == 20000
        ):
            print("\n✅ SUCCESS: Memorial booking creates correct debit/credit entries!")
            print("- 05310 debited €20,000 (money leaving)")
            print("- 05320 credited €20,000 (money arriving)")
        else:
            print("\n❌ FAILURE: Memorial booking logic still incorrect")

    else:
        print("❌ No journal entry exists for mutation 6353")

    return {"success": True, "journal_entry": je}


if __name__ == "__main__":
    test_memorial_booking_fix()
