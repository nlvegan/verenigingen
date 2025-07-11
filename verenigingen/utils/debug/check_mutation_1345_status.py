#!/usr/bin/env python3
"""
Check current status of mutation 1345 and force re-import if needed
"""

import json

import frappe


@frappe.whitelist()
def check_mutation_1345_status():
    """Check if mutation 1345 has been re-imported correctly"""
    try:
        results = {}

        # Step 1: Check if Journal Entry exists for mutation 1345
        existing_je = frappe.db.sql(
            """SELECT name, title, posting_date, user_remark, total_debit, total_credit
               FROM `tabJournal Entry`
               WHERE eboekhouden_mutation_nr = %s
               ORDER BY creation DESC
               LIMIT 1""",
            "1345",
            as_dict=True,
        )

        if existing_je:
            results["journal_entry_exists"] = True
            results["journal_entry"] = existing_je[0]

            # Get the accounts for this Journal Entry
            je_name = existing_je[0]["name"]
            accounts = frappe.db.sql(
                """SELECT account, debit, credit, user_remark
                   FROM `tabJournal Entry Account`
                   WHERE parent = %s
                   ORDER BY idx""",
                je_name,
                as_dict=True,
            )
            results["journal_entry"]["accounts"] = accounts

        else:
            results["journal_entry_exists"] = False
            results["message"] = "No Journal Entry found for mutation 1345 - ready for re-import"

        # Step 2: Check if there's a cache entry
        cache_entry = frappe.db.sql(
            """SELECT name, mutation_id, mutation_type, mutation_date
               FROM `tabEBoekhouden REST Mutation Cache`
               WHERE mutation_id = %s
               LIMIT 1""",
            "1345",
            as_dict=True,
        )

        if cache_entry:
            results["cache_exists"] = True
            results["cache_entry"] = cache_entry[0]
        else:
            results["cache_exists"] = False

        return {"success": True, "results": results}

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
def force_reimport_mutation_1345():
    """Force re-import of mutation 1345 using the fixed logic"""
    try:
        from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI
        from verenigingen.utils.eboekhouden_rest_full_migration import _import_rest_mutations_batch

        api = EBoekhoudenAPI()

        # Fetch mutation 1345
        mutation_result = api.make_request("v1/mutation/1345")

        if not mutation_result or not mutation_result.get("success"):
            return {"success": False, "error": "Failed to fetch mutation 1345 from API"}

        mutation_data = json.loads(mutation_result.get("data", "{}"))

        # Get settings
        settings = frappe.get_single("E-Boekhouden Settings")

        # Process the mutation
        batch_result = _import_rest_mutations_batch("Force Reimport Mutation 1345", [mutation_data], settings)

        return {
            "success": True,
            "mutation_data": mutation_data,
            "batch_result": batch_result,
            "message": "Mutation 1345 force re-import completed",
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
