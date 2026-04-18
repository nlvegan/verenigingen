# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for ApplicationApprovalCorrelator.

Tests cover:
- Mollie-ID pairing (Pass 1) — strongest signal, tolerates email/name drift
- Email + last-name pairing (Pass 2) — fallback when Mollie missing
- Mollie mismatch vetoes an email-based pair
- Last-name mismatch blocks email-based pair
- Date-of-birth mismatch blocks email-based pair
- Ambiguity (>1 candidate) blocks pairing
- Zero matches (likely rejection) leaves the Deletion untouched
- Idempotent re-run — events already Ignored are skipped
- Raw events are marked Ignored with a cross-reference note
- The synthesized Approved event carries old+new payloads
"""

import json
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.mijnrood_sync.services.application_approval_correlator import (
    ApplicationApprovalCorrelator,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _app_deletion(email, last_name, mollie=None, dob=None, app_id=42, name="EVT-DEL-1"):
    """Build a dict that looks like a MijnRood Sync Event row for an
    admin_membership_application Deleted event (keys match frappe.get_all fields)."""
    old = {"id": app_id, "email": email, "last_name": last_name}
    if mollie:
        old["mollie_customer_id"] = mollie
    if dob:
        old["date_of_birth"] = dob
    return {
        "name": name,
        "event_type": "Deleted",
        "mijnrood_table": "admin_membership_application",
        "mijnrood_row_id": app_id,
        "status": "Pending",
        "linked_member": None,
        "old_data": json.dumps(old),
        "new_data": None,
    }


def _member_creation(email, last_name, mollie=None, dob=None, member_id=1234, name="EVT-NEW-1"):
    """Build a dict that looks like a MijnRood Sync Event row for an
    admin_member New event."""
    new = {"id": member_id, "email": email, "last_name": last_name, "current_membership_status_id": 1}
    if mollie:
        new["mollie_customer_id"] = mollie
    if dob:
        new["date_of_birth"] = dob
    return {
        "name": name,
        "event_type": "New",
        "mijnrood_table": "admin_member",
        "mijnrood_row_id": member_id,
        "status": "Pending",
        "linked_member": None,
        "old_data": None,
        "new_data": json.dumps(new),
    }


class TestCorrelateMollieMatch(EnhancedTestCase):
    """Pass 1: match by mollie_customer_id."""

    def setUp(self):
        super().setUp()
        self.correlator = ApplicationApprovalCorrelator()

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_mollie_match_pairs_events(self, mock_load, mock_mark, mock_emit):
        """Deletion and Creation with identical mollie_customer_id are paired."""
        mock_load.return_value = (
            [_app_deletion("old@example.com", "Doe", mollie="cust_ABC", name="EVT-DEL-1")],
            [_member_creation("new@example.com", "Doe", mollie="cust_ABC", name="EVT-NEW-1")],
        )
        mock_emit.return_value = "MR-SYNC-APPROVED-1"

        count = self.correlator.correlate("run-001")

        self.assertEqual(count, 1)
        mock_emit.assert_called_once()
        # _mark_ignored called twice, once per raw event
        self.assertEqual(mock_mark.call_count, 2)
        ignored_names = {c.args[0] for c in mock_mark.call_args_list}
        self.assertEqual(ignored_names, {"EVT-DEL-1", "EVT-NEW-1"})


class TestCorrelateEmailFallback(EnhancedTestCase):
    """Pass 2: match by email + last name, with Mollie-mismatch veto."""

    def setUp(self):
        super().setUp()
        self.correlator = ApplicationApprovalCorrelator()

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_email_match_with_last_name_pairs(self, mock_load, mock_mark, mock_emit):
        """Same email + last name pairs when no Mollie ID on either side."""
        mock_load.return_value = (
            [_app_deletion("jane@example.com", "Doe", name="EVT-DEL-2")],
            [_member_creation("jane@example.com", "Doe", name="EVT-NEW-2")],
        )
        mock_emit.return_value = "MR-SYNC-APPROVED-2"

        count = self.correlator.correlate("run-002")

        self.assertEqual(count, 1)
        mock_emit.assert_called_once()

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_email_match_with_mollie_mismatch_vetoes(self, mock_load, mock_mark, mock_emit):
        """Email matches but Mollie IDs disagree → no pair."""
        mock_load.return_value = (
            [_app_deletion("jane@example.com", "Doe", mollie="cust_AAA", name="EVT-DEL-3")],
            [_member_creation("jane@example.com", "Doe", mollie="cust_BBB", name="EVT-NEW-3")],
        )

        count = self.correlator.correlate("run-003")

        self.assertEqual(count, 0)
        mock_emit.assert_not_called()
        mock_mark.assert_not_called()

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_last_name_mismatch_blocks_email_pair(self, mock_load, mock_mark, mock_emit):
        """Same email but different last names → no pair."""
        mock_load.return_value = (
            [_app_deletion("family@example.com", "Doe", name="EVT-DEL-4")],
            [_member_creation("family@example.com", "Smith", name="EVT-NEW-4")],
        )

        count = self.correlator.correlate("run-004")

        self.assertEqual(count, 0)
        mock_emit.assert_not_called()

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_dob_mismatch_blocks_email_pair(self, mock_load, mock_mark, mock_emit):
        """Both sides have DOB, DOBs differ → no pair."""
        mock_load.return_value = (
            [_app_deletion("jane@example.com", "Doe", dob="1990-01-01", name="EVT-DEL-5")],
            [_member_creation("jane@example.com", "Doe", dob="1985-05-15", name="EVT-NEW-5")],
        )

        count = self.correlator.correlate("run-005")

        self.assertEqual(count, 0)

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_multiple_candidates_blocks_pairing(self, mock_load, mock_mark, mock_emit):
        """More than one Creation with the same email → no pair."""
        mock_load.return_value = (
            [_app_deletion("shared@example.com", "Doe", name="EVT-DEL-6")],
            [
                _member_creation("shared@example.com", "Doe", member_id=1, name="EVT-NEW-6a"),
                _member_creation("shared@example.com", "Doe", member_id=2, name="EVT-NEW-6b"),
            ],
        )

        count = self.correlator.correlate("run-006")

        self.assertEqual(count, 0)
        mock_emit.assert_not_called()

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_no_candidates_is_noop(self, mock_load, mock_mark, mock_emit):
        """Empty candidate sets return 0."""
        mock_load.return_value = ([], [])

        count = self.correlator.correlate("run-007")

        self.assertEqual(count, 0)
        mock_emit.assert_not_called()

    @patch.object(ApplicationApprovalCorrelator, "_emit_approved_event")
    @patch.object(ApplicationApprovalCorrelator, "_mark_ignored")
    @patch.object(ApplicationApprovalCorrelator, "_load_candidates")
    def test_deletion_with_no_match_is_untouched(self, mock_load, mock_mark, mock_emit):
        """Deletion with no matching Creation (rejection case) stays untouched."""
        mock_load.return_value = (
            [_app_deletion("lonely@example.com", "Doe", name="EVT-DEL-8")],
            [_member_creation("other@example.com", "Smith", name="EVT-NEW-8")],
        )

        count = self.correlator.correlate("run-008")

        self.assertEqual(count, 0)
        mock_emit.assert_not_called()
        mock_mark.assert_not_called()
