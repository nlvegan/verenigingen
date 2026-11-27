"""Opt-in fixed-date billing periods for /word-lid door plans (#3450).

A door plan may say its billing periods start on the same day every year (`period_anchor`
"Fixed date", `anchor_month`, `anchor_day`) and that someone approved shortly before the next such day
starts there with nothing billed until then (`waive_final_months`). The anchor is written to the
dues schedule's `coverage_anchor_date`; from there the periods are ordinary running periods of the
plan's frequency, so the period calculator is untouched. A plan on "Join date" resolves to no anchor.
"""

from datetime import date

import frappe
from frappe import _
from frappe.utils import add_months, getdate

FIXED_DATE = "Fixed date"
DOOR = "Membership Application Door"
DOOR_PLAN = "Membership Application Door Plan"
# Not a leap year, so 29 February is refused as a fixed date (a day that exists only every fourth year).
_NON_LEAP_YEAR = 2001


def validate_fixed_date_plan(row) -> None:
    """Refuse a Fixed date plan without a real month/day, and a negative waiver."""
    if (row.waive_final_months or 0) < 0:
        frappe.throw(_("Row {0}: waive final months cannot be negative.").format(row.idx))
    if row.period_anchor != FIXED_DATE:
        return
    try:
        date(_NON_LEAP_YEAR, int(row.anchor_month or 0), int(row.anchor_day or 0))
    except ValueError:
        frappe.throw(_("Row {0}: choose a real month and day for the fixed date.").format(row.idx))


def anchor_for_approval(anchor_month: int, anchor_day: int, waive_final_months: int, on_date) -> date:
    """The anchor a membership approved on `on_date` runs from.

    The most recent anchor on or before `on_date`; the next one instead when it falls within
    `waive_final_months` of `on_date`.
    """
    on_date = getdate(on_date)
    previous = date(on_date.year, anchor_month, anchor_day)
    if previous > on_date:
        previous = date(on_date.year - 1, anchor_month, anchor_day)
    following = date(previous.year + 1, anchor_month, anchor_day)
    if following <= add_months(on_date, waive_final_months or 0):
        return following
    return previous


def door_plan_of_member(member_doc, template_name):
    """The Fixed date plan row (anchor fields) of the door the member applied through whose template is
    `template_name`, or None. `template_name` is the template approval resolved for this member, so a
    reviewer who approves under another type or template gets no anchor."""
    door = getattr(member_doc, "application_door", None)
    if not (door and template_name):
        return None
    return frappe.db.get_value(
        DOOR_PLAN,
        {"parent": door, "parenttype": DOOR, "dues_template": template_name, "period_anchor": FIXED_DATE},
        ["anchor_month", "anchor_day", "waive_final_months"],
        as_dict=True,
    )


def anchor_for_member(member_doc, template_name, on_date) -> date | None:
    """The coverage anchor approval gives `member_doc` on `on_date`, or None when its plan is not Fixed date."""
    plan = door_plan_of_member(member_doc, template_name)
    if not plan:
        return None
    return anchor_for_approval(int(plan.anchor_month), int(plan.anchor_day), plan.waive_final_months, on_date)
