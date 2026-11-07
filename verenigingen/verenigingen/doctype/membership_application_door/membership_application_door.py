# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

# Paths under /word-lid that are not doors.
RESERVED_SLUGS = {"bevestig"}
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class MembershipApplicationDoor(Document):
    def validate(self):
        self._validate_slug()
        self._validate_plans()
        self._validate_amount_options()
        self._validate_has_plan()

    def hidden(self) -> set[str]:
        return {row.question for row in self.hidden_questions}

    def _validate_slug(self):
        if not SLUG_PATTERN.match(self.slug or ""):
            frappe.throw(_("Slug may only contain lowercase letters, digits and single hyphens."))
        if self.slug in RESERVED_SLUGS:
            frappe.throw(_("Slug {0} is reserved.").format(self.slug))

    def _validate_plans(self):
        """A plan is a template of the door's type, offered once; exactly one plan is the default."""
        templates = [row.dues_template for row in self.plans]
        for template in set(templates):
            if templates.count(template) > 1:
                frappe.throw(_("{0} is offered more than once.").format(template))
        for row in self.plans:
            self._validate_template(row.dues_template)
        defaults = [row for row in self.plans if row.is_default]
        if self.plans and len(defaults) != 1:
            frappe.throw(_("Choose exactly one default payment plan."))

    def _validate_template(self, template):
        row = frappe.db.get_value(
            "Membership Dues Schedule",
            template,
            ["is_template", "membership_type", "contribution_mode", "dues_rate"],
            as_dict=True,
        )
        if not (row and row.is_template):
            frappe.throw(_("{0} is not a dues schedule template.").format(template))
        if row.membership_type != self.membership_type:
            frappe.throw(_("{0} belongs to a different membership type.").format(template))
        if (row.contribution_mode or "Fixed") == "Fixed" and flt(row.dues_rate) <= 0:
            frappe.throw(_("{0} has a fixed contribution but no rate.").format(template))

    def _validate_amount_options(self):
        """Each preset belongs to a plan of this door and may not undercut the template's minimum."""
        planned = {row.dues_template for row in self.plans}
        for option in self.amount_options:
            if option.dues_template not in planned:
                frappe.throw(
                    _("Row {0}: choose the template of one of the payment plans.").format(option.idx)
                )
            minimum = frappe.db.get_value("Membership Dues Schedule", option.dues_template, "minimum_amount")
            if flt(option.amount) < flt(minimum):
                frappe.throw(_("Row {0}: the amount is below the template minimum.").format(option.idx))

    def _validate_has_plan(self):
        if self.form_shape == "Regular" and not self.plans:
            frappe.throw(_("A regular door needs at least one payment plan."))
