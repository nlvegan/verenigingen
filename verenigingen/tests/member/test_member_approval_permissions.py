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
from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.api.membership_application_review import approve_application
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.integration.test_application_record_approval import ApprovalCase


def _create_chapter_pending_applicant(test_case, chapter_name, suffix, tag):
    """A Pending applicant holding an ACTIVE Chapter Member row for `chapter_name`.

    `tag` only varies the generated name/email so fixtures cannot collide.

    The chapter-board permission checks match the caller's manageable chapters against
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


class TestMemberApprovalPermissions(ApprovalCase):
    """Regression: approve_application must work for non-Admin actors (Staff, Verenigingen Administrator).

    Driven through the real flow (submit -> confirm -> approve_application); the member-keyed
    approve_membership_application these tests used to call was removed in #1765.
    """

    def _approve_with_type(self, name):
        return approve_application(name, membership_type=self.membership_type.name, create_invoice=False)

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
        name = self._stage_and_confirm()

        with self.as_staff(), patch("frappe.sendmail"):  # Mock justified: External Service - SMTP delivery
            result = self._approve_with_type(name)

        self.assertTrue(result.get("success"), f"Approval failed for Verenigingen Staff: {result}")
        self.assertEqual(
            frappe.db.get_value("Member", {"email": self.email}, "application_status"),
            "Approved",
            "Member should be Approved after Staff approval",
        )

    def test_approval_succeeds_for_verenigingen_administrator_role(self):
        """The Verenigingen Administrator *role* (not the Administrator *user*)
        must also work. Administrator-the-user bypasses DocPerms; this test
        ensures the role itself grants enough access.
        """
        name = self._stage_and_confirm()

        with self.as_admin_role(), patch("frappe.sendmail"):  # Mock justified: External Service - SMTP delivery
            result = self._approve_with_type(name)

        self.assertTrue(result.get("success"), f"Approval failed for Verenigingen Administrator role: {result}")
        self.assertEqual(frappe.db.get_value("Member", {"email": self.email}, "application_status"), "Approved")

    def test_member_role_without_a_seat_cannot_approve(self):
        """A plain member (no board seat, no staff role) is refused, and nothing is written.

        Moved here from test_membership_approval (where it called the member-keyed endpoint): the
        permission gate is the entry point's, so it is tested on the entry point.
        """
        name = self._stage_and_confirm()
        limited_user = self.create_test_user_with_roles(
            email=f"limited.{frappe.generate_hash(length=6)}@example.com", roles=["Verenigingen Member"]
        )

        with self.as_user(limited_user.email), patch("frappe.sendmail"):  # Mock justified: SMTP delivery
            with self.assertRaises(frappe.PermissionError):
                self._approve_with_type(name)

        self.assertEqual(frappe.db.get_value("Membership Application Submission", name, "status"), "Pending Review")
        self.assertEqual(frappe.db.count("Member", {"email": self.email}), 0)


class TestBoardMemberApprovalPermissions(EnhancedTestCase):
    """The board-member tier. The #250 fix (a board member resolves to a VOLUNTEER's seat, not a
    Member's) is pinned for approve_application by test_application_record_approval
    (TestApproveApplicationBoard); the member-keyed approve tests that used to sit here were removed
    with the member-keyed endpoint (#1765). What stays is the one test that drives the service
    directly, past every chapter gate.
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


class TestBoardMemberRealShapePendingApplication(EnhancedTestCase):
    """#1518: production writes an applicant's Chapter Member row with
    status="Pending" (services/member/approval/application_helpers.py::
    create_pending_chapter_membership, called by materialise_member during
    approval), never "Active". The approval core calls member.save(), which
    Frappe routes through has_member_permission -> _is_member_in_chapters
    (permissions.py) for the write-permission check; an Active-only filter there
    would 403 a board member's approval of their own chapter's applicant.

    These drive has_member_permission directly against the real producer's row
    for the two states that must NOT grant write (disabled, Inactive). The
    positive half -- a board member approving their own chapter's application
    end to end -- is test_application_record_approval (TestApproveApplicationBoard).
    The member-keyed approve/reject/can_review_application tests that used to
    sit here were removed with those endpoints (#1765).
    """

    def setUp(self):
        super().setUp()
        if not frappe.db.exists("Membership Type", "Test Real Shape Membership"):
            mt = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "Test Real Shape Membership",
                "minimum_amount": 15,
                "is_active": 1,
                "role_profile": "Verenigingen Member",
            })
            mt.insert(ignore_permissions=True)
            self.factory.track_document("Membership Type", mt.name, priority=1)
        else:
            frappe.db.set_value(
                "Membership Type", "Test Real Shape Membership", "is_active", 1, update_modified=False
            )
        self.membership_type = "Test Real Shape Membership"

    def _create_real_shape_applicant(self, chapter_name, suffix):
        """A Pending applicant holding the Chapter Member row PRODUCTION
        actually writes: create_pending_chapter_membership(member, chapter_name),
        status="Pending", enabled=1.
        """
        from verenigingen.services.member.approval.application_helpers import (
            create_pending_chapter_membership,
        )

        unique = f"{suffix}{self.uid[:6]}"
        member = self.create_test_member(
            first_name=f"RealApplicant{unique}",
            last_name=f"Shape{self.uid[6:]}",
            email=f"real.applicant.{unique}.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
        )
        member.reload()
        member.application_status = "Pending"
        member.status = "Pending"
        member.selected_membership_type = self.membership_type
        member.save(ignore_permissions=True)
        member.reload()

        result = create_pending_chapter_membership(member, chapter_name)
        self.assertIsNotNone(
            result,
            "create_pending_chapter_membership must actually create the row, or this "
            "test would be exercising no row at all",
        )
        row_status = frappe.db.get_value(
            "Chapter Member", {"parent": chapter_name, "member": member.name}, "status"
        )
        self.assertEqual(
            row_status,
            "Pending",
            "premise check: production's own producer must write status='Pending'",
        )
        member.reload()
        return member





    def test_member_write_permission_denied_for_disabled_same_chapter_row(self):
        """#1518 review, SIGNIFICANT 2: `_is_member_in_chapters`'s own status
        filter (permissions.py, consumed by has_member_permission) was
        untested -- every existing disabled/inactive control above drives
        `get_pending_applications` (which listed Members through chapter_security.py's
        SQL until #1765), never permissions.py's. Drive `has_member_permission` directly
        (the write-permission gate `member.save()` triggers during approve/
        reject) for a same-chapter, disabled (enabled=0) row, so a mutant that
        drops `_is_member_in_chapters`'s status/enabled filter is caught here
        even if chapter_security.py's own filter is untouched.
        """
        chapter = self.ensure_test_chapter("TEST Real Shape Perm Disabled")
        board = self.create_test_board_member(chapter.name, permissions_level="Admin")
        applicant = self._create_real_shape_applicant(chapter.name, "permdisabled")

        row_name = frappe.db.get_value(
            "Chapter Member", {"parent": chapter.name, "member": applicant.name}, "name"
        )
        frappe.db.set_value("Chapter Member", row_name, "enabled", 0)

        with self.as_user(board.user):
            self.assertFalse(
                frappe.has_permission("Member", "write", doc=applicant.name),
                "a disabled Chapter Member row must not grant Member write permission",
            )
            applicant_doc = frappe.get_doc("Member", applicant.name)
            with self.assertRaises(frappe.PermissionError):
                applicant_doc.save()

    def test_member_write_permission_denied_for_inactive_same_chapter_row(self):
        """Same as above, for a same-chapter row whose status is 'Inactive'
        rather than disabled -- the two are independent axes on the child
        table (enabled=0 vs status='Inactive') and #1518's review asked for
        both to be covered against permissions.py's own filter directly.
        """
        chapter = self.ensure_test_chapter("TEST Real Shape Perm Inactive")
        board = self.create_test_board_member(chapter.name, permissions_level="Admin")
        applicant = self._create_real_shape_applicant(chapter.name, "perminactive")

        row_name = frappe.db.get_value(
            "Chapter Member", {"parent": chapter.name, "member": applicant.name}, "name"
        )
        frappe.db.set_value("Chapter Member", row_name, "status", "Inactive")

        with self.as_user(board.user):
            self.assertFalse(
                frappe.has_permission("Member", "write", doc=applicant.name),
                "an Inactive Chapter Member row must not grant Member write permission",
            )
            applicant_doc = frappe.get_doc("Member", applicant.name)
            with self.assertRaises(frappe.PermissionError):
                applicant_doc.save()


