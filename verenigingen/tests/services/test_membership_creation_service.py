# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for approval/membership_creation_service.py.

Drives the MembershipCreationService end-to-end against REAL Member /
Membership Type / dues-schedule-template documents:
- full create_membership_on_approval happy path (membership + dues schedule
  + invoice + consolidated member updates)
- input validation (missing/invalid member, bad dues rate, bad approval fields)
- membership-type resolution + missing-template guard
- existing-membership reuse vs. wrong-type/too-old reject (retry scenario)
- custom dues rate / approval-field application
- create_invoice=False (historic CSV import) path
"""

import frappe

from verenigingen.services.member.approval.application_helpers import ensure_payment_modes_exist
from verenigingen.services.member.approval.membership_creation_service import (
    MembershipCreationService,
    get_membership_creation_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.non_resumable_errors import deadlock
from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
    MembershipDuesSchedule,
)


class TestMembershipCreationInputValidation(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = MembershipCreationService()
        self.member = self.create_test_member(
            first_name="Inval", last_name="Idate", email="invalidate@example.com"
        )

    def test_none_member_throws(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.service._validate_membership_creation_inputs(None)
        self.assertIn("Member document is required", str(ctx.exception))

    def test_wrong_doctype_throws(self):
        chapter = self.create_test_chapter(region="Zuid-Holland")
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.service._validate_membership_creation_inputs(chapter)
        self.assertIn("Invalid member document", str(ctx.exception))

    def test_negative_dues_rate_throws(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.service._validate_membership_creation_inputs(self.member, custom_dues_rate=-5)
        self.assertIn("non-negative", str(ctx.exception))

    def test_unreasonable_dues_rate_throws(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.service._validate_membership_creation_inputs(self.member, custom_dues_rate=50000)
        self.assertIn("unreasonably high", str(ctx.exception))

    def test_non_numeric_dues_rate_throws(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.service._validate_membership_creation_inputs(self.member, custom_dues_rate="not-a-number")
        self.assertIn("valid number", str(ctx.exception))

    def test_non_dict_approval_fields_throws(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.service._validate_membership_creation_inputs(
                self.member, approval_fields=["not", "a", "dict"]
            )
        self.assertIn("must be a dictionary", str(ctx.exception))


class TestValidateAndGetMembershipType(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = MembershipCreationService()
        self.mt = self.create_test_membership_type(membership_type_name="MCType", amount=20.0)

    def test_returns_type_when_template_present(self):
        member = self.create_test_member(
            first_name="HasType",
            last_name="Sel",
            email="hastype@example.com",
            selected_membership_type=self.mt.name,
        )
        result = self.service._validate_and_get_membership_type(member)
        self.assertEqual(result.name, self.mt.name)

    def test_no_selected_type_throws(self):
        member = self.create_test_member(first_name="NoType", last_name="Sel", email="notype@example.com")
        member.selected_membership_type = None
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.service._validate_and_get_membership_type(member)
        self.assertIn("No membership type selected", str(ctx.exception))

    def _build_type_without_template(self):
        """Setup helper: a Membership Type with no dues_schedule_template link."""
        import time

        role_profile = frappe.db.get_value("Role Profile", {"name": "Verenigingen Member"})
        bare = frappe.new_doc("Membership Type")
        bare.membership_type_name = f"NoTpl-{int(time.time() * 1000)}"
        bare.is_active = 1
        bare.minimum_amount = 10.0
        bare.contribution_mode = "Fixed Amount"
        if role_profile:
            bare.role_profile = role_profile
        bare.flags.ignore_after_insert_template_creation = True
        bare.insert(ignore_permissions=True)
        self.track_doc("Membership Type", bare.name)
        if bare.dues_schedule_template:
            bare.db_set("dues_schedule_template", None)
        return bare

    def test_missing_template_throws(self):
        bare = self._build_type_without_template()
        member = self.create_test_member(
            first_name="BareType",
            last_name="Sel",
            email="baretype@example.com",
            selected_membership_type=bare.name,
        )
        member.application_dues_schedule = None
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.service._validate_and_get_membership_type(member)
        self.assertIn("no dues schedule template configured", str(ctx.exception))


class TestCreateMembershipOnApproval(EnhancedTestCase):
    """Full orchestration happy path."""

    def setUp(self):
        super().setUp()
        ensure_payment_modes_exist()
        self.service = MembershipCreationService()
        self.mt = self.create_test_membership_type(membership_type_name="ApprovalType", amount=24.0)
        self.member = self.create_test_member(
            first_name="Full",
            last_name="Approve",
            email="fullapprove@example.com",
            contact_number="+31655556666",
            selected_membership_type=self.mt.name,
        )

    def test_happy_path_creates_membership_dues_schedule_and_invoice(self):
        membership = self.service.create_membership_on_approval(self.member, create_invoice=True)
        self.track_doc("Membership", membership.name)

        # Submitted Active membership of the right type
        self.assertEqual(membership.member, self.member.name)
        self.assertEqual(membership.membership_type, self.mt.name)
        self.assertEqual(membership.status, "Active")
        self.assertEqual(membership.docstatus, 1)

        # A non-template dues schedule exists for the member
        schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.member.name, "is_template": 0},
            "name",
        )
        self.assertTrue(schedule)

        # Member fields consolidated
        self.member.reload()
        self.assertEqual(self.member.current_membership_plan, membership.name)
        self.assertEqual(self.member.current_dues_schedule, schedule)
        # An invoice was created and submitted, linked to the member via the
        # Sales Invoice 'member' field (application_invoice is not a Member field
        # on this site, so the transient attr is not asserted here).
        inv = frappe.db.get_value(
            "Sales Invoice",
            {"member": self.member.name, "docstatus": 1, "is_membership_invoice": 1},
            "name",
        )
        self.assertTrue(inv)

    def test_create_invoice_false_skips_invoice(self):
        """create_invoice=False (historic import) creates no membership invoice."""
        membership = self.service.create_membership_on_approval(self.member, create_invoice=False)
        self.track_doc("Membership", membership.name)
        self.assertEqual(membership.status, "Active")
        # No submitted membership invoice was created for this member
        inv = frappe.db.get_value(
            "Sales Invoice",
            {"member": self.member.name, "is_membership_invoice": 1},
            "name",
        )
        self.assertFalse(inv)

    def test_approval_fields_are_applied(self):
        fields = {"application_status": "Approved"}
        self.member.flags.ignore_status_validation = True
        membership = self.service.create_membership_on_approval(
            self.member, create_invoice=False, approval_fields=fields
        )
        self.track_doc("Membership", membership.name)
        self.member.reload()
        self.assertEqual(self.member.application_status, "Approved")

    def test_custom_dues_rate_applied_to_schedule(self):
        """A custom dues rate flows into the created dues schedule's rate.

        The csv_import_custom_fee transient is consumed in-memory to seed the
        schedule and is NOT persisted on the Member; the originating amount is
        instead preserved durably on application_custom_fee for historical
        reference (see _consolidate_member_updates).
        """
        membership = self.service.create_membership_on_approval(
            self.member,
            create_invoice=False,
            custom_dues_rate=33.0,
            custom_rate_reason="Negotiated rate",
        )
        self.track_doc("Membership", membership.name)

        schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.member.name, "is_template": 0},
            ["name", "dues_rate"],
            as_dict=True,
        )
        self.assertTrue(schedule)
        self.assertAlmostEqual(float(schedule.dues_rate), 33.0, places=2)

        # The imported fee is preserved on the durable application_custom_fee
        # field (the transient csv_import_custom_fee gets cleared after use).
        self.member.reload()
        self.assertAlmostEqual(float(self.member.application_custom_fee), 33.0, places=2)

    def test_custom_dues_rate_does_not_clobber_existing_application_fee(self):
        """An existing application_custom_fee is not overwritten by the import fee.

        Web-application custom contributions are recorded on application_custom_fee
        before this service runs; the historical-preservation write must not stomp
        that value.
        """
        self.member.application_custom_fee = 99.0
        self.member.save()

        membership = self.service.create_membership_on_approval(
            self.member,
            create_invoice=False,
            custom_dues_rate=33.0,
            custom_rate_reason="Negotiated rate",
        )
        self.track_doc("Membership", membership.name)

        self.member.reload()
        self.assertAlmostEqual(float(self.member.application_custom_fee), 99.0, places=2)

    def test_reuse_existing_membership_on_retry(self):
        """Re-running approval reuses the same-day, same-type membership."""
        first = self.service.create_membership_on_approval(self.member, create_invoice=False)
        self.track_doc("Membership", first.name)

        self.member.reload()
        second = self.service.create_membership_on_approval(self.member, create_invoice=False)
        # Retry must reuse the existing membership, not create a duplicate
        self.assertEqual(second.name, first.name)


class TestEnsureDuesScheduleExistsNonResumableGuard(EnhancedTestCase):
    """`_ensure_dues_schedule_exists`'s catch-all is deliberately forgiving --
    "Don't fail approval if dues schedule creation fails" -- but that used to
    include 1213/1205, so a deadlock during dues-schedule creation was reported
    to the operator as a mere orange warning while the caller (a CSV import row)
    moved on to the next row against a transaction the server had discarded.
    """

    def setUp(self):
        super().setUp()
        ensure_payment_modes_exist()
        self.service = MembershipCreationService()
        self.mt = self.create_test_membership_type(membership_type_name="GuardType", amount=15.0)
        self.member = self.create_test_member(
            first_name="Guard",
            last_name="Dues",
            email="guarddues@example.com",
            selected_membership_type=self.mt.name,
        )
        self.membership = self.service._get_or_create_membership(self.member, self.mt, None, False)
        self.track_doc("Membership", self.membership.name)

    def test_a_deadlock_during_dues_schedule_creation_is_not_swallowed_as_a_warning(self):
        original = MembershipDuesSchedule.create_from_template

        def _boom(*args, **kwargs):
            raise deadlock()

        MembershipDuesSchedule.create_from_template = staticmethod(_boom)
        self.addCleanup(
            setattr, MembershipDuesSchedule, "create_from_template", staticmethod(original)
        )

        with self.assertRaises(frappe.QueryDeadlockError):
            self.service._ensure_dues_schedule_exists(self.member, self.membership, self.mt)

    def test_control_an_ordinary_failure_is_still_a_warning_not_a_raise(self):
        """Without this, the guard above could be satisfied by a change that
        made EVERY exception here propagate, not just the non-resumable two --
        which would turn "don't fail approval" into "always fail approval"."""
        original = MembershipDuesSchedule.create_from_template

        def _boom(*args, **kwargs):
            raise ValueError("ordinary template error")

        MembershipDuesSchedule.create_from_template = staticmethod(_boom)
        self.addCleanup(
            setattr, MembershipDuesSchedule, "create_from_template", staticmethod(original)
        )

        # Must not raise -- the whole point of this method is to degrade
        # gracefully for anything that isn't a destroyed transaction.
        self.service._ensure_dues_schedule_exists(self.member, self.membership, self.mt)


class TestResolveDuesTemplate(EnhancedTestCase):
    """_resolve_dues_template() validates an applicant-selected template and
    falls back to the membership type default on every mismatch."""

    def setUp(self):
        super().setUp()
        self.service = MembershipCreationService()
        self.mt = self.create_test_membership_type(membership_type_name="ResolveType", amount=20.0)
        self.member = self.create_test_member(
            first_name="Resolve",
            last_name="Tmpl",
            email="resolve.tmpl@example.com",
            selected_membership_type=self.mt.name,
        )
        # A dues-schedule instance requires the member to have an active membership.
        self.create_test_membership(member=self.member.name)

    def test_none_when_no_selection(self):
        """No applicant selection -> use the default (None)."""
        self.member.application_dues_schedule = None
        self.assertIsNone(self.service._resolve_dues_template(self.member, self.mt))

    def test_none_when_selected_template_missing(self):
        """A dangling application_dues_schedule reference falls back to default."""
        self.member.application_dues_schedule = "MDS-DOES-NOT-EXIST-9999"
        self.assertIsNone(self.service._resolve_dues_template(self.member, self.mt))

    def test_none_when_selection_is_not_a_template(self):
        """An instance (is_template=0) schedule is rejected as a template source."""
        instance = self.create_test_dues_schedule(
            member=self.member.name, membership_type=self.mt.name, amount=20.0
        )
        # Guard the branch we intend to exercise: this must be a non-template row.
        self.assertEqual(frappe.db.get_value("Membership Dues Schedule", instance.name, "is_template"), 0)
        self.member.application_dues_schedule = instance.name
        self.assertIsNone(self.service._resolve_dues_template(self.member, self.mt))

    def test_none_when_template_belongs_to_other_membership_type(self):
        """A valid template for a *different* membership type is rejected."""
        other = self.create_test_membership_type(membership_type_name="ResolveOther", amount=15.0)
        foreign = self.factory.ensure_dues_schedule_template(
            f"Resolve-Foreign-{self.factory.test_run_id}",
            {"membership_type": other.name, "dues_rate": 15.0},
        )
        self.member.application_dues_schedule = foreign.name
        self.assertIsNone(self.service._resolve_dues_template(self.member, self.mt))

    def test_returns_selection_when_valid_for_type(self):
        """A template that is a template and matches the type is used."""
        valid = self.factory.ensure_dues_schedule_template(
            f"Resolve-Valid-{self.factory.test_run_id}",
            {"membership_type": self.mt.name, "dues_rate": 20.0},
        )
        self.member.application_dues_schedule = valid.name
        self.assertEqual(self.service._resolve_dues_template(self.member, self.mt), valid.name)


class TestUpdateScheduleFromTemplate(EnhancedTestCase):
    """_update_schedule_from_template() copies template fields onto an existing
    instance schedule and stamps the template reference."""

    def setUp(self):
        super().setUp()
        self.service = MembershipCreationService()
        self.mt = self.create_test_membership_type(membership_type_name="UpdSchedType", amount=18.0)
        self.member = self.create_test_member(
            first_name="UpdSched",
            last_name="Tmpl",
            email="updsched.tmpl@example.com",
            selected_membership_type=self.mt.name,
        )
        # A dues-schedule instance requires the member to have an active membership.
        self.create_test_membership(member=self.member.name)

    def test_copies_distinctive_fields_and_stamps_reference(self):
        # Template carries the values we expect to be copied across. Rates stay
        # above the schedule's minimum (synced from the membership type) so the
        # financial-constraint validation passes on save.
        template = self.factory.ensure_dues_schedule_template(
            f"Upd-Src-{self.factory.test_run_id}",
            {"membership_type": self.mt.name, "dues_rate": 300.0, "billing_frequency": "Annual"},
        )
        # Instance starts on a different rate/frequency so the copy is observable.
        instance = self.create_test_dues_schedule(
            member=self.member.name, membership_type=self.mt.name, amount=150.0, frequency="monthly"
        )

        self.service._update_schedule_from_template(instance.name, template.name)

        updated = frappe.db.get_value(
            "Membership Dues Schedule",
            instance.name,
            ["dues_rate", "billing_frequency", "template_reference"],
            as_dict=True,
        )
        self.assertAlmostEqual(float(updated.dues_rate), 300.0, places=2)
        self.assertEqual(updated.billing_frequency, "Annual")
        self.assertEqual(updated.template_reference, template.name)


class TestSaveMemberWithRollbackRetry(EnhancedTestCase):
    """_save_member_with_rollback() recovers from a concurrent-write timestamp
    mismatch by reloading and re-applying member fields via the restore callback."""

    def setUp(self):
        super().setUp()
        self.service = MembershipCreationService()
        self.mt = self.create_test_membership_type(membership_type_name="RetryType", amount=24.0)
        self.member = self.create_test_member(
            first_name="Retry",
            last_name="Rollback",
            email="retry.rollback@example.com",
            selected_membership_type=self.mt.name,
        )
        self.membership = self.create_test_membership(member=self.member.name)

    def test_timestamp_mismatch_triggers_field_restore_and_retry(self):
        # Load the member, then mutate the same row out from under it so the
        # in-memory doc's timestamp is stale and the first save() raises
        # TimestampMismatchError (simulating a concurrent writer).
        member_doc = frappe.get_doc("Member", self.member.name)
        frappe.db.set_value("Member", self.member.name, "notes", "concurrent writer touched this")

        # restore_member_fields must re-apply current_membership_plan (always) and
        # the approval fields (here a validation-free notes write) after the reload.
        self.service._save_member_with_rollback(
            member_doc,
            self.membership,
            None,  # dues_schedule
            None,  # invoice
            {"notes": "approved via retry"},
        )

        self.member.reload()
        # The retry succeeded: the membership is still active (not rolled back) and
        # the restored fields persisted from the second save attempt.
        self.assertEqual(self.member.current_membership_plan, self.membership.name)
        self.assertEqual(self.member.notes, "approved via retry")
        self.assertEqual(frappe.db.get_value("Membership", self.membership.name, "docstatus"), 1)


class TestServiceAccessor(EnhancedTestCase):
    def test_get_service_returns_instance(self):
        self.assertIsInstance(get_membership_creation_service(), MembershipCreationService)
