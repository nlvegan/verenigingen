# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe


def execute(filters=None):
    columns = [
        {"fieldname": "pronouns", "label": "Pronouns", "fieldtype": "Data", "width": 150},
        {"fieldname": "count", "label": "Count", "fieldtype": "Int", "width": 100},
    ]

    data = []

    query = """
    SELECT
      CASE
        WHEN pronouns IS NULL OR pronouns = '' OR TRIM(pronouns) = ''
        THEN 'Unknown'
        ELSE pronouns
      END as pronouns,
      COUNT(*) as count
    FROM `tabMember`
    WHERE status IN ('Active', 'Dues Outstanding')
    GROUP BY pronouns
    ORDER BY count DESC
    """

    data = frappe.db.sql(query, as_dict=True)

    return columns, data