class TestBoardMemberJoinChapterEscalation(EnhancedTestCase):
    """#1518 review, CRITICAL 1: a SECOND, independent producer writes a
    Chapter Member row with status="Pending", enabled=1 --
    `member_manager.py::request_to_join`, reached via the real, whitelisted
    `Chapter.join_chapter` / `ChapterMembershipManager.join_chapter` portal
    endpoint an ALREADY-ACTIVE, already-approved member uses to request an
    ADDITIONAL chapter.

    The first #1518 fix round widened `can_user_manage_application` and
    `_is_member_in_chapters` (has_member_permission / has_membership_permission)
    to admit ANY Pending Chapter Member row, keyed only on the child row's own
    status. That is indistinguishable from this second producer's row, so it
    let the REQUESTED chapter's board read and write the member's entire,
    unrelated, already-approved record -- with no expiry, since the row stays
    Pending until a board member acts on the join request.

    Fixed by keying Pending-row admission on the target Member's OWN
    `application_status == "Pending"` (real applications have this; an
    already-approved member requesting an extra chapter does not -- their
    application_status stays "Approved").
    """

    def setUp(self):
        super().setUp()
        if not frappe.db.exists("Membership Type", "Test Escalation Membership"):
            mt = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "Test Escalation Membership",
                "minimum_amount": 15,
                "is_active": 1,
                "role_profile": "Verenigingen Member",
            })
            mt.insert(ignore_permissions=True)
            self.factory.track_document("Membership Type", mt.name, priority=1)
        else:
            frappe.db.set_value(
                "Membership Type", "Test Escalation Membership", "is_active", 1, update_modified=False
            )
        self.membership_type = "Test Escalation Membership"

    def _create_active_approved_member(self, home_chapter_name, suffix):
        """An already-Active, already-approved member with a home chapter --
        the state a REAL join_chapter caller always has (join_chapter is only
        reachable by an authenticated member with an existing Member record;
        `Chapter Join Request.validate_member_exists` independently requires
        `Member.status == "Active"` for its own, unrelated join flow, so an
        Active/Approved member is not a contrived state).
        """
        unique = f"{suffix}{self.uid[:6]}"
        member = self.create_test_member(
            first_name=f"ActiveJoiner{unique}",
            last_name=f"Escalation{self.uid[6:]}",
            email=f"active.joiner.{unique}.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
        )
        member.reload()
        member.application_status = "Approved"
        member.status = "Active"
        member.selected_membership_type = self.membership_type
        member.save(ignore_permissions=True)
        member.reload()
        # Home chapter membership -- setup only, not under test here, so the
        # ordinary fixture helper (an unambiguous Active row) is fine.
        self.add_member_to_test_chapter(member.name, home_chapter_name)
        return member

    def _request_to_join_additional_chapter(self, member_name, chapter_name):
        """The REAL producer of the escalation's Chapter Member row: the
        whitelisted portal endpoint an already-Active member calls to request
        an ADDITIONAL chapter, not a fixture standing in for it.
        """
        from verenigingen.verenigingen.doctype.chapter.chapter import join_chapter

        result = join_chapter(
            member_name=member_name, chapter_name=chapter_name, introduction="Escalation test"
        )
        self.assertTrue(
            result.get("success"),
            f"join_chapter must actually create the row, or this test exercises no row at all: {result}",
        )
        row = frappe.db.get_value(
            "Chapter Member",
            {"parent": chapter_name, "member": member_name},
            ["status", "enabled"],
            as_dict=True,
        )
        self.assertEqual(
            (row.status, row.enabled),
            ("Pending", 1),
            "premise check: request_to_join must write the SAME Pending, enabled shape "
            "as a real membership application, or this test is not exercising the escalation",
        )

    def test_join_chapter_pending_row_does_not_grant_access_to_active_member(self):
        """Measured on test_site_1 (matching the reviewer's test_site_7
        reproduction): an Active member M with home chapter A requests to
        join chapter B. Chapter B's board must be refused read AND write on
        M's Member record: M is not their applicant to manage, regardless of the
        Pending row. (No application exists for a join request, so the
        application-review surfaces have nothing to refuse since #1765.)
        """
        chapter_a = self.ensure_test_chapter("TEST Escalation Home A")
        chapter_b = self.ensure_test_chapter("TEST Escalation Requested B")
        board_b = self.create_test_board_member(chapter_b.name, permissions_level="Admin")
        member = self._create_active_approved_member(chapter_a.name, "esc")

        self._request_to_join_additional_chapter(member.name, chapter_b.name)

        with self.as_user(board_b.user):
            self.assertFalse(
                frappe.has_permission("Member", "read", doc=member.name),
                "chapter B's board must not gain READ on an unrelated Active member "
                "via that member's join-chapter request for chapter B",
            )
            self.assertFalse(
                frappe.has_permission("Member", "write", doc=member.name),
                "chapter B's board must not gain WRITE on an unrelated Active member "
                "via that member's join-chapter request for chapter B",
            )

        member.reload()
        self.assertEqual(member.application_status, "Approved")
        self.assertEqual(member.status, "Active")

    def test_escalation_guard_keys_on_application_status_not_member_status(self):
        """Regression guard for the specific field choice: `application_status`,
        not `status`. In the ordinary flow above the two happen to agree
        (Active member has status='Active', application_status='Approved'),
        so simply swapping which field the fix reads would still pass THAT
        test -- it needs a row where the fields diverge to actually
        discriminate.

        The diverging state constructed here -- `status='Pending'` while
        `application_status` is NOT 'Pending' -- is NOT reachable through any
        current production path: every writer of Member.status was grepped and
        none produces this combination. It is set directly via
        `frappe.db.set_value`, bypassing the controller entirely, purely to
        make the two fields disagree. That is deliberate, not a claim about
        real data: it is the only state that distinguishes a guard keyed on
        `application_status` (correct: still refuses) from one keyed on
        `status` (wrong: would treat this as manageable) -- mutation testing
        confirms swapping the field in the query reddens only this test.
        """
        chapter_a = self.ensure_test_chapter("TEST Escalation Divergence A")
        chapter_b = self.ensure_test_chapter("TEST Escalation Divergence B")
        board_b = self.create_test_board_member(chapter_b.name, permissions_level="Admin")
        member = self._create_active_approved_member(chapter_a.name, "divergence")

        self._request_to_join_additional_chapter(member.name, chapter_b.name)

        # Diverge the two fields via a raw db.set_value -- not reachable through
        # any production writer (grepped) -- so status='Pending' while
        # application_status stays 'Approved'.
        frappe.db.set_value("Member", member.name, "status", "Pending", update_modified=False)
        member.reload()
        self.assertEqual(member.status, "Pending")
        self.assertEqual(member.application_status, "Approved")

        with self.as_user(board_b.user):
            self.assertFalse(
                frappe.has_permission("Member", "write", doc=member.name),
                "member.status='Pending' must NOT substitute for "
                "application_status='Pending' -- the member is still an "
                "already-approved application, just with an unrelated status value",
            )


if __name__ == "__main__":
    unittest.main()
