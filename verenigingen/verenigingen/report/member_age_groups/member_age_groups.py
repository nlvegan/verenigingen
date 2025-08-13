# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe


def execute(filters=None):
    columns = [
        {"fieldname": "age_group", "label": "Age Group", "fieldtype": "Data", "width": 120},
        {"fieldname": "count", "label": "Count", "fieldtype": "Int", "width": 100},
    ]

    data = []

    query = """
    SELECT
      CASE
        WHEN age IS NULL THEN 'Unknown'
        WHEN age < 18 THEN 'Under 18'
        WHEN age BETWEEN 18 AND 22 THEN '18-22'
        WHEN age BETWEEN 23 AND 27 THEN '23-27'
        WHEN age BETWEEN 28 AND 32 THEN '28-32'
        WHEN age BETWEEN 33 AND 37 THEN '33-37'
        WHEN age BETWEEN 38 AND 42 THEN '38-42'
        WHEN age BETWEEN 43 AND 47 THEN '43-47'
        WHEN age BETWEEN 48 AND 52 THEN '48-52'
        WHEN age BETWEEN 53 AND 57 THEN '53-57'
        WHEN age BETWEEN 58 AND 62 THEN '58-62'
        WHEN age BETWEEN 63 AND 67 THEN '63-67'
        WHEN age >= 68 THEN '68+'
      END as age_group,
      COUNT(*) as count
    FROM `tabMember`
    WHERE status IN ('Active', 'Pending')
    GROUP BY age_group
    ORDER BY
      CASE age_group
        WHEN 'Under 18' THEN 1
        WHEN '18-22' THEN 2
        WHEN '23-27' THEN 3
        WHEN '28-32' THEN 4
        WHEN '33-37' THEN 5
        WHEN '38-42' THEN 6
        WHEN '43-47' THEN 7
        WHEN '48-52' THEN 8
        WHEN '53-57' THEN 9
        WHEN '58-62' THEN 10
        WHEN '63-67' THEN 11
        WHEN '68+' THEN 12
        ELSE 13
      END
    """

    data = frappe.db.sql(query, as_dict=True)

    return columns, data
