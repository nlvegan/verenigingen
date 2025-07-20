#!/usr/bin/env python3
"""
Debug the actual memorial processing logic that created the wrong balancing entry
"""

import json

import frappe


@frappe.whitelist()
def debug_memorial_processing_1345():
    """Debug the memorial processing logic for mutation 1345"""
    try:
        # Simulate the exact data that would be processed
        mutation_data = {
            "id": 1345,
            "type": 7,
            "date": "2019-12-31",
            "description": "Toekenning kosten MJKZ 2019",
            "ledgerId": 16167827,  # Main ledger - should be used for balancing
            "relationId": 0,
            "rows": [
                {"ledgerId": 13201866, "amount": -117.24, "description": "Toekenning kosten MJKZ 2019"},
                {"ledgerId": 13201866, "amount": 54.71, "description": "Toekenning kosten MJKZ 2019"},
                {"ledgerId": 13201865, "amount": 19525.95, "description": "Toekenning kosten MJKZ 2019"},
            ],
        }

        # Extract variables like the actual processing code does
        mutation_id = mutation_data.get("id")
        mutation_type = mutation_data.get("type")
        ledger_id = mutation_data.get("ledgerId")  # This should be 16167827
        relation_id = mutation_data.get("relationId")
        rows = mutation_data.get("rows", [])
        # description = mutation_data.get("description")

        results = {
            "mutation_id": mutation_id,
            "mutation_type": mutation_type,
            "ledger_id": ledger_id,
            "ledger_id_type": type(ledger_id).__name__,
            "ledger_id_str": str(ledger_id),
            "relation_id": relation_id,
            "rows_count": len(rows),
            "debug_steps": [],
        }

        # Step 1: Check if we have multiple rows (should be True for mutation 1345)
        has_multiple_rows = len(rows) > 1
        results["has_multiple_rows"] = has_multiple_rows
        results["debug_steps"].append("Multiple rows detected: {has_multiple_rows}")

        if has_multiple_rows:
            # Step 2: Track processed ledgers like the actual code does
            processed_ledgers = set()
            for row in rows:
                row_ledger_id = row.get("ledgerId")
                if row_ledger_id:
                    processed_ledgers.add(str(row_ledger_id))

            results["processed_ledgers"] = list(processed_ledgers)
            results["debug_steps"].append("Processed ledgers: {list(processed_ledgers)}")

            # Step 3: Simulate balancing logic
            # Calculate the balance difference like the actual code
            total_debit = 0
            total_credit = 0

            for row in rows:
                row_amount = float(row.get("amount", 0))
                if row_amount > 0:
                    total_debit += row_amount
                else:
                    total_credit += abs(row_amount)

            balance_difference = total_debit - total_credit
            results["total_debit"] = total_debit
            results["total_credit"] = total_credit
            results["balance_difference"] = balance_difference
            results["debug_steps"].append("Balance difference: {balance_difference}")

            # Step 4: Test main ledger lookup like the actual code
            source_account = None
            main_ledger_lookup_success = False

            if ledger_id:
                results["debug_steps"].append(
                    f"Testing main ledger lookup for ledger_id: {ledger_id} (type: {type(ledger_id)})"
                )

                # This is the EXACT query from the actual code
                mapping_result = frappe.db.sql(
                    """SELECT erpnext_account
                       FROM `tabE-Boekhouden Ledger Mapping`
                       WHERE ledger_id = %s
                       LIMIT 1""",
                    ledger_id,
                )

                if mapping_result:
                    source_account = mapping_result[0][0]
                    main_ledger_lookup_success = True
                    results["debug_steps"].append("✅ Main ledger lookup SUCCESS: {source_account}")
                else:
                    results["debug_steps"].append("❌ Main ledger lookup FAILED: No mapping found")
            else:
                results["debug_steps"].append("❌ Main ledger lookup SKIPPED: ledger_id is {ledger_id}")

            results["main_ledger_lookup_success"] = main_ledger_lookup_success
            results["source_account_from_main_ledger"] = source_account

            # Step 5: Test fallback logic if main ledger failed
            if not source_account:
                results["debug_steps"].append("Testing fallback to unprocessed row ledgers...")

                for row in rows:
                    row_ledger_id = row.get("ledgerId")
                    if row_ledger_id and str(row_ledger_id) not in processed_ledgers:
                        results["debug_steps"].append("Found unprocessed row ledger: {row_ledger_id}")

                        mapping_result = frappe.db.sql(
                            """SELECT erpnext_account
                               FROM `tabE-Boekhouden Ledger Mapping`
                               WHERE ledger_id = %s
                               LIMIT 1""",
                            row_ledger_id,
                        )
                        if mapping_result:
                            source_account = mapping_result[0][0]
                            results["debug_steps"].append(
                                f"✅ Fallback ledger lookup SUCCESS: {source_account}"
                            )
                            break
                        else:
                            results["debug_steps"].append(
                                "❌ Fallback ledger lookup FAILED for {row_ledger_id}"
                            )
                    else:
                        results["debug_steps"].append("Skipping processed ledger: {row_ledger_id}")

            # Step 6: Test 83280 fallback
            if not source_account:
                results["debug_steps"].append("Testing 83280 fallback...")

                income_account_83280 = frappe.db.sql(
                    """SELECT erpnext_account
                       FROM `tabE-Boekhouden Ledger Mapping`
                       WHERE erpnext_account LIKE %s
                       LIMIT 1""",
                    "83280%",
                )
                if income_account_83280:
                    source_account = income_account_83280[0][0]
                    results["debug_steps"].append("✅ 83280 fallback SUCCESS: {source_account}")
                else:
                    results["debug_steps"].append("❌ 83280 fallback FAILED")

            results["final_source_account"] = source_account

            # Step 7: Compare with actual Journal Entry
            results["debug_steps"].append("Comparing with actual Journal Entry ACC-JV-2025-72016...")

            je_data = frappe.get_doc("Journal Entry", "ACC-JV-2025-72016")
            balancing_entries = [
                acc for acc in je_data.accounts if "Balancing entry" in (acc.user_remark or "")
            ]

            if balancing_entries:
                actual_balancing_account = balancing_entries[0].account
                results["actual_balancing_account"] = actual_balancing_account
                results["debug_steps"].append("Actual balancing account used: {actual_balancing_account}")

                if source_account == actual_balancing_account:
                    results["debug_steps"].append("✅ MATCH: Simulated logic matches actual result")
                else:
                    results["debug_steps"].append(
                        f"❌ MISMATCH: Expected {source_account}, but actual was {actual_balancing_account}"
                    )
                    results["issue_found"] = True
            else:
                results["debug_steps"].append("No balancing entry found in Journal Entry")

        return results

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
