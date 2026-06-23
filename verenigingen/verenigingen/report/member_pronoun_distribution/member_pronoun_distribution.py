# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe


def execute(filters=None):
    columns = [
        {"fieldname": "pronouns", "label": "Pronouns", "fieldtype": "Data", "width": 150},
        {"fieldname": "count", "label": "Count", "fieldtype": "Int", "width": 100},
    ]

    data = []

    # Group on the *computed* pronoun bucket, not the raw column: members with an
    # empty-string pronoun and members with a NULL pronoun both render as
    # 'Unknown', but grouping on the raw column produced two separate 'Unknown'
    # rows (one for '' and one for NULL). Grouping on the CASE expression
    # collapses them into a single combined count.
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
    GROUP BY
      CASE
        WHEN pronouns IS NULL OR pronouns = '' OR TRIM(pronouns) = ''
        THEN 'Unknown'
        ELSE pronouns
      END
    ORDER BY count DESC
    """

    data = frappe.db.sql(query, as_dict=True)

    return columns, data
