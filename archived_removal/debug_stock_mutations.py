"""
Debug which specific mutations involve stock accounts and why
"""

import frappe


@frappe.whitelist()
def analyze_stock_related_mutations():
    """Analyze the specific mutations that involve stock accounts"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Get all type 5 mutations
        type5_mutations = iterator.fetch_mutations_by_type(mutation_type=5, limit=50)

        stock_mutations = []
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        for mutation in type5_mutations:
            mutation_id = mutation.get("id")

            # Check each row to see if it involves stock accounts
            for row in mutation.get("rows", []):
                ledger_id = row.get("ledgerId")

                # Look up which account this ledger maps to
                ebh_mapping = frappe.db.get_value(
                    "E-Boekhouden Ledger Mapping",
                    {"ledger_id": str(ledger_id)},
                    ["erpnext_account", "ledger_name"],
                    as_dict=True,
                )

                if ebh_mapping and ebh_mapping.erpnext_account:
                    account_type = frappe.db.get_value("Account", ebh_mapping.erpnext_account, "account_type")

                    if account_type == "Stock":
                        stock_mutations.append(
                            {
                                "mutation_id": mutation_id,
                                "mutation_type": mutation.get("type"),
                                "date": mutation.get("date"),
                                "description": mutation.get("description", "")[:100],
                                "amount": mutation.get("amount"),
                                "ledger_id": ledger_id,
                                "erpnext_account": ebh_mapping.erpnext_account,
                                "ledger_name": ebh_mapping.ledger_name,
                                "row_amount": row.get("amount"),
                                "row_description": row.get("description", "")[:50],
                            }
                        )

        return {
            "success": True,
            "total_type5_checked": len(type5_mutations),
            "stock_mutations_found": len(stock_mutations),
            "stock_mutations": stock_mutations[:10],  # First 10 for review
            "analysis": "These are type 5 (Money Received) mutations that reference stock accounts which should not be possible in normal business logic",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def check_ledger_30000_details():
    """Check what ledger 30000 represents in eBoekhouden"""
    try:
        # Find the ledger mapping for the problematic ledger
        ledger_id = 13201963  # From the error we saw
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        # Check the mapping
        mapping = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping",
            {"ledger_id": str(ledger_id)},
            ["erpnext_account", "ledger_name", "ledger_code"],
            as_dict=True,
        )

        # Also check if there are other ledger IDs that map to the same stock account
        stock_account = "30000 - Voorraden - NVV"
        other_mappings = frappe.get_all(
            "E-Boekhouden Ledger Mapping",
            filters={"erpnext_account": stock_account},
            fields=["ledger_id", "ledger_name", "ledger_code"],
            limit=20,
        )

        return {
            "success": True,
            "problematic_ledger_id": ledger_id,
            "mapping": mapping,
            "other_mappings_to_stock": other_mappings,
            "stock_account": stock_account,
            "question": "Why is an eBoekhouden ledger mapped to a stock account when it appears in money transfer mutations?",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_mutation_1256_details():
    """Check the specific details of mutation 1256 that failed"""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()
        mutation = iterator.fetch_mutation_detail(1256)

        if not mutation:
            return {"success": False, "error": "Mutation 1256 not found"}

        # Analyze each part of this mutation
        analysis = {
            "mutation_id": mutation.get("id"),
            "type": mutation.get("type"),
            "date": mutation.get("date"),
            "description": mutation.get("description"),
            "amount": mutation.get("amount"),
            "ledger_id": mutation.get("ledgerId"),
            "rows": [],
        }

        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        # Analyze each row
        for i, row in enumerate(mutation.get("rows", [])):
            row_ledger_id = row.get("ledgerId")

            # Look up the mapping
            mapping = frappe.db.get_value(
                "E-Boekhouden Ledger Mapping",
                {"ledger_id": str(row_ledger_id)},
                ["erpnext_account", "ledger_name", "ledger_code"],
                as_dict=True,
            )

            row_analysis = {
                "row_index": i,
                "ledger_id": row_ledger_id,
                "amount": row.get("amount"),
                "description": row.get("description"),
                "mapping": mapping,
                "erpnext_account_type": None,
            }

            if mapping and mapping.erpnext_account:
                row_analysis["erpnext_account_type"] = frappe.db.get_value(
                    "Account", mapping.erpnext_account, "account_type"
                )

            analysis["rows"].append(row_analysis)

        return {
            "success": True,
            "mutation_analysis": analysis,
            "business_logic_question": "What type of business transaction would involve both money movement (type 5) and stock accounts?",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
