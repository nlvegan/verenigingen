#!/usr/bin/env python3
"""
Debug script to investigate specific member's SEPA mandate status
"""

import json
import os
import sys

# Add the app directory to Python path
sys.path.insert(0, "/home/frappe/frappe-bench/apps/verenigingen")

# Set environment variables for Frappe
os.environ["FRAPPE_SITE"] = "dev.veganisme.net"


def debug_member_sepa_status(member_name):
    """Debug a specific member's SEPA mandate status"""

    print(f"=== DEBUGGING MEMBER: {member_name} ===\n")

    try:
        import frappe

        frappe.init(site="dev.veganisme.net")
        frappe.connect()

        # Get member data
        member = frappe.db.get_value(
            "Member",
            member_name,
            [
                "name",
                "full_name",
                "iban",
                "payment_method",
                "bic",
                "bank_account_name",
                "member_id",
                "docstatus",
            ],
            as_dict=True,
        )

        if not member:
            print(f"❌ Member {member_name} not found")
            return

        print(f"✅ Found Member: {member.name}")
        print(f"   Full Name: {member.full_name}")
        print(f"   IBAN: {member.iban}")
        print(f"   Payment Method: {member.payment_method}")
        print(f"   BIC: {member.bic}")
        print(f"   Bank Account Name: {member.bank_account_name}")
        print(f"   Member ID: {member.member_id}")
        print(f"   Doc Status: {member.docstatus}")
        print()

        # Check if member meets criteria for scheduler
        print("=== SCHEDULER CRITERIA CHECK ===")

        meets_payment_method = member.payment_method == "SEPA Direct Debit"
        has_iban = bool(member.iban and member.iban.strip())
        not_cancelled = member.docstatus != 2

        print(
            f"1. Payment method is SEPA Direct Debit: {meets_payment_method} {'✅' if meets_payment_method else '❌'}"
        )
        print(f"2. Has IBAN: {has_iban} {'✅' if has_iban else '❌'}")
        print(f"3. Document not cancelled: {not_cancelled} {'✅' if not_cancelled else '❌'}")

        # Check existing mandates
        mandates = frappe.db.get_all(
            "SEPA Mandate",
            filters={"member": member.name},
            fields=["name", "mandate_id", "status", "is_active", "iban", "sign_date", "used_for_memberships"],
            order_by="creation desc",
        )

        print(f"4. Existing mandates count: {len(mandates)}")

        active_mandates = []
        for i, mandate in enumerate(mandates):
            print(f"   Mandate {i+1}: {mandate.mandate_id}")
            print(f"     - Status: {mandate.status}")
            print(f"     - Is Active: {mandate.is_active}")
            print(f"     - IBAN: {mandate.iban}")
            print(f"     - Sign Date: {mandate.sign_date}")
            print(f"     - Used for Memberships: {mandate.used_for_memberships}")

            if mandate.status == "Active" and mandate.is_active:
                active_mandates.append(mandate)

        has_active_mandate = len(active_mandates) > 0
        print(f"5. Has active mandate: {has_active_mandate} {'❌' if has_active_mandate else '✅'}")
        print()

        # Check if member would be picked up by scheduler
        print("=== SCHEDULER PICKUP TEST ===")

        would_be_picked_up = meets_payment_method and has_iban and not_cancelled and not has_active_mandate

        print(
            f"Member would be picked up by scheduler: {would_be_picked_up} {'✅' if would_be_picked_up else '❌'}"
        )

        if would_be_picked_up:
            print("✅ Member SHOULD have a mandate created by scheduler")
            print("   → Check if scheduler is running properly")
            print("   → Check if there's a consent requirement missing")
        else:
            print("❌ Member would NOT be picked up by scheduler")
            if not meets_payment_method:
                print("   → Payment method needs to be 'SEPA Direct Debit'")
            if not has_iban:
                print("   → Member needs an IBAN")
            if not not_cancelled:
                print("   → Document is cancelled")
            if has_active_mandate:
                print("   → Member already has an active mandate")

        print()

        # Test manual creation
        print("=== MANUAL CREATION TEST ===")

        try:
            from verenigingen.api.sepa_mandate_fix import fix_specific_member_sepa_mandate

            print("Testing manual SEPA mandate creation...")
            # Don't actually create - just test the logic

            # Check if member has required info
            if not member.iban:
                print("❌ Manual creation would fail: No IBAN")
            elif member.payment_method != "SEPA Direct Debit":
                print("❌ Manual creation would fail: Payment method not SEPA Direct Debit")
            elif has_active_mandate:
                print("❌ Manual creation would fail: Already has active mandate")
            else:
                print("✅ Manual creation would succeed")

        except Exception as e:
            print(f"❌ Manual creation test error: {str(e)}")

        print()

        # Check for consent field
        print("=== CONSENT FIELD CHECK ===")

        # Look for any consent-related fields
        member_doc = frappe.get_doc("Member", member.name)
        consent_fields = [field for field in member_doc.meta.fields if "consent" in field.fieldname.lower()]

        if consent_fields:
            print("Found consent fields:")
            for field in consent_fields:
                value = getattr(member_doc, field.fieldname, None)
                print(f"   {field.fieldname}: {value}")
        else:
            print("❌ No consent fields found in Member doctype")
            print("   → This might be why scheduler doesn't create mandates automatically")
            print("   → SEPA mandates require explicit consent")

        print()
        print("=== SUMMARY ===")

        if would_be_picked_up and not has_active_mandate:
            print("🔍 ISSUE FOUND: Member meets all criteria but has no mandate")
            print("   → Scheduler should have created a mandate")
            print("   → Check if scheduler is running")
            print("   → Check if consent tracking is required")
        elif has_active_mandate:
            print("✅ Member has active mandate - no issue")
        else:
            print("ℹ️  Member doesn't meet criteria for automatic mandate creation")

        print()

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    member_name = "Assoc-Member-2025-07-0030"
    debug_member_sepa_status(member_name)
