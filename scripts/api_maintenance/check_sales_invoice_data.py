import frappe
from frappe import _


@frappe.whitelist()
def check_sales_invoice_data():
    """Check Sales Invoice data to understand customer extraction"""

    print("=== CHECKING SALES INVOICE DATA ===")

    # Check specific mutation 7495
    sinv_7495 = frappe.db.sql(
        """
        SELECT name, customer, customer_name, title, eboekhouden_mutation_nr
        FROM `tabSales Invoice`
        WHERE eboekhouden_mutation_nr = '7495'
    """,
        as_dict=True,
    )

    if sinv_7495:
        print("\nMutation 7495 found:")
        for inv in sinv_7495:
            print(f"  Invoice: {inv.name}")
            print(f"  Customer: {inv.customer}")
            print(f"  Customer Name: {inv.customer_name}")
            print(f"  Title: {inv.title}")

            # Check items for this invoice
            items = frappe.db.sql(
                """
                SELECT item_code, item_name, description
                FROM `tabSales Invoice Item`
                WHERE parent = %s
            """,
                inv.name,
                as_dict=True,
            )

            print("  Items:")
            for item in items:
                print(f"    - {item.item_code}: {item.item_name}")
                print(f"      Description: {item.description[:100] if item.description else 'N/A'}")

    # Check a few more Sales Invoices with E-Boekhouden Import
    print("\n=== OTHER SALES INVOICES ===")
    other_sinvs = frappe.db.sql(
        """
        SELECT si.name, si.customer, si.customer_name, si.title, si.eboekhouden_mutation_nr
        FROM `tabSales Invoice` si
        WHERE si.customer = 'E-Boekhouden Import'
        AND si.eboekhouden_mutation_nr IS NOT NULL
        LIMIT 5
    """,
        as_dict=True,
    )

    for sinv in other_sinvs:
        print(f"\nInvoice: {sinv.name} (Mutation: {sinv.eboekhouden_mutation_nr})")

        # Get first item to check description
        first_item = frappe.db.sql(
            """
            SELECT description
            FROM `tabSales Invoice Item`
            WHERE parent = %s
            LIMIT 1
        """,
            sinv.name,
            as_dict=True,
        )

        if first_item and len(first_item) > 0 and hasattr(first_item[0], 'description') and first_item[0].description:
            print(f"  First item description: {first_item[0].description[:150]}")

    # Check if we're storing original mutation data anywhere
    print("\n=== CHECKING FOR STORED MUTATION DATA ===")

    # Check if there's a custom field storing original data
    custom_fields = frappe.db.sql(
        """
        SELECT fieldname, label
        FROM `tabCustom Field`
        WHERE dt = 'Sales Invoice'
        AND fieldname LIKE '%eboekhouden%'
    """,
        as_dict=True,
    )

    print("Custom fields on Sales Invoice:")
    for field in custom_fields:
        print(f"  - {field.fieldname}: {field.label}")

    return True
