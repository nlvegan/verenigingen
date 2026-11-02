"""The applications waiting for review: one read path for every review surface (#1765).

The review page, the pending report, the chapter dashboard and its number card all list
`Pending Review` Membership Application Submissions through here. Every read goes through
`frappe.get_list`, so the MAS permission query (`get_application_permission_query`) scopes the
rows to the caller's seats; nothing here filters by hand, and none of it is `get_all`.
"""

import frappe
from frappe.utils import add_days, cint, getdate, today

SUBMISSION = "Membership Application Submission"
PENDING_REVIEW = "Pending Review"

_FIELDS = [
    "name",
    "application_id",
    "applicant_name",
    "email",
    "membership_type",
    "chapter",
    "confirmed_on",
    "source",
]


def pending_review_applications(chapter=None, days_overdue=None, chapters=None, oldest_first=False):
    """Pending Review applications the session user may read, newest first (`oldest_first` reverses).

    `chapter` narrows to one chapter ("Unassigned" for none); `chapters` narrows to any of a list
    (the dashboard's scope); `days_overdue` keeps those confirmed more than that many days ago.
    A caller who may not read applications at all gets the PermissionError, never [] (#1765 ruling AD):
    a refusal must not read as "nothing pending".
    """
    filters = _filters(chapter, days_overdue, chapters)
    if filters is None:
        return []
    rows = frappe.get_list(
        SUBMISSION,
        filters=filters,
        fields=_FIELDS,
        order_by="confirmed_on asc" if oldest_first else "confirmed_on desc",
        limit_page_length=0,
    )
    return [_as_row(row) for row in rows]


def count_pending_review_applications(chapters=None):
    """How many Pending Review applications the session user may read, in `chapters` (all when None).

    One COUNT through `frappe.get_list`, so the permission query applies and a refusal raises.
    """
    filters = _filters(None, None, chapters)
    if filters is None:
        return 0
    rows = frappe.get_list(SUBMISSION, filters=filters, fields=[{"COUNT": "name", "as": "total"}])
    return rows[0].total if rows else 0


def _filters(chapter, days_overdue, chapters):
    """The list filters, or None when the requested scope is empty (an empty chapter list)."""
    filters = {"status": PENDING_REVIEW}
    if chapter == "Unassigned":
        filters["chapter"] = ["is", "not set"]
    elif chapter:
        filters["chapter"] = chapter
    elif chapters is not None:
        if not chapters:
            return None
        filters["chapter"] = ["in", list(chapters)]
    if cint(days_overdue):
        filters["confirmed_on"] = ["<", add_days(today(), -cint(days_overdue))]
    return filters


def _as_row(row):
    row["application_date"] = row.pop("confirmed_on")
    row["days_pending"] = (
        (getdate(today()) - getdate(row["application_date"])).days if row["application_date"] else 0
    )
    return row
