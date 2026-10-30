# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

# Paths under /word-lid that are not doors.
RESERVED_SLUGS = {"bevestig"}
FREQUENCIES = ("Monthly", "Annual")
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class MembershipApplicationDoor(Document):
    def validate(self):
        self._validate_slug()
        self._validate_templates()
        self._validate_has_template()

    def get_template_for(self, frequency: str) -> str | None:
        return self.get(f"{frequency.lower()}_dues_template") or None

    def minimum_for(self, frequency: str, postal: bool) -> float:
        template = self.get_template_for(frequency)
        minimum = 0.0
        if template:
            minimum = frappe.db.get_value("Membership Dues Schedule", template, "minimum_amount") or 0
        if postal:
            minimum = max(minimum, self.get(f"postal_minimum_{frequency.lower()}") or 0)
        return float(minimum)

    def hidden(self) -> set[str]:
        return {row.question for row in self.hidden_questions}

    def _validate_slug(self):
        if not SLUG_PATTERN.match(self.slug or ""):
            frappe.throw(_("Slug may only contain lowercase letters, digits and single hyphens."))
        if self.slug in RESERVED_SLUGS:
            frappe.throw(_("Slug {0} is reserved.").format(self.slug))

    def _validate_templates(self):
        for frequency in FREQUENCIES:
            template = self.get_template_for(frequency)
            if template:
                self._validate_template(template, frequency)
        self._validate_amount_options()

    def _validate_template(self, template, frequency):
        """A slot takes only a template of the door's type billed at the slot's own frequency."""
        row = frappe.db.get_value(
            "Membership Dues Schedule",
            template,
            ["is_template", "membership_type", "billing_frequency"],
            as_dict=True,
        )
        if not (row and row.is_template):
            frappe.throw(_("{0} is not a dues schedule template.").format(template))
        if row.membership_type != self.membership_type:
            frappe.throw(_("{0} belongs to a different membership type.").format(template))
        if row.billing_frequency != frequency:
            frappe.throw(_("{0} is not billed {1}.").format(template, _(frequency).lower()))

    def _validate_amount_options(self):
        """Each suggested amount needs a template for its frequency and may not undercut its minimum."""
        for option in self.amount_options:
            if not self.get_template_for(option.frequency):
                frappe.throw(
                    _("Row {0}: this door has no {1} dues template.").format(option.idx, _(option.frequency))
                )
            if flt(option.amount) < self.minimum_for(option.frequency, postal=False):
                frappe.throw(_("Row {0}: the amount is below the template minimum.").format(option.idx))

    def _validate_has_template(self):
        if self.form_shape == "Regular" and not (self.monthly_dues_template or self.annual_dues_template):
            frappe.throw(_("A regular door needs at least one dues template."))
