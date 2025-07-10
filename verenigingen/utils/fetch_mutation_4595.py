#!/usr/bin/env python3
"""
Fetch raw eBoekhouden mutation 4595 data from REST API
"""

import json

import frappe


@frappe.whitelist()
def fetch_mutation_4595():
    """Fetch mutation 4595 from eBoekhouden REST API"""

    try:
        from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

        api = EBoekhoudenAPI()

        # Fetch specific mutation 4595
        print("Fetching mutation 4595 from eBoekhouden REST API...")
        result = api.make_request("v1/mutation/4595")

        if result and result.get("success") and result.get("status_code") == 200:
            mutation_data = json.loads(result.get("data", "{}"))

            print("Raw mutation data:")
            print("=" * 60)
            print(json.dumps(mutation_data, indent=2))
            print("=" * 60)

            # Extract key information
            print("\nKey Information:")
            print(f"ID: {mutation_data.get('id')}")
            print(f"Type: {mutation_data.get('type')} (7 = Memorial booking)")
            print(f"Date: {mutation_data.get('date')}")
            print(f"Description: {mutation_data.get('description')}")
            print(f"Amount: {mutation_data.get('amount')}")
            print(f"Main Ledger ID: {mutation_data.get('ledgerId')}")
            print(f"Relation ID: {mutation_data.get('relationId')}")
            print(f"Invoice Number: {mutation_data.get('invoiceNumber')}")

            # Extract rows (tegenrekeningen)
            rows = mutation_data.get("rows", [])
            print(f"\nRows ({len(rows)} entries):")
            for i, row in enumerate(rows, 1):
                print(f"  Row {i}:")
                print(f"    Ledger ID: {row.get('ledgerId')}")
                print(f"    Amount: {row.get('amount')}")
                print(f"    Description: {row.get('description', '')}")

            # Check ledger mappings
            print("\nLedger Mappings:")
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
                        "  Main Ledger {main_ledger_id}: {main_mapping.ledger_name} → {main_mapping.erpnext_account}"
                    )
                else:
                    print(f"  Main Ledger {main_ledger_id}: No mapping found")

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
                            "  Row Ledger {row_ledger_id}: {row_mapping.ledger_name} → {row_mapping.erpnext_account}"
                        )
                    else:
                        print(f"  Row Ledger {row_ledger_id}: No mapping found")

            # Analyze what the current logic would do
            print("\nAnalysis with current fix:")
            print("=" * 40)

            for row in rows:
                row_amount = row.get("amount")
                row_ledger_id = row.get("ledgerId")

                if row_amount > 0:
                    print(
                        f"Row {row_ledger_id}: Positive amount {row_amount} → becomes CREDIT (money TO this account)"
                    )
                elif row_amount < 0:
                    print(
                        "Row {row_ledger_id}: Negative amount {row_amount} → becomes DEBIT (money FROM this account)"
                    )
                else:
                    print(f"Row {row_ledger_id}: Zero amount {row_amount} → skipped")

            # Main ledger gets balancing entry
            print(f"Main Ledger {main_ledger_id}: Gets balancing entry")

            return {
                "success": True,
                "mutation_data": mutation_data,
                "main_ledger_id": main_ledger_id,
                "rows": rows,
            }
        else:
            print(f"API Error: {result}")
            return {"success": False, "error": "API call failed: {result}"}

    except Exception as e:
        print(f"Error fetching mutation: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    fetch_mutation_4595()
