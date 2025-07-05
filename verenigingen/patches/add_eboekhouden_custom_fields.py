"""
Add custom fields to store E-Boekhouden category and group information
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    """Add E-Boekhouden tracking fields to Account doctype"""

    custom_fields = {
        "Account": [
            {
                "fieldname": "eboekhouden_section",
                "label": "E-Boekhouden",
                "fieldtype": "Section Break",
                "insert_after": "disabled",
                "collapsible": 1,
            },
            {
                "fieldname": "eboekhouden_category",
                "label": "E-Boekhouden Category",
                "fieldtype": "Data",
                "insert_after": "eboekhouden_section",
                "read_only": 1,
                "description": "Original category from E-Boekhouden (e.g., DEB, CRED, FIN)",
            },
            {
                "fieldname": "eboekhouden_group",
                "label": "E-Boekhouden Group",
                "fieldtype": "Data",
                "insert_after": "eboekhouden_category",
                "read_only": 1,
                "description": "Original group code from E-Boekhouden",
            },
            {
                "fieldname": "eboekhouden_group_name",
                "label": "E-Boekhouden Group Name",
                "fieldtype": "Data",
                "insert_after": "eboekhouden_group",
                "read_only": 1,
                "description": "Inferred group name",
            },
        ]
    }

    create_custom_fields(custom_fields)

    # Clear cache
    frappe.clear_cache()
