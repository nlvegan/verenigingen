# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
#1453: approve_membership_application_background shares #1414's existence-oracle
shape on its own HIGH-tier population, in a different module
(verenigingen/api/background_approval_api.py) from the one #1414/#1458 fixed
(verenigingen/api/membership_application_review.py).

Before this fix:
- an unknown member_name hit ``frappe.db.exists("Member", ...)`` BEFORE the
  chapter-permission check, and was caught by the function's own generic
  ``except Exception`` and re-thrown as "Invalid input data provided";
- an existing-but-foreign member_name (in a chapter the caller cannot manage)
  that was NOT "Pending" hit the application_status check next, which raised a
  DIFFERENT message ("This application cannot be approved in its current
  state");
- only an existing-but-foreign member_name that WAS "Pending" reached
  ``validate_chapter_permission_or_throw`` and got the permission-denial
  message.

So a caller scoped to specific chapters (not "all") could distinguish THREE
populations by the resulting OperationResult.errors content: unknown,
foreign-Pending, foreign-non-Pending. Fix: run
validate_chapter_permission_or_throw before the existence check AND the status
check, matching the #1414/#1458 design (reusing
``_sanitize_member_name_for_review`` / ``_check_member_exists_for_review``
from membership_application_review.py rather than a third copy).

approve_membership_application_background never raises to its caller -- every
exception is caught by its own outermost ``except Exception`` and converted to
``OperationResult.fail(...)``, so these tests compare the returned
OperationResult's ``error_message``/``errors`` content (not exception type),
plus the message_log and the API Audit Log row count, across the two
populations.
"""

import unittest

import frappe
from frappe.utils import add_days, today

from verenigingen.api.background_approval_api import approve_membership_application_background
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.member.test_member_approval_permissions import (
    _create_chapter_pending_applicant,
    _message_log_contents,
)


class TestBackgroundApprovalExistenceOracle(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        if not frappe.db.exists("Membership Type", "Test BG Oracle Membership"):
            mt = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test BG Oracle Membership",
                    "minimum_amount": 15,
                    "is_active": 1,
                    "role_profile": "Verenigingen Member",
                }
            )
            mt.insert(ignore_permissions=True)
            self.factory.track_document("Membership Type", mt.name, priority=1)
        else:
            frappe.db.set_value(
                "Membership Type", "Test BG Oracle Membership", "is_active", 1, update_modified=False
            )
        self.membership_type = "Test BG Oracle Membership"

        own_chapter = self.ensure_test_chapter("TEST BG Oracle Board Own")
        other_chapter = self.ensure_test_chapter("TEST BG Oracle Board Other")
        self.board = self.create_test_board_member(own_chapter.name, permissions_level="Admin")
        self.foreign_applicant = _create_chapter_pending_applicant(
            self, other_chapter.name, "bgoracle", "BGOracle"
        )
        self.unknown_member_name = f"NONEXISTENT-BG-ORACLE-{frappe.generate_hash(length=10)}"

    def _make_foreign_applicant_non_pending(self):
        """A second foreign applicant, identical to self.foreign_applicant except
        for application_status -- isolates the STATUS channel (#1453's second
        channel) from the existence channel already covered by
        self.foreign_applicant/self.unknown_member_name."""
        other_chapter = self.ensure_test_chapter("TEST BG Oracle Board Other")
        applicant = _create_chapter_pending_applicant(
            self, other_chapter.name, "bgoraclenp", "BGOracleNP"
        )
        applicant.application_status = "Rejected"
        applicant.save(ignore_permissions=True)
        applicant.reload()
        return applicant

    @staticmethod
    def _audit_log_count():
        return frappe.db.count("API Audit Log", {"event_type": "unauthorized_access_attempt"})

    @staticmethod
    def _success(result):
        """approve_membership_application_background is wrapped by the security
        decorators, which serialize its OperationResult return value via
        ``to_dict()`` (nested schema) even for a direct Python call -- so the
        caller sees a plain dict, not an OperationResult instance."""
        return result["success"]

    @staticmethod
    def _result_message(result):
        return result["error"]["message"]

    @staticmethod
    def _result_errors(result):
        return result["error"]["errors"]

    def test_unknown_and_foreign_pending_refused_identically_for_scoped_board_member(self):
        """Existence channel: an unknown id and a foreign-but-Pending id must
        produce the identical failure for a scoped caller."""
        with self.as_user(self.board.user):
            frappe.clear_messages()
            before_audit = self._audit_log_count()
            unknown_result = approve_membership_application_background(
                member_name=self.unknown_member_name,
                membership_type=self.membership_type,
                create_invoice=False,
            )
            unknown_log = frappe.get_message_log()
            after_unknown_audit = self._audit_log_count()

            frappe.clear_messages()
            foreign_result = approve_membership_application_background(
                member_name=self.foreign_applicant.name,
                membership_type=self.membership_type,
                create_invoice=False,
            )
            foreign_log = frappe.get_message_log()
            after_foreign_audit = self._audit_log_count()

        self.assertFalse(self._success(unknown_result))
        self.assertFalse(self._success(foreign_result))
        self.assertEqual(
            self._result_message(unknown_result),
            self._result_message(foreign_result),
            "an unknown member_name must refuse with the identical top-level message as a foreign one",
        )
        self.assertEqual(
            self._result_errors(unknown_result),
            self._result_errors(foreign_result),
            "an unknown member_name must refuse with the identical error detail as a foreign one",
        )
        self.assertEqual(len(unknown_log), 1)
        self.assertEqual(
            _message_log_contents(unknown_log),
            _message_log_contents(foreign_log),
        )
        # The unauthorized_access_attempt audit row (#1414's "unknown-id oracle
        # via the security log") must NOT fire for a scoped caller before the
        # permission check -- neither call should have written one.
        self.assertEqual(before_audit, after_unknown_audit, "no audit row for a scoped caller's unknown id")
        self.assertEqual(
            after_unknown_audit, after_foreign_audit, "no audit row for a scoped caller's foreign id either"
        )

        self.foreign_applicant.reload()
        self.assertEqual(
            self.foreign_applicant.application_status,
            "Pending",
            "a denied approval must not have mutated application_status",
        )

    def test_unknown_and_foreign_non_pending_refused_identically_for_scoped_board_member(self):
        """Status channel (#1453's second finding): a foreign id that is NOT
        Pending must refuse identically to an unknown id too -- not with the
        status-specific message, which would leak application_status to a
        caller who cannot manage that member's chapter at all."""
        non_pending_applicant = self._make_foreign_applicant_non_pending()

        with self.as_user(self.board.user):
            frappe.clear_messages()
            unknown_result = approve_membership_application_background(
                member_name=self.unknown_member_name,
                membership_type=self.membership_type,
                create_invoice=False,
            )
            unknown_log = frappe.get_message_log()

            frappe.clear_messages()
            non_pending_result = approve_membership_application_background(
                member_name=non_pending_applicant.name,
                membership_type=self.membership_type,
                create_invoice=False,
            )
            non_pending_log = frappe.get_message_log()

        self.assertFalse(self._success(unknown_result))
        self.assertFalse(self._success(non_pending_result))
        self.assertEqual(self._result_message(unknown_result), self._result_message(non_pending_result))
        self.assertEqual(
            self._result_errors(unknown_result),
            self._result_errors(non_pending_result),
            "a foreign, non-Pending member_name must not raise the status-specific message "
            "for a scoped caller -- that would still leak application_status",
        )
        self.assertNotIn("current state", str(self._result_errors(non_pending_result)))
        self.assertEqual(len(unknown_log), 1)
        self.assertEqual(
            _message_log_contents(unknown_log),
            _message_log_contents(non_pending_log),
        )

        non_pending_applicant.reload()
        self.assertEqual(
            non_pending_applicant.application_status,
            "Rejected",
            "a denied approval must not have mutated application_status",
        )

    def test_own_chapter_pending_applicant_still_approvable_by_board_member(self):
        """Regression guard: the reorder must not break the legitimate path --
        a board member approving their OWN chapter's Pending applicant."""
        own_chapter = self.ensure_test_chapter("TEST BG Oracle Board Own")
        own_applicant = _create_chapter_pending_applicant(self, own_chapter.name, "bgoracleown", "BGOracleOwn")

        with self.as_user(self.board.user):
            result = approve_membership_application_background(
                member_name=own_applicant.name,
                membership_type=self.membership_type,
                create_invoice=False,
            )

        self.assertTrue(
            self._success(result),
            f"Board member could not approve their own chapter's applicant: {result}",
        )
        own_applicant.reload()
        self.assertEqual(own_applicant.application_status, "Approved")

    def test_unknown_member_still_distinguishable_for_staff(self):
        """A caller whose chapter access is "all" (Verenigingen Staff) may keep
        the distinguishable "Invalid member reference" -- existence reveals
        nothing extra to them (#1414 coordinator ruling, carried over to
        #1453)."""
        with self.as_staff():
            result = approve_membership_application_background(
                member_name=self.unknown_member_name,
                membership_type=self.membership_type,
                create_invoice=False,
            )

        self.assertFalse(self._success(result))
        self.assertTrue(
            any("Invalid member reference" in err for err in self._result_errors(result)),
            f"expected 'Invalid member reference' in errors, got: {self._result_errors(result)}",
        )


if __name__ == "__main__":
    unittest.main()
