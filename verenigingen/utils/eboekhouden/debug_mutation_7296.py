import frappe

from .eboekhouden_rest_iterator import EBoekhoudenRESTIterator


@frappe.whitelist()
def debug_mutation_7296():
    """Debug mutation 7296 to understand the issue"""

    iterator = EBoekhoudenRESTIterator()

    # Try to fetch mutation 7296
    try:
        mutation_detail = iterator.fetch_mutation_detail(7296)

        if mutation_detail:
            return {
                "success": True,
                "mutation_detail": mutation_detail,
                "id": mutation_detail.get("id"),
                "type": mutation_detail.get("type"),
                "invoiceNumber": mutation_detail.get("invoiceNumber"),
                "amount": mutation_detail.get("amount"),
                "relationId": mutation_detail.get("relationId"),
                "description": mutation_detail.get("description"),
                "date": mutation_detail.get("date"),
            }
        else:
            return {"success": False, "error": "Could not fetch mutation detail"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def check_mutations_with_invoice_20250601():
    """Check all mutations with invoice number 20250601"""

    # Check Sales Invoices
    sales_invoices = frappe.db.get_all(
        "Sales Invoice",
        filters={"eboekhouden_invoice_number": "20250601"},
        fields=[
            "name",
            "eboekhouden_mutation_nr",
            "eboekhouden_invoice_number",
            "customer",
            "grand_total",
            "posting_date",
        ],
    )

    # Check Purchase Invoices
    purchase_invoices = frappe.db.get_all(
        "Purchase Invoice",
        filters={"eboekhouden_invoice_number": "20250601"},
        fields=[
            "name",
            "eboekhouden_mutation_nr",
            "eboekhouden_invoice_number",
            "supplier",
            "grand_total",
            "posting_date",
        ],
    )

    return {
        "sales_invoices": sales_invoices,
        "purchase_invoices": purchase_invoices,
        "total_count": len(sales_invoices) + len(purchase_invoices),
    }
