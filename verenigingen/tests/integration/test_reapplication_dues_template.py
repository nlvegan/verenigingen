# -*- coding: utf-8 -*-
"""
#1730: a reapplying Member must be approved on the template and amount of the
reapplication, not on the ones from the earlier application.

Everything is driven through the REAL flow: submit_application (new member) ->
reject_membership_application -> submit_application (same email, reapplication)
-> approve_membership_application. Nothing is seeded with db_set; the expected
template and rate are read from the fixtures the test creates.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, today

from verenigingen.tests.utils.legacy_submit import submit_and_materialise
from verenigingen.api.membership_application_review import (
    approve_membership_application,
    reject_membership_application,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestReapplicationDuesTemplate(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        run = frappe.generate_hash(length=6)
        self.chapter = self.factory.ensure_test_chapter(
            f"Test Chapter {run}", {"short_name": "TST", "country": "Netherlands"}
        )
        self.membership_type = self.factory.ensure_membership_type(
            f"Reapp Type {run}", {"amount": 25.00, "billing_period": "Monthly"}
        )
        self.default_template = frappe.get_doc(
            "Membership Dues Schedule", self.membership_type.dues_schedule_template
        )
        self.minimum = flt(self.membership_type.minimum_amount or 0)
        # Two templates of DIFFERENT frequency and rate for the same type.
        self.monthly_template = self._template(f"Reapp Monthly {run}", "Monthly", self.minimum + 11)
        self.annual_template = self._template(f"Reapp Annual {run}", "Annual", self.minimum + 123)
        self._prepare_environment()

    def _template(self, name, frequency, rate):
        return self.ensure_dues_schedule_template(
            name,
            {
                "billing_frequency": frequency,
                "dues_rate": rate,
                "suggested_amount": rate,
                "minimum_amount": self.minimum,
                "membership_type": self.membership_type.name,
                "contribution_mode": "Fixed",
            },
        )

    def _prepare_environment(self):
        """Same approval prerequisites as tests/integration/test_membership_approval.py."""
        if not frappe.db.exists("Item Group", "Memberships"):
            frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Memberships",
                    "parent_item_group": "All Item Groups",
                    "is_group": 0,
                }
            ).insert()
        self.membership_type.get_or_create_membership_item()
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        self.admin_user = self.create_test_user_with_roles(
            email=f"reapp.admin.{frappe.generate_hash(length=6)}@example.com",
            roles=["System Manager", "Verenigingen Administrator"],
        )
        grant_matching_role_profiles(self.admin_user.email, "Verenigingen Administrator")

    # -- real-flow helpers -------------------------------------------------

    def _submit_application(self, email, template=None, amount=None):
        payload = dict(
            first_name="Reapp",
            last_name=f"Applicant{frappe.generate_hash(length=6)}",
            email=email,
            birth_date=add_days(today(), -365 * 30),
            address_line1="123 Test Street",
            city="Amsterdam",
            postal_code="1234AB",
            country="Netherlands",
            selected_membership_type=self.membership_type.name,
            selected_chapter=self.chapter.name,
        )
        if template:
            payload["selected_dues_schedule"] = template.name
        if amount is not None:
            payload["custom_contribution_fee"] = amount
            payload["uses_custom_amount"] = 1
        result = submit_and_materialise(**payload)
        self.assertTrue(result["success"], f"submit_application failed: {result}")
        return result["data"]["member_record"]

    def _reject(self, member_name):
        with self.as_user(self.admin_user.email):
            reject_membership_application(member_name, reason="first attempt rejected")
        self.assertEqual(frappe.db.get_value("Member", member_name, "application_status"), "Rejected")

    def _approve(self, member_name):
        with self.as_user(self.admin_user.email):
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch("frappe.sendmail"):
                result = approve_membership_application(
                    member_name=member_name,
                    membership_type=self.membership_type.name,
                    chapter=self.chapter.name,
                    notes="reapplication test",
                    create_invoice=False,
                )
        self.assertTrue(result.get("success"), f"Approval failed: {result}")
        return frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "is_template": 0},
            ["name", "template_reference", "billing_frequency", "dues_rate"],
            as_dict=True,
        )

    def _reapply_and_approve(self, first, second):
        """first/second are (template, amount) tuples; returns (member, schedule)."""
        email = f"reapp-{frappe.generate_hash(length=8)}@example.com"
        member = self._submit_application(email, *first)
        self._reject(member)
        self.assertEqual(self._submit_application(email, *second), member, "reapplication must reuse the Member")
        return member, self._approve(member)

    # -- tests --------------------------------------------------------------

    def test_reapplication_with_other_template_and_no_amount_uses_new_template(self):
        """Monthly template + custom amount first, Annual template and NO amount on reapplication."""
        old_amount = self.minimum + 7.5
        member, schedule = self._reapply_and_approve(
            (self.monthly_template, old_amount), (self.annual_template, None)
        )
        self.assertIsNotNone(schedule, "no dues schedule created on approval")
        self.assertEqual(schedule.template_reference, self.annual_template.name)
        self.assertEqual(schedule.billing_frequency, "Annual")
        self.assertEqual(flt(schedule.dues_rate), flt(self.annual_template.dues_rate))
        self.assertNotEqual(flt(schedule.dues_rate), flt(old_amount))

    def test_reapplication_with_other_template_and_new_amount_uses_new_template_and_amount(self):
        """Worst case: old Monthly template, new Annual template with a new amount."""
        new_amount = self.minimum + 200.25
        member, schedule = self._reapply_and_approve(
            (self.monthly_template, self.minimum + 7.5), (self.annual_template, new_amount)
        )
        self.assertEqual(schedule.template_reference, self.annual_template.name)
        self.assertEqual(schedule.billing_frequency, "Annual")
        self.assertEqual(flt(schedule.dues_rate), flt(new_amount))

    def test_reapplication_without_template_or_amount_falls_back_to_type_default(self):
        """A reapplication that picks nothing must not inherit the earlier template or fee."""
        old_amount = self.minimum + 7.5
        member, schedule = self._reapply_and_approve(
            (self.monthly_template, old_amount), (None, None)
        )
        self.assertNotEqual(schedule.template_reference, self.monthly_template.name)
        self.assertEqual(schedule.template_reference, self.default_template.name)
        self.assertNotEqual(flt(schedule.dues_rate), flt(old_amount))
        self.assertEqual(frappe.db.get_value("Member", member, "application_dues_schedule"), None)
        self.assertFalse(frappe.db.get_value("Member", member, "application_custom_fee"))

    def test_pending_application_updated_before_review_uses_the_latest_choice(self):
        """Scenario 2 (no rejection): the applicant resubmits while still Pending."""
        email = f"reapp-{frappe.generate_hash(length=8)}@example.com"
        member = self._submit_application(email, self.monthly_template, self.minimum + 7.5)
        self.assertEqual(self._submit_application(email, self.annual_template, None), member)
        schedule = self._approve(member)
        self.assertEqual(schedule.template_reference, self.annual_template.name)
        self.assertEqual(schedule.billing_frequency, "Annual")
        self.assertEqual(flt(schedule.dues_rate), flt(self.annual_template.dues_rate))

    def test_voluntary_quit_reapplication_records_the_new_template_on_the_member(self):
        """Narrow on purpose: only Member.application_dues_schedule, after a voluntary Quit.

        This does NOT claim a rejoiner is approved on the new template: the earlier
        schedule is reused at approval and stays Cancelled (#1737, #1741, not fixed here).
        PROBE SHORTCUT: the Membership's commitment_end_date is backdated so a genuine
        past-dated termination can run; the termination and reapplication are real.
        """
        from verenigingen.tests.support.termination_request import execute_real_termination

        email = f"reapp-{frappe.generate_hash(length=8)}@example.com"
        member = self._submit_application(email, self.monthly_template, None)
        self._approve(member)
        plan = frappe.db.get_value("Member", member, "current_membership_plan")
        frappe.db.set_value("Membership", plan, "commitment_end_date", add_days(today(), -60))
        execute_real_termination(self, member, add_days(today(), -30))
        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Quit")

        self.assertEqual(self._submit_application(email, self.annual_template, None), member)
        self.assertEqual(
            frappe.db.get_value("Member", member, "application_dues_schedule"), self.annual_template.name
        )

    def test_staff_override_on_a_pending_member_survives_a_resubmission(self):
        """A fee override staff saved on the Pending Member is not the application's: keep it."""
        email = f"reapp-{frappe.generate_hash(length=8)}@example.com"
        member = self._submit_application(email, self.monthly_template, None)
        staff_amount = self.minimum + 1
        with self.as_user(self.admin_user.email):
            doc = frappe.get_doc("Member", member)
            doc.dues_rate = staff_amount
            doc.fee_override_reason = "krappe beurs"
            doc.save()
        stored = frappe.db.get_value("Member", member, ["dues_rate", "fee_override_reason"], as_dict=True)
        self.assertEqual(flt(stored.dues_rate), flt(staff_amount), "precondition: staff save persisted")

        self.assertEqual(self._submit_application(email, self.annual_template, None), member)
        kept = frappe.db.get_value(
            "Member", member, ["dues_rate", "fee_override_reason", "application_dues_schedule"], as_dict=True
        )
        self.assertEqual(flt(kept.dues_rate), flt(staff_amount))
        self.assertEqual(kept.fee_override_reason, "krappe beurs")
        self.assertEqual(kept.application_dues_schedule, self.annual_template.name)
