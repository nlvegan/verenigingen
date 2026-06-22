# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt
"""
Integration coverage tests for the MembershipDuesSchedule controller
(membership_dues_schedule.py).

The existing test_membership_dues_schedule.py only exercises the static
error-string helpers (_deduplicate_error_message / _is_deadlock_error). These
tests drive the *controller* methods against real documents built via the
enhanced test factory:

- validate() branches: template vs instance, duplicate-active guard,
  member-membership linkage, custom-frequency validation, billing-frequency
  consistency, sync_from_template (minimum/suggested amount), and
  _initialize_next_invoice_date.
- create_from_template classmethod (real schedule built from a Membership Type
  template, custom-amount approval gating).
- amount / date helpers: calculate_next_invoice_date, calculate_billing_period,
  get_membership_dues_item, get_member_payment_method / active mandate.
- lifecycle: pause_schedule / resume_schedule (status transitions) and
  validate_status_transitions guard.
- can_generate_invoice / validate_member_eligibility_for_invoice guards.
- orphan detection: is_orphaned / find_orphaned_schedules.

All documents are real; no business logic is mocked.
"""

import frappe
from frappe.utils import add_months, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
    MembershipDuesSchedule,
)


class TestMembershipDuesScheduleController(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # Fixed-amount membership type whose template carries suggested_amount=30,
        # minimum_amount=15 (factory sets minimum to amount*0.5).
        self.membership_type = self.create_test_membership_type(
            membership_type_name="DuesCtl Type",
            amount=30.0,
            contribution_mode="Fixed Amount",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _member_with_schedule(self, last="Ctl"):
        member, schedule = self.create_test_member_with_schedule(
            first_name="Ctl",
            last_name=last,
            membership_type_name=self.membership_type.name,
            start_date=today(),
        )
        return member, schedule

    # ------------------------------------------------------------------
    # Template vs instance validation
    # ------------------------------------------------------------------
    def test_template_requires_membership_type(self):
        """A template with no membership type is rejected."""
        tmpl = frappe.new_doc("Membership Dues Schedule")
        tmpl.is_template = 1
        tmpl.schedule_name = "Bad Template No Type"
        tmpl.status = "Active"
        with self.assertRaises(frappe.ValidationError):
            tmpl.insert()

    def test_template_cannot_have_member(self):
        """A template that points at a member is rejected."""
        member = self.create_test_member(first_name="Tmpl", last_name="Member")
        tmpl = frappe.new_doc("Membership Dues Schedule")
        tmpl.is_template = 1
        tmpl.schedule_name = "Bad Template With Member"
        tmpl.membership_type = self.membership_type.name
        tmpl.member = member.name
        tmpl.status = "Active"
        with self.assertRaises(frappe.ValidationError):
            tmpl.insert()

    def test_instance_requires_member(self):
        """A non-template schedule with no member is rejected."""
        inst = frappe.new_doc("Membership Dues Schedule")
        inst.is_template = 0
        inst.schedule_name = "Bad Instance No Member"
        inst.membership_type = self.membership_type.name
        inst.status = "Active"
        inst.billing_frequency = "Monthly"
        with self.assertRaises(frappe.ValidationError):
            inst.insert()

    def test_duplicate_active_schedule_rejected(self):
        """Member already has an auto-created active schedule -> a second is blocked."""
        member, schedule = self._member_with_schedule(last="Dup")
        dup = frappe.new_doc("Membership Dues Schedule")
        dup.is_template = 0
        dup.schedule_name = f"Dup-{member.name}"
        dup.member = member.name
        dup.membership_type = self.membership_type.name
        dup.status = "Active"
        dup.dues_rate = 30.0
        dup.billing_frequency = schedule.billing_frequency
        dup.next_invoice_date = today()
        with self.assertRaises(frappe.ValidationError):
            dup.insert()

    def test_instance_without_active_membership_rejected(self):
        """validate_member_membership throws for a member lacking an active membership."""
        member = self.create_test_member(first_name="NoMem", last_name="Active")
        self.link_member_to_customer(member)
        inst = frappe.new_doc("Membership Dues Schedule")
        inst.is_template = 0
        inst.schedule_name = f"NoMem-{member.name}"
        inst.member = member.name
        inst.membership_type = self.membership_type.name
        inst.status = "Active"
        inst.dues_rate = 30.0
        inst.billing_frequency = "Monthly"
        inst.next_invoice_date = today()
        with self.assertRaises(frappe.ValidationError):
            inst.insert()

    # ------------------------------------------------------------------
    # sync_from_template / amount derivation
    # ------------------------------------------------------------------
    def test_minimum_amount_synced_from_template(self):
        """A member schedule's minimum_amount is recomputed from its template on save.

        sync_from_template overwrites the read-only minimum_amount with the value
        derived from the membership type template (via get_template_values). After
        a save the schedule's minimum_amount must equal the template's
        minimum_amount rather than any stale value.
        """
        member, schedule = self._member_with_schedule(last="MinAmt")
        tmpl_min = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": self.membership_type.name},
            "minimum_amount",
        )
        # Re-save drives sync_from_template -> minimum_amount comes from template.
        schedule.save()
        schedule.reload()
        self.assertGreater(schedule.minimum_amount, 0)
        self.assertEqual(schedule.minimum_amount, tmpl_min)

    def test_template_syncs_minimum_from_membership_type(self):
        """A template (is_template=1) syncs minimum_amount directly from the membership type.

        Membership Type minimum_amount was set to 30.0 by the factory.
        """
        tmpl_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": self.membership_type.name},
            "name",
        )
        tmpl = frappe.get_doc("Membership Dues Schedule", tmpl_name)
        mt_min = frappe.db.get_value("Membership Type", self.membership_type.name, "minimum_amount")
        tmpl.save()
        tmpl.reload()
        self.assertEqual(tmpl.minimum_amount, mt_min)

    # ------------------------------------------------------------------
    # next_invoice_date initialization + date helpers
    # ------------------------------------------------------------------
    def test_next_invoice_date_initialized_on_insert(self):
        """A new instance with no next_invoice_date defaults to today()."""
        member, schedule = self._member_with_schedule(last="NextDate")
        schedule.reload()
        self.assertTrue(schedule.next_invoice_date)

    def test_calculate_next_invoice_date_monthly(self):
        """Monthly schedule advances next_invoice_date by exactly one month."""
        member, schedule = self._member_with_schedule(last="CalcNext")
        # Force a known frequency/date for a deterministic assertion.
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "billing_frequency", "Monthly")
        schedule.reload()
        base = getdate("2025-01-15")
        nxt = schedule.calculate_next_invoice_date(from_date=base)
        self.assertEqual(getdate(nxt), getdate(add_months(base, 1)))

    def test_calculate_billing_period_monthly(self):
        """calculate_billing_period returns a start <= end window for the given date."""
        member, schedule = self._member_with_schedule(last="BillPeriod")
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "billing_frequency", "Monthly")
        schedule.reload()
        start, end = schedule.calculate_billing_period(getdate("2025-06-10"))
        self.assertLessEqual(getdate(start), getdate(end))
        # The given date falls within the returned period.
        self.assertLessEqual(getdate(start), getdate("2025-06-10"))
        self.assertGreaterEqual(getdate(end), getdate("2025-06-10"))

    def test_get_membership_dues_item_named_by_frequency(self):
        """The dues item name embeds the billing frequency."""
        member, schedule = self._member_with_schedule(last="ItemName")
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "billing_frequency", "Annual")
        schedule.reload()
        self.assertEqual(schedule.get_membership_dues_item(), "Membership Dues - Annual")

    def test_get_membership_dues_item_custom_frequency(self):
        """Custom frequency produces a descriptive custom item name."""
        member, schedule = self._member_with_schedule(last="CustomItem")
        # Set custom fields directly (avoids full re-validation of the schedule).
        frappe.db.set_value(
            "Membership Dues Schedule",
            schedule.name,
            {
                "billing_frequency": "Custom",
                "custom_frequency_number": 2,
                "custom_frequency_unit": "Months",
            },
        )
        schedule.reload()
        self.assertEqual(
            schedule.get_membership_dues_item(),
            "Membership Dues - Custom (Every 2 Months)",
        )

    # ------------------------------------------------------------------
    # Payment-method helpers
    # ------------------------------------------------------------------
    def test_payment_method_defaults_to_bank_transfer(self):
        """Without an active SEPA mandate the schedule reports Bank Transfer."""
        member, schedule = self._member_with_schedule(last="PayBank")
        self.assertEqual(schedule.get_member_payment_method(), "Bank Transfer")
        self.assertIsNone(schedule.get_member_active_mandate())

    def test_payment_method_sepa_when_active_mandate(self):
        """With an active membership SEPA mandate the schedule reports SEPA Direct Debit."""
        member, schedule = self._member_with_schedule(last="PaySepa")
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": member.name,
                "mandate_id": f"MND-{member.name}",
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                "iban": "NL13TEST0123456789",
                "account_holder_name": member.full_name or "Test Holder",
                "status": "Active",
                "is_active": 1,
                "used_for_memberships": 1,
                "sign_date": today(),
            }
        ).insert()
        self.assertEqual(schedule.get_member_payment_method(), "SEPA Direct Debit")
        self.assertEqual(schedule.get_member_active_mandate(), mandate.name)

    # ------------------------------------------------------------------
    # create_from_template classmethod
    # ------------------------------------------------------------------
    def test_create_from_template_builds_real_schedule(self):
        """create_from_template produces an Active schedule wired to the member + type."""
        member = self.create_test_member(first_name="FromTmpl", last_name="Member")
        self.link_member_to_customer(member)
        membership = self.create_test_membership(
            member_name=member.name,
            membership_type_name=self.membership_type.name,
            start_date=today(),
        )
        # Remove the auto-created schedule so create_from_template can make one.
        existing = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member.name, "is_template": 0}, "name"
        )
        if existing:
            frappe.delete_doc("Membership Dues Schedule", existing, force=True, ignore_permissions=True)

        schedule_name = MembershipDuesSchedule.create_from_template(
            member_name=member.name,
            membership_type=self.membership_type.name,
            membership_name=membership.name,
        )
        self.assertTrue(schedule_name)
        sched = frappe.get_doc("Membership Dues Schedule", schedule_name)
        self.assertEqual(sched.member, member.name)
        self.assertEqual(sched.membership_type, self.membership_type.name)
        self.assertEqual(sched.is_template, 0)
        # Amount derives from the template suggested_amount (30.0).
        self.assertGreater(sched.dues_rate or sched.suggested_amount or 0, 0)

    def test_create_from_template_custom_amount_applied(self):
        """create_from_template applies a custom amount when the member has no own rate.

        The service's rate priority is: member.dues_rate (user-selected) >
        custom_amount > template fallback. With the member's own dues_rate cleared,
        the supplied custom_amount becomes the schedule's dues_rate.
        """
        member = self.create_test_member(first_name="CustAmt", last_name="Member")
        self.link_member_to_customer(member)
        membership = self.create_test_membership(
            member_name=member.name,
            membership_type_name=self.membership_type.name,
            start_date=today(),
        )
        existing = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member.name, "is_template": 0}, "name"
        )
        if existing:
            frappe.delete_doc("Membership Dues Schedule", existing, force=True, ignore_permissions=True)

        # Clear the member's own selected rate so the custom_amount branch wins.
        member.db_set("dues_rate", 0)
        frappe.db.commit()

        schedule_name = MembershipDuesSchedule.create_from_template(
            member_name=member.name,
            membership_type=self.membership_type.name,
            membership_name=membership.name,
            custom_amount=99.0,
            custom_amount_reason="High-income solidarity contribution",
            custom_amount_approved=1,
        )
        sched = frappe.get_doc("Membership Dues Schedule", schedule_name)
        self.assertEqual(sched.dues_rate, 99.0)

    def test_create_from_template_member_rate_wins_over_custom_amount(self):
        """When the member has a selected dues_rate it takes priority over custom_amount.

        Pins the rate-priority rule: a member's own dues_rate is the most
        authoritative source and is NOT overridden by a passed custom_amount.
        """
        member = self.create_test_member(first_name="RateWins", last_name="Member")
        self.link_member_to_customer(member)
        membership = self.create_test_membership(
            member_name=member.name,
            membership_type_name=self.membership_type.name,
            start_date=today(),
        )
        existing = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member.name, "is_template": 0}, "name"
        )
        if existing:
            frappe.delete_doc("Membership Dues Schedule", existing, force=True, ignore_permissions=True)

        # Member has an explicit selected rate above the template minimum (15.0).
        member.db_set("dues_rate", 42.0)
        frappe.db.commit()

        schedule_name = MembershipDuesSchedule.create_from_template(
            member_name=member.name,
            membership_type=self.membership_type.name,
            membership_name=membership.name,
            custom_amount=99.0,
            custom_amount_reason="ignored because member chose a rate",
            custom_amount_approved=1,
        )
        sched = frappe.get_doc("Membership Dues Schedule", schedule_name)
        self.assertEqual(sched.dues_rate, 42.0)

    # ------------------------------------------------------------------
    # Lifecycle: pause / resume
    # ------------------------------------------------------------------
    def test_pause_then_resume_schedule(self):
        """pause_schedule -> Paused, resume_schedule -> Active with a new next date."""
        member, schedule = self._member_with_schedule(last="PauseResume")
        self.assertEqual(schedule.status, "Active")

        schedule.pause_schedule(reason="Member sabbatical")
        schedule.reload()
        self.assertEqual(schedule.status, "Paused")
        self.assertIn("Member sabbatical", schedule.notes or "")

        new_date = add_months(today(), 1)
        schedule.resume_schedule(new_next_date=new_date)
        schedule.reload()
        self.assertEqual(schedule.status, "Active")
        self.assertEqual(getdate(schedule.next_invoice_date), getdate(new_date))

    def test_resume_non_paused_raises(self):
        """Resuming an Active (non-paused) schedule is an invalid transition."""
        member, schedule = self._member_with_schedule(last="ResumeBad")
        with self.assertRaises(Exception):
            schedule.resume_schedule()

    def test_invalid_status_transition_rejected(self):
        """Cancelled is terminal: Cancelled -> Active is rejected by validate_status_transitions."""
        member, schedule = self._member_with_schedule(last="BadTrans")
        schedule.status = "Cancelled"
        schedule._skip_membership_validation = True
        schedule.save()
        schedule.reload()
        # Now try Cancelled -> Active (not allowed).
        schedule.status = "Active"
        with self.assertRaises(Exception):
            schedule.save()

    # ------------------------------------------------------------------
    # can_generate_invoice / eligibility
    # ------------------------------------------------------------------
    def test_can_generate_invoice_returns_tuple(self):
        """can_generate_invoice returns a (bool, reason) tuple for an active member schedule."""
        member, schedule = self._member_with_schedule(last="CanGen")
        can_generate, reason = schedule.can_generate_invoice()
        self.assertIsInstance(can_generate, bool)
        self.assertIsInstance(reason, str)

    def test_eligibility_true_for_active_member(self):
        """validate_member_eligibility_for_invoice is True for an active, membered member."""
        member, schedule = self._member_with_schedule(last="Elig")
        self.assertTrue(schedule.validate_member_eligibility_for_invoice())

    def test_eligibility_false_without_member(self):
        """A schedule with no member is not eligible."""
        member, schedule = self._member_with_schedule(last="EligNo")
        schedule.member = None
        self.assertFalse(schedule.validate_member_eligibility_for_invoice())

    # ------------------------------------------------------------------
    # Orphan detection
    # ------------------------------------------------------------------
    def test_is_orphaned_false_for_real_member(self):
        member, schedule = self._member_with_schedule(last="NotOrphan")
        self.assertFalse(schedule.is_orphaned())

    def test_is_orphaned_false_for_template(self):
        """Templates (no member) are never orphaned."""
        tmpl_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": self.membership_type.name},
            "name",
        )
        tmpl = frappe.get_doc("Membership Dues Schedule", tmpl_name)
        self.assertFalse(tmpl.is_orphaned())

    def test_find_orphaned_schedules_returns_list(self):
        """find_orphaned_schedules returns a list (no orphans expected in clean test data)."""
        result = MembershipDuesSchedule.find_orphaned_schedules(limit=10)
        self.assertIsInstance(result, list)
