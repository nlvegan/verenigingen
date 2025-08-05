from decimal import Decimal

import frappe


@frappe.whitelist()
def investigate_overpaid_invoice(invoice_number="vf-stickers-24"):
    """Investigate why invoice shows negative outstanding amount"""
    results = []

    results.append(f"=== Investigating Invoice {invoice_number} ===")

    # Find the invoice
    invoice_name = frappe.db.get_value(
        "Sales Invoice", {"eboekhouden_invoice_number": invoice_number}, "name"
    )

    if not invoice_name:
        results.append(f"Invoice with eboekhouden_invoice_number {invoice_number} not found")
        return "\n".join(results)

    invoice = frappe.get_doc("Sales Invoice", invoice_name)

    results.append("\nInvoice Details:")
    results.append(f"  Name: {invoice.name}")
    results.append(f"  Customer: {invoice.customer}")
    results.append(f"  Grand Total: {invoice.grand_total}")
    results.append(f"  Outstanding Amount: {invoice.outstanding_amount}")
    results.append(f"  Status: {invoice.status}")

    # Check all payment entries linked to this invoice
    results.append("\n=== Payment Entries ===")
    payment_refs = frappe.db.sql(
        """
        SELECT
            per.parent as payment_entry,
            per.allocated_amount,
            pe.posting_date,
            pe.paid_amount,
            pe.eboekhouden_mutation_nr,
            pe.docstatus,
            pe.remarks
        FROM `tabPayment Entry Reference` per
        JOIN `tabPayment Entry` pe ON pe.name = per.parent
        WHERE per.reference_name = %s
        ORDER BY pe.posting_date
    """,
        invoice.name,
        as_dict=True,
    )

    total_allocated = Decimal("0")
    for ref in payment_refs:
        results.append(f"\nPayment Entry: {ref.payment_entry}")
        results.append(f"  Date: {ref.posting_date}")
        results.append(f"  Paid Amount: {ref.paid_amount}")
        results.append(f"  Allocated to Invoice: {ref.allocated_amount}")
        results.append(f"  Mutation Nr: {ref.eboekhouden_mutation_nr}")
        results.append(
            f"  Status: {'Submitted' if ref.docstatus == 1 else 'Draft' if ref.docstatus == 0 else 'Cancelled'}"
        )
        if ref.remarks:
            results.append(f"  Remarks: {ref.remarks[:100]}")
        if ref.docstatus == 1:  # Only count submitted entries
            total_allocated += Decimal(str(ref.allocated_amount))

    results.append(f"\nTotal Allocated: {total_allocated}")
    results.append(f"Expected Outstanding: {Decimal(str(invoice.grand_total)) - total_allocated}")

    # Check GL entries for receivables account
    results.append("\n=== GL Entries for Receivables ===")
    gl_entries = frappe.db.sql(
        """
        SELECT
            gle.posting_date,
            gle.voucher_type,
            gle.voucher_no,
            gle.debit,
            gle.credit,
            gle.against,
            gle.remarks
        FROM `tabGL Entry` gle
        WHERE gle.party = %s
        AND gle.account = %s
        AND (gle.against_voucher = %s OR gle.voucher_no = %s)
        AND gle.is_cancelled = 0
        ORDER BY gle.posting_date, gle.creation
    """,
        (invoice.customer, invoice.debit_to, invoice.name, invoice.name),
        as_dict=True,
    )

    running_balance = Decimal("0")
    for gle in gl_entries:
        amount = Decimal(str(gle.debit or 0)) - Decimal(str(gle.credit or 0))
        running_balance += amount
        results.append(
            f"  {gle.posting_date} {gle.voucher_type} {gle.voucher_no}: {'+' if amount > 0 else ''}{amount} (Balance: {running_balance})"
        )

    results.append(f"\nFinal GL Balance: {running_balance}")

    # Check for any journal entries that might affect this
    results.append("\n=== Related Journal Entries ===")
    je_entries = frappe.db.sql(
        """
        SELECT DISTINCT
            je.name,
            je.posting_date,
            je.total_debit,
            je.user_remark
        FROM `tabJournal Entry` je
        JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
        WHERE (jea.reference_name = %s OR je.user_remark LIKE %s)
        AND je.docstatus = 1
        ORDER BY je.posting_date
    """,
        (invoice.name, f"%{invoice_number}%"),
        as_dict=True,
    )

    for je in je_entries:
        results.append(f"  {je.name} ({je.posting_date}): {je.total_debit}")
        if je.user_remark:
            results.append(f"    Remark: {je.user_remark[:100]}")

    # Try to manually recalculate outstanding
    results.append("\n=== Manual Recalculation ===")
    try:
        results.append(f"Before update_outstanding_amt: {invoice.outstanding_amount}")

        # Force recalculation
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import update_outstanding_amt

        update_outstanding_amt(invoice.name)

        # Check again
        invoice.reload()
        results.append(f"After update_outstanding_amt: {invoice.outstanding_amount}")

    except Exception as e:
        results.append(f"Error during recalculation: {e}")

    return "\n".join(results)
