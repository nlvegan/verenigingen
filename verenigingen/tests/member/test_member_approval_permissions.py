# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
Permission-tier regression tests for member approval.

The approval workflow is a HIGH-security operation that should be callable by
Verenigingen Staff and up. Frappe's Administrator user bypasses all DocPerms
(frappe/permissions.py:107), so a test that runs as Administrator silently
masks permission gaps for real Staff/Admin role users. These tests use the
EnhancedTestCase as_staff() and as_admin_role() helpers to exercise the flow
under the actual target roles.
"""

import unittest

import frappe
from frappe.utils import add_days, today

from verenigingen.api.membership_application_review import (
    approve_membership_application,
    reject_membership_application,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _create_chapter_pending_applicant(test_case, chapter_name, suffix, tag):
    """A Pending applicant holding an ACTIVE Chapter Member row for `chapter_name`.

    Shared by TestBoardMemberApprovalPermissions and
    TestApplicationReviewExistenceOracle below (duplicate-helper ratchet: keep
    this logic in ONE place rather than one copy per class). `tag` only varies
    the generated name/email so fixtures from the two classes cannot collide.

    can_user_manage_application() matches the caller's manageable chapters against
    `tabChapter Member` rows with enabled=1 AND status='Active', so an applicant
    without one is unreachable by any board member and the test would pass for the
    wrong reason.
    """
    unique = f"{suffix}{test_case.uid[:6]}"
    member = test_case.create_test_member(
        first_name=f"Applicant{unique}",
        last_name=f"{tag}{test_case.uid[6:]}",
        email=f"applicant.{tag.lower()}.{unique}.{test_case.uid}@test.invalid",
        birth_date=add_days(today(), -365 * 30),
    )
    test_case.add_member_to_test_chapter(member.name, chapter_name)
    member.reload()
    member.application_status = "Pending"
    member.status = "Pending"
    member.selected_membership_type = test_case.membership_type
    member.save(ignore_permissions=True)
    member.reload()
    return member


def _message_log_contents(log):
    """frappe.throw() appends a dict to message_log carrying a random,
    per-call `__frappe_exc_id` -- unrelated to member_name or existence, so
    comparing it would fail two calls that are otherwise identical. Strip it
    before comparing content.

    Module-level (duplicate-helper ratchet, like `_create_chapter_pending_applicant`
    above): shared with test_background_approval_existence_oracle.py (#1453),
    which compares the same message_log shape for a different endpoint.
    """
    return [{k: v for k, v in entry.items() if k != "__frappe_exc_id"} for entry in log]


class TestMemberApprovalPermissions(EnhancedTestCase):
    """Regression: approve_membership_application must work for non-Admin actors."""

    def setUp(self):
        super().setUp()
        # Reuse / ensure a default Membership Type exists (matches existing tests).
        # is_active=1 is required for approve_membership_application — the canonical
        # impl validates is_active before creating the Membership record.
        if not frappe.db.exists("Membership Type", "Test Approval Membership"):
            mt = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "Test Approval Membership",
                "minimum_amount": 15,
                "is_active": 1,
                "role_profile": "Verenigingen Member",
            })
            mt.insert(ignore_permissions=True)
            self.factory.track_document("Membership Type", mt.name, priority=1)
        else:
            # Ensure is_active=1 even if the type was created by a previous test
            frappe.db.set_value(
                "Membership Type", "Test Approval Membership", "is_active", 1, update_modified=False
            )
        self.membership_type = "Test Approval Membership"

    def _create_pending_member(self, suffix):
        """Create a Member in 'Pending' application_status ready for approval."""
        # Include uid to avoid Customer/Member name collisions across test runs
        # (EnhancedTestCase doesn't roll back Customer rows committed via member.save())
        unique = f"{suffix}{self.uid[:6]}"
        member = self.create_test_member(
            first_name=f"Pending{unique}",
            last_name=f"Approval{self.uid[6:]}",
            email=f"pending.approval.{unique}.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
        )
        member.reload()
        member.application_status = "Pending"
        member.status = "Pending"
        member.selected_membership_type = self.membership_type
        member.save(ignore_permissions=True)
        member.reload()
        return member

    def test_approval_succeeds_for_verenigingen_staff(self):
        """Verenigingen Staff IS allowed to approve memberships.

        Membership approval is a HIGH-security operation that, by design, is
        callable by "Verenigingen Staff and up" (see this module's docstring).
        The permission gate is
        ``chapter_security.get_user_manageable_chapters``, which grants Staff
        (alongside Verenigingen Administrator, System Manager and National Board)
        management of *all* chapters' applications. This test is the regression
        guard for that tier: any change that revokes Staff approval rights should
        be deliberate and update ``get_user_manageable_chapters`` + this test
        together.
        """
        member = self._create_pending_member("staff")

        with self.as_staff():
            result = approve_membership_application(
                member_name=member.name,
                membership_type=self.membership_type,
                create_invoice=False,
                notes="Approved by Verenigingen Staff",
            )

        self.assertTrue(
            result.get("success"),
            f"Approval failed for Verenigingen Staff: "
            f"{result.get('message') or result}",
        )
        member.reload()
        self.assertEqual(
            member.application_status, "Approved",
            "Member should be Approved after Staff approval",
        )

    def test_approval_succeeds_for_verenigingen_administrator_role(self):
        """The Verenigingen Administrator *role* (not the Administrator *user*)
        must also work. Administrator-the-user bypasses DocPerms; this test
        ensures the role itself grants enough access.
        """
        member = self._create_pending_member("adminrole")

        with self.as_admin_role():
            result = approve_membership_application(
                member_name=member.name,
                membership_type=self.membership_type,
                create_invoice=False,
                notes="Approved by Verenigingen Administrator role",
            )

        self.assertTrue(
            result.get("success"),
            f"Approval failed for Verenigingen Administrator role: "
            f"{result.get('message') or result}",
        )
        member.reload()
        self.assertEqual(member.application_status, "Approved")


class TestBoardMemberApprovalPermissions(EnhancedTestCase):
    """The board-member tier: the case that was broken for months and never tested.

    `chapter_security.get_user_manageable_chapters` resolved the caller's MEMBER name
    and compared it against `Chapter Board Member.volunteer`, which holds a VOLUNTEER
    name. Different namespaces, so the query never matched and a board member managed
    no chapters -- meaning they could not approve their own chapter's applicants at
    all. Fixed in #250.

    That fix had no positive test. `TestMemberApprovalPermissions` above covers only
    Staff and Verenigingen Administrator, both of which short-circuit
    get_user_manageable_chapters to "all" and never reach the board lookup;
    tests/services/test_chapter_board_chapters.py seats a real board member but stops
    at get_user_board_chapters and never reaches the approval gate. So nothing asserted
    that a board member CAN approve, which is the behaviour that was broken.

    Both tests here are needed. The positive one alone would also pass if the gate were
    replaced by `return True`, so the cross-chapter denial pins the boundary.
    """

    def setUp(self):
        super().setUp()
        if not frappe.db.exists("Membership Type", "Test Board Approval Membership"):
            mt = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "Test Board Approval Membership",
                "minimum_amount": 15,
                "is_active": 1,
                "role_profile": "Verenigingen Member",
            })
            mt.insert(ignore_permissions=True)
            self.factory.track_document("Membership Type", mt.name, priority=1)
        else:
            frappe.db.set_value(
                "Membership Type", "Test Board Approval Membership", "is_active", 1, update_modified=False
            )
        self.membership_type = "Test Board Approval Membership"

    def _create_pending_applicant(self, chapter_name, suffix):
        """See module-level `_create_chapter_pending_applicant`."""
        return _create_chapter_pending_applicant(self, chapter_name, suffix, "Board")

    def test_board_member_can_approve_own_chapter_applicant(self):
        """A non-admin board member approves an applicant in their own chapter.

        This is the regression guard for #250. Against the pre-#250 lookup it fails
        with a PermissionError, because the Member-vs-Volunteer namespace mismatch
        made get_user_manageable_chapters() return [].
        """
        chapter = self.ensure_test_chapter("TEST Board Approve Own")
        board = self.create_test_board_member(chapter.name, permissions_level="Admin")
        applicant = self._create_pending_applicant(chapter.name, "own")

        with self.as_user(board.user):
            result = approve_membership_application(
                member_name=applicant.name,
                membership_type=self.membership_type,
                create_invoice=False,
                notes="Approved by chapter board member",
            )

        self.assertTrue(
            result.get("success"),
            f"Board member could not approve their own chapter's applicant: "
            f"{result.get('message') or result}",
        )
        applicant.reload()
        self.assertEqual(applicant.application_status, "Approved")

    def test_board_member_cannot_approve_other_chapter_applicant(self):
        """A board seat grants approval for THAT chapter only, not globally.

        Without this, the positive test above would still pass if the gate were
        widened to allow everyone -- which is the failure mode a lookup fix is most
        likely to introduce.
        """
        own_chapter = self.ensure_test_chapter("TEST Board Approve Scope A")
        other_chapter = self.ensure_test_chapter("TEST Board Approve Scope B")
        board = self.create_test_board_member(own_chapter.name, permissions_level="Admin")
        outsider = self._create_pending_applicant(other_chapter.name, "other")

        with self.as_user(board.user):
            with self.assertRaises(frappe.PermissionError):
                approve_membership_application(
                    member_name=outsider.name,
                    membership_type=self.membership_type,
                    create_invoice=False,
                    notes="Should be denied - applicant belongs to another chapter",
                )

        outsider.reload()
        self.assertEqual(
            outsider.application_status, "Pending",
            "A denied approval must not have mutated application_status",
        )

    def test_permission_failure_during_creation_keeps_its_cause(self):
        """A permission failure inside membership creation must not lose its cause.

        `frappe.PermissionError` is raised bare by
        frappe/model/document.py::raise_no_permission_to, so `str(e)` is "". The
        service wrapped every exception as
        `frappe.throw(_("Error creating membership: {0}").format(str(e)))`, which
        rendered as a bare `Error creating membership: ` with nothing after the colon
        -- an operator sees that a membership could not be created but not that it
        was a permission problem, nor on which doctype.

        This test drives the service directly as a user with no Membership rights,
        bypassing the chapter gate that would otherwise reject earlier.
        """
        from verenigingen.services.member.approval.membership_creation_service import (
            MembershipCreationService,
        )

        applicant = self._create_pending_applicant(
            self.ensure_test_chapter("TEST Board Approve Cause").name, "cause"
        )
        plain_user = self.create_test_user(
            self.factory.generate_test_email("nomembership"), roles=["Verenigingen Member"]
        )
        member_doc = frappe.get_doc("Member", applicant.name)

        with self.as_user(plain_user.name):
            with self.assertRaises(frappe.PermissionError) as ctx:
                MembershipCreationService().create_membership_on_approval(
                    member_doc, create_invoice=False, approval_fields={}
                )

        # assertRaises(frappe.PermissionError) above IS the whole guard: before the
        # fix the service caught the PermissionError and re-threw it via frappe.throw,
        # which raises ValidationError, so this block raised ValidationError and the
        # test failed there.
        #
        # An assertNotIsInstance(ctx.exception, frappe.ValidationError) used to follow
        # and was deleted as tautological: frappe/exceptions.py declares
        # `class ValidationError(Exception)` and `class PermissionError(Exception)` as
        # siblings, so given the enclosing assertRaises it could never fail.
        self.assertEqual(str(ctx.exception), "", "bare PermissionError carries no message")


class TestApplicationReviewExistenceOracle(EnhancedTestCase):
    """#1414: approve_membership_application / reject_membership_application share
    #1394's existence-oracle shape on their own HIGH-tier population.

    _validate_member_for_review used to run BEFORE validate_chapter_permission_or_throw,
    so an unknown member_name raised a distinguishable ValidationError("Invalid member
    reference") while an existing-but-foreign one raised PermissionError from the
    chapter-permission check -- letting a non-staff Chapter Board Member (HIGH tier,
    not just staff) enumerate real Member ids.

    Coordinator ruling (#1414): a caller SCOPED to specific chapters (chapter access
    not "all") must get an IDENTICAL refusal for an unknown id and a foreign one. A
    caller whose chapter access covers every member ("all" -- staff/admin) may keep
    the distinguishable "Invalid member reference", since existence reveals nothing
    extra to them.
    """

    def setUp(self):
        super().setUp()
        if not frappe.db.exists("Membership Type", "Test Oracle Membership"):
            mt = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Oracle Membership",
                    "minimum_amount": 15,
                    "is_active": 1,
                    "role_profile": "Verenigingen Member",
                }
            )
            mt.insert(ignore_permissions=True)
            self.factory.track_document("Membership Type", mt.name, priority=1)
        else:
            frappe.db.set_value(
                "Membership Type", "Test Oracle Membership", "is_active", 1, update_modified=False
            )
        self.membership_type = "Test Oracle Membership"

        own_chapter = self.ensure_test_chapter("TEST Oracle Board Own")
        other_chapter = self.ensure_test_chapter("TEST Oracle Board Other")
        self.board = self.create_test_board_member(own_chapter.name, permissions_level="Admin")
        self.foreign_applicant = self._create_pending_applicant(other_chapter.name, "oracle")
        self.unknown_member_name = f"NONEXISTENT-ORACLE-{frappe.generate_hash(length=10)}"

    def _create_pending_applicant(self, chapter_name, suffix):
        """See module-level `_create_chapter_pending_applicant`.

        (own_chapter is deliberately NOT this member's chapter -- see
        test_board_member_cannot_approve_other_chapter_applicant above for why that
        matters to can_user_manage_application.)
        """
        return _create_chapter_pending_applicant(self, chapter_name, suffix, "Oracle")

    def test_approve_refuses_unknown_and_foreign_identically_for_scoped_board_member(self):
        with self.as_user(self.board.user):
            frappe.clear_messages()
            with self.assertRaises(frappe.PermissionError) as unknown_ctx:
                approve_membership_application(member_name=self.unknown_member_name)
            unknown_log = frappe.get_message_log()

            frappe.clear_messages()
            with self.assertRaises(frappe.PermissionError) as foreign_ctx:
                approve_membership_application(member_name=self.foreign_applicant.name)
            foreign_log = frappe.get_message_log()

        self.assertEqual(
            str(unknown_ctx.exception),
            str(foreign_ctx.exception),
            "an unknown member_name must refuse with the identical message as a foreign one",
        )
        self.assertEqual(len(unknown_log), 1)
        self.assertEqual(
            _message_log_contents(unknown_log),
            _message_log_contents(foreign_log),
        )

        self.foreign_applicant.reload()
        self.assertEqual(
            self.foreign_applicant.application_status,
            "Pending",
            "a denied approval must not have mutated application_status",
        )

    def test_reject_refuses_unknown_and_foreign_identically_for_scoped_board_member(self):
        with self.as_user(self.board.user):
            frappe.clear_messages()
            with self.assertRaises(frappe.PermissionError) as unknown_ctx:
                reject_membership_application(member_name=self.unknown_member_name, reason="test")
            unknown_log = frappe.get_message_log()

            frappe.clear_messages()
            with self.assertRaises(frappe.PermissionError) as foreign_ctx:
                reject_membership_application(member_name=self.foreign_applicant.name, reason="test")
            foreign_log = frappe.get_message_log()

        self.assertEqual(
            str(unknown_ctx.exception),
            str(foreign_ctx.exception),
            "an unknown member_name must refuse with the identical message as a foreign one",
        )
        self.assertEqual(len(unknown_log), 1)
        self.assertEqual(
            _message_log_contents(unknown_log),
            _message_log_contents(foreign_log),
        )

        self.foreign_applicant.reload()
        self.assertEqual(
            self.foreign_applicant.application_status,
            "Pending",
            "a denied rejection must not have mutated application_status",
        )

    def test_approve_unknown_member_still_distinguishable_for_all_chapter_access(self):
        """A caller whose chapter access is "all" (Verenigingen Staff) may keep the
        distinguishable "Invalid member reference" -- existence reveals nothing extra
        to them (#1414 coordinator ruling). Regression guard: staff UX (a clear error
        for a typo'd member_name) must survive this fix."""
        with self.as_staff():
            with self.assertRaises(frappe.ValidationError) as ctx:
                approve_membership_application(member_name=self.unknown_member_name)
        self.assertIn("Invalid member reference", str(ctx.exception))

    def test_reject_unknown_member_still_distinguishable_for_all_chapter_access(self):
        with self.as_staff():
            with self.assertRaises(frappe.ValidationError) as ctx:
                reject_membership_application(member_name=self.unknown_member_name, reason="test")
        self.assertIn("Invalid member reference", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
