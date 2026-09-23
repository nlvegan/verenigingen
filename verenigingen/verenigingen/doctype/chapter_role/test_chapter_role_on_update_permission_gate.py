# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""Regression for #1229.

ChapterRole.on_update() called update_chapters_with_role() -- @high_security_api
(HIGH) -- wrapped in a bare `except Exception`. HIGH access is only grantable
through an assigned Role Profile (AuthorizationPolicy.PROFILE_ONLY_LEVELS), never a
bare role, but chapter_role.json grants write/create to the BARE roles "System
Manager" and "Verenigingen Administrator". So a user holding one of those bare
roles -- no matching Role Profile -- could save a Chapter Role (the DocType
permission passes) while update_chapters_with_role() raised PermissionError
internally; the old code swallowed it silently, so the save succeeded while the
chapter_head propagation silently failed with no user-visible trace.

Same class of problem as #1224 (DirectDebitBatch.on_submit calling a
CRITICAL-gated method internally), fixed here the same way: a
can_clear_security_level() pre-check (shared with #1224's fix, now living in
api_security_framework.py) gates the call BEFORE it runs, instead of catching
broadly after the fact, and the skipped propagation is made observable via
msgprint + frappe.log_error rather than silently absorbed.

Round 2 (review finding): the first version of this msgprint told the writer to
"save this role again" to recover. That is FALSE -- on_update()'s whole body is
gated by `has_value_changed("is_chair")`, so once the deferred save has already
persisted is_chair=1, a later save that leaves is_chair unchanged skips the
entire method silently (no gate check, no message, nothing). The real recovery
path is the "Update Affected Chapters" button (chapter_role.js, Actions group),
which calls update_chapters_with_role() directly and is unaffected by
has_value_changed. The tests below assert the message names that real action
(not "save again"), and separately prove BOTH that the button's own dispatch
path recovers the propagation AND that a plain re-save does not -- so nobody
can reintroduce the false claim without a test going red.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.chapter_role.chapter_role import update_chapters_with_role


