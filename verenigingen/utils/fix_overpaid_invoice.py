import frappe


@frappe.whitelist()
def fix_overpaid_invoice_vf_stickers_24():
    """Fix the overpaid invoice by cancelling the incorrect €297 payment entry"""
    results = []

    # The €297 payment should not have been allocated to the invoice
    # It's a correction/reversal that should reduce the payment, not add to it

    results.append("=== Fixing Overpaid Invoice vf-stickers-24 ===")

    # Find the incorrect payment entry
    pe_name = "ACC-PAY-2025-64784"  # The €297 entry

    try:
        pe = frappe.get_doc("Payment Entry", pe_name)
        results.append(f"\nFound Payment Entry: {pe.name}")
        results.append(f"  Amount: {pe.paid_amount}")
        results.append(f"  Mutation: {pe.eboekhouden_mutation_nr}")
        results.append(f"  Status: {pe.docstatus}")

        if pe.docstatus == 1:
            # Cancel the incorrect payment entry
            results.append("\nCancelling incorrect payment entry...")
            pe.cancel()
            results.append("  Payment Entry cancelled successfully")

            # Check the invoice status after cancellation
            invoice = frappe.get_doc("Sales Invoice", "ACC-SINV-2025-26713")
            invoice.reload()
            results.append("\nInvoice status after cancellation:")
            results.append(f"  Outstanding Amount: {invoice.outstanding_amount}")
            results.append(f"  Status: {invoice.status}")

            # The invoice should now show outstanding of 0 instead of -18
            # because only the €300 payment remains, of which €18 was allocated

        else:
            results.append("\nPayment Entry is not submitted, cannot cancel")

    except Exception as e:
        results.append(f"\nError: {str(e)}")
        import traceback

        results.append(traceback.format_exc())

    return "\n".join(results)


@frappe.whitelist()
def check_eboekhouden_mutation_6208():
    """Check what E-Boekhouden mutation 6208 actually represents"""
    results = []

    results.append("=== Checking E-Boekhouden Mutation 6208 ===")

    # First check if it's a Journal Entry
    je = frappe.db.get_value(
        "Journal Entry",
        {"eboekhouden_mutation_nr": "6208"},
        ["name", "posting_date", "user_remark", "total_debit"],
        as_dict=True,
    )

    if je:
        results.append(f"\nFound as Journal Entry: {je.name}")
        results.append(f"  Date: {je.posting_date}")
        results.append(f"  Amount: {je.total_debit}")
        results.append(f"  Remark: {je.user_remark}")

        # Get the accounts involved
        accounts = frappe.db.sql(
            """
            SELECT account, debit, credit
            FROM `tabJournal Entry Account`
            WHERE parent = %s
        """,
            je.name,
            as_dict=True,
        )

        results.append("\n  Accounts:")
        for acc in accounts:
            if acc.debit:
                results.append(f"    DEBIT  {acc.account}: {acc.debit}")
            if acc.credit:
                results.append(f"    CREDIT {acc.account}: {acc.credit}")

    # Also check Payment Entry
    pe = frappe.db.get_value(
        "Payment Entry",
        {"eboekhouden_mutation_nr": "6208"},
        ["name", "payment_type", "paid_amount", "received_amount"],
        as_dict=True,
    )

    if pe:
        results.append(f"\nFound as Payment Entry: {pe.name}")
        results.append(f"  Type: {pe.payment_type}")
        results.append(f"  Amount: {pe.paid_amount or pe.received_amount}")

    return "\n".join(results)
