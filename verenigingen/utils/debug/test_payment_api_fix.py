#!/usr/bin/env python3
"""
Test the payment API fix to simulate what accounts would be used
"""

import frappe


@frappe.whitelist()
def test_payment_api_fix():
    """Test the payment fix with actual API data"""

    try:
        # Get the payment mutation that was problematic
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()
        mutation = iterator.fetch_mutation_detail(6724)

        if not mutation:
            return {"success": False, "error": "Could not fetch mutation 6724"}

        company = frappe.get_single("E-Boekhouden Settings").default_company

        # Simulate the new logic
        main_ledger_id = mutation.get("ledgerId")
        rows = mutation.get("rows", [])

        # Get bank account from main ledger
        bank_account = None
        if main_ledger_id:
            mapping_result = frappe.db.sql(
                """SELECT erpnext_account FROM `tabE-Boekhouden Ledger Mapping` WHERE ledger_id = %s LIMIT 1""",
                main_ledger_id,
            )
            if mapping_result:
                bank_account = mapping_result[0][0]

        # Get party account from row ledger
        party_account = None
        if rows and len(rows) > 0:
            row_ledger_id = rows[0].get("ledgerId")
            if row_ledger_id:
                mapping_result = frappe.db.sql(
                    """SELECT erpnext_account FROM `tabE-Boekhouden Ledger Mapping` WHERE ledger_id = %s LIMIT 1""",
                    row_ledger_id,
                )
                if mapping_result:
                    party_account = mapping_result[0][0]

        # For type 3 (customer payment), the mapping should be:
        payment_type = "Receive" if mutation.get("type") == 3 else "Pay"

        result = {
            "success": True,
            "mutation_id": mutation.get("id"),
            "mutation_type": mutation.get("type"),
            "payment_type": payment_type,
            "api_data": {
                "main_ledger_id": main_ledger_id,
                "row_ledger_id": rows[0].get("ledgerId") if rows else None,
                "amount": mutation.get("amount", 0),
                "relation_id": mutation.get("relationId"),
            },
            "account_mapping": {"bank_account": bank_account, "party_account": party_account},
            "expected_payment_structure": {
                "paid_from": party_account if payment_type == "Receive" else bank_account,
                "paid_to": bank_account if payment_type == "Receive" else party_account,
                "explanation": f"Money flows from {party_account if payment_type == 'Receive' else bank_account} to {bank_account if payment_type == 'Receive' else party_account}",
            },
        }

        # Compare with what the old logic would have done
        if mutation.get("relationId"):
            try:
                from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
                    _get_or_create_customer,
                    get_party_account,
                )

                customer = _get_or_create_customer(mutation.get("relationId"), [])
                old_fallback = get_party_account(customer, "Customer", company)
                result["old_vs_new"] = {
                    "old_fallback_account": old_fallback,
                    "new_api_account": party_account,
                    "improvement": f"API-based: {party_account} vs Fallback: {old_fallback}",
                }
            except Exception as e:
                result["old_vs_new"] = {"error": str(e)}

        return result

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
