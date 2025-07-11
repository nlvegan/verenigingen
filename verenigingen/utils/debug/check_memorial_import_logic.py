#!/usr/bin/env python3
"""
Check memorial booking import logic issue
"""

import json

import frappe


@frappe.whitelist()
def check_mutation_6353():
    """Check the specific mutation that's causing the issue"""

    # Get the eBoekhouden mutation data
    mutation_data = frappe.db.get_value(
        "EBoekhouden REST Mutation Cache", {"mutation_id": "6353"}, "mutation_data"
    )

    if not mutation_data:
        print("Mutation 6353 not found in cache")
        return {"error": "Not found"}

    data = json.loads(mutation_data)

    print("eBoekhouden Mutation 6353:")
    print(f"Type: {data.get('type')} (Memorial booking)")
    print(f"Date: {data.get('date')}")
    print(f"Description: {data.get('description')}")
    print(f"Amount: {data.get('amount')}")
    print("\nLines:")

    for line in data.get("lines", []):
        ledger_id = line.get("ledgerId")
        amount = line.get("amount")

        # Get account mapping
        account = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping",
            {"ledger_id": str(ledger_id)},
            ["erpnext_account", "ledger_name"],
            as_dict=True,
        )

        if account:
            print(f"  Ledger {ledger_id} ({account.ledger_name}): €{amount:,.2f}")
            print(f"    → Maps to: {account.erpnext_account}")
        else:
            print(f"  Ledger {ledger_id}: €{amount:,.2f} (NO MAPPING)")

    print("\n" + "=" * 70)
    print("ANALYSIS:")
    print("=" * 70)

    # Check how this was imported
    je = frappe.db.get_value("Journal Entry", {"eboekhouden_mutation_nr": "6353"}, "name")

    if je:
        print(f"\nImported as Journal Entry: {je}")

        # Get the journal entry details
        je_doc = frappe.get_doc("Journal Entry", je)
        print(f"Title: {je_doc.title}")
        print("\nJournal Entry Lines:")

        for acc in je_doc.accounts:
            if acc.debit_in_account_currency > 0:
                print(f"  DEBIT: {acc.account} - €{acc.debit_in_account_currency:,.2f}")
            if acc.credit_in_account_currency > 0:
                print(f"  CREDIT: {acc.account} - €{acc.credit_in_account_currency:,.2f}")

    return {"mutation_data": data, "journal_entry": je}


@frappe.whitelist()
def check_memorial_import_logic_in_code():
    """Check how memorial bookings are imported in the code"""

    print("Checking memorial booking import logic...")

    # Read the import logic
    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    with open(file_path, "r") as f:
        content = f.read()

    # Find the memorial booking handling section
    import_start = content.find("# Type 7 (memorial booking)")
    if import_start == -1:
        import_start = content.find("mutation_type == 7")

    if import_start != -1:
        # Get the next 50 lines
        lines = content[import_start:].split("\n")[:50]

        print("Memorial booking (Type 7) import logic:")
        print("=" * 70)
        for i, line in enumerate(lines):
            if "debit" in line.lower() or "credit" in line.lower() or "amount" in line:
                print(f"{i}: {line}")

    return {"found": import_start != -1}


if __name__ == "__main__":
    print("Check memorial import logic")
