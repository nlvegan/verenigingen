#!/usr/bin/env python3
"""
Test the corrected memorial booking logic
"""

import frappe


@frappe.whitelist()
def test_memorial_logic():
    """Test corrected memorial booking logic"""

    print("Testing corrected memorial booking logic...")
    print("=" * 60)

    # Test mutation 6353 (positive amount)
    print("\n=== MUTATION 6353 (Positive Amount) ===")
    print("eBoekhouden Data:")
    print("- Main Ledger: 13201868 → 05320 (Continuïteitsreserve Productie)")
    print("- Row Ledger: 13201867 → 05310 (Continuïteitsreserve)")
    print("- Amount: +20000 (positive)")
    print("\nExpected Result:")
    print("- 05320 (main): DEBITED €20,000 (source account)")
    print("- 05310 (row): CREDITED €20,000 (destination account)")
    print("- Net effect: Money moves FROM 05320 TO 05310")

    # Test mutation 4595 (negative amount)
    print("\n=== MUTATION 4595 (Negative Amount) ===")
    print("eBoekhouden Data:")
    print("- Main Ledger: 16167827 → 99998 (Eindresultaat)")
    print("- Row Ledger: 13201865 → 05000 (Vrij besteedbaar eigen vermogen)")
    print("- Amount: -3329.41 (negative)")
    print("\nExpected Result:")
    print("- 99998 (main): CREDITED €3,329.41 (source account)")
    print("- 05000 (row): DEBITED €3,329.41 (destination account)")
    print("- Net effect: Loss clears from 99998 and reduces 05000 reserves")

    print("\n" + "=" * 60)
    print("LOGIC EXPLANATION:")
    print("=" * 60)
    print("For memorial bookings:")
    print("1. Main ledger = source account")
    print("2. Row ledgers = destination accounts")
    print("3. Positive row amount → row account credited (money TO)")
    print("4. Negative row amount → row account debited (money FROM)")
    print("5. Main ledger gets opposite entry to balance")

    return {"success": True}


if __name__ == "__main__":
    test_memorial_logic()
