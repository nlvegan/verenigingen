#!/usr/bin/env python3
"""
Fetch raw eBoekhouden mutation 6316 data and compare with journal entry
"""

import json

import frappe


@frappe.whitelist()
def fetch_and_compare_mutation_6316():
    """Fetch mutation 6316 from eBoekhouden REST API and compare with journal entry"""

    try:
        from verenigingen.utils.eboekhouden.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI()

        # Fetch specific mutation 6316
        print("Fetching mutation 6316 from eBoekhouden REST API...")
        result = api.make_request("v1/mutation/6316")

        if result and result.get("success") and result.get("status_code") == 200:
            mutation_data = json.loads(result.get("data", "{}"))

            print("RAW EBOEKHOUDEN DATA:")
            print("=" * 60)
            print(json.dumps(mutation_data, indent=2))
            print("=" * 60)

            # Extract key information
            print("\nEBOEKHOUDEN MUTATION 6316:")
            print("-" * 40)
            print(f"ID: {mutation_data.get('id')}")
            print(f"Type: {mutation_data.get('type')} (7 = Memorial booking)")
            print(f"Date: {mutation_data.get('date')}")
            print(f"Description: {mutation_data.get('description')}")
            print(f"Main Ledger ID: {mutation_data.get('ledgerId')}")
            print(f"Relation ID: {mutation_data.get('relationId')}")

            # Extract rows (tegenrekeningen)
            rows = mutation_data.get("rows", [])
            print(f"\nRows ({len(rows)} entries):")
            for i, row in enumerate(rows, 1):
                print(f"  Row {i}:")
                print(f"    Ledger ID: {row.get('ledgerId')}")
                print(f"    Amount: {row.get('amount')}")
                print(f"    Description: {row.get('description', '')}")

            # Check ledger mappings
            print("\nLEDGER MAPPINGS:")
            print("-" * 40)
            main_ledger_id = mutation_data.get("ledgerId")
            if main_ledger_id:
                main_mapping = frappe.db.get_value(
                    "E-Boekhouden Ledger Mapping",
                    {"ledger_id": str(main_ledger_id)},
                    ["ledger_name", "erpnext_account"],
                    as_dict=True,
                )
                if main_mapping:
                    print(
                        "Main Ledger {main_ledger_id}: {main_mapping.ledger_name} → {main_mapping.erpnext_account}"
                    )
                else:
                    print(f"Main Ledger {main_ledger_id}: No mapping found")

            for row in rows:
                row_ledger_id = row.get("ledgerId")
                if row_ledger_id:
                    row_mapping = frappe.db.get_value(
                        "E-Boekhouden Ledger Mapping",
                        {"ledger_id": str(row_ledger_id)},
                        ["ledger_name", "erpnext_account"],
                        as_dict=True,
                    )
                    if row_mapping:
                        print(
                            "Row Ledger {row_ledger_id}: {row_mapping.ledger_name} → {row_mapping.erpnext_account}"
                        )
                    else:
                        print(f"Row Ledger {row_ledger_id}: No mapping found")

            # Now get the journal entry data
            print("\n" + "=" * 60)
            print("COMPARING WITH JOURNAL ENTRY ACC-JV-2025-86423:")
            print("=" * 60)

            je_data = frappe.db.sql(
                """
                SELECT
                    je.name,
                    je.posting_date,
                    je.title,
                    je.total_debit,
                    je.total_credit,
                    je.eboekhouden_mutation_nr,
                    je.eboekhouden_main_ledger_id,
                    jea.account,
                    jea.debit_in_account_currency,
                    jea.credit_in_account_currency,
                    jea.user_remark
                FROM `tabJournal Entry` je
                JOIN `tabJournal Entry Account` jea ON je.name = jea.parent
                WHERE je.name = 'ACC-JV-2025-86423'
                ORDER BY jea.idx
            """,
                as_dict=True,
            )

            if je_data:
                je = je_data[0]
                print(f"Journal Entry: {je.name}")
                print(f"Posting Date: {je.posting_date}")
                print(f"Title: {je.title}")
                print(f"Total Debit: {je.total_debit}")
                print(f"Total Credit: {je.total_credit}")
                print(f"eBoekhouden Mutation Nr: {je.eboekhouden_mutation_nr}")
                print(f"eBoekhouden Main Ledger ID: {je.eboekhouden_main_ledger_id}")

                print(f"\nJournal Entry Accounts ({len(je_data)} entries):")
                for i, acc in enumerate(je_data, 1):
                    print(f"  Entry {i}:")
                    print(f"    Account: {acc.account}")
                    print(f"    Debit: {acc.debit_in_account_currency}")
                    print(f"    Credit: {acc.credit_in_account_currency}")
                    print(f"    Remark: {acc.user_remark}")

                # Analysis
                print("\n" + "=" * 60)
                print("ANALYSIS:")
                print("=" * 60)

                print(f"eBoekhouden has {len(rows)} row(s), Journal Entry has {len(je_data)} account entries")

                if len(je_data) > len(rows) + 1:  # +1 for main ledger
                    print("⚠️  WARNING: Journal entry has more accounts than expected!")
                    print(f"Expected: {len(rows) + 1} (rows + main ledger)")
                    print(f"Actual: {len(je_data)}")

                # Check if accounts match
                print("\nAccount Matching:")
                for row in rows:
                    row_ledger_id = row.get("ledgerId")
                    row_amount = row.get("amount")

                    # Find corresponding journal entry line
                    matching_accounts = [
                        acc for acc in je_data if row_ledger_id and str(row_ledger_id) in acc.account
                    ]
                    if matching_accounts:
                        for acc in matching_accounts:
                            print(f"Row Ledger {row_ledger_id} (amount: {row_amount}) → {acc.account}")
                            print(
                                "  JE: Debit {acc.debit_in_account_currency}, Credit {acc.credit_in_account_currency}"
                            )
                    else:
                        print(f"Row Ledger {row_ledger_id} (amount: {row_amount}) → NOT FOUND in JE")

            else:
                print("❌ Journal Entry ACC-JV-2025-86423 not found!")

            return {"success": True, "mutation_data": mutation_data, "journal_entry_data": je_data}
        else:
            print(f"API Error: {result}")
            return {"success": False, "error": "API call failed: {result}"}

    except Exception as e:
        print(f"Error fetching mutation: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    fetch_and_compare_mutation_6316()
