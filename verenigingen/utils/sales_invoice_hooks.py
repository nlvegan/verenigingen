"""
Sales Invoice hooks to automatically populate member field
"""

import frappe


def set_member_from_customer(doc, method):
    """
    Automatically set member field on Sales Invoice from Customer
    Called on before_save and before_validate
    """
    if doc.customer and not doc.get("member"):
        # Fetch member from customer
        member = frappe.db.get_value("Customer", doc.customer, "member")
        if member:
            doc.member = member
