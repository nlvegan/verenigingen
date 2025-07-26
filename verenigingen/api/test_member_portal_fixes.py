#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def test_member_portal_fixes():
    """Test both portal fixes for member 07-0030"""
    try:
        member_name = "Assoc-Member-2025-07-0030"
        result = {}

        # Test 1: Check current payment status in portal
        from verenigingen.templates.pages.member_portal import get_payment_status

        member_doc = frappe.get_doc("Member", member_name)
        membership = frappe.db.get_value(
            "Membership",
            {"member": member_name, "status": "Active", "docstatus": 1},
            ["name", "membership_type", "start_date", "renewal_date", "status"],
            as_dict=True,
        )

        payment_status = get_payment_status(member_doc, membership)

        result["portal_payment_status"] = {
            "next_invoice_date": payment_status.get("next_invoice_date") if payment_status else None,
            "billing_frequency": payment_status.get("billing_frequency") if payment_status else None,
            "current_fee": payment_status.get("current_fee") if payment_status else None,
        }

        # Test 2: Test refresh dues history function
        from verenigingen.verenigingen.doctype.member.member import refresh_fee_change_history

        # Check current fee history count before refresh
        member_before = frappe.get_doc("Member", member_name)
        history_before = len(member_before.fee_change_history or [])

        # Run refresh
        refresh_result = refresh_fee_change_history(member_name)

        # Check after refresh
        member_after = frappe.get_doc("Member", member_name)
        history_after = len(member_after.fee_change_history or [])

        result["dues_history_refresh"] = {
            "refresh_result": refresh_result,
            "history_count_before": history_before,
            "history_count_after": history_after,
            "fee_history_entries": [
                {
                    "change_date": row.change_date,
                    "new_dues_rate": row.new_dues_rate,
                    "billing_frequency": row.billing_frequency,
                    "change_type": row.change_type,
                    "reason": row.reason,
                }
                for row in member_after.fee_change_history
            ]
            if member_after.fee_change_history
            else [],
        }

        # Test 3: Compare dates to understand the 2026 issue
        result["date_comparison"] = {
            "member_next_invoice_date": member_doc.next_invoice_date,
            "current_schedule_next_invoice": None,
            "membership_renewal_date": membership.renewal_date if membership else None,
        }

        if member_doc.current_dues_schedule:
            schedule_doc = frappe.get_doc("Membership Dues Schedule", member_doc.current_dues_schedule)
            result["date_comparison"]["current_schedule_next_invoice"] = schedule_doc.next_invoice_date

        return result

    except Exception as e:
        frappe.log_error(f"Error testing member portal fixes: {str(e)}")
        return {"error": str(e)}
