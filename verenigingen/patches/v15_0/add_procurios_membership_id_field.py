# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def execute():
    """Add Membership.procurios_membership_id — idempotency key for the
    Procurios membership import (stores the Procurios membership `Id`)."""
    if frappe.get_meta("Membership").get_field("procurios_membership_id"):
        return
    create_custom_field(
        "Membership",
        {
            "fieldname": "procurios_membership_id",
            "label": "Procurios Membership ID",
            "fieldtype": "Data",
            "read_only": 1,
            "no_copy": 1,
            "search_index": 1,
            "insert_after": "amended_from",
            "description": "Procurios membership Id this record was imported from (idempotency key).",
        },
    )
    frappe.clear_cache(doctype="Membership")
