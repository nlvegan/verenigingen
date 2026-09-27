# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
#1529: the Desk list-view permission queries for Member and Membership
(``get_member_permission_query`` / ``get_membership_permission_query``) must
grant a Chapter Board Member what the doc-level checks (``has_member_permission``
/ ``has_membership_permission``, both reached through ``frappe.has_permission``)
grant, for the ``enabled`` / Pending-application mechanism this fix touches.

Before this fix both queries matched ``Chapter Member.status = 'Active'``
only, which was simultaneously:

- too NARROW: it excluded the board's own chapter's real Pending applicant
  (the Chapter Member row ``application_helpers.create_pending_chapter_membership``
  writes), even though #1518 already grants that case doc-level via
  ``has_permission`` -> ``_is_member_in_chapters(include_pending=True)``.
- too WIDE: it matched a disabled row unconditionally, so a member who left
  (``remove_member(permanent=False)`` leaves ``enabled=0, status='Active'``)
  or was terminated (``disable_chapter_memberships_safe`` leaves
  ``enabled=0, status='Inactive'``) stayed LISTED for the source chapter's
  board even though ``has_permission`` (which #1518 also made check
  ``enabled``) already refused doc-level access.

Each test drives the underlying Chapter Member row through its REAL
production writer (never ``db.set_value``) and asserts that the list-view
result and the doc-level ``frappe.has_permission`` result AGREE on that
mechanism, and that both equal the expected verdict. Where a writer creates
a state that must NOT grant access, the test is a control: it plants the
real row the wrong behaviour would need to find.

