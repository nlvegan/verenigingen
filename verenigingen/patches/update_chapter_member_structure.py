#!/usr/bin/env python3
"""
Migration patch to update Chapter Member structure
- Remove member_name field (replaced by title_field)
- Set default join dates for existing members
"""

import frappe
from frappe.utils import today


def execute():
    """Execute the migration"""

    # Update existing chapter members that don't have join dates
    frappe.db.sql(
        """
        UPDATE `tabChapter Member`
        SET chapter_join_date = %s
        WHERE chapter_join_date IS NULL OR chapter_join_date = ''
    """,
        (today(),),
    )

    frappe.db.commit()

    print("Updated Chapter Member structure - set default join dates for existing members")
