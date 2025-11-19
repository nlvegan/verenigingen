#!/usr/bin/env python3
"""
Clarify what the invoice numbers 646, 673, 670 represent
"""

import frappe


def analyze_invoice_numbers():
    """Analyze what the numbers 646, 673, 670 represent"""

    print("=== Analyzing Invoice Numbers 646, 673, 670 ===")

    numbers_to_check = ["646", "673", "670"]

    for num in numbers_to_check:
        print(f"\n--- Analyzing Number: {num} ---")

        # Check as Sales Invoice name
        si_by_name = frappe.db.get_value(
            "Sales Invoice",
            {"name": num},
            ["name", "customer", "grand_total", "eboekhouden_mutation_nr", "eboekhouden_invoice_number"],
            as_dict=True,
        )
        if si_by_name:
            print(f"✓ Found as Sales Invoice name: {si_by_name}")
        else:
            print("❌ Not found as Sales Invoice name")

        # Check as Sales Invoice eboekhouden_invoice_number
        si_by_eb_invoice = frappe.db.get_value(
            "Sales Invoice",
            {"eboekhouden_invoice_number": num},
            ["name", "customer", "grand_total", "eboekhouden_mutation_nr", "eboekhouden_invoice_number"],
            as_dict=True,
        )
        if si_by_eb_invoice:
            print(f"✓ Found as Sales Invoice eboekhouden_invoice_number: {si_by_eb_invoice}")
        else:
            print("❌ Not found as Sales Invoice eboekhouden_invoice_number")

        # Check as Sales Invoice eboekhouden_mutation_nr
        si_by_mutation = frappe.db.get_value(
            "Sales Invoice",
            {"eboekhouden_mutation_nr": num},
            ["name", "customer", "grand_total", "eboekhouden_mutation_nr", "eboekhouden_invoice_number"],
            as_dict=True,
        )
        if si_by_mutation:
            print(f"✓ Found as Sales Invoice eboekhouden_mutation_nr: {si_by_mutation}")
        else:
            print("❌ Not found as Sales Invoice eboekhouden_mutation_nr")

        # Check Purchase Invoices similarly
        pi_by_name = frappe.db.get_value(
            "Purchase Invoice",
            {"name": num},
            ["name", "supplier", "grand_total", "eboekhouden_mutation_nr", "eboekhouden_invoice_number"],
            as_dict=True,
        )
        if pi_by_name:
            print(f"✓ Found as Purchase Invoice name: {pi_by_name}")
        else:
            print("❌ Not found as Purchase Invoice name")

        pi_by_eb_invoice = frappe.db.get_value(
            "Purchase Invoice",
            {"eboekhouden_invoice_number": num},
            ["name", "supplier", "grand_total", "eboekhouden_mutation_nr", "eboekhouden_invoice_number"],
            as_dict=True,
        )
        if pi_by_eb_invoice:
            print(f"✓ Found as Purchase Invoice eboekhouden_invoice_number: {pi_by_eb_invoice}")
        else:
            print("❌ Not found as Purchase Invoice eboekhouden_invoice_number")

        pi_by_mutation = frappe.db.get_value(
            "Purchase Invoice",
            {"eboekhouden_mutation_nr": num},
            ["name", "supplier", "grand_total", "eboekhouden_mutation_nr", "eboekhouden_invoice_number"],
            as_dict=True,
        )
        if pi_by_mutation:
            print(f"✓ Found as Purchase Invoice eboekhouden_mutation_nr: {pi_by_mutation}")
        else:
            print("❌ Not found as Purchase Invoice eboekhouden_mutation_nr")


def examine_payment_mutation_structure():
    """Examine how payment mutations reference invoices"""

    print("\n=== Examining Payment Mutation Structure ===")

    # Look at the failing payment mutations 880, 881, 882
    failing_mutations = ["880", "881", "882"]

    for mutation_nr in failing_mutations:
        print(f"\n--- Payment Entry for Mutation {mutation_nr} ---")

        pe = frappe.db.get_value(
            "Payment Entry",
            {"eboekhouden_mutation_nr": mutation_nr},
            ["name", "party", "paid_amount", "reference_no", "eboekhouden_mutation_nr"],
            as_dict=True,
        )

        if pe:
            print(f"Payment Entry: {pe.name}")
            print(f"Party: {pe.party}, Amount: {pe.paid_amount}")
            print(f"Reference: {pe.reference_no}")
            print(f"E-Boekhouden Mutation Nr: {pe.eboekhouden_mutation_nr}")

            # Check payment references (invoice allocations)
            pe_doc = frappe.get_doc("Payment Entry", pe.name)

            if hasattr(pe_doc, "references") and pe_doc.references:
                print(f"Invoice References ({len(pe_doc.references)}):")
                for ref in pe_doc.references:
                    print(
                        f"  - {ref.reference_doctype}: {ref.reference_name} (Amount: {ref.allocated_amount})"
                    )
            else:
                print("No invoice references (unallocated payment)")
        else:
            print(f"❌ Payment Entry not found for mutation {mutation_nr}")


def check_eboekhouden_cache_data():
    """Check the original E-Boekhouden mutation data"""

    print("\n=== Checking E-Boekhouden Cache Data ===")

    # Check cached mutation data for the failing mutations
    cache_data = frappe.db.sql(
        """
        SELECT mutation_id, mutation_data
        FROM `tabEBoekhouden REST Mutation Cache`
        WHERE mutation_id IN ('880', '881', '882')
        LIMIT 10
    """,
        as_dict=True,
    )

    if cache_data:
        import json

        for cache in cache_data:
            print(f"\n--- Cached Mutation {cache.mutation_id} ---")
            try:
                data = json.loads(cache.mutation_data)
                print(f"Mutation ID: {data.get('id')}")
                print(f"Type: {data.get('type')}")
                print(f"Invoice Number: {data.get('invoiceNumber')}")
                print(f"Description: {data.get('description', 'N/A')[:100]}...")
                print(f"Amount: {data.get('amount')}")

                if data.get("rows"):
                    print(f"Rows: {len(data.get('rows'))}")
                    for i, row in enumerate(data.get("rows", [])[:2]):  # Show first 2 rows
                        print(f"  Row {i+1}: Amount {row.get('amount')}, Ledger {row.get('ledgerId')}")

            except Exception as e:
                print(f"Error parsing mutation data: {str(e)}")
    else:
        print("❌ No cached mutation data found for 880, 881, 882")


def show_invoice_lookup_logic():
    """Show how the system looks up invoices"""

    print("\n=== Invoice Lookup Logic ===")

    print("The payment handler looks for invoices in this order:")
    print("1. Parse invoice numbers from mutation.invoiceNumber field")
    print("2. Look for Sales Invoice with matching name")
    print("3. Look for Purchase Invoice with matching name")
    print("4. If not found, create unallocated payment")

    print("\nFrom the error logs:")
    print("- 'No invoice found for number: 646' means no Sales/Purchase Invoice with name='646'")
    print("- This is checking ERPNext document names, not E-Boekhouden mutation numbers")
    print("- The numbers 646, 673, 670 are likely E-Boekhouden invoice numbers that don't exist in ERPNext")


if __name__ == "__main__":
    try:
        frappe.init()
        frappe.connect()

        analyze_invoice_numbers()
        examine_payment_mutation_structure()
        check_eboekhouden_cache_data()
        show_invoice_lookup_logic()

    except Exception as e:
        print(f"Analysis error: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()
