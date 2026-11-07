"""Regression tests for #1938.

``membership.cancel_membership`` cancelled the Membership but left its Membership
Dues Schedule Active (still billing), and because that Active schedule existed,
the next Membership submitted for the member only re-typed it (``membership`` link
unchanged) instead of getting its own schedule.

Everything runs through the real flows: submit a Membership (auto-creates the
schedule), call ``cancel_membership``, submit a second Membership. No direct field
writes stand in for any step.
"""

import frappe
from frappe.utils import today

from verenigingen.services.billing.dues_schedule_creation_service import DuesScheduleCreationService
from verenigingen.services.termination.termination_integration import cancel_membership_safe
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.schedule_frequency_fixture import ScheduleFrequencyFixtureMixin
from verenigingen.verenigingen.doctype.membership.membership import (
    _cancel_linked_dues_schedule,
    cancel_membership,
)


class TestCancelMembershipDuesSchedule(ScheduleFrequencyFixtureMixin, VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self._create_schedule_test_member("CancelSched")

    def _cs_submit_membership(self, billing_period, skip_schedule=False):
        return self._submit_membership_via_template(
            self.member, billing_period, billing_period, skip_schedule=skip_schedule
        )

    def _cs_schedules(self, **filters):
        return frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "is_template": 0, **filters},
            fields=["name", "status", "membership", "billing_frequency"],
        )

    def test_immediate_cancel_cancels_the_linked_schedule(self):
        first = self._cs_submit_membership("Monthly")
        before = self._cs_schedules(membership=first.name)
        self.assertEqual([s.status for s in before], ["Active"], "fixture: submit must create the schedule")

        cancel_membership(first.name, cancellation_reason="staff", cancellation_type="Immediate")

        self.assertEqual(frappe.db.get_value("Membership", first.name, "status"), "Cancelled")
        self.assertEqual([s.status for s in self._cs_schedules(membership=first.name)], ["Cancelled"])
        self.assertEqual(self._cs_schedules(status="Active"), [], "member must not keep being billed")

    def test_new_membership_after_immediate_cancel_gets_its_own_schedule(self):
        first = self._cs_submit_membership("Monthly")
        cancel_membership(first.name, cancellation_reason="staff", cancellation_type="Immediate")

        second = self._cs_submit_membership("Annual")

        active = self._cs_schedules(status="Active")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].membership, second.name)
        self.assertEqual(active[0].billing_frequency, "Annual")
        self.assertEqual(
            frappe.db.get_value("Member", self.member.name, "current_dues_schedule"), active[0].name
        )

    def test_retry_service_creates_a_schedule_when_only_a_cancelled_one_exists(self):
        """The retry service reported a Cancelled schedule as 'already exists' and created nothing."""
        first = self._cs_submit_membership("Monthly")
        cancel_membership(first.name, cancellation_reason="staff", cancellation_type="Immediate")
        second = self._cs_submit_membership("Annual", skip_schedule=True)
        self.assertEqual(self._cs_schedules(status="Active"), [], "fixture: nothing created on submit")

        result = DuesScheduleCreationService().create_schedule_with_retry(
            member_name=self.member.name,
            membership_name=second.name,
            membership_type=second.membership_type,
        )

        self.assertTrue(result.success)
        active = self._cs_schedules(status="Active")
        self.assertEqual([s.membership for s in active], [second.name])

    def test_new_membership_after_termination_cancel_gets_its_own_schedule(self):
        """The termination path already cancelled the schedule but the next Membership got none."""
        first = self._cs_submit_membership("Monthly")
        self.assertTrue(cancel_membership_safe(first.name, cancellation_type="Immediate"))
        self.assertEqual([s.status for s in self._cs_schedules(membership=first.name)], ["Cancelled"])

        second = self._cs_submit_membership("Annual")

        active = self._cs_schedules(status="Active")
        self.assertEqual([s.membership for s in active], [second.name])

    def test_cancelling_one_member_does_not_touch_another_members_schedule(self):
        """Control: only the cancelled membership's own schedule is cancelled."""
        first = self._cs_submit_membership("Monthly")
        other = self._create_schedule_test_member("Other")
        other_membership = self._submit_membership_via_template(other, "Monthly", "Monthly")
        self.assertEqual(
            frappe.db.count(
                "Membership Dues Schedule", {"membership": other_membership.name, "status": "Active"}
            ),
            1,
            "fixture: other member has an Active schedule",
        )

        cancel_membership(first.name, cancellation_reason="staff", cancellation_type="Immediate")

        self.assertEqual(
            frappe.db.count(
                "Membership Dues Schedule", {"membership": other_membership.name, "status": "Active"}
            ),
            1,
        )

    def test_end_of_period_cancel_leaves_the_schedule_alone(self):
        """Control: #1938 does not settle End of Period; its behaviour is unchanged."""
        first = self._cs_submit_membership("Monthly")
        cancel_membership(first.name, cancellation_reason="staff", cancellation_type="End of Period")
        self.assertEqual([s.status for s in self._cs_schedules(membership=first.name)], ["Active"])

    def test_every_live_schedule_linked_to_the_membership_is_cancelled(self):
        """Probe shortcut: a second, Paused schedule linked to the same Membership is inserted
        directly (as the amendment service links extra schedules); no flow in this test makes
        one. Two ACTIVE ones cannot coexist (validate refuses), so Active + Paused it is."""
        first = self._cs_submit_membership("Monthly")
        extra = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"Extra {frappe.generate_hash(length=6)}",
                "member": self.member.name,
                "membership": first.name,
                "membership_type": first.membership_type,
                "contribution_mode": "Fixed",
                "dues_rate": 20,
                "billing_frequency": "Monthly",
                "status": "Paused",
                "auto_generate": 1,
                "next_invoice_date": today(),
            }
        )
        extra.flags.from_amendment = True
        extra.insert()
        self.assertEqual(
            sorted(s.status for s in self._cs_schedules(membership=first.name)),
            ["Active", "Paused"],
            "fixture",
        )

        cancel_membership(first.name, cancellation_reason="staff", cancellation_type="Immediate")

        self.assertEqual(self._cs_schedules(status=["!=", "Cancelled"]), [])

    def test_unwritable_schedule_refuses_instead_of_leaving_it_billing(self):
        """cancel_dues_schedule_safe returns False when the caller may not write the schedule
        (secure_document_operation refuses, no raw-SQL fallback on that branch); the
        membership must then not be reported cancelled."""
        first = self._cs_submit_membership("Monthly")
        self.expectErrorLog("Secure Operation Failed")
        self.expectErrorLog("Dues Schedule Termination Security")
        user_email = f"cs_nowrite_{frappe.generate_hash(length=6)}@example.com"
        self.create_test_user(user_email, roles=[])

        caller = frappe.session.user
        frappe.set_user(user_email)
        try:
            with self.assertRaises(frappe.ValidationError) as ctx:
                _cancel_linked_dues_schedule(first.name)
        finally:
            frappe.set_user(caller)

        self.assertIn("membership not cancelled", str(ctx.exception))
        self.assertEqual([s.status for s in self._cs_schedules(membership=first.name)], ["Active"])
