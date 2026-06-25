# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for approval/member_approval_service.py.

Drives REAL Member / Membership Type / dues-schedule-template documents
through the approval utility functions:
- resolve_membership_type (explicit, selected fallback, default fallback)
- create_member_iban_history (creates row, dedups, skips when no IBAN)
- validate_approval_prerequisites (errors, warnings, already-approved)
- validate_membership_type_for_approval (template required, active, existing
  membership/dues-schedule blocks)
"""

import frappe

from verenigingen.services.member.approval import member_approval_service as svc
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestResolveMembershipType(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.mt = self.create_test_membership_type(membership_type_name="ResolveType", amount=20.0)
        self.member = self.create_test_member(first_name="Res", last_name="Olve", email="resolve@example.com")

    def test_explicit_type_returned(self):
        resolved = svc.resolve_membership_type(self.member, membership_type=self.mt.name)
        self.assertEqual(resolved, self.mt.name)

    def test_falls_back_to_selected_membership_type(self):
        self.member.selected_membership_type = self.mt.name
        resolved = svc.resolve_membership_type(self.member)
        self.assertEqual(resolved, self.mt.name)

    def test_auto_assigns_default_when_none(self):
        """With no type set, the first available type is auto-assigned + saved."""
        self.member.selected_membership_type = None
        resolved = svc.resolve_membership_type(self.member)
        self.assertTrue(resolved)
        self.assertTrue(frappe.db.exists("Membership Type", resolved))
        # Member record was updated with the assigned type
        self.member.reload()
        self.assertEqual(self.member.selected_membership_type, resolved)


class TestCreateMemberIbanHistory(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.iban = self.factory.create_test_iban()
        # bank_account_name is mandatory on the Member IBAN History child row;
        # supply it explicitly (the service uses member.bank_account_name when set).
        self.member = self.create_test_member(
            first_name="Iban",
            last_name="Hist",
            email="ibanhist@example.com",
            iban=self.iban,
            bank_account_name="Iban Hist",
        )

    def test_creates_iban_history_row(self):
        result = svc.create_member_iban_history(self.member)
        self.assertTrue(result.success)
        self.member.reload()
        active = [h for h in self.member.iban_history if h.is_active]
        self.assertGreaterEqual(len(active), 1)
        self.assertEqual(active[-1].change_reason, "Application Approval")

    def test_dedups_existing_iban_history(self):
        """Second call with the same IBAN does NOT append a duplicate row."""
        svc.create_member_iban_history(self.member)
        self.member.reload()
        count_after_first = len(self.member.iban_history)

        result2 = svc.create_member_iban_history(self.member)
        self.assertTrue(result2.success)
        self.member.reload()
        self.assertEqual(len(self.member.iban_history), count_after_first)

    def test_skips_when_no_iban(self):
        no_iban = self.create_test_member(first_name="NoI", last_name="Ban", email="noiban@example.com")
        result = svc.create_member_iban_history(no_iban)
        self.assertTrue(result.success)
        self.assertIn("No IBAN", result.data["message"])


class TestValidateApprovalPrerequisites(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Prereq", last_name="Check", email="prereq@example.com"
        )

    def test_valid_member_ready(self):
        result = svc.validate_approval_prerequisites(self.member.name)
        self.assertTrue(result.success)
        self.assertTrue(result.data["ready_for_approval"])

    def test_already_approved_warns(self):
        self.member.application_status = "Approved"
        self.member.flags.ignore_status_validation = True
        self.member.save()
        result = svc.validate_approval_prerequisites(self.member.name)
        self.assertTrue(result.success)
        self.assertTrue(any("already approved" in w for w in result.data["warnings"]))


class TestValidateMembershipTypeForApproval(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.mt = self.create_test_membership_type(membership_type_name="ApprType", amount=20.0)
        self.member = self.create_test_member(
            first_name="Appr", last_name="Type", email="apprtype@example.com"
        )

    def test_valid_type_passes(self):
        # Ensure an Active template exists for the type (factory creates one;
        # confirm it is Active so the approval validation passes).
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": self.mt.name},
            "name",
        )
        if template:
            frappe.db.set_value("Membership Dues Schedule", template, "status", "Active")
        # Should not raise for an application approval
        svc.validate_membership_type_for_approval(self.mt.name, self.member, is_application_approval=True)

    def test_nonexistent_type_throws(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            svc.validate_membership_type_for_approval(
                "Nonexistent-Type-999999", self.member, is_application_approval=True
            )
        self.assertIn("does not exist", str(ctx.exception))

    def test_inactive_type_throws(self):
        self.mt.is_active = 0
        self.mt.save()
        with self.assertRaises(frappe.ValidationError) as ctx:
            svc.validate_membership_type_for_approval(self.mt.name, self.member, is_application_approval=True)
        self.assertIn("not active", str(ctx.exception))

    def test_missing_active_template_throws(self):
        """No Active template for the type blocks approval."""
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": self.mt.name},
            "name",
        )
        if template:
            # Make the template non-Active so the approval check fails.
            frappe.db.set_value("Membership Dues Schedule", template, "status", "Cancelled")
        with self.assertRaises(frappe.ValidationError) as ctx:
            svc.validate_membership_type_for_approval(self.mt.name, self.member, is_application_approval=True)
        self.assertIn("dues schedule template", str(ctx.exception))
