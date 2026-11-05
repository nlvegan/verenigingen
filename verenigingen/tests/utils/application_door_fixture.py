"""One shared builder for Membership Application Door fixtures in the short-application tests."""

import frappe

DOOR = "Membership Application Door"
LEGACY_SLOTS = (
    ("Monthly", "monthly_dues_template", "postal_minimum_monthly"),
    ("Annual", "annual_dues_template", "postal_minimum_annual"),
)
LEGACY_FIELDS = tuple(f for slot in LEGACY_SLOTS for f in slot[1:]) + ("allow_custom_amount",)


def plans_from_legacy_slots(data: dict) -> dict:
    """Turn the pre-#2127 door fields (a template per frequency slot, a postal minimum per slot, amount
    options keyed by frequency) into plan rows, the way an old test names a door.

    The old door took any amount at or above the template's minimum, so a template that ends up in a
    plan this way is made Flexible with a custom amount allowed: the same acceptance, under the
    contribution mode that now decides it. Tests of the new modes pass `plans` directly.
    """
    data = dict(data)
    slots = {
        frequency: (data.get(template_field), data.get(postal_field) or 0)
        for frequency, template_field, postal_field in LEGACY_SLOTS
        if data.get(template_field)
    }
    custom = data.get("allow_custom_amount")
    for field in LEGACY_FIELDS:
        data.pop(field, None)
    if "plans" in data or not (slots or "amount_options" in data):
        return data
    default = "Monthly" if "Monthly" in slots else "Annual"
    data["plans"] = [
        {"dues_template": template, "postal_minimum": postal, "is_default": int(frequency == default)}
        for frequency, (template, postal) in slots.items()
    ]
    for template, _postal in slots.values():
        make_flexible(template, allow_custom=1 if custom is None else custom)
    data["amount_options"] = [
        {"dues_template": slots[option["frequency"]][0], "amount": option["amount"]}
        if "frequency" in option
        else option
        for option in data.get("amount_options", [])
    ]
    return data


def make_flexible(template, allow_custom=1):
    frappe.db.set_value(
        "Membership Dues Schedule",
        template,
        {"contribution_mode": "Flexible", "allow_custom_amount": allow_custom},
    )


class ApplicationDoorMixin:
    """Gives a test case `_door(**fields)`: an inserted, tracked, enabled Regular door.

    Needs `self.membership_type`. A test that wants every door to carry more (for
    example a dues template) sets `self.door_extra` to a dict of fields. The pre-#2127 slot
    fields (`monthly_dues_template` and friends) are still accepted and become plan rows.
    """

    def _plan_template(self, frequency="Monthly", mode="Flexible", **fields):
        """A tracked template of `self.membership_type` with the given billing frequency and contribution
        mode. The values are written after the insert: validate rewrites the minimum from the type."""
        type_template = frappe.db.get_value(
            "Membership Type", self.membership_type.name, "dues_schedule_template"
        )
        template = frappe.copy_doc(frappe.get_doc("Membership Dues Schedule", type_template))
        template.schedule_name = f"Plan {frequency} {frappe.generate_hash(length=6)}"
        template.billing_frequency = frequency
        template.insert()
        self.track_doc("Membership Dues Schedule", template.name)
        values = {
            "contribution_mode": mode,
            "dues_rate": 12,
            "suggested_amount": 12,
            "minimum_amount": 2.5,
            "allow_custom_amount": 1,
        }
        frappe.db.set_value("Membership Dues Schedule", template.name, values | fields)
        return template.name

    def _door(self, **fields):
        data = {
            "doctype": DOOR,
            "title": "Testdeur",
            "slug": f"deur-{frappe.generate_hash(length=8).lower()}",
            "membership_type": self.membership_type.name,
            "form_shape": "Regular",
            "enabled": 1,
        }
        data.update(getattr(self, "door_extra", {}))
        data.update(fields)
        door = frappe.get_doc(plans_from_legacy_slots(data)).insert()
        self.track_doc(DOOR, door.name)
        return door
