"""
Check payment implementation details
"""

import frappe


@frappe.whitelist()
def check_payment_implementation():
    """Check how payments are implemented"""

    results = []

    # Check Payment Entries
    results.append("=== Payment Entry Analysis ===")

    # Sample payment entries
    sample_payments = frappe.db.sql(
        """
        SELECT
            pe.name,
            pe.payment_type,
            pe.party_type,
            pe.party,
            pe.paid_from,
            pe.paid_to,
            pe.eboekhouden_mutation_nr,
            pe.reference_no,
            pe.paid_amount,
            pe.received_amount,
            (SELECT COUNT(*) FROM `tabPayment Entry Reference` WHERE parent = pe.name) as ref_count
        FROM `tabPayment Entry` pe
        WHERE pe.eboekhouden_mutation_nr IS NOT NULL
        AND pe.docstatus = 1
        ORDER BY pe.creation DESC
        LIMIT 10
    """,
        as_dict=True,
    )

    for payment in sample_payments:
        results.append(f"\nPayment: {payment['name']}")
        results.append(f"  Type: {payment['payment_type']}")
        results.append(f"  Party: {payment['party_type']} - {payment['party']}")
        results.append(f"  From Account: {payment['paid_from']}")
        results.append(f"  To Account: {payment['paid_to']}")
        results.append(f"  Reference Count: {payment['ref_count']}")
        results.append(f"  E-Boekhouden Mutation: {payment['eboekhouden_mutation_nr']}")
        results.append(f"  Reference No: {payment['reference_no']}")

        # Check if party exists
        if payment["party"]:
            if payment["party_type"] == "Customer":
                exists = frappe.db.exists("Customer", payment["party"])
            else:
                exists = frappe.db.exists("Supplier", payment["party"])
            results.append(f"  Party exists: {exists}")

    # Check how bank accounts are being used
    results.append("\n=== Bank Account Usage ===")
    bank_usage = frappe.db.sql(
        """
        SELECT
            CASE
                WHEN payment_type = 'Receive' THEN paid_to
                ELSE paid_from
            END as bank_account,
            COUNT(*) as count
        FROM `tabPayment Entry`
        WHERE eboekhouden_mutation_nr IS NOT NULL
        AND docstatus = 1
        GROUP BY bank_account
        ORDER BY count DESC
        LIMIT 10
    """,
        as_dict=True,
    )

    for usage in bank_usage:
        results.append(f"  {usage['bank_account']}: {usage['count']} payments")

    # Check if there are payment references
    results.append("\n=== Payment References ===")
    ref_stats = frappe.db.sql(
        """
        SELECT
            per.reference_doctype,
            COUNT(*) as count,
            SUM(per.allocated_amount) as total_allocated
        FROM `tabPayment Entry Reference` per
        JOIN `tabPayment Entry` pe ON pe.name = per.parent
        WHERE pe.eboekhouden_mutation_nr IS NOT NULL
        AND pe.docstatus = 1
        GROUP BY per.reference_doctype
    """,
        as_dict=True,
    )

    for stat in ref_stats:
        results.append(
            f"  {stat['reference_doctype']}: {stat['count']} references, €{stat['total_allocated'] or 0:,.2f} allocated"
        )

    # Check a specific payment with references
    results.append("\n=== Sample Payment with References ===")
    payment_with_ref = frappe.db.sql(
        """
        SELECT
            pe.name,
            pe.eboekhouden_mutation_nr,
            per.reference_doctype,
            per.reference_name,
            per.allocated_amount
        FROM `tabPayment Entry` pe
        JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
        WHERE pe.eboekhouden_mutation_nr IS NOT NULL
        AND pe.docstatus = 1
        LIMIT 5
    """,
        as_dict=True,
    )

    for ref in payment_with_ref:
        results.append(f"  Payment {ref['name']} (Mutation {ref['eboekhouden_mutation_nr']})")
        results.append(
            f"    -> {ref['reference_doctype']} {ref['reference_name']}: €{ref['allocated_amount']}"
        )

    return "\n".join(results)


if __name__ == "__main__":
    print(
        "Run via: bench --site dev.veganisme.net execute check_payment_implementation.check_payment_implementation"
    )
