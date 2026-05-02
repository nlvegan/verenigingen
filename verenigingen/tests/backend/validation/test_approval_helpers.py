# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Tests for extracted approval helper functions in membership_application_review.py

Tests the 7 helpers extracted during CC decomposition of approve_membership_application
(CC 50 -> 11), plus integration tests for the refactored main function.
"""

import time
from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.api.membership_application_review import (
    _activate_volunteer_if_requested,
    _build_approval_response,
    _calculate_billing_amount,
    _handle_idempotent_approval,
    _prepare_approval_fields,
    approve_membership_application,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestHandleIdempotentApproval(EnhancedTestCase):
    """Tests for _handle_idempotent_approval: checks if member already approved."""

    def test_returns_none_for_pending_member(self):
        """Pending member should not be treated as idempotent."""
        member = self.create_test_member(
            first_name="Pending",
            last_name="Member",
            status="Pending",
            application_status="Pending",
            birth_date=add_days(today(), -365 * 25),
        )
        if member.application_status != "Pending":
            member.db_set("application_status", "Pending", update_modified=False)

        result = _handle_idempotent_approval(member.name)
        self.assertIsNone(result)

    def test_returns_existing_data_for_approved_member(self):
        """Already-approved member should return idempotent response."""
        member = self.create_test_member(
            first_name="Approved",
            last_name="Member",
            status="Active",
            application_status="Approved",
            birth_date=add_days(today(), -365 * 30),
        )
        # Force approved status in DB
        member.db_set("application_status", "Approved", update_modified=False)
        member.db_set("status", "Active", update_modified=False)

        result = _handle_idempotent_approval(member.name)
        self.assertIsNotNone(result)
        self.assertTrue(result["success"])
        self.assertTrue(result["idempotent"])
        self.assertIn("already approved", result["message"].lower())

    def test_returns_none_for_nonexistent_member(self):
        """Non-existent member name should return None (no DB row found)."""
        result = _handle_idempotent_approval("NONEXISTENT-MEMBER-12345")
        self.assertIsNone(result)


class TestPrepareApprovalFields(EnhancedTestCase):
    """Tests for _prepare_approval_fields: builds approval fields dict."""

    def _make_member(self, **overrides):
        """Create a test member for field preparation tests."""
        defaults = {
            "first_name": "Prep",
            "last_name": "Fields",
            "birth_date": add_days(today(), -365 * 25),
            "status": "Pending",
            "application_status": "Pending",
        }
        defaults.update(overrides)
        return self.create_test_member(**defaults)

    def test_basic_fields_present(self):
        """All 6 required keys should be set correctly."""
        member = self._make_member()
        fields = _prepare_approval_fields(member, "Standard Member", None)

        self.assertEqual(fields["application_status"], "Approved")
        self.assertEqual(fields["status"], "Active")
        self.assertIn("member_since", fields)
        self.assertIn("reviewed_by", fields)
        self.assertIn("review_date", fields)
        self.assertEqual(fields["selected_membership_type"], "Standard Member")

    def test_includes_review_notes_when_provided(self):
        """Review notes should be included when a non-empty string is passed."""
        member = self._make_member()
        fields = _prepare_approval_fields(member, "Standard Member", "Good application")

        self.assertEqual(fields["review_notes"], "Good application")

    def test_excludes_review_notes_when_empty(self):
        """review_notes key should be absent when notes is None or empty."""
        member = self._make_member()

        fields_none = _prepare_approval_fields(member, "Standard Member", None)
        self.assertNotIn("review_notes", fields_none)

        fields_empty = _prepare_approval_fields(member, "Standard Member", "")
        self.assertNotIn("review_notes", fields_empty)

    def test_adds_fee_override_reason_when_dues_rate_set(self):
        """Auto-set fee_override_reason when member has custom dues_rate."""
        member = self._make_member()
        member.dues_rate = 50.0
        # Ensure no existing override reason
        if hasattr(member, "fee_override_reason"):
            member.fee_override_reason = None

        fields = _prepare_approval_fields(member, "Standard Member", None)
        self.assertEqual(fields["fee_override_reason"], "Application approval")

    def test_preserves_existing_fee_override_reason(self):
        """Existing fee_override_reason should NOT be overwritten."""
        member = self._make_member()
        member.dues_rate = 50.0
        member.fee_override_reason = "Board decision"

        fields = _prepare_approval_fields(member, "Standard Member", None)
        self.assertNotIn("fee_override_reason", fields)


class TestCalculateBillingAmount(EnhancedTestCase):
    """Tests for _calculate_billing_amount: 3-way fallback logic."""

    def test_prefers_invoice_grand_total(self):
        """Invoice grand_total should be preferred over member rate and type minimum."""
        member = frappe._dict(dues_rate=25.0)
        invoice = frappe._dict(grand_total=50.0)
        mt_doc = frappe._dict(minimum_amount=10.0)

        result = _calculate_billing_amount(member, invoice, mt_doc)
        self.assertEqual(result, 50.0)

    def test_falls_back_to_member_dues_rate(self):
        """When no invoice, member dues_rate should be used."""
        member = frappe._dict(dues_rate=25.0)
        mt_doc = frappe._dict(minimum_amount=10.0)

        result = _calculate_billing_amount(member, None, mt_doc)
        self.assertEqual(result, 25.0)

    def test_falls_back_to_membership_type_minimum(self):
        """When no invoice and no dues_rate, membership type minimum should be used."""
        member = frappe._dict(dues_rate=0)
        mt_doc = frappe._dict(minimum_amount=10.0)

        result = _calculate_billing_amount(member, None, mt_doc)
        self.assertEqual(result, 10.0)


class TestActivateVolunteerIfRequested(EnhancedTestCase):
    """Tests for _activate_volunteer_if_requested: 4-way branching logic.

    Tests the 3 non-activation branches. Full activation requires a real
    volunteer record + age validation, tested via integration tests.
    """

    def _make_member(self, interested=False):
        """Create a minimal member for volunteer activation tests."""
        member = self.create_test_member(
            first_name="Vol",
            last_name="Test",
            birth_date=add_days(today(), -365 * 25),
            status="Pending",
            application_status="Pending",
        )
        member.interested_in_volunteering = interested
        return member

    def test_returns_false_when_neither_interest_nor_flag(self):
        """No interest and no activation flag -> False."""
        member = self._make_member(interested=False)
        result = _activate_volunteer_if_requested(member, activate_as_volunteer=False)
        self.assertFalse(result)

    def test_returns_false_when_interest_only(self):
        """Interest but no activation flag -> False (deferred activation)."""
        member = self._make_member(interested=True)
        result = _activate_volunteer_if_requested(member, activate_as_volunteer=False)
        self.assertFalse(result)

    def test_returns_false_when_flag_but_no_interest(self):
        """Activation flag but no interest -> False (edge case guard)."""
        member = self._make_member(interested=False)
        result = _activate_volunteer_if_requested(member, activate_as_volunteer=True)
        self.assertFalse(result)


class TestBuildApprovalResponse(EnhancedTestCase):
    """Tests for _build_approval_response: pure response builder with 5-way user account status."""

    def _make_response(self, action=None, success=True, account_request=None):
        """Build a response with given user_creation_result params."""
        member = frappe._dict(name="MEM-001")
        invoice = frappe._dict(name="SINV-001")
        billing_amount = 25.0

        user_result = {"success": success}
        if action:
            user_result["action"] = action
        if account_request:
            user_result["account_request"] = account_request

        return _build_approval_response(member, invoice, billing_amount, user_result)

    def test_failed_user_creation(self):
        """Failed user creation should set status to 'failed'."""
        resp = self._make_response(success=False)
        self.assertEqual(resp["user_account_status"], "failed")
        self.assertTrue(resp["success"])

    def test_created_new_user(self):
        """Created new user should set status to 'created'."""
        resp = self._make_response(action="created_new")
        self.assertEqual(resp["user_account_status"], "created")

    def test_linked_existing_user(self):
        """Linked existing user should set status to 'linked'."""
        resp = self._make_response(action="linked_existing")
        self.assertEqual(resp["user_account_status"], "linked")

    def test_queued_secure_user(self):
        """Queued secure creation should set status to 'queued' with progress_tracking."""
        resp = self._make_response(action="queued_secure", account_request="ACR-001")
        self.assertEqual(resp["user_account_status"], "queued")
        self.assertIn("progress_tracking", resp)
        self.assertEqual(resp["progress_tracking"]["account_request_id"], "ACR-001")
        self.assertEqual(resp["progress_tracking"]["estimated_completion"], "2-3 minutes")

    def test_no_invoice(self):
        """When invoice is None, response invoice field should be None."""
        member = frappe._dict(name="MEM-002")
        user_result = {"success": False}
        resp = _build_approval_response(member, None, 0, user_result)
        self.assertIsNone(resp["invoice"])

    def test_response_has_all_required_keys(self):
        """Response must contain all 7 expected keys."""
        resp = self._make_response(action="created_new")
        expected_keys = {
            "success",
            "message",
            "invoice",
            "amount",
            "user_account",
            "user_account_status",
            "progress_tracking",
        }
        self.assertTrue(expected_keys.issubset(set(resp.keys())))


class TestApproveMainFunction(EnhancedTestCase):
    """Integration tests for the refactored approve_membership_application main function."""

    def setUp(self):
        super().setUp()

        self.membership_type = self.create_test_membership_type(
            membership_type_name="Approval Test Type",
            amount=25.0,
        )

        # Ensure dues schedule template is properly configured
        if self.membership_type.dues_schedule_template:
            template = frappe.get_doc(
                "Membership Dues Schedule", self.membership_type.dues_schedule_template
            )
            if not template.contribution_mode:
                template.db_set("contribution_mode", "Fixed", update_modified=False)
            if template.dues_rate < self.membership_type.minimum_amount:
                template.db_set(
                    "dues_rate", self.membership_type.minimum_amount, update_modified=False
                )

        # Clean up orphaned templates for this membership type
        orphans = frappe.get_all(
            "Membership Dues Schedule",
            filters={
                "membership_type": self.membership_type.name,
                "is_template": 1,
                "name": ["!=", self.membership_type.dues_schedule_template or ""],
            },
            pluck="name",
        )
        for orphan in orphans:
            frappe.db.delete("Membership Dues Schedule", {"name": orphan})
        if orphans:
            frappe.db.commit()

    def _create_pending_member(self, **extra):
        """Create a member in Pending state ready for approval."""
        unique_id = int(time.time() * 1000) % 100000
        defaults = {
            "first_name": "Approve",
            "last_name": f"Test{unique_id}",
            "email": f"approve.test.{unique_id}@example.com",
            "status": "Pending",
            "application_status": "Pending",
            "selected_membership_type": self.membership_type.name,
            "birth_date": add_days(today(), -365 * 25),
        }
        defaults.update(extra)
        member = self.create_test_member(**defaults)

        # Force pending status in DB if business logic overrode it
        if member.status != "Pending" or member.application_status != "Pending":
            member.db_set("status", "Pending", update_modified=False)
            member.db_set("application_status", "Pending", update_modified=False)
            member.reload()

        return member

    # Mock justified: External Service - SMTP delivery, not business logic
    @patch("frappe.sendmail")
    def test_approve_pending_member(self, _mock_sendmail):
        """Approving a pending member should set status to Approved/Active."""
        member = self._create_pending_member()

        result = approve_membership_application(
            member_name=member.name,
            membership_type=self.membership_type.name,
            notes="Test approval",
        )

        self.assertTrue(result["success"])
        self.assertNotEqual(result.get("idempotent"), True)

        # Verify member status changed
        member.reload()
        self.assertEqual(member.application_status, "Approved")
        self.assertEqual(member.status, "Active")

    # Mock justified: External Service - SMTP delivery, not business logic
    @patch("frappe.sendmail")
    def test_idempotent_approval(self, _mock_sendmail):
        """Calling approve on an already-approved member should return idempotent=True."""
        member = self._create_pending_member()

        # First approval
        approve_membership_application(
            member_name=member.name,
            membership_type=self.membership_type.name,
        )

        # Second approval should be idempotent
        result = approve_membership_application(
            member_name=member.name,
            membership_type=self.membership_type.name,
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["idempotent"])

    def test_rejects_non_pending_member(self):
        """Approving a rejected member should throw a validation error."""
        member = self._create_pending_member()
        member.db_set("application_status", "Rejected", update_modified=False)
        member.db_set("status", "Rejected", update_modified=False)

        with self.assertRaises(frappe.exceptions.ValidationError):
            approve_membership_application(
                member_name=member.name,
                membership_type=self.membership_type.name,
            )
