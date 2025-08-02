#!/usr/bin/env python3
"""
Test the enhanced payment handler with API row ledger data
"""

import frappe


@frappe.whitelist()
def test_enhanced_handler_api_fix():
    """Test the enhanced handler uses API row ledger data correctly"""

    try:
        # Get the payment mutation that was problematic
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()
        mutation = iterator.fetch_mutation_detail(6724)

        if not mutation:
            return {"success": False, "error": "Could not fetch mutation 6724"}

        company = frappe.get_single("E-Boekhouden Settings").default_company
        cost_center = frappe.db.get_value("Company", company, "cost_center")

        # Test the enhanced handler directly
        from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import (
            PaymentEntryHandler,
        )

        handler = PaymentEntryHandler(company, cost_center)

        # Test the new API row ledger method
        party_account = handler._get_party_account_from_api_rows(mutation, "Customer", "Test Party")

        # Get expected values for comparison
        main_ledger_id = mutation.get("ledgerId")
        rows = mutation.get("rows", [])
        row_ledger_id = rows[0].get("ledgerId") if rows else None

        # Get mappings for both
        main_mapping = (
            frappe.db.get_value(
                "E-Boekhouden Ledger Mapping", {"ledger_id": main_ledger_id}, "erpnext_account"
            )
            if main_ledger_id
            else None
        )
        row_mapping = (
            frappe.db.get_value(
                "E-Boekhouden Ledger Mapping", {"ledger_id": row_ledger_id}, "erpnext_account"
            )
            if row_ledger_id
            else None
        )

        result = {
            "success": True,
            "mutation_id": mutation.get("id"),
            "api_data": {
                "main_ledger_id": main_ledger_id,
                "row_ledger_id": row_ledger_id,
                "amount": mutation.get("amount", 0),
                "relation_id": mutation.get("relationId"),
            },
            "account_mappings": {"main_ledger_mapping": main_mapping, "row_ledger_mapping": row_mapping},
            "enhanced_handler_result": {
                "party_account_from_api": party_account,
                "uses_api_row_data": party_account == row_mapping,
                "debug_log": handler.get_debug_log(),
            },
        }

        # Test what a full payment creation would look like
        try:
            debug_info = []
            payment_name = handler.process_payment_mutation(mutation)

            if payment_name:
                payment_doc = frappe.get_doc("Payment Entry", payment_name)
                result["full_payment_test"] = {
                    "payment_created": True,
                    "payment_name": payment_name,
                    "paid_from": payment_doc.paid_from,
                    "paid_to": payment_doc.paid_to,
                    "uses_correct_accounts": {
                        "bank_account_correct": payment_doc.paid_to == main_mapping,
                        "party_account_correct": payment_doc.paid_from == row_mapping,
                    },
                }

                # Clean up test payment
                payment_doc.cancel()
                payment_doc.delete()

            else:
                result["full_payment_test"] = {
                    "payment_created": False,
                    "error": "Handler returned None",
                    "debug_log": handler.get_debug_log(),
                }
        except Exception as e:
            result["full_payment_test"] = {
                "payment_created": False,
                "error": str(e),
                "debug_log": handler.get_debug_log(),
            }

        return result

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
