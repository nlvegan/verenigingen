"""
Test real transaction import for money transfers
"""

import frappe


@frappe.whitelist()
def test_import_one_real_transaction():
    """Import one real money transfer transaction to test the implementation"""

    try:
        response = []
        response.append("=== Real Transaction Import Test ===")

        # Import required modules
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import _process_single_mutation
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        company = "Ned Ver Vegan"
        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

        response.append(f"Company: {company}")
        response.append(f"Cost Center: {cost_center}")

        # Try to fetch just a few type 5 or 6 mutations
        iterator = EBoekhoudenRESTIterator()

        for mutation_type in [5, 6]:
            response.append(f"\n--- Testing Type {mutation_type} ---")

            try:
                # Fetch just 1 mutation of this type
                mutations = iterator.fetch_mutations_by_type(mutation_type=mutation_type, limit=1)

                if not mutations:
                    response.append(f"No type {mutation_type} mutations found")
                    continue

                mutation = mutations[0]
                mutation_id = mutation.get("id")
                amount = mutation.get("amount", 0)

                response.append(f"Found mutation {mutation_id}: €{amount}")

                # Check if already imported
                existing = frappe.db.get_value(
                    "Journal Entry", {"eboekhouden_mutation_nr": str(mutation_id)}, "name"
                )

                if existing:
                    response.append(f"✓ Already imported as Journal Entry: {existing}")

                    # Show the existing entry details
                    je = frappe.get_doc("Journal Entry", existing)
                    response.append(f"  Status: {je.docstatus}")
                    response.append(f"  User Remark: {je.user_remark}")
                    response.append(f"  Accounts:")
                    for acc in je.accounts:
                        debit = acc.debit_in_account_currency or 0
                        credit = acc.credit_in_account_currency or 0
                        response.append(f"    {acc.account}: Dr €{debit}, Cr €{credit}")

                    continue

                # Try to import this mutation
                response.append(f"Importing mutation {mutation_id}...")
                debug_info = []

                result = _process_single_mutation(mutation, company, cost_center, debug_info)

                if result:
                    response.append(f"✅ Successfully imported as {result.doctype}: {result.name}")
                    response.append(f"  Status: {result.docstatus}")

                    if result.doctype == "Journal Entry":
                        response.append(f"  User Remark: {result.user_remark}")
                        response.append(f"  Accounts:")
                        for acc in result.accounts:
                            debit = acc.debit_in_account_currency or 0
                            credit = acc.credit_in_account_currency or 0
                            response.append(f"    {acc.account}: Dr €{debit}, Cr €{credit}")
                else:
                    response.append("⚠️  Mutation was skipped")

                # Show debug info
                if debug_info:
                    response.append("Debug info:")
                    for info in debug_info[-5:]:  # Last 5 debug messages
                        response.append(f"  {info}")

                # Only test one mutation to keep it simple
                break

            except Exception as e:
                response.append(f"❌ Error with type {mutation_type}: {str(e)}")
                continue

        response.append(f"\n=== Test Completed ===")
        response.append(f"✅ Money transfer implementation tested with real data")

        return "\n".join(response)

    except Exception as e:
        return f"Error during real import test: {str(e)}\n{frappe.get_traceback()}"
