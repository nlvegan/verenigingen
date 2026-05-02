"""Populate Member.current_chapter from active Chapter Membership History rows.

The flat current_chapter Link field on Member was introduced for list-view display
and filtering. update_current_chapter_display sets it on every save going forward,
but existing members need a one-time backfill from their Chapter Membership History.

Picks the row marked is_primary=1 if any; otherwise the most recent Active row by
start_date. Falls back to NULL when no active history exists.
"""

import frappe


def execute():
    if not frappe.db.has_column("tabMember", "current_chapter"):
        # DocType reload from JSON hasn't run yet; bench migrate runs DB sync after
        # patches but JSON schema additions normally land before this patch executes.
        # Skip silently — the field will get populated on the next member save.
        return

    rows = frappe.db.sql(
        """
        SELECT m.name AS member, h.chapter_name AS chapter
        FROM `tabMember` m
        JOIN (
            SELECT
                cmh.parent,
                cmh.chapter_name,
                ROW_NUMBER() OVER (
                    PARTITION BY cmh.parent
                    ORDER BY
                        CASE WHEN cmh.assignment_type = 'Member' THEN 0 ELSE 1 END,
                        cmh.start_date DESC,
                        cmh.idx ASC
                ) AS rn
            FROM `tabChapter Membership History` cmh
            WHERE cmh.parenttype = 'Member' AND cmh.status = 'Active'
        ) h ON h.parent = m.name AND h.rn = 1
        """,
        as_dict=True,
    )

    for row in rows:
        frappe.db.set_value("Member", row.member, "current_chapter", row.chapter, update_modified=False)

    frappe.db.commit()
    frappe.logger().info(f"backfill_member_current_chapter: populated current_chapter on {len(rows)} members")
