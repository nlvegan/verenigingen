"""Test single mutation import"""

import frappe


@frappe.whitelist()
def get_sample_mutation():
    """Get a sample mutation ID for testing"""
    # Get a recent sales invoice mutation
    mutation = frappe.db.sql(
        """
        SELECT DISTINCT eboekhouden_mutation_nr
        FROM `tabSales Invoice`
        WHERE eboekhouden_mutation_nr != ''
        ORDER BY posting_date DESC
        LIMIT 1
    """,
        as_dict=True,
    )

    if mutation:
        return {"mutation_id": mutation[0].eboekhouden_mutation_nr}

    # Try purchase invoice
    mutation = frappe.db.sql(
        """
        SELECT DISTINCT eboekhouden_mutation_nr
        FROM `tabPurchase Invoice`
        WHERE eboekhouden_mutation_nr != ''
        ORDER BY posting_date DESC
        LIMIT 1
    """,
        as_dict=True,
    )

    if mutation:
        return {"mutation_id": mutation[0].eboekhouden_mutation_nr}

    return {"error": "No E-Boekhouden mutations found"}
