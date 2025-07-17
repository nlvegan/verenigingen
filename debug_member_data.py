#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def debug_member_sepa_data():
    """Debug member SEPA data for Assoc-Member-2025-07-0030"""
    member = frappe.db.get_value(
        "Member",
        "Assoc-Member-2025-07-0030",
        ["name", "full_name", "iban", "payment_method", "bic", "bank_account_name", "member_id", "docstatus"],
        as_dict=True,
    )

    if not member:
        return {"error": "Member not found"}

    # Check existing mandates
    mandates = frappe.db.get_all(
        "SEPA Mandate",
        filters={"member": member["name"]},
        fields=["name", "mandate_id", "status", "is_active", "iban", "sign_date"],
        order_by="creation desc",
    )

    # Check criteria
    has_iban = bool(member["iban"] and member["iban"].strip())
    is_sepa_dd = member["payment_method"] == "SEPA Direct Debit"
    not_cancelled = member["docstatus"] != 2
    active_mandates = [m for m in mandates if m.status == "Active" and m.is_active]
    has_active = len(active_mandates) > 0

    return {
        "member": member,
        "mandates": mandates,
        "analysis": {
            "has_iban": has_iban,
            "is_sepa_dd": is_sepa_dd,
            "not_cancelled": not_cancelled,
            "has_active": has_active,
            "meets_scheduler_criteria": has_iban and is_sepa_dd and not_cancelled and not has_active,
            "should_show_button": has_iban and is_sepa_dd and not has_active,
        },
    }
