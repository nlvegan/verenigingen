import frappe

from .eboekhouden_rest_full_migration import _check_if_invoice_number_exists


@frappe.whitelist()
def test_duplicate_detection():
    """Test the duplicate detection function"""

    # Test existing invoice number
    existing = _check_if_invoice_number_exists("20250601", "Sales Invoice")

    # Test non-existing invoice number
    non_existing = _check_if_invoice_number_exists("99999999", "Sales Invoice")

    # Test None/empty
    none_result = _check_if_invoice_number_exists(None, "Sales Invoice")
    empty_result = _check_if_invoice_number_exists("", "Sales Invoice")

    return {
        "existing": existing,
        "non_existing": non_existing,
        "none_result": none_result,
        "empty_result": empty_result,
    }


@frappe.whitelist()
def check_invoice_20250601():
    """Check what exists for invoice number 20250601"""

    # Check Sales Invoice
    si = frappe.db.get_value(
        "Sales Invoice",
        {"eboekhouden_invoice_number": "20250601"},
        ["name", "eboekhouden_mutation_nr", "customer", "grand_total"],
        as_dict=True,
    )

    # Check Purchase Invoice
    pi = frappe.db.get_value(
        "Purchase Invoice",
        {"eboekhouden_invoice_number": "20250601"},
        ["name", "eboekhouden_mutation_nr", "supplier", "grand_total"],
        as_dict=True,
    )

    return {"sales_invoice": si, "purchase_invoice": pi, "invoice_number": "20250601"}
