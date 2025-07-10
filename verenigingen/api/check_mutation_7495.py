import json

import frappe
from frappe import _


@frappe.whitelist()
def check_mutation_7495():
    """Check mutation 7495 details"""

    print("=== CHECKING MUTATION 7495 ===")

    # Check the Sales Invoice
    sinv = frappe.db.sql(
        """
        SELECT name, customer, customer_name, title, eboekhouden_mutation_nr,
               eboekhouden_invoice_number, posting_date
        FROM `tabSales Invoice`
        WHERE eboekhouden_mutation_nr = '7495'
    """,
        as_dict=True,
    )

    if sinv:
        inv = sinv[0]
        print(f"Sales Invoice: {inv.name}")
        print(f"Customer: {inv.customer}")
        print(f"Invoice Number: {inv.eboekhouden_invoice_number}")
        print(f"Date: {inv.posting_date}")

        # Check all custom fields for relation data
        custom_fields = frappe.db.sql(
            """
            SELECT fieldname, label
            FROM `tabCustom Field`
            WHERE dt = 'Sales Invoice'
            AND fieldname LIKE '%relation%'
        """,
            as_dict=True,
        )

        print("\nChecking for relation fields:")
        for field in custom_fields:
            value = frappe.db.get_value("Sales Invoice", inv.name, field.fieldname)
            if value:
                print(f"  {field.fieldname}: {value}")

    # Check if we have mutation cache data
    print("\n=== CHECKING EBOEKHOUDEN CACHE ===")
    cache_data = frappe.db.sql(
        """
        SELECT name, mutation_data, mutation_type, relation_id
        FROM `tabEBoekhouden REST Mutation Cache`
        WHERE mutation_id = '7495'
    """,
        as_dict=True,
    )

    if cache_data:
        for cache in cache_data:
            print(f"Cache record: {cache.name}")
            print(f"Relation ID from cache: {cache.relation_id}")

            if cache.mutation_data:
                try:
                    data = json.loads(cache.mutation_data)
                    print("Parsed mutation data:")
                    print(f"  relationId: {data.get('relationId')}")
                    print(f"  description: {data.get('description', '')[:100]}...")
                    print(f"  invoiceNumber: {data.get('invoiceNumber')}")

                    # Check rows for customer info
                    if data.get("rows"):
                        print(f"  Rows: {len(data.get('rows', []))}")
                        for i, row in enumerate(data.get("rows", [])[:2]):
                            print(f"    Row {i}: {row.get('description', '')[:80]}...")
                except:
                    print("  Could not parse mutation_data")

    # Check for relation 1495
    print("\n=== CHECKING RELATION 1495 ===")

    # Check if Customer exists with relation code 1495
    customer_1495 = frappe.db.sql(
        """
        SELECT name, customer_name, eboekhouden_relation_code
        FROM `tabCustomer`
        WHERE eboekhouden_relation_code = '1495'
    """,
        as_dict=True,
    )

    if customer_1495:
        print("Found customer with relation code 1495:")
        for cust in customer_1495:
            print(f"  - {cust.name}: {cust.customer_name}")
    else:
        print("No customer found with relation code 1495")

        # Check if this relation exists in any mutation
        other_mutations = frappe.db.sql(
            """
            SELECT mutation_id, mutation_type
            FROM `tabEBoekhouden REST Mutation Cache`
            WHERE relation_id = '1495'
            LIMIT 5
        """,
            as_dict=True,
        )

        if other_mutations:
            print(f"\nFound {len(other_mutations)} mutations with relation 1495:")
            for mut in other_mutations:
                print(f"  - Mutation {mut.mutation_id} (type {mut.mutation_type})")

    return True