class TestChapterRoleOnUpdatePermissionGate(EnhancedTestCase):
    def setUp(self):
        super().setUp()

        self.chapter = self.create_chapter(chapter_name=f"TEST ChapterRole Gate {self.uid}")

        self.role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Test Chair Role {self.uid}",
                "permissions_level": "Admin",
                "is_chair": 0,
                "is_active": 1,
            }
        )
        self.role.insert(ignore_permissions=True)
        self.factory.track_document("Chapter Role", self.role.name, priority=3)

        # Seats a real board member (User -> Member -> Volunteer -> Chapter Board
        # Member) on self.chapter, holding self.role. The role is NOT yet chair,
        # so Chapter's own validate()-time auto-update (chapter_validator.py
        # _auto_update_chapter_head, which runs whenever the CHAPTER itself is
        # saved) has nothing to set chapter_head to -- isolating the propagation
        # under test to the ChapterRole.on_update() -> update_chapters_with_role()
        # path, not a side effect of the board-seating save.
        self.board = self.create_test_board_member(
            self.chapter.name, permissions_level="Admin", role_name=self.role.name
        )

        self.chapter.reload()
        self.assertIsNone(
            self.chapter.chapter_head,
            "Fixture sanity: chapter_head must start unset (role is not yet chair)",
        )

    def test_admin_with_role_profile_propagates_chapter_head(self):
        """Positive control: an admin holding the matching Role Profile clears the
        HIGH gate, so flipping is_chair still propagates to chapter_head."""
        with self.as_admin_role():
            role = frappe.get_doc("Chapter Role", self.role.name)
            role.is_chair = 1
            role.save()  # must not raise, and must actually propagate

        role.reload()
        self.assertEqual(role.is_chair, 1)

        self.chapter.reload()
        self.assertEqual(
            self.chapter.chapter_head,
            self.board.member,
            "Admin with the matching Role Profile should have propagated chapter_head",
        )

    def test_bare_role_writer_save_succeeds_but_propagation_is_visibly_skipped(self):
        """A bare 'System Manager' role has write permission on Chapter Role
        (chapter_role.json) but NO Role Profile, so AuthorizationPolicy Rule 6
        caps it at MEDIUM -- it cannot clear update_chapters_with_role()'s HIGH
        gate. The save must still succeed (#1229's chosen behaviour: option (b)),
        and the skipped propagation must be OBSERVABLE (msgprint + a real
        frappe.log_error entry), not silently absorbed.
        """
        self.expectErrorLog("Chapter Role Update Deferred")

        before_messages = len(frappe.message_log or [])

        with self.as_role(["System Manager"]):
            role = frappe.get_doc("Chapter Role", self.role.name)
            with self.assertErrorLog("Chapter Role Update Deferred"):
                role.is_chair = 1
                role.save()  # must NOT raise -- the save itself must succeed

        new_messages = " ".join(str(m) for m in (frappe.message_log or [])[before_messages:]).lower()
        self.assertIn(
            "not updated",
            new_messages,
            "The skipped propagation must surface a visible msgprint warning",
        )
        # Round 2: the message must name the REAL recovery action (the "Update
        # Affected Chapters" button, chapter_role.js Actions group), not "save
        # this role again" -- has_value_changed("is_chair") makes a plain re-save
        # a silent no-op once is_chair is already persisted as 1 (see
        # test_plain_resave_does_not_recover_propagation below).
        self.assertIn(
            "update affected chapters",
            new_messages,
            "The message must name the actual recovery action (the button in the "
            "Actions group), not an ineffective re-save",
        )
        self.assertNotIn(
            "save this role again",
            new_messages,
            "Must not tell the writer to re-save -- has_value_changed() makes that a no-op",
        )

        role.reload()
        self.assertEqual(role.is_chair, 1, "The Chapter Role save itself must succeed for this writer")

        self.chapter.reload()
        self.assertIsNone(
            self.chapter.chapter_head,
            "Chapter head must NOT be updated when the writer cannot clear the HIGH gate "
            "(propagation must be skipped, not silently run as someone else)",
        )

    def test_recovery_via_update_affected_chapters_button_succeeds(self):
        """After a deferred save, the message's named recovery action must
        actually work. chapter_role.js's "Update Affected Chapters" button
        (Actions group) dispatches straight to update_chapters_with_role() via
        frappe.call -- the security decorator enforces identically regardless of
        HTTP dispatch vs. a direct Python call (decorators run on internal calls
        too in this app, per #1224), so calling the function directly, under a
        profile-holding user, exercises the exact same path the button uses.
        """
        self.expectErrorLog("Chapter Role Update Deferred")

        with self.as_role(["System Manager"]):
            role = frappe.get_doc("Chapter Role", self.role.name)
            role.is_chair = 1
            role.save()  # deferred: is_chair persists, chapter_head does not

        self.chapter.reload()
        self.assertIsNone(
            self.chapter.chapter_head, "Fixture sanity: propagation must still be deferred here"
        )

        with self.as_admin_role():
            result = update_chapters_with_role(self.role.name)

        self.assertEqual(result["chapters_updated"], 1)

        self.chapter.reload()
        self.assertEqual(
            self.chapter.chapter_head,
            self.board.member,
            "The Update Affected Chapters button's own dispatch path must recover the propagation",
        )

    def test_plain_resave_does_not_recover_propagation(self):
        """Documents the failure mode the round-2 review caught: once is_chair=1
        is already persisted (from the deferred save), has_value_changed("is_chair")
        is False on a later save that leaves is_chair untouched, so on_update()
        returns immediately -- no gate check, no message, no propagation. A
        profile-holding admin re-saving the SAME role does NOT recover it. This
        guards against reintroducing "save this role again" as the advertised fix.
        """
        self.expectErrorLog("Chapter Role Update Deferred")

        with self.as_role(["System Manager"]):
            role = frappe.get_doc("Chapter Role", self.role.name)
            role.is_chair = 1
            role.save()  # deferred

        self.chapter.reload()
        self.assertIsNone(self.chapter.chapter_head, "Fixture sanity: still deferred")

        with self.as_admin_role():
            role = frappe.get_doc("Chapter Role", self.role.name)
            role.role_name = role.role_name + " (renamed)"  # any change, but NOT is_chair
            role.save()

        self.chapter.reload()
        self.assertIsNone(
            self.chapter.chapter_head,
            "A plain re-save (is_chair unchanged) must NOT retry the propagation -- "
            "has_value_changed('is_chair') is False, so on_update() returns immediately",
        )
