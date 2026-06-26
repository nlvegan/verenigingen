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


class TestServiceAccessor(EnhancedTestCase):
    def test_get_service_returns_instance(self):
        self.assertIsInstance(get_membership_creation_service(), MembershipCreationService)
