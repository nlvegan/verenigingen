import frappe


def main():
    # Remove unique constraint from Purchase Invoice field
    frappe.db.sql(
        """
        UPDATE `tabCustom Field`
        SET unique = 0
        WHERE fieldname = 'eboekhouden_invoice_number'
        AND dt = 'Purchase Invoice'
    """
    )

    # Remove unique constraint from Sales Invoice field
    frappe.db.sql(
        """
        UPDATE `tabCustom Field`
        SET unique = 0
        WHERE fieldname = 'eboekhouden_invoice_number'
        AND dt = 'Sales Invoice'
    """
    )

    # Commit changes
    frappe.db.commit()

    print("✅ Successfully removed unique constraints from eboekhouden_invoice_number fields")

    # Verify the changes
    results = frappe.db.sql(
        """
        SELECT dt, fieldname, unique
        FROM `tabCustom Field`
        WHERE fieldname = 'eboekhouden_invoice_number'
    """,
        as_dict=True,
    )

    for result in results:
        print(f"   {result.dt}: {result.fieldname} unique = {result.unique}")


if __name__ == "__main__":
    main()
