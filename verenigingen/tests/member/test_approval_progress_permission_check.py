# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
#1484: get_approval_progress (verenigingen/api/background_approval_api.py) had NO
chapter-permission check at all -- unlike its sibling
approve_membership_application_background in the same file (#1453/#1487), which at
least called validate_chapter_permission_or_throw (in the wrong order, before the
fix). get_approval_progress called get_approval_background_job_status(member_name)
directly, with no check that the caller may manage that member's chapter.

Measured before this fix (test_site_2, console): a plain Chapter Board Member of
chapter A calling get_approval_progress(member_name=<chapter B applicant>) got
OperationResult.ok(...) back -- the call SUCCEEDED with no permission check at all.
The RQ Job doctype's own DocPerm (role=System Manager/Administrator only) means
get_approval_background_job_status's frappe.get_all("RQ Job", ...) call itself
raises frappe.PermissionError for any caller without System Manager, which that
function's own try/except swallows and returns as {"error": ""} -- so no REAL job
data is disclosed to a non-System-Manager caller today, for any member_name,
including the caller's own chapter's. That accidental wall is not a substitute for
an explicit check: it depends on RQ Job's unrelated DocPerm, not on chapter
membership, and it means the endpoint is silently non-functional for the very
Chapter Board Members and Staff it exists to serve, not just for attackers.

Every MEDIUM-tier caller who DOES clear RQ Job's own permission (System Manager or
Administrator) already gets "all" chapter access from
get_user_manageable_chapters() (SYSTEM_MANAGER is in that allow-list), so this fix
changes nothing for anyone who can currently see real data.

