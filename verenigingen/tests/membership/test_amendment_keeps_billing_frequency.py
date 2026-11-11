"""Regression tests for #1937.

An amendment that replaces a member's Membership Dues Schedule used to take the
replacement's ``billing_frequency`` from the Membership Type (its template, else its
``billing_period``), so a member billed on a cadence that differs from their Type's
silently changed cadence. Maintainer ruling (2026-11-11): the replacement KEEPS the old
schedule's frequency unless the amendment explicitly requests one
(``requested_billing_frequency``; empty = keep).

Fixture shape (the #1773 case): the Type's template is Monthly while the member is
submitted, so the member's schedule is Monthly; the template is then edited to Annual.
The member is now billed Monthly under a Type whose template says Annual.

Real flow throughout: amendment insert -> approve_amendment (when it lands in Pending
Approval) -> apply_amendment. Probe shortcut: the template edit after the schedule exists
stands in for "the member's schedule frequency differs from the Type's".
"""

import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.repositories.dues_schedule_repository import DuesScheduleRepository
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.schedule_frequency_fixture import ScheduleFrequencyFixtureMixin


class TestAmendmentKeepsBillingFrequency(ScheduleFrequencyFixtureMixin, VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self._create_schedule_test_member("AmendFreq")
        self.membership = self._submit_membership_via_template(
            self.member, "Annual", "Monthly", start_date=today()
        )
        self.old_type = self.membership.membership_type
        self._set_type_template_frequency(self.old_type, "Annual")
        self.old_schedule = self._live_schedule()
        self.assertEqual(self.old_schedule.billing_frequency, "Monthly", "fixture: member billed Monthly")
        self.assertEqual(self._template_frequency(self.old_type), "Annual", "fixture: Type template Annual")

    # ------------------------------------------------------------------ helpers

    def _set_type_template_frequency(self, membership_type_name, frequency):
        template = frappe.db.get_value(
            "Membership Dues Schedule", {"is_template": 1, "membership_type": membership_type_name}
        )
        doc = frappe.get_doc("Membership Dues Schedule", template)
        doc.billing_frequency = frequency
        doc.save()

    def _template_frequency(self, membership_type_name):
        return frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": membership_type_name},
            "billing_frequency",
        )

    def _live_schedule(self):
        return frappe.get_doc(
            "Membership Dues Schedule",
            frappe.db.get_value(
                "Membership Dues Schedule",
                {"member": self.member.name, "status": "Active", "is_template": 0},
                "name",
            ),
        )

    def _other_type(self, billing_period="Quarterly", template_frequency="Quarterly"):
        mtype = self.create_test_membership_type(billing_period=billing_period)
        self._set_type_template_frequency(mtype.name, template_frequency)
        return mtype

    def _amend(self, **overrides):
        data = {
            "doctype": "Contribution Amendment Request",
            "membership": self.membership.name,
            "member": self.member.name,
            "amendment_type": "Fee Change",
            "requested_amount": float(self.old_schedule.dues_rate) + 7,
            "reason": "test amendment",
            "effective_date": today(),
        }
        data.update(overrides)
        amendment = frappe.get_doc(data)
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        if amendment.status == "Pending Approval":
            amendment.approve_amendment("approved in test")
            amendment.reload()
        self.assertEqual(amendment.status, "Approved", "fixture: amendment approved through the real flow")
        amendment._force_apply = True
        result = amendment.apply_amendment()
        self.assertEqual(result["status"], "success", result)
        amendment.reload()
        return amendment

    def _non_pure_fee_change(self, **overrides):
        other = self._other_type()
        return self._amend(
            amendment_type="Fee Change",
            requested_membership_type=other.name,
            **overrides,
        )

    def _type_change(self, **overrides):
        other = self._other_type()
        return self._amend(
            amendment_type="Membership Type Change",
            requested_membership_type=other.name,
            **overrides,
        ), other

    def _new_schedule(self, amendment):
        self.assertTrue(amendment.new_dues_schedule)
        return frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)

    # ------------------------------------------------------------------ the defect

    def test_non_pure_fee_change_replacement_keeps_the_members_frequency(self):
        amendment = self._non_pure_fee_change()
        replacement = self._new_schedule(amendment)
        self.assertNotEqual(replacement.name, self.old_schedule.name, "fixture: a replacement, not in place")
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", self.old_schedule.name, "status"), "Cancelled"
        )
        self.assertEqual(replacement.billing_frequency, "Monthly")

    def test_type_change_keeps_the_members_frequency(self):
        amendment, other = self._type_change()
        schedule = self._new_schedule(amendment)
        self.assertEqual(schedule.membership_type, other.name)
        self.assertEqual(schedule.billing_frequency, "Monthly")

    def test_type_change_with_no_live_schedule_falls_back_to_the_types_template(self):
        """No old schedule means nothing to keep: the requested Type's template decides."""
        self.assertTrue(DuesScheduleRepository().cancel_schedule(self.old_schedule.name, "test").success)
        other = self._other_type(billing_period="Quarterly", template_frequency="Quarterly")
        amendment = self._amend(amendment_type="Membership Type Change", requested_membership_type=other.name)
        self.assertEqual(self._new_schedule(amendment).billing_frequency, "Quarterly")

    # ------------------------------------------------------------------ explicit request

    def test_requested_frequency_is_used_on_a_replacement(self):
        amendment = self._non_pure_fee_change(requested_billing_frequency="Semi-Annual")
        self.assertEqual(self._new_schedule(amendment).billing_frequency, "Semi-Annual")

    def test_requested_frequency_is_used_on_a_type_change(self):
        amendment, _other = self._type_change(requested_billing_frequency="Annual")
        self.assertEqual(self._new_schedule(amendment).billing_frequency, "Annual")

    def test_empty_requested_frequency_means_keep_not_monthly(self):
        """The member is billed Annual here, so a 'blank means Monthly' fallback would show."""
        self.old_schedule.billing_frequency = "Annual"
        self.old_schedule.save()
        amendment = self._non_pure_fee_change(requested_billing_frequency="")
        self.assertEqual(self._new_schedule(amendment).billing_frequency, "Annual")

    def test_requested_frequency_on_a_pure_fee_change_is_refused(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            frappe.get_doc(
                {
                    "doctype": "Contribution Amendment Request",
                    "membership": self.membership.name,
                    "member": self.member.name,
                    "amendment_type": "Fee Change",
                    "requested_amount": float(self.old_schedule.dues_rate) + 7,
                    "requested_billing_frequency": "Annual",
                    "reason": "pure",
                    "effective_date": today(),
                }
            ).insert()
        self.assertIn("billing frequency", str(ctx.exception).lower())

    # ------------------------------------------------------------------ controls

    def test_pure_fee_change_updates_in_place_and_keeps_frequency(self):
        amendment = self._amend()
        self.assertEqual(amendment.new_dues_schedule, self.old_schedule.name)
        schedule = self._live_schedule()
        self.assertEqual(schedule.name, self.old_schedule.name)
        self.assertEqual(schedule.billing_frequency, "Monthly")
        self.assertEqual(float(schedule.dues_rate), float(self.old_schedule.dues_rate) + 7)

    def test_replacement_carries_amount_type_template_and_running_period_anchor(self):
        amount = float(self.old_schedule.dues_rate) + 11
        amendment = self._non_pure_fee_change(requested_amount=amount, effective_date=today())
        replacement = self._new_schedule(amendment)
        self.assertEqual(float(replacement.dues_rate), amount)
        self.assertEqual(replacement.contribution_mode, "Fixed")
        self.assertEqual(replacement.membership_type, self.old_type)
        self.assertEqual(replacement.membership, self.membership.name)
        self.assertEqual(replacement.status, "Active")
        self.assertEqual(getdate(replacement.next_invoice_date), getdate(today()))

        # Next invoice discharges ONE full running period from the anchor (not calendar-bound).
        invoice = replacement.generate_invoice(force=True)
        self.assertIsNotNone(invoice, "fixture: the replacement can bill")
        self.track_doc("Sales Invoice", invoice.name)
        start = getdate(invoice.custom_coverage_start_date)
        end = getdate(invoice.custom_coverage_end_date)
        self.assertEqual(start, getdate(today()))
        self.assertEqual(end, add_days(add_months(start, 1), -1), "Monthly running period from the anchor")
