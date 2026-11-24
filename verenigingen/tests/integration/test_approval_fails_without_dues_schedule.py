# -*- coding: utf-8 -*-
"""
#2133 (maintainer ruling 2026-11-24): an approval whose dues schedule cannot be created FAILS and rolls
back; the application stays Pending Review and no half-approved Member is left behind.

The failure is real, not injected: the dues schedule template's minimum is raised between the applicant's
submission and the approval (a legitimate staff action), so `create_from_template` refuses the
applicant's rate with "cannot be less than minimum amount". Staged through ApprovalCase's real
submit -> confirm -> approve flow. PROBE SHORTCUT: the minimum is raised with db.set_value on the
Membership Dues Schedule template (the Desk form would do the same through a save).
"""

import frappe
from frappe.utils import flt

from verenigingen.tests.integration.test_application_record_approval import SUBMISSION, ApprovalCase

SCHEDULE = "Membership Dues Schedule"


class TestApprovalFailsWithoutDuesSchedule(ApprovalCase):
    def _template(self):
        template = frappe.db.get_value(
            SCHEDULE, {"is_template": 1, "membership_type": self.membership_type.name}, "name"
        )
        self.assertTrue(template, "precondition: the type has a dues schedule template")
        return template

    def _raise_template_minimum_above_the_application(self):
        template = self._template()
        self._original_minimum = frappe.db.get_value(SCHEDULE, template, "minimum_amount")
        frappe.db.set_value(
            SCHEDULE, template, "minimum_amount", flt(frappe.db.get_value(SCHEDULE, template, "dues_rate")) + 500
        )

    def _snapshot(self):
        return {
            dt: frappe.db.count(dt)
            for dt in (SCHEDULE, "Membership", "Member", "Customer", "Sales Invoice", "Account Creation Request")
        }

    def _assert_nothing_approved(self, application, before):
        self.assertEqual(frappe.db.get_value(SUBMISSION, application, "status"), "Pending Review")
        self.assertEqual(frappe.db.count("Member", {"email": self.email}), 0, "no Member, Active or not")
        self.assertEqual(before, self._snapshot(), "no schedule, membership, customer, invoice or account request")

    def _approve_expecting_refusal(self, application, **kwargs):
        self.expectErrorLog("Dues Schedule Creation Failed")
        before = self._snapshot()
        with self.assertRaises(frappe.ValidationError) as caught:
            self._approve_as(application, **kwargs)
        self.assertIn("dues schedule could not be created", str(caught.exception))
        self.assertIn("minimum", str(caught.exception))
        self._assert_nothing_approved(application, before)

    def test_a_refused_dues_schedule_fails_the_approval_and_leaves_the_application_pending(self):
        application = self._stage_and_confirm()
        self._raise_template_minimum_above_the_application()

        self._approve_expecting_refusal(application, create_invoice=False)

    def test_the_same_refusal_with_an_invoice_requested_leaves_no_invoice_either(self):
        application = self._stage_and_confirm()
        self._raise_template_minimum_above_the_application()

        self._approve_expecting_refusal(application, create_invoice=True)

    def test_control_once_the_schedule_can_be_created_a_retry_approves_normally(self):
        """The refusal is about the schedule, not about the application: after staff fix the cause, the same
        application approves, and the Member ends Active with its schedule."""
        application = self._stage_and_confirm()
        self._raise_template_minimum_above_the_application()
        self._approve_expecting_refusal(application, create_invoice=False)
        frappe.db.set_value(SCHEDULE, self._template(), "minimum_amount", self._original_minimum)

        result = self._approve_as(application, create_invoice=False)

        self.assertTrue(result["success"], result)
        member = frappe.db.get_value("Member", {"email": self.email}, ["name", "status"], as_dict=True)
        self.assertEqual(member.status, "Active")
        self.assertEqual(frappe.db.count(SCHEDULE, {"member": member.name, "is_template": 0}), 1)
        self.assertEqual(frappe.db.get_value(SUBMISSION, application, "status"), "Approved")
