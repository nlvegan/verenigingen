# -*- coding: utf-8 -*-
"""
Coverage tests for services/member/approval/membership_creation_service.py

This service is the documented reference implementation for multi-step
orchestration. Full create_membership_on_approval() runs are exercised by the
integration approval suites; here we pin the focused, independently-testable
units:
    - _validate_membership_creation_inputs() (defense-in-depth validation)
    - _validate_and_get_membership_type() (template requirement checks)
    - _resolve_dues_template() (applicant template selection + fallbacks)
"""

import frappe

from verenigingen.services.member.approval.membership_creation_service import (
    MembershipCreationService,
    get_membership_creation_service,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestValidateMembershipCreationInputs(VereningingenTestCase):
    """_validate_membership_creation_inputs() — defense-in-depth branches."""

    def setUp(self):
        super().setUp()
        self.service = MembershipCreationService()

    def test_missing_member_doc_throws(self):
        with self.assertRaises(frappe.ValidationError):
            self.service._validate_membership_creation_inputs(None)

    def test_wrong_doctype_throws(self):
        not_a_member = frappe.get_doc({"doctype": "Membership Type", "membership_type_name": "X"})
        with self.assertRaises(frappe.ValidationError):
            self.service._validate_membership_creation_inputs(not_a_member)

    def test_unsaved_member_throws(self):
        member = frappe.get_doc({"doctype": "Member", "first_name": "Un", "last_name": "Saved"})
        # name is None for an unsaved doc.
        with self.assertRaises(frappe.ValidationError):
            self.service._validate_membership_creation_inputs(member)

    def test_negative_custom_dues_rate_throws(self):
        member = self.create_test_member()
        with self.assertRaises(frappe.ValidationError):
            self.service._validate_membership_creation_inputs(member, custom_dues_rate=-1)

    def test_absurd_custom_dues_rate_throws(self):
        member = self.create_test_member()
        with self.assertRaises(frappe.ValidationError):
            self.service._validate_membership_creation_inputs(member, custom_dues_rate=999999)

    def test_non_numeric_custom_dues_rate_throws(self):
        member = self.create_test_member()
        with self.assertRaises(frappe.ValidationError):
            self.service._validate_membership_creation_inputs(member, custom_dues_rate="not-a-number")

    def test_non_dict_approval_fields_throws(self):
        member = self.create_test_member()
        with self.assertRaises(frappe.ValidationError):
            self.service._validate_membership_creation_inputs(member, approval_fields=["a", "b"])

    def test_valid_inputs_pass(self):
        member = self.create_test_member()
        # Should not raise: valid rate + dict approval fields, no start_date.
        self.service._validate_membership_creation_inputs(
            member, custom_dues_rate=12.5, approval_fields={"reviewed_by": "x"}
        )

    def test_csv_import_skips_start_date_window(self):
        """is_csv_import=True bypasses the historical-date-window check, so an
        old start_date does not raise."""
        member = self.create_test_member()
        # 10 years in the past would fail the 5-year window if not skipped.
        self.service._validate_membership_creation_inputs(
            member, start_date="2010-01-01", is_csv_import=True
        )


class TestValidateAndGetMembershipType(VereningingenTestCase):
    """_validate_and_get_membership_type() — template requirement checks."""

    def setUp(self):
        super().setUp()
        self.service = MembershipCreationService()

    def test_no_selected_type_throws(self):
        member = self.create_test_member()
        self.assertFalse(member.selected_membership_type)
        with self.assertRaises(frappe.ValidationError):
            self.service._validate_and_get_membership_type(member)

    def test_valid_type_with_template_returns_doc(self):
        mt = self.create_test_membership_type()
        member = self.create_test_member(selected_membership_type=mt.name)
        result = self.service._validate_and_get_membership_type(member)
        self.assertEqual(result.name, mt.name)

    def test_type_missing_template_and_no_application_template_throws(self):
        """A membership type whose dues_schedule_template is blanked, and a member
        with no application_dues_schedule, must raise."""
        mt = self.create_test_membership_type()
        # Blank the auto-linked template to simulate misconfiguration.
        frappe.db.set_value("Membership Type", mt.name, "dues_schedule_template", "")
        member = self.create_test_member(selected_membership_type=mt.name)
        member.reload()
        with self.assertRaises(frappe.ValidationError):
            self.service._validate_and_get_membership_type(member)


class TestResolveDuesTemplate(VereningingenTestCase):
    """_resolve_dues_template() — applicant-selected template validation."""

    def setUp(self):
        super().setUp()
        self.service = MembershipCreationService()

    def test_no_application_template_returns_none(self):
        mt = self.create_test_membership_type()
        member = self.create_test_member(selected_membership_type=mt.name)
        self.assertIsNone(self.service._resolve_dues_template(member, frappe.get_doc("Membership Type", mt.name)))

    def test_nonexistent_application_template_returns_none(self):
        mt = self.create_test_membership_type()
        member = self.create_test_member(selected_membership_type=mt.name)
        member.application_dues_schedule = "Nonexistent Schedule XYZ"
        result = self.service._resolve_dues_template(member, frappe.get_doc("Membership Type", mt.name))
        self.assertIsNone(result)

    def test_template_belonging_to_other_type_returns_none(self):
        """An application_dues_schedule whose template belongs to a DIFFERENT
        membership type is rejected and falls back to the default."""
        mt_a = self.create_test_membership_type()
        mt_b = self.create_test_membership_type()
        # Use mt_b's own template, but resolve against mt_a — type mismatch branch.
        other_template = mt_b.dues_schedule_template
        if not other_template or not frappe.db.get_value(
            "Membership Dues Schedule", other_template, "is_template"
        ):
            self.skipTest("No usable cross-type template in this environment")

        member = self.create_test_member(selected_membership_type=mt_a.name)
        member.application_dues_schedule = other_template
        result = self.service._resolve_dues_template(member, frappe.get_doc("Membership Type", mt_a.name))
        self.assertIsNone(result)

    def test_valid_template_for_type_returned(self):
        """A valid template for the membership type is returned as-is."""
        mt = self.create_test_membership_type()
        template_name = mt.dues_schedule_template
        if not template_name or not frappe.db.get_value(
            "Membership Dues Schedule", template_name, "is_template"
        ):
            self.skipTest("Membership type has no usable template in this environment")

        member = self.create_test_member(selected_membership_type=mt.name)
        member.application_dues_schedule = template_name
        result = self.service._resolve_dues_template(member, frappe.get_doc("Membership Type", mt.name))
        self.assertEqual(result, template_name)


class TestServiceAccessor(VereningingenTestCase):
    def test_accessor_returns_instance(self):
        svc = get_membership_creation_service()
        self.assertIsInstance(svc, MembershipCreationService)
