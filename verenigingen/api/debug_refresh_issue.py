#!/usr/bin/env python3

import frappe
from frappe.utils import getdate, now_datetime

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def debug_member_refresh_issue(member_name="Assoc-Member-2025-07-0030"):
    """Debug the refresh dues history issue for a specific member"""

    print(f"\n=== DEBUGGING REFRESH DUES HISTORY ISSUE FOR {member_name} ===\n")

    try:
        # Check if member exists
        if not frappe.db.exists("Member", member_name):
            return {"error": f"Member {member_name} does not exist!"}

        # Get member data
        member = frappe.get_doc("Member", member_name)
        result = {
            "member_name": member_name,
            "full_name": f"{member.first_name} {member.last_name}",
            "customer": member.customer,
            "payment_history_count": len(member.payment_history or []),
            "fee_change_history_count": len(member.fee_change_history or []),
        }

        # Check customer invoices directly
        invoices = []
        if member.customer:
            invoice_data = frappe.get_all(
                "Sales Invoice",
                filters={"customer": member.customer, "docstatus": ["in", [0, 1]]},
                fields=["name", "posting_date", "grand_total", "outstanding_amount", "status", "creation"],
                order_by="creation desc",
            )

            for inv in invoice_data:
                hours_ago = (now_datetime() - inv.creation).total_seconds() / 3600
                invoices.append(
                    {
                        "name": inv.name,
                        "posting_date": str(inv.posting_date),
                        "grand_total": inv.grand_total,
                        "outstanding_amount": inv.outstanding_amount,
                        "status": inv.status,
                        "hours_since_creation": round(hours_ago, 1),
                    }
                )

        result["invoices"] = invoices
        result["invoice_count"] = len(invoices)

        # Check dues schedules
        schedule_data = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name},
            fields=["name", "schedule_name", "dues_rate", "billing_frequency", "status", "creation"],
            order_by="creation",
        )

        result["schedules"] = schedule_data
        result["schedule_count"] = len(schedule_data)

        # Check current payment history details
        payment_history_details = []
        for entry in member.payment_history or []:
            payment_history_details.append(
                {
                    "invoice": entry.invoice,
                    "posting_date": str(entry.posting_date) if entry.posting_date else None,
                    "amount": entry.amount,
                    "transaction_type": getattr(entry, "transaction_type", "Unknown"),
                    "status": getattr(entry, "status", "Unknown"),
                }
            )

        result["payment_history_details"] = payment_history_details

        # Test refresh functionality
        print("Testing refresh_fee_change_history...")
        from verenigingen.verenigingen.doctype.member.member import refresh_fee_change_history

        fee_result = refresh_fee_change_history(member_name)
        result["fee_refresh_result"] = fee_result

        print("Testing refresh_financial_history...")
        financial_result = member.refresh_financial_history()
        result["financial_refresh_result"] = financial_result

        # Re-load member to see changes
        member.reload()
        result["after_refresh"] = {
            "payment_history_count": len(member.payment_history or []),
            "fee_change_history_count": len(member.fee_change_history or []),
        }

        return result

    except Exception as e:
        error_msg = str(e)
        frappe.log_error(f"Debug error: {error_msg}", "Debug Refresh Issue")
        return {"error": error_msg}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def test_atomic_vs_full_refresh(member_name="Assoc-Member-2025-07-0030"):
    """Test the difference between atomic and full refresh approaches"""

    try:
        member = frappe.get_doc("Member", member_name)

        # Capture initial state
        initial_count = len(member.payment_history or [])
        initial_invoices = [row.invoice for row in (member.payment_history or [])]

        print("Testing NEW atomic refresh approach...")

        # Test the NEW atomic approach
        atomic_result = member.refresh_financial_history()

        return {
            "member_name": member_name,
            "initial_payment_history_count": initial_count,
            "initial_invoices": initial_invoices,
            "atomic_result": atomic_result,
            "after_atomic_refresh_count": len(member.payment_history or []),
            "new_invoices_after_atomic": [
                row.invoice for row in (member.payment_history or []) if row.invoice not in initial_invoices
            ],
            "refresh_method": "atomic_updates_only",
            "improvement": "No longer clears existing data - only adds missing entries",
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def test_legacy_full_refresh(member_name="Assoc-Member-2025-07-0030"):
    """Test the legacy full refresh method (for comparison)"""

    try:
        member = frappe.get_doc("Member", member_name)

        # Capture initial state
        initial_count = len(member.payment_history or [])

        # Test the legacy full refresh
        legacy_result = member.force_full_payment_history_rebuild()

        return {
            "member_name": member_name,
            "initial_payment_history_count": initial_count,
            "legacy_result": legacy_result,
            "after_legacy_refresh_count": len(member.payment_history or []),
            "refresh_method": "legacy_full_rebuild",
            "warning": "This method clears and rebuilds entire table",
        }

    except Exception as e:
        return {"error": str(e)}
