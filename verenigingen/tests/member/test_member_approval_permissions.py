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


def _operation_succeeded(result):
    """Whether an OperationResult-shaped dict reports success.

    Several of these API endpoints (approve/reject/background-approval/
    approval-progress) are wrapped by the security decorators, which serialize
    the OperationResult return value via ``to_dict()`` (nested schema) even for
    a direct Python call -- so the caller sees a plain dict, not an
    OperationResult instance.

    Module-level (duplicate-helper ratchet, like `_message_log_contents`
    above): shared by test_background_approval_existence_oracle.py (#1453) and
    test_approval_progress_permission_check.py (#1484), which each compare
    this same result shape for a different endpoint in the same file.
    """
    return result["success"]


def _operation_error_message(result):
    return result["error"]["message"]


def _operation_errors(result):
    return result["error"]["errors"]


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


class TestBoardMemberRealShapePendingApplication(EnhancedTestCase):
    """#1518: production writes an applicant's Chapter Member row with
    status="Pending" (services/member/approval/application_helpers.py::
    create_pending_chapter_membership, called from the application submission
    flow), never "Active". chapter_security.can_user_manage_application's SQL
    required cm.status = 'Active', so a Chapter Board Member saw ZERO of their
    own chapter's real pending applications through get_pending_applications /
    can_review_application, and was refused by approve/reject too (both call
    the same function via validate_chapter_permission_or_throw).

    Every other test in this module -- including this file's own
    _create_chapter_pending_applicant -- uses add_member_to_test_chapter,
    which fabricates an ACTIVE row specifically so the (buggy) gate matches.
    None of them could ever see this bug. These use the real producer instead.

    A second, independent path to the same harm: approve/reject both call
    member.save(), which Frappe routes through has_member_permission ->
    _is_member_in_chapters (permissions.py) for the write-permission check.
    That helper carried the identical Active-only shape, so even after the
    chapter_security gate is fixed, the actual save() would still 403.
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

    def test_board_member_sees_real_shape_pending_application(self):
        chapter = self.ensure_test_chapter("TEST Real Shape Own")
        board = self.create_test_board_member(chapter.name, permissions_level="Admin")
        applicant = self._create_real_shape_applicant(chapter.name, "own")

        from verenigingen.api.membership_application_review import (
            can_review_application,
            get_pending_applications,
        )

        with self.as_user(board.user):
            applications = get_pending_applications()
            can_review = can_review_application(applicant.name)

        application_names = [a["name"] for a in applications]
        self.assertIn(
            applicant.name,
            application_names,
            "board member must see their own chapter's REAL-shape pending application",
        )
        self.assertTrue(can_review, "can_review_application must agree with get_pending_applications")

    def test_board_member_can_approve_real_shape_pending_application(self):
        chapter = self.ensure_test_chapter("TEST Real Shape Approve")
        board = self.create_test_board_member(chapter.name, permissions_level="Admin")
        applicant = self._create_real_shape_applicant(chapter.name, "approve")

        with self.as_user(board.user):
            result = approve_membership_application(
                member_name=applicant.name,
                membership_type=self.membership_type,
                create_invoice=False,
                notes="Approved by board member against the real applicant shape",
            )

        self.assertTrue(
            result.get("success"),
            f"Board member could not approve their own chapter's REAL-shape applicant: "
            f"{result.get('message') or result}",
        )
        applicant.reload()
        self.assertEqual(applicant.application_status, "Approved")

    def test_board_member_can_reject_real_shape_pending_application(self):
        chapter = self.ensure_test_chapter("TEST Real Shape Reject")
        board = self.create_test_board_member(chapter.name, permissions_level="Admin")
        applicant = self._create_real_shape_applicant(chapter.name, "reject")

        with self.as_user(board.user):
            result = reject_membership_application(
                member_name=applicant.name,
                reason="Test rejection against real applicant shape",
            )

        self.assertTrue(
            result.get("success"),
            f"Board member could not reject their own chapter's REAL-shape applicant: "
            f"{result.get('message') or result}",
        )
        applicant.reload()
        self.assertEqual(applicant.application_status, "Rejected")

    def test_board_member_cannot_see_or_act_on_other_chapters_real_shape_applicant(self):
        """Cross-chapter control: widening the status filter must not widen
        which CHAPTERS a board member may act on."""
        own_chapter = self.ensure_test_chapter("TEST Real Shape Cross Own")
        other_chapter = self.ensure_test_chapter("TEST Real Shape Cross Other")
        board = self.create_test_board_member(own_chapter.name, permissions_level="Admin")
        outsider = self._create_real_shape_applicant(other_chapter.name, "cross")

        from verenigingen.api.membership_application_review import (
            can_review_application,
            get_pending_applications,
        )

        with self.as_user(board.user):
            applications = get_pending_applications()
            can_review = can_review_application(outsider.name)

        application_names = [a["name"] for a in applications]
        self.assertNotIn(outsider.name, application_names)
        self.assertFalse(can_review)

        with self.as_user(board.user):
            with self.assertRaises(frappe.PermissionError):
                approve_membership_application(
                    member_name=outsider.name,
                    membership_type=self.membership_type,
                    create_invoice=False,
                )
        outsider.reload()
        self.assertEqual(
            outsider.application_status,
            "Pending",
            "a denied approval must not have mutated application_status",
        )

    def test_board_member_cannot_act_on_disabled_chapter_member_row(self):
        """A disabled (enabled=0) Chapter Member row must not grant access,
        even with the widened status filter."""
        chapter = self.ensure_test_chapter("TEST Real Shape Disabled")
        board = self.create_test_board_member(chapter.name, permissions_level="Admin")
        applicant = self._create_real_shape_applicant(chapter.name, "disabled")

        row_name = frappe.db.get_value(
            "Chapter Member", {"parent": chapter.name, "member": applicant.name}, "name"
        )
        frappe.db.set_value("Chapter Member", row_name, "enabled", 0)

        from verenigingen.api.membership_application_review import get_pending_applications

        with self.as_user(board.user):
            applications = get_pending_applications()

        application_names = [a["name"] for a in applications]
        self.assertNotIn(applicant.name, application_names)

    def test_board_member_cannot_act_on_inactive_chapter_member_row(self):
        """An Inactive Chapter Member row (a former member) must not grant
        access -- the widened filter is Active OR Pending, never Inactive."""
        chapter = self.ensure_test_chapter("TEST Real Shape Inactive")
        board = self.create_test_board_member(chapter.name, permissions_level="Admin")
        applicant = self._create_real_shape_applicant(chapter.name, "inactive")

        row_name = frappe.db.get_value(
            "Chapter Member", {"parent": chapter.name, "member": applicant.name}, "name"
        )
        frappe.db.set_value("Chapter Member", row_name, "status", "Inactive")

        from verenigingen.api.membership_application_review import get_pending_applications

        with self.as_user(board.user):
            applications = get_pending_applications()

        application_names = [a["name"] for a in applications]
        self.assertNotIn(applicant.name, application_names)

    def test_member_write_permission_denied_for_disabled_same_chapter_row(self):
        """#1518 review, SIGNIFICANT 2: `_is_member_in_chapters`'s own status
        filter (permissions.py, consumed by has_member_permission) was
        untested -- every existing disabled/inactive control above drives
        `get_pending_applications`, which goes through chapter_security.py's
        SQL, never permissions.py's. Drive `has_member_permission` directly
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
        M's Member record, and refused on every application-review surface --
        M is not their applicant to manage, regardless of the Pending row.
        """
        chapter_a = self.ensure_test_chapter("TEST Escalation Home A")
        chapter_b = self.ensure_test_chapter("TEST Escalation Requested B")
        board_b = self.create_test_board_member(chapter_b.name, permissions_level="Admin")
        member = self._create_active_approved_member(chapter_a.name, "esc")

        self._request_to_join_additional_chapter(member.name, chapter_b.name)

        from verenigingen.api.membership_application_review import (
            approve_membership_application,
            can_review_application,
            get_pending_applications,
            reject_membership_application,
        )

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
            self.assertFalse(
                can_review_application(member.name),
                "can_review_application must not treat a join-chapter request as "
                "a manageable application",
            )

            applications = get_pending_applications()
            application_names = [a["name"] for a in applications]
            self.assertNotIn(
                member.name,
                application_names,
                "an Active, already-approved member must never appear in the "
                "pending-applications list",
            )

            with self.assertRaises(frappe.PermissionError):
                approve_membership_application(
                    member_name=member.name,
                    membership_type=self.membership_type,
                    create_invoice=False,
                )
            with self.assertRaises(frappe.PermissionError):
                reject_membership_application(member_name=member.name, reason="should be refused")

        member.reload()
        self.assertEqual(
            member.application_status,
            "Approved",
            "a refused approve/reject attempt must not have mutated the member's "
            "application_status",
        )
        self.assertEqual(member.status, "Active")

    def test_escalation_guard_keys_on_application_status_not_member_status(self):
        """Regression guard for the specific field choice: `application_status`,
        not `status`. In the ordinary flow above the two happen to agree
        (Active member has status='Active', application_status='Approved'),
        so simply swapping which field the fix reads would still pass THAT
        test -- it needs a row where the fields diverge to actually
        discriminate. Constructed here: an Active, already-approved member
        whose `status` field has been independently reset to 'Pending' (e.g.
        by an unrelated administrative action), while `application_status`
        correctly still reads 'Approved'. A guard keyed on `member.status`
        would wrongly treat this as manageable; keyed on `application_status`
        it correctly does not.
        """
        chapter_a = self.ensure_test_chapter("TEST Escalation Divergence A")
        chapter_b = self.ensure_test_chapter("TEST Escalation Divergence B")
        board_b = self.create_test_board_member(chapter_b.name, permissions_level="Admin")
        member = self._create_active_approved_member(chapter_a.name, "divergence")

        self._request_to_join_additional_chapter(member.name, chapter_b.name)

        # Diverge the two fields: status flips to 'Pending' (e.g. some unrelated
        # administrative reset), application_status is untouched and still 'Approved'.
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
