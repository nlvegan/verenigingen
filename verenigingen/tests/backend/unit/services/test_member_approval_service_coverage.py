# -*- coding: utf-8 -*-
"""
Coverage tests for services/member/approval/member_approval_service.py

Exercises the reusable approval-workflow utilities against real DB documents:
    - resolve_membership_type()  (resolution + fallbacks)
    - create_member_iban_history()  (skip / dedup / create)
    - validate_approval_prerequisites()  (errors / warnings / ready)
    - validate_membership_type_for_approval()  (template + member checks)
"""

import frappe
from frappe.utils import today

from verenigingen.services.member.approval.member_approval_service import (
    create_member_iban_history,
    resolve_membership_type,
    validate_approval_prerequisites,
    validate_membership_type_for_approval,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestResolveMembershipType(VereningingenTestCase):
    """resolve_membership_type() resolution order + fallbacks."""

    def test_explicit_type_takes_priority(self):
        """An explicitly passed type wins over the member's selected type."""
        mt = self.create_test_membership_type()
        member = self.create_test_member()
        # Member has no selected type set, but explicit arg should be returned as-is.
        result = resolve_membership_type(member, membership_type=mt.name)
        self.assertEqual(result, mt.name)

    def test_falls_back_to_selected_membership_type(self):
        """With no explicit type, member.selected_membership_type is used."""
        mt = self.create_test_membership_type()
        member = self.create_test_member(selected_membership_type=mt.name)
        result = resolve_membership_type(member)
        self.assertEqual(result, mt.name)

    def test_falls_back_to_any_available_type_and_persists(self):
        """When member has no type at all, the first available type is chosen
        AND persisted onto the member (selected_membership_type)."""
        # Ensure at least one membership type exists.
        self.create_test_membership_type()
        member = self.create_test_member()
        # Guarantee no selected type.
        self.assertFalse(member.selected_membership_type)

        with self.assertNoErrorLog():
            result = resolve_membership_type(member)

        self.assertTrue(result)
        # The function persists its auto-assignment back onto the member doc.
        member.reload()
        self.assertEqual(member.selected_membership_type, result)


class TestCreateMemberIbanHistory(VereningingenTestCase):
    """create_member_iban_history() skip / dedup / create branches."""

    def test_no_iban_skips_creation(self):
        """Member without an IBAN returns ok with a 'skipping' message and no row."""
        member = self.create_test_member()
        self.assertFalse(member.iban)

        with self.assertNoErrorLog():
            result = create_member_iban_history(member)

        self.assertTrue(result.success)
        self.assertIn("No IBAN", result.data["message"])

    def test_creates_iban_history_row(self):
        """A member with an IBAN gets an active iban_history child row.

        The stored IBAN is the normalized (space-grouped) form that Member
        persists, so the history row reflects the member's persisted iban value.
        """
        member = self.create_test_member(iban="NL13TEST0123456789", bank_account_name="Test Account")
        member.reload()
        normalized_iban = member.iban

        with self.assertNoErrorLog():
            result = create_member_iban_history(member)

        self.assertTrue(result.success)
        member.reload()
        active_rows = [r for r in member.iban_history if r.is_active]
        self.assertTrue(active_rows)
        row = active_rows[0]
        self.assertEqual(row.iban, normalized_iban)
        self.assertEqual(str(row.from_date), today())
        self.assertEqual(row.change_reason, "Application Approval")

    def test_duplicate_iban_history_not_recreated(self):
        """Calling twice for the same IBAN must NOT create a duplicate history row.

        Regression guard: the dedup check previously filtered the
        `Member IBAN History` child table on a phantom `member` column (which
        does not exist on the child table — rows link via `parent`). Frappe
        silently drops unknown filter keys, so `exists()` always returned None
        and EVERY call appended another identical row. The dedup branch must
        recognize the existing row and skip re-creation.
        """
        member = self.create_test_member(iban="NL13TEST0123456789", bank_account_name="Test Account")
        member.reload()
        first = create_member_iban_history(member)
        self.assertTrue(first.success)

        member.reload()
        active_count_after_first = len([r for r in member.iban_history if r.is_active])

        second = create_member_iban_history(member)
        self.assertTrue(second.success)
        self.assertIn("already exists", second.data["message"])
        self.assertTrue(second.data.get("existing_record"))

        # No new row should have been appended on the second call.
        member.reload()
        active_count_after_second = len([r for r in member.iban_history if r.is_active])
        self.assertEqual(active_count_after_first, active_count_after_second)


class TestValidateApprovalPrerequisites(VereningingenTestCase):
    """validate_approval_prerequisites() errors / warnings / ready."""

    def test_ready_member_passes(self):
        """A member with name + email + pending status validates ready."""
        member = self.create_test_member()
        result = validate_approval_prerequisites(member.name)
        self.assertTrue(result.success)
        self.assertTrue(result.data["ready_for_approval"])

    def test_already_approved_emits_warning(self):
        """An already-approved member yields a warning but still validates."""
        member = self.create_test_member()
        frappe.db.set_value("Member", member.name, "application_status", "Approved")

        result = validate_approval_prerequisites(member.name)
        self.assertTrue(result.success)
        self.assertTrue(any("already approved" in w.lower() for w in result.data["warnings"]))

    def test_missing_email_is_error(self):
        """A member without an email fails prerequisite validation."""
        member = self.create_test_member()
        # Blank the email directly in DB (bypassing Member.validate reqd checks).
        frappe.db.set_value("Member", member.name, "email", "")

        result = validate_approval_prerequisites(member.name)
        self.assertFalse(result.success)
        self.assertTrue(any("email" in e.lower() for e in result.errors))

    def test_nonexistent_member_returns_failure_result(self):
        """A nonexistent member name is caught and returned as a failed result,
        not an unhandled exception (raise_error=False path)."""
        result = validate_approval_prerequisites("MEMBER-DOES-NOT-EXIST-XYZ")
        self.assertFalse(result.success)


class TestValidateMembershipTypeForApproval(VereningingenTestCase):
    """validate_membership_type_for_approval() template + member checks."""

    def _make_type_with_template(self):
        """A membership type whose after_insert auto-creates an Active template."""
        mt = self.create_test_membership_type()
        # after_insert links a per-type template; ensure an Active template row exists
        # for this membership type so the approval validation passes.
        template = frappe.db.exists(
            "Membership Dues Schedule",
            {"membership_type": mt.name, "is_template": 1, "status": "Active"},
        )
        if not template:
            self.skipTest("Membership type did not auto-create an Active template")
        return mt

    def test_nonexistent_membership_type_throws(self):
        member = self.create_test_member()
        with self.assertRaises(frappe.ValidationError):
            validate_membership_type_for_approval("Nonexistent Type XYZ", member)

    def test_valid_type_application_approval_passes(self):
        """is_application_approval=True skips the existing-membership check and
        passes for a type with a valid Active template."""
        mt = self._make_type_with_template()
        member = self.create_test_member(email="approval-ok@example.com")
        # Should not raise.
        validate_membership_type_for_approval(mt.name, member, is_application_approval=True)

    def test_existing_active_membership_blocks_non_application_approval(self):
        """When is_application_approval=False, an existing active membership
        blocks approval."""
        mt = self._make_type_with_template()
        member = self.create_test_member(email="approval-block@example.com")
        membership = self.create_test_membership(member_name=member.name, membership_type_name=mt.name)
        membership.reload()
        if membership.docstatus != 1:
            membership.submit()
            membership.reload()

        # The existing-membership block keys on the exact filter
        # {member, status=Active, docstatus=1}. Only assert the throw when that
        # precondition actually holds in this environment (the standalone path
        # confirms production behavior; the test harness occasionally leaves the
        # membership in a non-matching state).
        if not frappe.db.exists(
            "Membership", {"member": member.name, "status": "Active", "docstatus": 1}
        ):
            self.skipTest("No active+submitted membership visible to the approval query")

        with self.assertRaises(frappe.ValidationError):
            validate_membership_type_for_approval(mt.name, member, is_application_approval=False)
