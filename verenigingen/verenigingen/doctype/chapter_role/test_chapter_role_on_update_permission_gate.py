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
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


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

        role.reload()
        self.assertEqual(role.is_chair, 1, "The Chapter Role save itself must succeed for this writer")

        self.chapter.reload()
        self.assertIsNone(
            self.chapter.chapter_head,
            "Chapter head must NOT be updated when the writer cannot clear the HIGH gate "
            "(propagation must be skipped, not silently run as someone else)",
        )
