#!/usr/bin/env python3
"""
Debug script to investigate Foppe de Haan's SEPA mandate issues
"""

import frappe
from frappe import _


def debug_foppe_sepa_mandate():
    """Debug Foppe de Haan's SEPA mandate status"""

    print("=== FOPPE DE HAAN SEPA MANDATE DEBUG ===\n")

    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    # Find Foppe de Haan
    member = frappe.db.get_value(
        "Member",
        {"full_name": "Foppe de Haan"},
        ["name", "iban", "payment_method", "bic", "bank_account_name", "member_id"],
        as_dict=True,
    )

    if not member:
        print("❌ Foppe de Haan not found in Member table")
        return

    print(f"✅ Found Member: {member.name}")
    print(f"   Full Name: Foppe de Haan")
    print(f"   IBAN: {member.iban}")
    print(f"   Payment Method: {member.payment_method}")
    print(f"   BIC: {member.bic}")
    print(f"   Bank Account Name: {member.bank_account_name}")
    print(f"   Member ID: {member.member_id}")
    print()

    # Check conditions for SEPA mandate button display
    print("=== SEPA MANDATE BUTTON DISPLAY CONDITIONS ===")

    has_iban = bool(member.iban)
    is_sepa_direct_debit = member.payment_method == "SEPA Direct Debit"

    print(f"1. Has IBAN: {has_iban} {'✅' if has_iban else '❌'}")
    print(
        f"2. Payment method is SEPA Direct Debit: {is_sepa_direct_debit} {'✅' if is_sepa_direct_debit else '❌'}"
    )

    # Check existing SEPA mandates
    mandates = frappe.db.get_all(
        "SEPA Mandate",
        filters={"member": member.name},
        fields=["name", "mandate_id", "status", "is_active", "iban", "sign_date", "used_for_memberships"],
        order_by="creation desc",
    )

    print(f"3. Existing SEPA mandates: {len(mandates)}")

    for i, mandate in enumerate(mandates):
        print(f"   Mandate {i+1}: {mandate.mandate_id}")
        print(f"     - Status: {mandate.status}")
        print(f"     - Is Active: {mandate.is_active}")
        print(f"     - IBAN: {mandate.iban}")
        print(f"     - Sign Date: {mandate.sign_date}")
        print(f"     - Used for Memberships: {mandate.used_for_memberships}")

    # Check for active mandates
    active_mandates = [m for m in mandates if m.status == "Active" and m.is_active]
    has_active_mandate = len(active_mandates) > 0

    print(f"4. Has active SEPA mandate: {has_active_mandate} {'❌' if has_active_mandate else '✅'}")
    print()

    # Final button display decision
    should_show_button = has_iban and is_sepa_direct_debit and not has_active_mandate

    print("=== FINAL BUTTON DISPLAY DECISION ===")
    print(
        f"Should show 'Create SEPA Mandate' button: {should_show_button} {'✅' if should_show_button else '❌'}"
    )
    print()

    if should_show_button:
        print("✅ SEPA mandate creation button SHOULD be visible")
        print("   If button is not showing, it's likely a JavaScript loading issue")
    else:
        print("❌ SEPA mandate creation button should NOT be visible")
        if not has_iban:
            print("   → Member needs an IBAN")
        if not is_sepa_direct_debit:
            print("   → Member needs payment method set to 'SEPA Direct Debit'")
        if has_active_mandate:
            print("   → Member already has an active SEPA mandate")

    print()

    # Test the scheduler logic
    print("=== SCHEDULER LOGIC TEST ===")

    # Check if member would be picked up by create_missing_sepa_mandates
    scheduler_query = """
        SELECT
            m.name,
            m.full_name,
            m.iban,
            m.bic,
            m.bank_account_name,
            m.member_id
        FROM `tabMember` m
        WHERE
            m.name = %s
            AND m.payment_method = 'SEPA Direct Debit'
            AND m.iban IS NOT NULL
            AND m.iban != ''
            AND m.docstatus != 2
            AND NOT EXISTS (
                SELECT 1
                FROM `tabSEPA Mandate` sm
                WHERE sm.member = m.name
                AND sm.status = 'Active'
                AND sm.is_active = 1
            )
    """

    scheduler_result = frappe.db.sql(scheduler_query, [member.name], as_dict=True)

    if scheduler_result:
        print("✅ Member WOULD be processed by scheduler")
        print("   → Scheduler should create a SEPA mandate automatically")
    else:
        print("❌ Member would NOT be processed by scheduler")
        print("   → Check why scheduler is not creating mandates")

    print()

    # Test the manual fix function
    print("=== MANUAL FIX TEST ===")

    try:
        # Import and test the manual fix function
        from verenigingen.api.sepa_mandate_fix import fix_specific_member_sepa_mandate

        print("Testing manual SEPA mandate creation...")
        result = fix_specific_member_sepa_mandate(member.name)

        print(f"Manual fix result: {result}")

        if result.get("success"):
            print("✅ Manual fix successful")
            print(f"   Created mandate: {result.get('mandate_id')}")
        else:
            print("❌ Manual fix failed")
            print(f"   Error: {result.get('message')}")

    except Exception as e:
        print(f"❌ Manual fix error: {str(e)}")

    print()
    print("=== DEBUG COMPLETE ===")


if __name__ == "__main__":
    debug_foppe_sepa_mandate()
