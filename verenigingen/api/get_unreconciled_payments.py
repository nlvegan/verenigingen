"""
Get unreconciled payments from E-Boekhouden migration
"""

import frappe

from verenigingen.utils.security.api_security_framework import critical_api, high_security_api, standard_api


@high_security_api()
@frappe.whitelist()
def get_unreconciled_payments():
    """Get all unreconciled payment entries created during migration"""

    # Get unreconciled customer payments
    customer_payments = frappe.db.sql(
        """
        SELECT
            pe.name,
            pe.party,
            pe.party_type,
            pe.posting_date,
            pe.paid_amount,
            pe.reference_no as mutation_nr,
            pe.remarks
        FROM `tabPayment Entry` pe
        WHERE
            pe.party_type = 'Customer'
            AND pe.docstatus = 1
            AND pe.unallocated_amount > 0
            AND pe.remarks LIKE '%E-Boekhouden%Invoice Not Found%'
        ORDER BY pe.posting_date DESC
    """,
        as_dict=True,
    )

    # Get unreconciled supplier payments
    supplier_payments = frappe.db.sql(
        """
        SELECT
            pe.name,
            pe.party,
            pe.party_type,
            pe.posting_date,
            pe.paid_amount,
            pe.reference_no as mutation_nr,
            pe.remarks
        FROM `tabPayment Entry` pe
        WHERE
            pe.party_type = 'Supplier'
            AND pe.docstatus = 1
            AND pe.unallocated_amount > 0
            AND pe.remarks LIKE '%E-Boekhouden%Invoice Not Found%'
        ORDER BY pe.posting_date DESC
    """,
        as_dict=True,
    )

    # Get journal entries for unmatched payments
    journal_entries = frappe.db.sql(
        """
        SELECT
            je.name,
            je.posting_date,
            je.total_debit as amount,
            je.eboekhouden_mutation_nr as mutation_nr,
            je.eboekhouden_invoice_number as invoice_no,
            je.title,
            je.user_remark
        FROM `tabJournal Entry` je
        WHERE
            je.docstatus = 1
            AND (je.title LIKE '%Payment - Invoice Not Found%'
                 OR je.user_remark LIKE '%Invoice Not Found%')
        ORDER BY je.posting_date DESC
    """,
        as_dict=True,
    )

    return {
        "customer_payments": {
            "count": len(customer_payments),
            "total_amount": sum(p.paid_amount for p in customer_payments),
            "entries": customer_payments[:50],  # Limit to 50 for display
        },
        "supplier_payments": {
            "count": len(supplier_payments),
            "total_amount": sum(p.paid_amount for p in supplier_payments),
            "entries": supplier_payments[:50],
        },
        "journal_entries": {
            "count": len(journal_entries),
            "total_amount": sum(j.amount for j in journal_entries),
            "entries": journal_entries[:50],
        },
        "total_unreconciled": len(customer_payments) + len(supplier_payments) + len(journal_entries),
    }


@critical_api()
@frappe.whitelist()
def reconcile_payment_with_invoice(payment_entry, invoice_type, invoice_name):
    """Reconcile an unreconciled payment with an invoice"""

    try:
        pe = frappe.get_doc("Payment Entry", payment_entry)

        if pe.docstatus != 1:
            return {"success": False, "error": "Payment Entry is not submitted"}

        if pe.unallocated_amount <= 0:
            return {"success": False, "error": "Payment is already fully allocated"}

        # Get the invoice
        invoice = frappe.get_doc(invoice_type, invoice_name)

        if invoice.docstatus != 1:
            return {"success": False, "error": "Invoice is not submitted"}

        if invoice.outstanding_amount <= 0:
            return {"success": False, "error": "Invoice is already fully paid"}

        # Create a new payment entry for reconciliation
        new_pe = frappe.new_doc("Payment Entry")
        new_pe.payment_type = pe.payment_type
        new_pe.company = pe.company
        new_pe.posting_date = pe.posting_date
        new_pe.party_type = pe.party_type
        new_pe.party = pe.party

        # Set amounts
        amount_to_allocate = min(pe.unallocated_amount, invoice.outstanding_amount)
        new_pe.paid_amount = amount_to_allocate
        new_pe.received_amount = amount_to_allocate

        # Link to invoice
        new_pe.append(
            "references",
            {
                "reference_doctype": invoice_type,
                "reference_name": invoice_name,
                "allocated_amount": amount_to_allocate,
            },
        )

        # Set accounts
        if pe.payment_type == "Receive":
            new_pe.paid_to = pe.paid_to
            new_pe.paid_from = invoice.debit_to
        else:
            new_pe.paid_from = pe.paid_from
            new_pe.paid_to = invoice.credit_to

        new_pe.reference_no = f"Reconciliation for {pe.name}"
        new_pe.remarks = f"Reconciliation of unallocated payment {pe.name} with {invoice_type} {invoice_name}"

        new_pe.insert()
        new_pe.submit()

        # Cancel the original unallocated payment
        pe.cancel()

        return {
            "success": True,
            "message": f"Successfully reconciled payment with {invoice_type} {invoice_name}",
            "new_payment_entry": new_pe.name,
        }

    except Exception as e:
        frappe.log_error(f"Payment reconciliation error: {str(e)}", "Payment Reconciliation")
        return {"success": False, "error": str(e)}
