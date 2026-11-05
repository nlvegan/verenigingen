"""Move each Membership Application Door's Monthly/Annual slots into payment plan rows (#2127).

A door used to carry two fixed slots (monthly_dues_template, annual_dues_template), a postal minimum per
slot and amount options keyed by a Monthly/Annual Select. A door now has one plan row per offered
template (any billing frequency) and its amount options name the plan's template. Per door:

- the Monthly slot becomes a plan and is the default; when only the Annual slot is set, that one is;
- each slot's postal minimum moves onto its plan;
- each amount option moves onto the plan of its frequency (an option for a frequency the door has no
  slot for was never offered and is dropped);
- the old fields are left as they were (hidden), so the patch can be re-read and the change undone.

Idempotent: a door that already has plan rows is skipped. The door's old allow_custom_amount is NOT
migrated: the dues template's own allow_custom_amount (and contribution mode) decides it now.
"""

import frappe

DOOR = "Membership Application Door"
SLOTS = (
    ("Monthly", "monthly_dues_template", "postal_minimum_monthly"),
    ("Annual", "annual_dues_template", "postal_minimum_annual"),
)


def execute():
    frappe.reload_doc("verenigingen", "doctype", "membership_application_door_plan")
    frappe.reload_doc("verenigingen", "doctype", "membership_application_door_amount")
    frappe.reload_doc("verenigingen", "doctype", "membership_application_door")
    for name in frappe.get_all(DOOR, pluck="name"):
        door = frappe.get_doc(DOOR, name)
        if not door.plans:
            migrate_door(door)


def migrate_door(door) -> bool:
    """Give ``door`` plan rows from its old slots. Returns whether it changed."""
    slots = legacy_slots(door)
    if not slots:
        return False
    default = "Monthly" if "Monthly" in slots else "Annual"
    for frequency, slot in slots.items():
        door.append(
            "plans",
            {
                "dues_template": slot["template"],
                "postal_minimum": slot["postal_minimum"],
                "is_default": int(frequency == default),
            },
        )
    door.set("amount_options", _options_on_plans(door, slots))
    # The rows were built from slots the old validation had already checked; saving the door must not
    # lose its offer because a template was edited since.
    door.flags.ignore_validate = True
    door.save(ignore_permissions=True)
    return True


def legacy_slots(door) -> dict:
    """{frequency: {"template", "postal_minimum"}} for each slot that names a template."""
    return {
        frequency: {"template": door.get(template_field), "postal_minimum": door.get(postal_field) or 0}
        for frequency, template_field, postal_field in SLOTS
        if door.get(template_field)
    }


def _options_on_plans(door, slots) -> list:
    return [
        {"dues_template": slots[option.frequency]["template"], "amount": option.amount}
        for option in door.amount_options
        if option.frequency in slots
    ]
