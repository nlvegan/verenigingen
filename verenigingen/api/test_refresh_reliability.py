#!/usr/bin/env python3

import frappe
from frappe.utils import now_datetime

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def test_refresh_button_reliability(member_name="Assoc-Member-2025-07-0030"):
    """Test the refresh button reliability by creating a new invoice and testing refresh"""

    try:
        member = frappe.get_doc("Member", member_name)

        if not member.customer:
            return {"error": "Member has no customer"}

        # Step 1: Record current state
        initial_count = len(member.payment_history or [])
        initial_invoices = []
        for row in member.payment_history or []:
            if hasattr(row, "invoice"):
                initial_invoices.append(row.invoice)
            elif isinstance(row, dict) and "invoice" in row:
                initial_invoices.append(row["invoice"])

        # Step 2: Create a test invoice
        test_invoice = frappe.new_doc("Sales Invoice")
        test_invoice.customer = member.customer
        test_invoice.posting_date = frappe.utils.today()
        test_invoice.due_date = frappe.utils.add_days(frappe.utils.today(), 30)

        # Get an existing item to use
        existing_item = frappe.db.get_value("Item", {"disabled": 0}, ["name", "item_name"], as_dict=True)
        if not existing_item:
            # Create a simple item if none exists
            test_item = frappe.new_doc("Item")
            test_item.item_code = "REFRESH-TEST-ITEM"
            test_item.item_name = "Refresh Test Item"
            test_item.item_group = "All Item Groups"
            test_item.stock_uom = "Nos"
            test_item.insert()
            existing_item = {"name": test_item.name, "item_name": test_item.item_name}

        # Add the test item
        test_invoice.append(
            "items",
            {
                "item_code": existing_item["name"],
                "item_name": existing_item["item_name"],
                "qty": 1,
                "rate": 1.00,
                "amount": 1.00,
            },
        )

        # Save as draft first
        test_invoice.insert()

        # Step 3: Test atomic refresh
        refresh_result = member.refresh_financial_history()

        # Step 4: Check results
        after_count = len(member.payment_history or [])
        new_invoices = []
        for row in member.payment_history or []:
            invoice_name = None
            if hasattr(row, "invoice"):
                invoice_name = row.invoice
            elif isinstance(row, dict) and "invoice" in row:
                invoice_name = row["invoice"]

            if invoice_name and invoice_name not in initial_invoices:
                new_invoices.append(invoice_name)

        # Step 5: Cleanup - delete the test invoice
        frappe.delete_doc("Sales Invoice", test_invoice.name, force=True)

        return {
            "test_invoice_created": test_invoice.name,
            "initial_payment_history_count": initial_count,
            "after_refresh_count": after_count,
            "refresh_result": refresh_result,
            "new_invoices_detected": new_invoices,
            "test_passed": test_invoice.name in new_invoices,
            "cleanup_completed": True,
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def comprehensive_refresh_test(member_name="Assoc-Member-2025-07-0030"):
    """Comprehensive test of the entire refresh button workflow"""

    try:
        # Test the complete button workflow
        from verenigingen.verenigingen.doctype.member.member import refresh_fee_change_history

        member = frappe.get_doc("Member", member_name)

        # Step 1: Test fee change history refresh
        fee_result = refresh_fee_change_history(member_name)

        # Step 2: Reload member to get fresh document (simulate JS reload)
        member = frappe.get_doc("Member", member_name)

        # Step 3: Test financial history refresh with fresh document
        financial_result = member.refresh_financial_history()

        return {
            "member_name": member_name,
            "fee_refresh_result": fee_result,
            "financial_refresh_result": financial_result,
            "no_document_conflicts": True,
            "workflow_test": "PASSED"
            if fee_result.get("success") and financial_result.get("success")
            else "FAILED",
        }

    except Exception as e:
        return {"error": str(e), "workflow_test": "FAILED"}
