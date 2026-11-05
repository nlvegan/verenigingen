"""The payment plans a Membership Application Door offers, and the amount rules of each.

One plan is one dues template. The template, not the door, says how the amount is chosen
(``contribution_mode``): Fixed is the template's rate, Flexible is its suggested amount plus the door's
preset amounts for that plan (and a free amount only when the template allows one), Income-Based is a
free amount from the income calculator. The offer is read through the same service the full application
form uses (``get_dues_schedules``), so both forms see a template alike. /word-lid renders this offer and
the submit validator enforces it, so the page and the server cannot disagree.
"""

import frappe
from frappe import _
from frappe.utils import flt

from verenigingen.services.billing.template_configuration_service import TemplateConfigurationService
from verenigingen.services.member.application.membership_application_service import (
    get_membership_application_service,
)

CENT = 0.005


def offered_plans(door) -> list[dict]:
    """The door's plans that can be offered right now, in the order the door lists them.

    A plan whose template can no longer be offered (not a template of the door's type, archived,
    or a Fixed template whose rate is below the minimum it would be billed under) is left out rather
    than shown broken.
    """
    approval_minimum = _approval_minimum(door.membership_type)
    if approval_minimum is None:  # approval could not tell the floor either: offer nothing
        return []
    schedules = _schedules_by_name(door.membership_type)
    minimums = _template_minimums([row.dues_template for row in door.plans], approval_minimum)
    plans = []
    for row in door.plans:
        schedule = schedules.get(row.dues_template)
        plan = _offer(door, row, schedule, minimums.get(row.dues_template, 0)) if schedule else None
        if plan:
            plans.append(plan)
    return plans


def find_plan(door, plan_id=None, frequency=None) -> dict | None:
    """The offered plan an applicant named, or None. Only this door's plans are searched, so a plan of
    another door and a plan that does not exist look the same.

    A form loaded before plans existed names a ``frequency`` instead of a plan: that picks the door's one
    plan billed that way, and nothing when the door has none or several.
    """
    plans = offered_plans(door)
    if isinstance(plan_id, str) and plan_id:
        return next((plan for plan in plans if plan["id"] == plan_id), None)
    matching = (
        [plan for plan in plans if plan["frequency"] == frequency] if isinstance(frequency, str) else []
    )
    return matching[0] if len(matching) == 1 else None


def check_amount(plan: dict, amount: float, postal: bool):
    """Raise a ValidationError unless ``amount`` is one this plan accepts."""
    if amount < minimum_for(plan, postal) - CENT:
        frappe.throw(_("The amount is below the minimum for this choice."))
    mode = plan["mode"]
    if mode == "Fixed":
        accepted = _same(amount, fixed_price(plan, postal))
    elif mode == "Flexible":
        accepted = plan["allow_custom"] or any(_same(amount, offered) for offered in _flexible_amounts(plan))
    else:
        accepted = mode == "Income-Based"
    if not accepted:
        frappe.throw(_("This amount is not available for this payment plan."))


def minimum_for(plan: dict, postal: bool) -> float:
    """The template's minimum, raised to the plan's postal minimum when paper delivery is chosen (#1968)."""
    return max(plan["minimum"], plan["postal_minimum"]) if postal else plan["minimum"]


def fixed_price(plan: dict, postal: bool) -> float:
    """What a Fixed plan charges: the rate, or the plan's postal minimum when that is higher and paper
    delivery is chosen (ruling on #2127)."""
    return max(plan["amount"], plan["postal_minimum"]) if postal else plan["amount"]


def _flexible_amounts(plan: dict) -> list[float]:
    return [plan["suggested"], *plan["presets"]]


def _same(left, right) -> bool:
    return abs(flt(left) - flt(right)) < CENT


def _schedules_by_name(membership_type) -> dict:
    result = get_membership_application_service().get_dues_schedules(membership_type)
    if not result.get("success"):
        return {}
    return {schedule["name"]: schedule for schedule in result["schedules"]}


def _approval_minimum(membership_type) -> float | None:
    """The minimum approval applies to the schedule it creates: the same service call, so submit and
    approval cannot drift apart. None when that call refuses (fail closed)."""
    try:
        values = TemplateConfigurationService().get_template_values(
            schedule_doc=frappe._dict(), membership_type=membership_type, is_template=False
        )
    except frappe.ValidationError:
        frappe.clear_messages()
        return None
    return flt(values["minimum_amount"])


def _template_minimums(templates, approval_minimum) -> dict:
    """Each template's floor: its own ``minimum_amount`` (the shared service shows ``minimum_amount or
    dues_rate``, which would raise a template with no minimum to its rate), and never below what approval
    will enforce."""
    rows = frappe.get_all(
        "Membership Dues Schedule", filters={"name": ["in", templates]}, fields=["name", "minimum_amount"]
    )
    return {row.name: max(flt(row.minimum_amount), approval_minimum) for row in rows}


def _offer(door, row, schedule, minimum) -> dict | None:
    settings = schedule["contribution_settings"]
    mode = settings["mode"]
    if mode == "Fixed" and flt(schedule["amount"]) <= 0:
        return None
    if mode == "Fixed" and flt(schedule["amount"]) < minimum - CENT:
        return None
    return {
        "id": row.name,
        "template": row.dues_template,
        "label": row.label or schedule["schedule_name"],
        "is_default": bool(row.is_default),
        "frequency": schedule["billing_frequency"],
        "billing_display": schedule["billing_display"],
        "currency": schedule["currency"],
        "mode": mode,
        "amount": flt(schedule["amount"]),
        "minimum": minimum,
        "postal_minimum": flt(row.postal_minimum),
        "suggested": flt(settings["suggested"]),
        "allow_custom": mode == "Flexible" and bool(settings.get("allow_custom")),
        "presets": _presets(door, row.dues_template) if mode == "Flexible" else [],
        "calculator": settings if mode == "Income-Based" else None,
    }


def _presets(door, template) -> list[float]:
    return sorted({flt(option.amount) for option in door.amount_options if option.dues_template == template})
