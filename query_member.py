#!/usr/bin/env python3

import frappe


def main():
    """Query member data for debugging"""
    member = frappe.db.get_value(
        "Member",
        "Assoc-Member-2025-07-0030",
        ["name", "full_name", "iban", "payment_method", "bic", "bank_account_name", "member_id", "docstatus"],
        as_dict=True,
    )

    if member:
        print("=== MEMBER DATA ===")
        for key, value in member.items():
            print(f"{key}: {value}")
        print()

        # Check existing mandates
        mandates = frappe.db.get_all(
            "SEPA Mandate",
            filters={"member": member["name"]},
            fields=["name", "mandate_id", "status", "is_active", "iban", "sign_date"],
            order_by="creation desc",
        )

        print(f"=== EXISTING MANDATES: {len(mandates)} ===")
        for mandate in mandates:
            print(f"Mandate: {mandate.mandate_id}")
            print(f"  Status: {mandate.status}")
            print(f"  Is Active: {mandate.is_active}")
            print(f"  IBAN: {mandate.iban}")
            print(f"  Sign Date: {mandate.sign_date}")
            print()

        # Check criteria
        has_iban = bool(member["iban"] and member["iban"].strip())
        is_sepa_dd = member["payment_method"] == "SEPA Direct Debit"
        not_cancelled = member["docstatus"] != 2
        active_mandates = [m for m in mandates if m.status == "Active" and m.is_active]
        has_active = len(active_mandates) > 0

        print("=== ANALYSIS ===")
        print(f"Has IBAN: {has_iban}")
        print(f"Payment method is SEPA Direct Debit: {is_sepa_dd}")
        print(f"Document not cancelled: {not_cancelled}")
        print(f"Has active mandate: {has_active}")
        print(f"MEETS SCHEDULER CRITERIA: {has_iban and is_sepa_dd and not_cancelled and not has_active}")
        print(f"SHOULD SHOW BUTTON: {has_iban and is_sepa_dd and not has_active}")
    else:
        print("Member not found")


if __name__ == "__main__":
    main()
