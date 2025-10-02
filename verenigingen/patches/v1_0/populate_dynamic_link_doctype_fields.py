"""
Data migration: Populate doctype fields for Dynamic Links in payment history child tables.

After converting Link fields to Dynamic Link fields, we need to populate the corresponding
*_doctype fields for existing records so that the Dynamic Links work correctly.
"""

import frappe


def execute():
    """Populate doctype fields for existing Dynamic Link records"""

    # Update Member Payment History records
    frappe.db.sql(
        """
        UPDATE `tabMember Payment History`
        SET
            invoice_doctype = 'Sales Invoice',
            payment_entry_doctype = CASE
                WHEN payment_entry IS NOT NULL AND payment_entry != ''
                THEN 'Payment Entry'
                ELSE NULL
            END,
            sepa_mandate_doctype = CASE
                WHEN sepa_mandate IS NOT NULL AND sepa_mandate != ''
                THEN 'SEPA Mandate'
                ELSE NULL
            END
        WHERE parenttype = 'Member'
    """
    )

    # Update Member SEPA Mandate Link records
    frappe.db.sql(
        """
        UPDATE `tabMember SEPA Mandate Link`
        SET sepa_mandate_doctype = 'SEPA Mandate'
        WHERE sepa_mandate IS NOT NULL AND sepa_mandate != ''
    """
    )

    # Update Volunteer Expense records
    frappe.db.sql(
        """
        UPDATE `tabVolunteer Expense`
        SET expense_claim_doctype = 'Expense Claim'
        WHERE expense_claim_id IS NOT NULL AND expense_claim_id != ''
    """
    )

    # Update Member Fee Change History records
    frappe.db.sql(
        """
        UPDATE `tabMember Fee Change History`
        SET
            dues_schedule_doctype = 'Membership Dues Schedule',
            amendment_request_doctype = CASE
                WHEN amendment_request IS NOT NULL AND amendment_request != ''
                THEN 'Contribution Amendment Request'
                ELSE NULL
            END
        WHERE parenttype = 'Member'
    """
    )

    frappe.db.commit()

    print("✅ Populated Dynamic Link doctype fields for existing records")
