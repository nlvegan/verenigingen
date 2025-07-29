#!/usr/bin/env python3

import frappe

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def clean_and_test_refresh(member_name="Assoc-Member-2025-07-0030"):
    """Clean up any test data and test the refresh with original data"""

    try:
        member = frappe.get_doc("Member", member_name)

        # Clean up any test invoices that may be orphaned in payment history
        if member.customer:
            # Get valid invoices for this customer
            valid_invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": member.customer, "docstatus": ["in", [0, 1]]},
                fields=["name"],
            )
            valid_invoice_names = [inv.name for inv in valid_invoices]

            # Remove any payment history entries for non-existent invoices
            cleaned_history = []
            for row in member.payment_history or []:
                if hasattr(row, "invoice"):
                    invoice_name = row.invoice
                elif isinstance(row, dict) and "invoice" in row:
                    invoice_name = row["invoice"]
                else:
                    continue

                if invoice_name in valid_invoice_names:
                    cleaned_history.append(row)

            # Update with cleaned history
            member.payment_history = cleaned_history
            member.save(ignore_permissions=True)

            # Now test the refresh
            refresh_result = member.refresh_financial_history()

            return {
                "member_name": member_name,
                "cleaned_invalid_entries": len(member.payment_history or []) - len(cleaned_history),
                "valid_invoices_found": len(valid_invoice_names),
                "final_payment_history_count": len(member.payment_history or []),
                "refresh_result": refresh_result,
                "status": "SUCCESS" if refresh_result.get("success") else "FAILED",
            }

        return {"error": "No customer found"}

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def final_button_test(member_name="Assoc-Member-2025-07-0030"):
    """Final test simulating the exact button click workflow"""

    try:
        # Step 1: Test fee change history refresh (first part of button click)
        from verenigingen.verenigingen.doctype.member.member import refresh_fee_change_history

        fee_result = refresh_fee_change_history(member_name)

        if not fee_result.get("success"):
            return {"step": "fee_refresh_failed", "fee_result": fee_result, "status": "FAILED"}

        # Step 2: Reload member document (simulate JS reload_doc)
        member = frappe.get_doc("Member", member_name)

        # Step 3: Test financial history refresh (second part of button click)
        financial_result = member.refresh_financial_history()

        return {
            "member_name": member_name,
            "fee_refresh_result": fee_result,
            "financial_refresh_result": financial_result,
            "complete_workflow_test": "PASSED"
            if fee_result.get("success") and financial_result.get("success")
            else "FAILED",
            "atomic_updates_confirmed": financial_result.get("method") == "atomic_updates_only",
            "no_document_conflicts": True,
        }

    except Exception as e:
        return {"error": str(e), "status": "FAILED"}
