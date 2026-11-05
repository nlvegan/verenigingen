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
from frappe.utils import add_days, today

from verenigingen.services.billing.dues_schedule_creation_service import DuesScheduleCreationService
from verenigingen.services.termination.termination_integration import cancel_membership_safe
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.membership.membership import cancel_membership


class TestCancelMembershipDuesSchedule(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="CancelSched",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"cancelsched.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
            auto_create_customer=True,
        )
        self.member.reload()

    def _cs_submit_membership(self, billing_period, skip_schedule=False):
        membership_type = self.create_test_membership_type(billing_period=billing_period)
        template = frappe.db.get_value(
            "Membership Dues Schedule", {"is_template": 1, "membership_type": membership_type.name}
        )
        template_doc = frappe.get_doc("Membership Dues Schedule", template)
        template_doc.billing_frequency = billing_period
        template_doc.save()
        membership = self.create_test_membership(
            member=self.member.name, membership_type=membership_type.name
        )
        membership.start_date = add_days(today(), -120)
        membership.flags.skip_dues_schedule_creation = skip_schedule
        membership.submit()
        return membership

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
        other = self.create_test_member(
            first_name="Other",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"other.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
            auto_create_customer=True,
        )
        other.reload()
        other_type = self.create_test_membership_type(billing_period="Monthly")
        other_membership = self.create_test_membership(member=other.name, membership_type=other_type.name)
        other_membership.start_date = add_days(today(), -120)
        other_membership.submit()
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
