"""
Test script to examine payment mutation data from E-Boekhouden
"""

import json

import frappe


@frappe.whitelist()
def examine_payment_mutations():
    """Examine payment mutations to understand available data"""

    results = []

    # Get some payment mutations
    payment_mutations = frappe.db.sql(
        """
        SELECT
            name,
            mutation_id,
            mutation_data
        FROM `tabEBoekhouden REST Mutation Cache`
        WHERE mutation_type IN (3, 4, 5, 6)
        LIMIT 5
    """,
        as_dict=True,
    )

    results.append(f"Found {len(payment_mutations)} payment mutations in cache")

    for mut in payment_mutations:
        try:
            data = json.loads(mut.mutation_data)
            results.append(f"\n=== Mutation {mut.mutation_id} (Type {data.get('type')}) ===")

            # Show all fields available
            for key, value in data.items():
                if key not in ["rows", "Regels"]:  # Skip arrays for now
                    results.append(f"  {key}: {value}")

            # Check ledgerId specifically
            if "ledgerId" in data:
                results.append(f"  ** LedgerId present: {data['ledgerId']}")

                # Check if this ledger is mapped
                mapping = frappe.db.get_value(
                    "E-Boekhouden Ledger Mapping",
                    {"ledger_id": str(data["ledgerId"])},
                    ["erpnext_account", "account_type"],
                    as_dict=True,
                )

                if mapping:
                    results.append(f"     Mapped to: {mapping['erpnext_account']}")
                    results.append(f"     Type: {mapping['account_type']}")
                else:
                    results.append(f"     No mapping found for ledger {data['ledgerId']}")

            # Check rows if present
            if "rows" in data and data["rows"]:
                results.append(f"  Has {len(data['rows'])} row entries")
                for i, row in enumerate(data["rows"][:2]):  # First 2 rows
                    results.append(f"    Row {i}: ledgerId={row.get('ledgerId')}, amount={row.get('amount')}")

            # Check Regels if present
            if "Regels" in data and data["Regels"]:
                results.append(f"  Has {len(data['Regels'])} Regel entries")

        except Exception as e:
            results.append(f"Error parsing mutation {mut.mutation_id}: {str(e)}")

    # Also check how bank accounts are mapped
    results.append("\n=== Bank Account Mappings ===")
    bank_mappings = frappe.db.sql(
        """
        SELECT
            ledger_id,
            erpnext_account,
            account_type
        FROM `tabE-Boekhouden Ledger Mapping`
        WHERE account_type IN ('Bank', 'Cash')
        OR erpnext_account LIKE '%bank%'
        OR erpnext_account LIKE '%kas%'
        LIMIT 10
    """,
        as_dict=True,
    )

    for mapping in bank_mappings:
        results.append(
            f"  Ledger {mapping['ledger_id']} -> {mapping['erpnext_account']} ({mapping['account_type']})"
        )

    return "\n".join(results)


if __name__ == "__main__":
    print(
        "Run via: bench --site dev.veganisme.net execute verenigingen.test_payment_data.examine_payment_mutations"
    )