Fix: call validate_chapter_permission_or_throw(member_name, "view") before
delegating to get_approval_background_job_status, reusing the same helper
approve_membership_application_background already uses (#1453/#1487) rather than
inventing a second check. Unlike that write path, this is a read-only probe
(matching can_review_application, #1394) so it does NOT add a separate
existence-revealing check: an unknown member_name and a foreign one both fail
identically inside can_user_manage_application (zero Chapter Member rows either
way).

get_approval_progress never raises to its caller -- every exception (including the
PermissionError from validate_chapter_permission_or_throw) is caught by its own
outermost except Exception and converted to OperationResult.fail(...), so these
tests compare the returned OperationResult's error_message/errors content (not
exception type), plus the message_log and the Error Log row count, across an
unknown and a foreign member_name.
"""

import unittest

import frappe
from frappe.utils import add_days, today

from verenigingen.api.background_approval_api import get_approval_progress
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.member.test_member_approval_permissions import (
    _message_log_contents,
    _operation_error_message,
    _operation_errors,
    _operation_succeeded,
)


class TestApprovalProgressPermissionCheck(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.own_chapter = self.ensure_test_chapter("TEST Approval Progress Own")
        self.other_chapter = self.ensure_test_chapter("TEST Approval Progress Other")
        self.board = self.create_test_board_member(self.own_chapter.name, permissions_level="Admin")

        self.foreign_applicant = self.create_test_member(
            first_name="ProgressForeign",
            last_name=f"Applicant{self.uid[:6]}",
            email=f"progress.foreign.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
        )
        self.add_member_to_test_chapter(self.foreign_applicant.name, self.other_chapter.name)
        self.foreign_applicant.reload()

        self.own_applicant = self.create_test_member(
            first_name="ProgressOwn",
            last_name=f"Applicant{self.uid[:6]}",
            email=f"progress.own.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
        )
        self.add_member_to_test_chapter(self.own_applicant.name, self.own_chapter.name)
        self.own_applicant.reload()

        self.unknown_member_name = f"NONEXISTENT-PROGRESS-{frappe.generate_hash(length=10)}"

    @staticmethod
    def _approval_progress_error_log_count():
        return frappe.db.count("Error Log", {"method": "Get Approval Progress Error"})

    def test_foreign_chapter_board_member_is_refused(self):
        """Core regression: before the fix, this call SUCCEEDED (no permission
        check existed at all). A Chapter Board Member scoped to their own chapter
        must not be able to query another chapter's applicant."""
        with self.as_user(self.board.user):
            result = get_approval_progress(member_name=self.foreign_applicant.name)

        self.assertFalse(
            _operation_succeeded(result),
            f"a scoped board member must be refused for a foreign chapter's member, got: {result}",
        )
        self.assertTrue(
            any("permission" in err.lower() for err in _operation_errors(result)),
            f"expected a permission-denial message in errors, got: {result}",
        )

    def test_unknown_and_foreign_member_refused_identically_for_scoped_board_member(self):
        """Existence channel: an unknown id and a foreign id must produce the
        IDENTICAL failure for a scoped caller -- this endpoint is a read-only
        probe and must not distinguish 'doesn't exist' from 'exists, not yours'
        (matching can_review_application, #1394), on top of not exposing either."""
        with self.as_user(self.board.user):
            frappe.clear_messages()
            before_errors = self._approval_progress_error_log_count()
            unknown_result = get_approval_progress(member_name=self.unknown_member_name)
            unknown_log = frappe.get_message_log()
            after_unknown_errors = self._approval_progress_error_log_count()

            frappe.clear_messages()
            foreign_result = get_approval_progress(member_name=self.foreign_applicant.name)
            foreign_log = frappe.get_message_log()
            after_foreign_errors = self._approval_progress_error_log_count()

        self.assertFalse(_operation_succeeded(unknown_result))
        self.assertFalse(_operation_succeeded(foreign_result))
        self.assertEqual(
            _operation_error_message(unknown_result),
            _operation_error_message(foreign_result),
            "an unknown member_name must refuse with the identical top-level message as a foreign one",
        )
        self.assertEqual(
            _operation_errors(unknown_result),
            _operation_errors(foreign_result),
            "an unknown member_name must refuse with the identical error detail as a foreign one",
        )
        self.assertEqual(len(unknown_log), 1)
        self.assertEqual(
            _message_log_contents(unknown_log),
            _message_log_contents(foreign_log),
        )
        # Each denial is caught by get_approval_progress's own except block and
        # logged once via frappe.log_error("Get Approval Progress Error", ...) --
        # both populations must produce exactly one such row, not a differing count.
        self.assertEqual(after_unknown_errors - before_errors, 1)
        self.assertEqual(after_foreign_errors - after_unknown_errors, 1)

    def test_own_chapter_board_member_still_gets_a_response(self):
        """Regression guard: the new check must not additionally block a board
        member querying their OWN chapter's applicant. get_approval_progress
        still returns OperationResult.ok(...) for them -- exactly as it did
        before this fix (the RQ Job permission wall inside
        get_approval_background_job_status is a separate, pre-existing issue
        that this fix neither creates nor repairs)."""
        with self.as_user(self.board.user):
            result = get_approval_progress(member_name=self.own_applicant.name)

        self.assertTrue(
            _operation_succeeded(result),
            f"board member could not query their own chapter's applicant: {result}",
        )

    def test_staff_can_still_query_an_arbitrary_member(self):
        """Opposite-harm guard: a caller whose chapter access is "all"
        (Verenigingen Staff, #1101) must keep working for any member_name --
        the new check must not regress the legitimate broad-access path."""
        with self.as_staff():
            result = get_approval_progress(member_name=self.foreign_applicant.name)

        self.assertTrue(
            _operation_succeeded(result),
            f"a staff caller must not be refused for an arbitrary member: {result}",
        )

    @staticmethod
    def _measure_query_count(fn):
        """frappe's own assertQueryCount is a ceiling assertion (assertLessEqual)
        and does not expose the measured count, so it cannot compare two calls
        against EACH OTHER. Capture the raw SQL the same way it does (wrapping
        frappe.db.__class__.sql) instead of inventing a second mechanism.
        Returns the list of queries (not just the count) so a mismatch can be
        diffed rather than merely reported as two numbers."""
        queries = []
        orig_sql = frappe.db.__class__.sql

        def _counting_sql(*args, **kwargs):
            queries.append(args[0])
            return orig_sql(*args, **kwargs)

        # Query capture, not a fake: every call is forwarded to the real
        # frappe.db.__class__.sql, using the same mechanism frappe's own
        # assertQueryCount/recorder use internally; this test needs the raw
        # query LIST (not just a count) to diff unknown-vs-foreign ids
        # against each other.
        frappe.db.__class__.sql = _counting_sql  # Mock justified: Infrastructure
        try:
            fn()
        finally:
            frappe.db.__class__.sql = orig_sql  # Mock justified: Infrastructure - restore
        return queries

    def test_query_count_identical_for_unknown_and_foreign_member(self):
        """Query-count channel: validate_chapter_permission_or_throw runs the
        same Chapter Member lookup regardless of whether member_name exists, so
        an unknown id must not cost a different number of queries than a
        foreign one (which would itself be a side-channel).

        A cold cache makes the FIRST call of the test measure dozens of extra
        warm-up queries regardless of which id it is called with -- the first
        REFUSAL specifically, since that is what warms the Error Log
        naming/meta caches that get_approval_progress's own except-block
        frappe.log_error() call needs the first time it ever runs in this
        process (measured: 31 vs 8 with a same-branch warm-up omitted or
        using a DIFFERENT branch; 8 vs 8 once the warm-up call also takes the
        refusal branch).

        #1484 review round: an independent reviewer measured an intermittent
        1-in-5 mismatch (unknown=8, foreign=9) with a warm-up on the foreign id
        ONLY. 40/40 consecutive full-module runs here did not reproduce it
        (see the commit message for the investigation), which points at
        environment/timing state rather than an existence-dependent query --
        but a warm-up keyed on only ONE of the two ids cannot rule out a cache
        keyed on "has THIS SPECIFIC id been seen before", so warm up with BOTH
        ids, in the same order they are measured, before measuring either.
        This is the "measure each in a state reset the same way" option from
        that review, applied literally rather than trusting the 40/40 result
        alone to justify leaving the asymmetric warm-up in place."""
        with self.as_user(self.board.user):
            get_approval_progress(member_name=self.unknown_member_name)  # warm-up, uncounted
            get_approval_progress(member_name=self.foreign_applicant.name)  # warm-up, uncounted

            unknown_queries = self._measure_query_count(
                lambda: get_approval_progress(member_name=self.unknown_member_name)
            )
            foreign_queries = self._measure_query_count(
                lambda: get_approval_progress(member_name=self.foreign_applicant.name)
            )

        self.assertEqual(
            len(unknown_queries),
            len(foreign_queries),
            f"unknown id cost {len(unknown_queries)} queries, foreign id cost {len(foreign_queries)} -- "
            "a difference here would itself be a distinguishing side-channel\n"
            f"unknown queries: {unknown_queries}\n"
            f"foreign queries: {foreign_queries}",
        )


if __name__ == "__main__":
    unittest.main()
