#!/usr/bin/env python3
"""
Debug mutation 1345 processing and compare with ACC-JV-2025-72016
Direct execution through bench execute
"""

import json

import frappe


@frappe.whitelist()
def debug_mutation_1345_direct():
    """Debug mutation 1345 and compare with Journal Entry ACC-JV-2025-72016"""
    try:
        from verenigingen.utils.eboekhouden.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI()
        results = {
            "success": True,
            "mutation_data": {},
            "journal_entry": {},
            "comparison": {},
            "ledger_analysis": {},
            "issues": [],
        }

        # 1. Fetch mutation 1345 raw data
        try:
            mutation_result = api.make_request("v1/mutation/1345")

            if mutation_result and mutation_result.get("success"):
                mutation_data = json.loads(mutation_result.get("data", "{}"))
                results["mutation_data"] = mutation_data

                # Extract key fields
                mutation_summary = {
                    "id": mutation_data.get("id"),
                    "type": mutation_data.get("type"),
                    "date": mutation_data.get("date"),
                    "description": mutation_data.get("description"),
                    "amount": mutation_data.get("amount"),
                    "relationId": mutation_data.get("relationId"),
                    "ledgerId": mutation_data.get("ledgerId"),
                    "invoiceNumber": mutation_data.get("invoiceNumber"),
                    "rows": mutation_data.get("rows", []),
                }

                results["mutation_summary"] = mutation_summary

                # Analyze ledger IDs
                main_ledger = mutation_data.get("ledgerId")
                row_ledgers = []

                for row in mutation_data.get("rows", []):
                    row_ledgers.append(
                        {
                            "ledgerId": row.get("ledgerId"),
                            "amount": row.get("amount"),
                            "description": row.get("description"),
                        }
                    )

                results["ledger_analysis"] = {
                    "main_ledger_id": main_ledger,
                    "row_ledgers": row_ledgers,
                    "total_ledgers": len(row_ledgers) + (1 if main_ledger else 0),
                }

            else:
                results["issues"].append("Failed to fetch mutation 1345 from API")
                results["mutation_data"] = {"error": "API call failed"}

        except Exception as e:
            results["issues"].append(f"Error fetching mutation 1345: {str(e)}")
            results["mutation_data"] = {"error": str(e)}

        # 2. Fetch Journal Entry ACC-JV-2025-72016 data
        try:
            je_data = frappe.get_doc("Journal Entry", "ACC-JV-2025-72016")

            je_summary = {
                "name": je_data.name,
                "title": je_data.title,
                "posting_date": str(je_data.posting_date),
                "voucher_type": je_data.voucher_type,
                "user_remark": je_data.user_remark,
                "eboekhouden_mutation_nr": getattr(je_data, "eboekhouden_mutation_nr", "Not set"),
                "total_debit": je_data.total_debit,
                "total_credit": je_data.total_credit,
                "accounts": [],
            }

            for account in je_data.accounts:
                account_entry = {
                    "account": account.account,
                    "debit": float(account.debit or 0),
                    "credit": float(account.credit or 0),
                    "debit_in_account_currency": float(account.debit_in_account_currency or 0),
                    "credit_in_account_currency": float(account.credit_in_account_currency or 0),
                    "party_type": account.party_type,
                    "party": account.party,
                    "user_remark": account.user_remark,
                }
                je_summary["accounts"].append(account_entry)

            results["journal_entry"] = je_summary

        except Exception as e:
            results["issues"].append(f"Error fetching Journal Entry ACC-JV-2025-72016: {str(e)}")
            results["journal_entry"] = {"error": str(e)}

        # 3. Check for ledger mapping in database
        if results["ledger_analysis"]:
            ledger_mappings = {}

            # Check main ledger mapping
            main_ledger = results["ledger_analysis"].get("main_ledger_id")
            if main_ledger:
                mapping = frappe.db.sql(
                    """SELECT erpnext_account, ledger_name
                       FROM `tabE-Boekhouden Ledger Mapping`
                       WHERE ledger_id = %s LIMIT 1""",
                    main_ledger,
                    as_dict=True,
                )
                if mapping:
                    ledger_mappings[str(main_ledger)] = mapping[0]
                else:
                    results["issues"].append("No mapping found for main ledger {main_ledger}")

            # Check row ledger mappings
            for row in results["ledger_analysis"].get("row_ledgers", []):
                row_ledger_id = row.get("ledgerId")
                if row_ledger_id:
                    mapping = frappe.db.sql(
                        """SELECT erpnext_account, ledger_name
                           FROM `tabE-Boekhouden Ledger Mapping`
                           WHERE ledger_id = %s LIMIT 1""",
                        row_ledger_id,
                        as_dict=True,
                    )
                    if mapping:
                        ledger_mappings[str(row_ledger_id)] = mapping[0]
                    else:
                        results["issues"].append("No mapping found for row ledger {row_ledger_id}")

            results["ledger_mappings"] = ledger_mappings

        return results

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
