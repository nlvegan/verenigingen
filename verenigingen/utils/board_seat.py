"""The one definition of a live Chapter Board Member seat (#2472).

A seat is live when ``is_active=1`` AND it has no ``to_date`` or its ``to_date`` is
today or later. ``is_active`` alone is not enough: nothing flips it when a fixed-term
seat's ``to_date`` passes, and a Desk edit can save ``is_active=1`` beside a past
``to_date`` (the board validator only warns). The role withdrawal and the role-profile
calculator used to disagree on this; both now read it from here.
"""

import frappe
from frappe.utils import today


def get_live_seats(filters: dict, fields: list = None, pluck: str = None, exclude_row: str = None) -> list:
    """Chapter Board Member rows matching ``filters`` that are live seats today."""
    filters = {**filters, "is_active": 1}
    if exclude_row:
        filters["name"] = ["!=", exclude_row]
    # "is" accepts only "set" / "not set" in Frappe filters.
    or_filters = [["to_date", "is", "not set"], ["to_date", ">=", today()]]
    return frappe.db.get_all(
        "Chapter Board Member", filters=filters, or_filters=or_filters, fields=fields, pluck=pluck
    )


def count_live_seats(volunteer: str, exclude_row: str = None) -> int:
    """How many live seats ``volunteer`` holds, ignoring ``exclude_row`` if given."""
    return len(get_live_seats({"volunteer": volunteer}, pluck="name", exclude_row=exclude_row))