NOT covered here: list and doc-level resolve the CALLING board user's own
Member identity through two different lookups (``get_member_name_for_user``,
which falls back to ``Member.email``, vs.
``get_user_chapter_memberships_cached``, which joins on ``Member.user``
only) -- a pre-existing asymmetry, unrelated to the enabled/Pending
mechanism this fix addresses, tracked separately as #1546. Every board
fixture in this file is built with both ``Member.user`` and email set
consistently (``create_test_board_member``), so these tests cannot see
that asymmetry either way.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.api.membership_application_review import approve_membership_application
from verenigingen.services.member.approval.application_helpers import create_pending_chapter_membership
from verenigingen.services.termination.termination_integration import disable_chapter_memberships_safe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestChapterBoardListPermissionMatchesDocLevel(EnhancedTestCase):
    """Compare the Desk list query against frappe.has_permission for every
    Chapter Member row-state a real writer produces, for a Chapter Board Member."""

    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter()
        self.other_chapter = self.create_test_chapter()
        self.board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")

        type_name = f"Test 1529 List Perm Type {self.uid[:6]}"
        if not frappe.db.exists("Membership Type", type_name):
            mt = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": type_name,
                    "minimum_amount": 15,
                    "is_active": 1,
                    "role_profile": "Verenigingen Member",
                }
            )
            mt.insert(ignore_permissions=True)
            self.factory.track_document("Membership Type", mt.name, priority=1)
        self.membership_type = type_name

    # ---- assertion helpers --------------------------------------------------

    def _listed(self, doctype, name):
        """Whether the board user's real Desk list query (permission_query_conditions
        + DocType read perm) returns `name`."""
        with self.as_user(self.board.user):
            return name in frappe.get_list(doctype, filters={"name": name}, pluck="name")

    def _doc_permission(self, doctype, name):
        """The doc-level channel a single-document open goes through."""
        return bool(frappe.has_permission(doctype, ptype="read", doc=name, user=self.board.user))

    def _assert_visibility(self, doctype, name, expected, label):
        listed = self._listed(doctype, name)
        doc_ok = self._doc_permission(doctype, name)
        self.assertEqual(
            doc_ok,
            expected,
            f"{label}: has_permission({doctype}, {name}) expected {expected}, got {doc_ok}",
        )
        self.assertEqual(
            listed,
            expected,
            f"{label}: list-view({doctype}, {name}) expected {expected}, got {listed}",
        )
        self.assertEqual(
            listed,
            doc_ok,
            f"{label}: list-view and doc-level DISAGREE for {doctype} {name} "
            f"(listed={listed}, doc_permission={doc_ok})",
        )

    def _fresh_chapter(self, chapter_name):
        return frappe.get_doc("Chapter", chapter_name)

    def _create_real_pending_applicant(self, suffix):
        """A real applicant: Member.status/application_status = Pending, ready to
        be handed to create_pending_chapter_membership. The
        ``save(ignore_permissions=True)`` mirrors
        application_helpers.create_member_from_application, which also writes
        these fields as a system user rather than the (not yet authenticated)
        applicant."""
        applicant = self.create_test_member(
            first_name="Applicant",
            last_name=f"{suffix}{self.uid}",
            email=f"applicant.{suffix.lower()}.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
        )
        applicant.application_status = "Pending"
        applicant.status = "Pending"
        applicant.selected_membership_type = self.membership_type
        applicant.save(ignore_permissions=True)
        applicant.reload()
        return applicant

    def _create_approved_active_member(self, suffix):
        """An already-approved, Active member -- NOT an applicant. Used to prove
        that a Pending Chapter Member row written by request_to_join must not
        grant access the way a real application's Pending row does."""
        member = self.create_test_member(
            first_name="Active",
            last_name=f"{suffix}{self.uid}",
            email=f"active.{suffix.lower()}.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
        )
        member.application_status = "Approved"
        member.status = "Active"
        member.save(ignore_permissions=True)
        member.reload()
        return member

    # ---- writer-produced states ----------------------------------------------

    def test_positive_control_active_member_of_own_chapter(self):
        """Baseline: a plain Active member of the board's own chapter must stay
        listed and permitted. The fix must not remove existing, legitimate access."""
        member = self.create_test_member(
            first_name="Active",
            last_name=f"Own{self.uid}",
            email=f"active.own.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
        )
        self.add_member_to_test_chapter(member.name, self.chapter.name)
        membership = self.create_test_membership(
            member_name=member.name, membership_type_name=self.membership_type
        )

        self._assert_visibility("Member", member.name, True, "active member, own chapter")
        self._assert_visibility(
            "Membership", membership.name, True, "active member's membership, own chapter"
        )

    def test_cross_chapter_active_member_not_visible(self):
        """An Active member of a DIFFERENT chapter must stay invisible to this
        board -- the fix must not become globally permissive."""
        member = self.create_test_member(
            first_name="Active",
            last_name=f"Other{self.uid}",
            email=f"active.other.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
        )
        self.add_member_to_test_chapter(member.name, self.other_chapter.name)
        membership = self.create_test_membership(
            member_name=member.name, membership_type_name=self.membership_type
        )

        self._assert_visibility("Member", member.name, False, "active member, other chapter")
        self._assert_visibility(
            "Membership", membership.name, False, "active member's membership, other chapter"
        )

    def test_application_submission_pending_applicant_visible(self):
        """A real applicant: Chapter Member row enabled=1/status=Pending, written by
        application_helpers.create_pending_chapter_membership, AND the target Member
        itself is application_status=Pending. Must be visible to its own chapter's
        board -- the positive case #1529/#1518 exist for."""
        applicant = self._create_real_pending_applicant("Pending")

        created = create_pending_chapter_membership(applicant, self.chapter.name)
        self.assertIsNotNone(created, "fixture setup: create_pending_chapter_membership failed")

        self._assert_visibility("Member", applicant.name, True, "pending applicant, own chapter")

    def test_request_to_join_by_already_active_member_not_visible(self):
        """#1518's escalation case, at the list-view layer: an ALREADY-Active member,
        approved via a DIFFERENT chapter, requests to join the board's chapter too.
        member_manager.request_to_join writes the SAME enabled=1/status=Pending
        Chapter Member shape a real application does, but this Member's own
        application_status is 'Approved', not 'Pending'. Must NOT grant the
        requested chapter's board any access -- widening on `cm.status='Pending'`
        alone (without the application_status guard) would leak this."""
        member = self._create_approved_active_member("Requester")
        self.add_member_to_test_chapter(member.name, self.other_chapter.name)

        chapter_doc = self._fresh_chapter(self.chapter.name)
        result = chapter_doc.member_manager.request_to_join(member.name, notify=False)
        self.assertTrue(result.get("success"), f"fixture setup: request_to_join failed: {result}")

        cm_row = frappe.db.get_value(
            "Chapter Member",
            {"member": member.name, "parent": self.chapter.name},
            ["enabled", "status"],
            as_dict=True,
        )
        self.assertEqual(
            (cm_row.enabled, cm_row.status),
            (1, "Pending"),
            "fixture setup: request_to_join did not leave the expected enabled=1/Pending row",
        )

        self._assert_visibility(
            "Member", member.name, False, "already-active member's join request, requested chapter"
        )

    def test_approve_member_request_converges_to_active_visible(self):
        """member_manager.approve_member_request -- the chapter JOIN-REQUEST
        approval path (verenigingen/api/chapter_dashboard_api.py's "pending
        Chapter Member" branch, distinct from approve_membership_application's
        Membership-APPLICATION path) -- flips the join request's Pending row to
        Active without touching `enabled` (already 1 from request_to_join).

        This is GREEN-ON-ARRIVAL coverage, not a regression guard: #1529's
        review already found list and doc-level agree here (both see the
        resulting enabled=1/Active row as a plain active chapter membership,
        the same state test_positive_control_active_member_of_own_chapter
        covers). The test pins that agreement so a future change to either
        side cannot silently break it unnoticed."""
        member = self._create_approved_active_member("Approver")
        self.add_member_to_test_chapter(member.name, self.other_chapter.name)

        chapter_doc = self._fresh_chapter(self.chapter.name)
        join_result = chapter_doc.member_manager.request_to_join(member.name, notify=False)
        self.assertTrue(join_result.get("success"), f"fixture setup: request_to_join failed: {join_result}")

        chapter_doc = self._fresh_chapter(self.chapter.name)
        approve_result = chapter_doc.member_manager.approve_member_request(
            member.name, approved_by=self.board.user
        )
        self.assertTrue(
            approve_result.get("success"),
            f"fixture setup: approve_member_request failed: {approve_result}",
        )

        cm_row = frappe.db.get_value(
            "Chapter Member",
            {"member": member.name, "parent": self.chapter.name},
            ["enabled", "status"],
            as_dict=True,
        )
        self.assertEqual(
            (cm_row.enabled, cm_row.status),
            (1, "Active"),
            "fixture setup: approve_member_request did not leave the expected enabled=1/Active row",
        )

        self._assert_visibility("Member", member.name, True, "join request approved, requested chapter")

    def test_reject_member_request_deletes_row_not_visible(self):
        """member_manager.reject_member_request DELETES the pending Chapter
        Member row outright rather than changing its status or enabled flag.

        GREEN-ON-ARRIVAL coverage, not a regression guard: with no row at all,
        list and doc-level trivially agree there is nothing to see -- true both
        before and after #1529's fix, since neither version of the query ever
        matched a row that does not exist. Pinned here so a future change that
        makes reject_member_request soft-delete (set a status) instead of
        hard-deleting does not silently change this."""
        member = self._create_approved_active_member("Rejecter")
        self.add_member_to_test_chapter(member.name, self.other_chapter.name)

        chapter_doc = self._fresh_chapter(self.chapter.name)
        join_result = chapter_doc.member_manager.request_to_join(member.name, notify=False)
        self.assertTrue(join_result.get("success"), f"fixture setup: request_to_join failed: {join_result}")

        chapter_doc = self._fresh_chapter(self.chapter.name)
        reject_result = chapter_doc.member_manager.reject_member_request(
            member.name, reason="Not eligible", rejected_by=self.board.user
        )
        self.assertTrue(
            reject_result.get("success"),
            f"fixture setup: reject_member_request failed: {reject_result}",
        )

        self.assertFalse(
            frappe.db.exists("Chapter Member", {"member": member.name, "parent": self.chapter.name}),
            "fixture setup: reject_member_request did not delete the Chapter Member row",
        )

        self._assert_visibility("Member", member.name, False, "join request rejected, requested chapter")

    def test_approval_flips_pending_row_to_active_and_stays_visible(self):
        """approve_membership_application flips the Pending Chapter Member row to
        Active and creates the Membership record. Both must stay visible to the
        board that just approved (and now legitimately manages) this member."""
        applicant = self._create_real_pending_applicant("Approved")
        create_pending_chapter_membership(applicant, self.chapter.name)

        result = approve_membership_application(
            member_name=applicant.name,
            membership_type=self.membership_type,
            create_invoice=False,
            notes="Approved for #1529 list-permission test",
        )
        self.assertTrue(result.get("success"), f"fixture setup: approval failed: {result}")

        cm_row = frappe.db.get_value(
            "Chapter Member",
            {"member": applicant.name, "parent": self.chapter.name},
            ["enabled", "status"],
            as_dict=True,
        )
        self.assertEqual(
            (cm_row.enabled, cm_row.status),
            (1, "Active"),
            "fixture setup: approval did not activate the Chapter Member row",
        )

        membership_name = frappe.db.get_value("Membership", {"member": applicant.name})
        self.assertIsNotNone(membership_name, "fixture setup: approval did not create a Membership")

        self._assert_visibility("Member", applicant.name, True, "approved member, own chapter")
        self._assert_visibility("Membership", membership_name, True, "approved member's membership")

    def test_remove_member_permanent_false_not_visible(self):
        """remove_member(permanent=False) -- what a member leaving the chapter
        actually does -- leaves enabled=0, status UNCHANGED ('Active'). The board
        that just lost this member must stop seeing them, on both doctypes. This
        is the CORE list-view fix: the pre-#1529 query matched `status='Active'`
        with no `enabled` check, so this exact row stayed listed."""
        member = self.create_test_member(
            first_name="Leaving",
            last_name=f"Member{self.uid}",
            email=f"leaving.member.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
        )
        self.add_member_to_test_chapter(member.name, self.chapter.name)
        membership = self.create_test_membership(
            member_name=member.name, membership_type_name=self.membership_type
        )

        # Sanity: visible before removal (else the test proves nothing).
        self._assert_visibility("Member", member.name, True, "member before removal")

        chapter_doc = self._fresh_chapter(self.chapter.name)
        chapter_doc.member_manager.remove_member(member.name, leave_reason="left", notify=False)

        cm_row = frappe.db.get_value(
            "Chapter Member",
            {"member": member.name, "parent": self.chapter.name},
            ["enabled", "status"],
            as_dict=True,
        )
        self.assertEqual(
            (cm_row.enabled, cm_row.status),
            (0, "Active"),
            "fixture setup: remove_member(permanent=False) did not leave the expected "
            "enabled=0/status=Active row",
        )

        self._assert_visibility("Member", member.name, False, "member after remove_member(permanent=False)")
        self._assert_visibility(
            "Membership", membership.name, False, "membership after remove_member(permanent=False)"
        )

    def test_termination_disables_membership_not_visible(self):
        """disable_chapter_memberships_safe -- the writer termination actually
        calls -- leaves enabled=0, status='Inactive'. Must not be visible."""
        member = self.create_test_member(
            first_name="Terminated",
            last_name=f"Member{self.uid}",
            email=f"terminated.member.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
        )
        self.add_member_to_test_chapter(member.name, self.chapter.name)
        membership = self.create_test_membership(
            member_name=member.name, membership_type_name=self.membership_type
        )

        self._assert_visibility("Member", member.name, True, "member before termination")

        disabled_count = disable_chapter_memberships_safe(member.name, today(), "Test termination #1529")
        self.assertEqual(disabled_count, 1, "fixture setup: disable_chapter_memberships_safe disabled 0 rows")

        cm_row = frappe.db.get_value(
            "Chapter Member",
            {"member": member.name, "parent": self.chapter.name},
            ["enabled", "status"],
            as_dict=True,
        )
        self.assertEqual(
            (cm_row.enabled, cm_row.status),
            (0, "Inactive"),
            "fixture setup: disable_chapter_memberships_safe did not leave the expected "
            "enabled=0/status=Inactive row",
        )

        self._assert_visibility("Member", member.name, False, "member after termination")
        self._assert_visibility("Membership", membership.name, False, "membership after termination")

    def test_add_member_for_suspended_member_not_visible(self):
        """add_member's own status-derivation: a non-Active Member (Suspended, here
        -- not one of the 'Quit'/'Banned'/'Deceased' names the query already
        excludes, so this isolates the enabled/status fix from that pre-existing
        exclusion) is added as enabled=0, status='Inactive'. Must not be visible."""
        member = self.create_test_member(
            first_name="Suspended",
            last_name=f"Member{self.uid}",
            email=f"suspended.member.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
            status="Suspended",
        )

        chapter_doc = self._fresh_chapter(self.chapter.name)
        added = chapter_doc.member_manager.add_member(member.name, notify=False)
        self.assertTrue(added.get("success"), f"fixture setup: add_member failed: {added}")

        cm_row = frappe.db.get_value(
            "Chapter Member",
            {"member": member.name, "parent": self.chapter.name},
            ["enabled", "status"],
            as_dict=True,
        )
        self.assertEqual(
            (cm_row.enabled, cm_row.status),
            (0, "Inactive"),
            "fixture setup: add_member did not leave the expected enabled=0/status=Inactive row "
            "for a non-Active member",
        )

        self._assert_visibility("Member", member.name, False, "suspended member added to chapter")
