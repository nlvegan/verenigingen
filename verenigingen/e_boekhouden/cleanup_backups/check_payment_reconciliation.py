"""
Check how payments are reconciled with invoices
"""

import frappe


@frappe.whitelist()
def check_payment_reconciliation():
    """Check how payments are reconciled"""

    results = []

    # Check Sales Invoices
    results.append("=== Sales Invoice Status ===")
    si_stats = frappe.db.sql(
        """
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN outstanding_amount = 0 THEN 1 END) as paid,
            COUNT(CASE WHEN outstanding_amount > 0 THEN 1 END) as unpaid
        FROM `tabSales Invoice`
        WHERE eboekhouden_mutation_nr IS NOT NULL
        AND docstatus = 1
    """,
        as_dict=True,
    )[0]

    results.append(f"Total Sales Invoices from E-Boekhouden: {si_stats['total']}")
    results.append(f"Paid: {si_stats['paid']} ({si_stats['paid'] / si_stats['total'] * 100:.1f}%)")
    results.append(f"Unpaid: {si_stats['unpaid']}")

    # Check Purchase Invoices
    results.append("\n=== Purchase Invoice Status ===")
    pi_stats = frappe.db.sql(
        """
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN outstanding_amount = 0 THEN 1 END) as paid,
            COUNT(CASE WHEN outstanding_amount > 0 THEN 1 END) as unpaid
        FROM `tabPurchase Invoice`
        WHERE eboekhouden_mutation_nr IS NOT NULL
        AND docstatus = 1
    """,
        as_dict=True,
    )[0]

    results.append(f"Total Purchase Invoices from E-Boekhouden: {pi_stats['total']}")
    results.append(f"Paid: {pi_stats['paid']} ({pi_stats['paid'] / pi_stats['total'] * 100:.1f}%)")
    results.append(f"Unpaid: {pi_stats['unpaid']}")

    # Check if Payment Entries have references
    results.append("\n=== Payment Entry Analysis ===")
    pe_stats = frappe.db.sql(
        """
        SELECT
            payment_type,
            COUNT(*) as total,
            COUNT(CASE WHEN (SELECT COUNT(*) FROM `tabPayment Entry Reference` WHERE parent = pe.name) > 0 THEN 1 END) as with_references
        FROM `tabPayment Entry` pe
        WHERE eboekhouden_mutation_nr IS NOT NULL
        AND docstatus = 1
        GROUP BY payment_type
    """,
        as_dict=True,
    )

    for stat in pe_stats:
        results.append(f"\n{stat['payment_type']} Payments:")
        results.append(f"  Total: {stat['total']}")
        results.append(f"  With invoice references: {stat['with_references']}")
        results.append(f"  Without references: {stat['total'] - stat['with_references']}")

    # Sample some paid invoices to see how they were paid
    results.append("\n=== Sample Paid Sales Invoices ===")
    paid_invoices = frappe.db.sql(
        """
        SELECT
            si.name,
            si.eboekhouden_invoice_number,
            si.grand_total,
            si.posting_date,
            GROUP_CONCAT(pe.name) as payment_entries
        FROM `tabSales Invoice` si
        LEFT JOIN `tabPayment Entry Reference` per ON per.reference_name = si.name AND per.reference_doctype = 'Sales Invoice'
        LEFT JOIN `tabPayment Entry` pe ON pe.name = per.parent
        WHERE si.outstanding_amount = 0
        AND si.eboekhouden_mutation_nr IS NOT NULL
        AND si.docstatus = 1
        GROUP BY si.name
        LIMIT 5
    """,
        as_dict=True,
    )

    for inv in paid_invoices:
        results.append(f"\nInvoice: {inv['name']}")
        results.append(f"  E-Boekhouden Number: {inv['eboekhouden_invoice_number']}")
        results.append(f"  Amount: €{inv['grand_total']}")
        results.append(f"  Payment Entries: {inv['payment_entries'] or 'None found!'}")

    # Check if there's some other mechanism
    results.append("\n=== GL Entry Analysis for Paid Invoice ===")
    if paid_invoices:
        sample_invoice = paid_invoices[0]["name"]
        gl_entries = frappe.db.sql(
            """
            SELECT
                voucher_type,
                voucher_no,
                debit,
                credit,
                account,
                posting_date
            FROM `tabGL Entry`
            WHERE against_voucher = %s
            AND is_cancelled = 0
            ORDER BY posting_date
        """,
            sample_invoice,
            as_dict=True,
        )

        results.append(f"GL Entries against {sample_invoice}:")
        for gle in gl_entries:
            results.append(
                f"  {gle['voucher_type']} {gle['voucher_no']}: Dr {gle['debit']} Cr {gle['credit']}"
            )

    return "\n".join(results)


if __name__ == "__main__":
    print(
        "Run via: bench --site dev.veganisme.net execute check_payment_reconciliation.check_payment_reconciliation"
    )
