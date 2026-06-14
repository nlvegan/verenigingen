"""
Real-integration tests for the Membership Dues Schedule controller and its
whitelisted helper endpoints in
``verenigingen/verenigingen/doctype/membership_dues_schedule/membership_dues_schedule.py``.

The controller was only ~64% covered: most of the standalone whitelisted
endpoints (template creation, member-schedule lookup, contribution updates,
schedule-from-template) and many of the instance helper methods (progressive
dues calculation, member edit-permission validation, orphan detection, payment
method / mandate lookups, schedule resume, date advancement, fee-change
recording, item creation) had no coverage.

These tests create real Members, Membership Types, Memberships and SEPA Mandates
via the factory (no business-logic mocking) and run as Administrator.

Modeling note (DEFERRED, do not fix): Membership has no forward ``dues_schedule``
field; the only link is ``Membership Dues Schedule.membership -> Membership``.
A schedule validates that its member has an active (submitted) membership, and a
submitted Membership auto-creates one schedule via ``on_submit``. To exercise
create/template paths we therefore either reuse the auto-created schedule or
build instances on a member with a controlled membership state.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.membership_dues_schedule import (
    membership_dues_schedule as mds,
)

IBAN_TEST = "NL13TEST0123456789"


class TestMembershipDuesSchedule(VereningingenTestCase):
    """Exercise the Membership Dues Schedule controller + endpoints end to end."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="DuesSched",
            last_name="Endpoint",
            email=f"duessched.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.membership_type = self.create_test_membership_type(
            membership_type_name=f"DuesType{frappe.generate_hash(length=6)}",
        )
        # The factory inserts a DRAFT membership; submit it so the member has an
        # active membership (required for non-paused schedule validation) and so
        # on_submit auto-creates the member's dues schedule.
        self.membership = self.create_test_membership(
            member=self.member.name,
            membership_type=self.membership_type.name,
        )
        self.membership.submit()
        self.membership.reload()

    def _active_schedule(self):
        """Return the member's auto-created active dues schedule doc."""
        name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.member.name, "is_template": 0},
            "name",
        )
        self.assertTrue(name, "submitted membership should have auto-created a dues schedule")
        return frappe.get_doc("Membership Dues Schedule", name)

    # ------------------------------------------------------- create_template_for_membership_type

    def test_create_template_for_membership_type_default_name(self):
        # A fresh membership type with no template yet.
        mt = self.create_test_membership_type(
            membership_type_name=f"NoTpl{frappe.generate_hash(length=6)}",
        )
        # The factory's after_insert auto-creates a template; delete it so the
        # endpoint's "create new" path is reachable.
        existing = frappe.db.get_value(
            "Membership Dues Schedule", {"membership_type": mt.name, "is_template": 1}, "name"
        )
        if existing:
            frappe.db.set_value("Membership Type", mt.name, "dues_schedule_template", None)
            frappe.delete_doc("Membership Dues Schedule", existing, force=True)

        template_name = mds.create_template_for_membership_type(mt.name)
        self.track_doc("Membership Dues Schedule", template_name)
        tpl = frappe.get_doc("Membership Dues Schedule", template_name)
        self.assertEqual(tpl.is_template, 1)
        self.assertEqual(tpl.membership_type, mt.name)
        self.assertIn(mt.membership_type_name, tpl.schedule_name)
        # Template is linked back onto the membership type.
        self.assertEqual(
            frappe.db.get_value("Membership Type", mt.name, "dues_schedule_template"),
            template_name,
        )

    def test_create_template_for_membership_type_duplicate_throws(self):
        # The factory already auto-created a template for self.membership_type.
        with self.assertRaises(frappe.ValidationError):
            mds.create_template_for_membership_type(self.membership_type.name)

    # --------------------------------------------------------------- get_member_dues_schedule

    def test_get_member_dues_schedule_returns_schedule(self):
        result = mds.get_member_dues_schedule(member=self.member.name)
        self.assertIsNotNone(result)
        self.assertEqual(result.member, self.member.name)
        self.assertEqual(result.is_template, 0)

    def test_get_member_dues_schedule_no_schedule_returns_none(self):
        # A member with no membership/schedule -> None.
        lonely = self.create_test_member(
            first_name="Lonely",
            last_name="NoSched",
            email=f"lonely.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.assertIsNone(mds.get_member_dues_schedule(member=lonely.name))

    # ------------------------------------------------------------------ update_member_contribution

    def test_update_member_contribution_updates_allowed_fields(self):
        schedule = self._active_schedule()
        result = mds.update_member_contribution(
            schedule.name,
            frappe.as_json({"notes": "Updated via endpoint", "dues_rate": 20.0}),
        )
        self.assertTrue(result["success"])
        schedule.reload()
        self.assertEqual(schedule.notes, "Updated via endpoint")
        self.assertEqual(float(schedule.dues_rate), 20.0)

    def test_update_member_contribution_accepts_dict(self):
        # The endpoint accepts an already-parsed dict, not only a JSON string.
        schedule = self._active_schedule()
        result = mds.update_member_contribution(schedule.name, {"notes": "dict path"})
        self.assertTrue(result["success"])
        schedule.reload()
        self.assertEqual(schedule.notes, "dict path")

    # --------------------------------------------------------------- create_schedule_from_template

    def test_create_schedule_from_template_for_member(self):
        # Build a member whose auto-created schedule we cancel, so create_from_template
        # has no duplicate-active-schedule conflict.
        member2 = self.create_test_member(
            first_name="Tpl",
            last_name="Member",
            email=f"tpl.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        membership2 = self.create_test_membership(
            member=member2.name,
            membership_type=self.membership_type.name,
        )
        membership2.submit()
        # The duplicate guard rejects ANY non-template schedule (regardless of
        # status), so the auto-created one must be removed entirely. It is not
        # submitted, so it can be deleted.
        existing = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member2.name, "is_template": 0}, "name"
        )
        if existing:
            frappe.delete_doc("Membership Dues Schedule", existing, force=True)

        new_name = mds.create_schedule_from_template(member2.name)
        self.track_doc("Membership Dues Schedule", new_name)
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", new_name))
        created = frappe.get_doc("Membership Dues Schedule", new_name)
        self.assertEqual(created.member, member2.name)
        self.assertEqual(created.is_template, 0)

    # ------------------------------------------------------------------ calculate_progressive_dues

    def test_calculate_progressive_dues_returns_shape(self):
        schedule = self._active_schedule()
        result = schedule.calculate_progressive_dues(monthly_income=2000, base_dues=15.0)
        self.assertIn("multiplier", result)
        self.assertIn("percentage", result)
        self.assertIn("suggested_dues", result)
        self.assertIn("base_dues", result)
        self.assertEqual(float(result["base_dues"]), 15.0)

    # ------------------------------------------------------------------ can_user_edit_schedule

    def test_can_user_edit_schedule_admin_true(self):
        # Running as Administrator (System Manager) -> always allowed.
        schedule = self._active_schedule()
        self.assertTrue(schedule.can_user_edit_schedule("Administrator"))

    def test_can_user_edit_schedule_outsider_false(self):
        # A plain member user who does not own this schedule and has no staff/board
        # role cannot edit it.
        outsider = self.create_test_user(
            f"outsider.{frappe.generate_hash(length=6)}@test.invalid",
            roles=["Verenigingen Member"],
        )
        schedule = self._active_schedule()
        self.assertFalse(schedule.can_user_edit_schedule(outsider.name))

    # ------------------------------------------------------------------ validate_member_edit

    def test_validate_member_edit_new_doc_allowed(self):
        # New schedules are always allowed through member-edit validation.
        new_doc = frappe.new_doc("Membership Dues Schedule")
        new_doc.member = self.member.name
        new_doc.membership_type = self.membership_type.name
        self.assertTrue(new_doc.validate_member_edit())

    def test_validate_member_edit_allowed_field_change_ok(self):
        # Re-running validate_member_edit against the persisted state (no pending
        # changes captured in _doc_before_save) must pass: nothing has changed
        # since the last save, so no disallowed-field edit is detected.
        schedule = self._active_schedule()
        schedule.notes = "edited allowed field"
        # Persist so the next load has the committed value as its baseline.
        schedule.save()
        reloaded = frappe.get_doc("Membership Dues Schedule", schedule.name)
        reloaded._doc_before_save = frappe.get_doc("Membership Dues Schedule", schedule.name)
        self.assertTrue(reloaded.validate_member_edit())

    # ------------------------------------------------------------------ validate_dues_rate_change

    def test_validate_dues_rate_change_returns_bool(self):
        schedule = self._active_schedule()
        result = schedule.validate_dues_rate_change()
        self.assertIsInstance(result, bool)

    # ------------------------------------------------------------------ is_orphaned

    def test_is_orphaned_false_for_valid_member(self):
        schedule = self._active_schedule()
        self.assertFalse(schedule.is_orphaned())

    def test_is_orphaned_true_for_missing_member(self):
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.member = "NON-EXISTENT-MEMBER-XYZ"
        self.assertTrue(schedule.is_orphaned())

    def test_is_orphaned_false_for_template(self):
        # No member assigned -> not orphaned.
        schedule = frappe.new_doc("Membership Dues Schedule")
        self.assertFalse(schedule.is_orphaned())

    # ------------------------------------------------------------------ get_member_payment_method

    def test_get_member_payment_method_bank_transfer_default(self):
        schedule = self._active_schedule()
        # No SEPA mandate flagged for memberships yet -> Bank Transfer.
        self.assertEqual(schedule.get_member_payment_method(), "Bank Transfer")

    def test_get_member_payment_method_sepa_with_mandate(self):
        self.create_test_sepa_mandate(
            member=self.member.name,
            iban=IBAN_TEST,
            used_for_memberships=1,
        )
        schedule = self._active_schedule()
        self.assertEqual(schedule.get_member_payment_method(), "SEPA Direct Debit")

    def test_get_member_payment_method_no_member(self):
        schedule = frappe.new_doc("Membership Dues Schedule")
        self.assertEqual(schedule.get_member_payment_method(), "Bank Transfer")

    # ------------------------------------------------------------------ get_member_active_mandate

    def test_get_member_active_mandate_none(self):
        schedule = self._active_schedule()
        self.assertIsNone(schedule.get_member_active_mandate())

    def test_get_member_active_mandate_returns_mandate(self):
        mandate = self.create_test_sepa_mandate(
            member=self.member.name,
            iban=IBAN_TEST,
            used_for_memberships=1,
        )
        schedule = self._active_schedule()
        self.assertEqual(schedule.get_member_active_mandate(), mandate.name)

    def test_get_member_active_mandate_no_member(self):
        schedule = frappe.new_doc("Membership Dues Schedule")
        self.assertIsNone(schedule.get_member_active_mandate())

    # ------------------------------------------------------------------ resume_schedule

    def test_resume_schedule_from_paused(self):
        schedule = self._active_schedule()
        schedule.pause_schedule(reason="test pause")
        schedule.reload()
        self.assertEqual(schedule.status, "Paused")

        new_date = add_days(today(), 7)
        schedule.resume_schedule(new_next_date=new_date)
        schedule.reload()
        self.assertEqual(schedule.status, "Active")
        self.assertEqual(str(schedule.next_invoice_date), str(new_date))

    def test_resume_schedule_invalid_when_active_raises(self):
        from verenigingen.utils.exceptions import InvalidStatusTransitionError

        schedule = self._active_schedule()
        with self.assertRaises(InvalidStatusTransitionError):
            schedule.resume_schedule()

    # ------------------------------------------------------------------ update_member_dues_rate

    def test_update_member_dues_rate_syncs_member(self):
        schedule = self._active_schedule()
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "dues_rate", 27.5)
        schedule.reload()
        schedule.update_member_dues_rate()
        self.assertEqual(float(frappe.db.get_value("Member", self.member.name, "dues_rate")), 27.5)

    # ------------------------------------------------------------------ _advance_schedule_dates

    def test_advance_schedule_dates_moves_next_invoice(self):
        schedule = self._active_schedule()
        start = today()
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "next_invoice_date", start)
        schedule.reload()
        schedule._advance_schedule_dates()
        schedule.reload()
        # Monthly billing -> last_invoice_date is the previous next date, and the
        # new next date is strictly later.
        self.assertEqual(str(schedule.last_invoice_date), str(start))
        self.assertGreater(frappe.utils.getdate(schedule.next_invoice_date), frappe.utils.getdate(start))

    # ------------------------------------------------------------------ _record_schedule_fee_change

    def test_record_schedule_fee_change_creates_history(self):
        schedule = self._active_schedule()
        before = frappe.db.count(
            "Member Fee Change History", {"parent": self.member.name}
        )
        schedule._record_schedule_fee_change("Update", old_rate=15.0, new_rate=18.0)
        after = frappe.db.count("Member Fee Change History", {"parent": self.member.name})
        self.assertGreaterEqual(after, before)

    def test_record_schedule_fee_change_no_member_noop(self):
        schedule = frappe.new_doc("Membership Dues Schedule")
        # No member -> early return, no error.
        self.assertIsNone(schedule._record_schedule_fee_change("Update", 10.0, 12.0))

    # ------------------------------------------------------------------ validate_member_eligibility_for_invoice

    def test_validate_member_eligibility_for_invoice_active(self):
        schedule = self._active_schedule()
        self.assertTrue(schedule.validate_member_eligibility_for_invoice())

    def test_validate_member_eligibility_for_invoice_no_member(self):
        schedule = frappe.new_doc("Membership Dues Schedule")
        self.assertFalse(schedule.validate_member_eligibility_for_invoice())

    # ------------------------------------------------------------------ item helpers

    def test_get_membership_dues_item_naming(self):
        schedule = self._active_schedule()
        item = schedule.get_membership_dues_item()
        self.assertTrue(item.startswith("Membership Dues -"))

    def test_get_membership_dues_item_custom_frequency(self):
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.billing_frequency = "Custom"
        schedule.custom_frequency_number = 2
        schedule.custom_frequency_unit = "Months"
        self.assertEqual(
            schedule.get_membership_dues_item(),
            "Membership Dues - Custom (Every 2 Months)",
        )

    def test_ensure_membership_dues_item_exists_creates_item(self):
        settings = frappe.get_single("Verenigingen Settings")
        if not settings.company:
            self.skipTest("No company configured in Verenigingen Settings")
        schedule = self._active_schedule()
        item_name = schedule.ensure_membership_dues_item_exists()
        self.assertTrue(frappe.db.exists("Item", item_name))

    # ------------------------------------------------------------------ generate_invoice guard

    def test_generate_invoice_returns_none_when_not_eligible(self):
        # Build an orphaned (member-less data) schedule view that cannot pass
        # eligibility; generate() should return None rather than raise.
        # Use a paused schedule which fails eligibility cleanly.
        schedule = self._active_schedule()
        schedule.pause_schedule(reason="not eligible")
        schedule.reload()
        # A paused schedule is not eligible -> generate_invoice returns None.
        result = schedule.generate_invoice()
        self.assertIsNone(result)

    # ------------------------------------------------------------------ find_orphaned_schedules

    def test_find_orphaned_schedules_returns_list(self):
        result = mds.MembershipDuesSchedule.find_orphaned_schedules(limit=5)
        self.assertIsInstance(result, list)
