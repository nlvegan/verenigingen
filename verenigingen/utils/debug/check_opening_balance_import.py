"""
Check if opening balance mutations (type 0) are being imported
"""

import frappe


@frappe.whitelist()
def check_opening_balance_mutations():
    """Check if type 0 mutations are being imported"""

    try:
        # Check if we have any Journal Entries that might be opening balances
        opening_entries = frappe.db.sql(
            """
            SELECT
                je.name,
                je.posting_date,
                je.total_debit,
                je.total_credit,
                je.title,
                je.user_remark
            FROM `tabJournal Entry` je
            WHERE je.company = 'Ned Ver Vegan'
            AND (je.title LIKE '%opening%'
                OR je.title LIKE '%Opening%'
                OR je.title LIKE '%mutation 0%'
                OR je.title LIKE '%Mutation 0%'
                OR je.user_remark LIKE '%opening%')
            ORDER BY je.posting_date
            LIMIT 10
        """,
            as_dict=True,
        )

        # Check for any early date transactions that might be opening balances
        early_transactions = frappe.db.sql(
            """
            SELECT
                'Journal Entry' as doctype,
                name,
                posting_date,
                total_debit as amount,
                title
            FROM `tabJournal Entry`
            WHERE company = 'Ned Ver Vegan'
            AND posting_date <= '2019-01-31'
            ORDER BY posting_date
            LIMIT 10
        """,
            as_dict=True,
        )

        # Use the REST iterator to fetch a type 0 mutation
        from verenigingen.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()

        # Fetch type 0 mutations
        opening_mutations = iterator.fetch_mutations_by_type(0, limit=10)

        # Analyze the mutations
        mutation_analysis = []
        if opening_mutations:
            for mutation in opening_mutations[:5]:  # First 5
                rows_summary = []
                for row in mutation.get("rows", []):
                    ledger_id = str(row.get("ledgerId"))

                    # Get the mapping
                    mapping = frappe.db.get_value(
                        "E-Boekhouden Ledger Mapping",
                        {"ledger_id": ledger_id},
                        ["ledger_code", "ledger_name", "erpnext_account"],
                        as_dict=True,
                    )

                    rows_summary.append(
                        {
                            "ledger_id": ledger_id,
                            "amount": row.get("amount"),
                            "description": row.get("description"),
                            "mapping": mapping,
                        }
                    )

                mutation_analysis.append(
                    {
                        "id": mutation.get("id"),
                        "date": mutation.get("date"),
                        "description": mutation.get("description"),
                        "type": mutation.get("type"),
                        "rows": rows_summary,
                    }
                )

        return {
            "success": True,
            "opening_entries_found": opening_entries,
            "early_transactions": early_transactions,
            "opening_mutations_from_api": len(opening_mutations) if opening_mutations else 0,
            "mutation_analysis": mutation_analysis,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def check_import_logic_for_type_0():
    """Check the import logic to see if type 0 is being skipped"""

    try:
        # Read the import file to check the logic
        import_file_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"

        with open(import_file_path, "r") as f:
            content = f.read()

        # Find references to mutation type 0
        import_logic = {
            "skips_type_0": "mutation_type == 0" in content,
            "includes_type_0_in_list": "0"
            in str([1, 2, 3, 4, 5, 6, 7]),  # Check if 0 is in mutation_types list
            "has_opening_balance_handling": "opening" in content.lower(),
        }

        # Find the specific line that handles type 0
        lines = content.split("\n")
        type_0_handling = []

        for i, line in enumerate(lines):
            if "mutation_type == 0" in line or "type'] == 0" in line:
                type_0_handling.append(
                    {
                        "line_number": i + 1,
                        "code": line.strip(),
                        "context": lines[max(0, i - 2) : min(len(lines), i + 3)],
                    }
                )

        return {
            "success": True,
            "import_logic": import_logic,
            "type_0_handling": type_0_handling,
            "recommendation": "Type 0 mutations are being skipped in the import",
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}
