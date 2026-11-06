"""Move each Membership Application Door's Monthly/Annual slots into payment plan rows (#2127).

A door used to carry two fixed slots (monthly_dues_template, annual_dues_template), a postal minimum per
slot and amount options keyed by a Monthly/Annual Select. A door now has one plan row per offered
template (any billing frequency) and its amount options name the plan's template. Per door:

- the Monthly slot becomes a plan and is the default; when only the Annual slot is set, that one is;
- each slot's postal minimum moves onto its plan;
- each amount option moves onto the plan of its frequency (an option for a frequency the door has no
  slot for was never offered and is dropped);
- the old fields and each migrated amount row's frequency are left as they were (hidden), so the
  old shape can still be read.

Idempotent: a door that already has plan rows is skipped. The door's old allow_custom_amount is NOT
migrated: the dues template's own contribution mode and allow_custom_amount decide it now. That, and
other changes, alter what a migrated door accepts, so each such door is REPORTED (a printed line
and an Info comment on the door): a Fixed template with presets (presets are now ignored), a door that
took any amount whose template no longer does, a door that offered only presets whose Income-Based or
free-amount Flexible template now takes any amount, and a slot whose template is billed on another
period than the slot said (the plan bills the template's period).
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
    reported = 0
    for name in frappe.get_all(DOOR, pluck="name"):
        door = frappe.get_doc(DOOR, name)
        if not door.plans:
            notes = migrate_door(door)
            reported += _report_door(door, notes)
    if reported:
        print(f"Door payment plans: {reported} door(s) changed what they accept, see the Info comment on each.")


def _report_door(door, notes) -> int:
    if not notes:
        return 0
    text = "; ".join(notes)
    print(f"Door {door.name}: {text}")
    door.add_comment("Info", f"Payment plan migration (#2127): {text}")
    return 1


def migrate_door(door) -> list[str]:
    """Give ``door`` plan rows from its old slots. Returns the notes on what now behaves differently
    (empty when nothing changed meaning, or when the door had no slots)."""
    slots = legacy_slots(door)
    if not slots:
        return []
    notes = _behaviour_changes(door, slots)
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
    return notes


def _behaviour_changes(door, slots) -> list[str]:
    old_custom = bool(door.allow_custom_amount) or not door.amount_options
    notes = []
    for frequency, slot in slots.items():
        template = slot["template"]
        mode, allow_custom, billed = frappe.db.get_value(
            "Membership Dues Schedule",
            template,
            ["contribution_mode", "allow_custom_amount", "billing_frequency"],
        )
        mode = mode or "Fixed"
        presets = [o for o in door.amount_options if o.frequency == frequency]
        if billed != frequency:
            notes.append(f"the {frequency} slot's template {template} is billed {billed}, so the plan bills {billed}")
        if mode == "Fixed" and presets:
            notes.append(f"{len(presets)} preset amount(s) on Fixed template {template} are now ignored")
        if old_custom and (mode == "Fixed" or (mode == "Flexible" and not allow_custom)):
            notes.append(f"{template} ({mode}) no longer takes a free amount, which the door did")
        if not old_custom:
            notes.extend(_looser_notes(template, mode, allow_custom, presets))
    return notes


def _looser_notes(template, mode, allow_custom, presets) -> list[str]:
    """The door offered only its presets; the template now takes a free amount (the stricter cases
    are the other branch of _behaviour_changes)."""
    if mode == "Income-Based":
        note = f"{template} (Income-Based) now takes any amount at or above the minimum"
        return [note + (", and its preset amount(s) are no longer offered" if presets else "")]
    if mode == "Flexible" and allow_custom:
        return [f"{template} (Flexible) now takes a free amount, which the door did not"]
    return []


def legacy_slots(door) -> dict:
    """{frequency: {"template", "postal_minimum"}} for each slot that names a template."""
    return {
        frequency: {"template": door.get(template_field), "postal_minimum": door.get(postal_field) or 0}
        for frequency, template_field, postal_field in SLOTS
        if door.get(template_field)
    }


def _options_on_plans(door, slots) -> list:
    return [
        {
            "dues_template": slots[option.frequency]["template"],
            "amount": option.amount,
            "frequency": option.frequency,
        }
        for option in door.amount_options
        if option.frequency in slots
    ]
