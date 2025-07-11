import json

import frappe


@frappe.whitelist()
def check_invoice_customer_data():
    """Check how customer data is stored in Sales Invoices"""

    print("=== Sales Invoice with mutation 7495 ===")
    # Get Sales Invoice with mutation 7495
    invoice_7495 = frappe.db.sql(
        """
        SELECT name, customer, customer_name, eboekhouden_invoice_number, eboekhouden_mutation_nr, remarks
        FROM `tabSales Invoice`
        WHERE eboekhouden_mutation_nr = '7495'
    """,
        as_dict=True,
    )

    if invoice_7495:
        print(json.dumps(invoice_7495[0], indent=2))

        # Get items for this invoice
        print("\n=== Sales Invoice Items ===")
        items = frappe.db.sql(
            """
            SELECT item_code, item_name, description
            FROM `tabSales Invoice Item`
            WHERE parent = %s
        """,
            invoice_7495[0]["name"],
            as_dict=True,
        )

        for item in items:
            print(json.dumps(item, indent=2))

    # Check if we have any Payment Entries linked to this mutation
    print("\n=== Related Payment Entries ===")
    payments = frappe.db.sql(
        """
        SELECT name, party, party_name, title, remarks, reference_no
        FROM `tabPayment Entry`
        WHERE reference_no = '7495'
        OR eboekhouden_mutation_nr = '7495'
    """,
        as_dict=True,
    )

    for payment in payments:
        print(json.dumps(payment, indent=2))

    # Check Journal Entries
    print("\n=== Related Journal Entries ===")
    journals = frappe.db.sql(
        """
        SELECT name, title, user_remark, eboekhouden_mutation_nr
        FROM `tabJournal Entry`
        WHERE eboekhouden_mutation_nr = '7495'
    """,
        as_dict=True,
    )

    for journal in journals:
        print(json.dumps(journal, indent=2))

    return {
        "invoice_data": invoice_7495[0] if invoice_7495 else None,
        "items": items if invoice_7495 else [],
        "payments": payments,
        "journals": journals,
    }


@frappe.whitelist()
def search_for_customer_name():
    """Search for any reference to 'Maxime Boven' in the system"""

    results = {}

    # Check Customers
    customers = frappe.db.sql(
        """
        SELECT name, customer_name, eboekhouden_relation_code
        FROM `tabCustomer`
        WHERE customer_name LIKE '%Maxime%'
        OR customer_name LIKE '%Boven%'
    """,
        as_dict=True,
    )

    results["customers"] = customers

    # Check Payment Entries
    payments = frappe.db.sql(
        """
        SELECT name, party, party_name, title, remarks, reference_no, eboekhouden_mutation_nr
        FROM `tabPayment Entry`
        WHERE party_name LIKE '%Maxime%'
        OR title LIKE '%Maxime%'
        OR remarks LIKE '%Maxime%'
    """,
        as_dict=True,
    )

    results["payments"] = payments

    # Check Journal Entries
    journals = frappe.db.sql(
        """
        SELECT name, title, user_remark, eboekhouden_mutation_nr
        FROM `tabJournal Entry`
        WHERE title LIKE '%Maxime%'
        OR user_remark LIKE '%Maxime%'
    """,
        as_dict=True,
    )

    results["journals"] = journals

    return results
