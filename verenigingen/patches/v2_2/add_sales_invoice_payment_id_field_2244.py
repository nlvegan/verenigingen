# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def execute():
    """Add Sales Invoice.payment_id (#2244): the Mollie payment id of the invoice's open online
    payment, so a repeat checkout reuses it and the webhook can match the payment to the invoice."""
    if frappe.get_meta("Sales Invoice").has_field("payment_id"):
        return
    create_custom_field(
        "Sales Invoice",
        {
            "fieldname": "payment_id",
            "label": "Mollie Payment ID",
            "fieldtype": "Data",
            "read_only": 1,
            "no_copy": 1,
            "allow_on_submit": 1,
            "print_hide": 1,
            "insert_after": "remarks",
            "description": "Mollie payment id of the open online payment for this invoice (#2244).",
        },
    )
    frappe.clear_cache(doctype="Sales Invoice")
