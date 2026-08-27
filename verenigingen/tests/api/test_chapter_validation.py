# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Meaningful tests for verenigingen/api/chapter_validation.py

These exercise the five whitelisted validation endpoints:
  - validate_chapter_head
  - validate_region
  - update_publication_status
  - validate_board_member
  - validate_board_removal

IMPORTANT — decorator serialization:
  Every endpoint is wrapped by @standard_api, which calls
  OperationResult.to_dict(scrub_sensitive=True) on the return value. So an
  in-process call from a test receives a NESTED DICT, not an OperationResult:

    success path: {"success": True, "timestamp": ..., "data": {...}, "meta": {...}}
    failure path: {"success": False, "timestamp": ...,
                   "error": {"message": ..., "errors": [...], "code": ...},
                   "meta": {...}}

  We assert on that dict shape. The validation business outcome ("is this
  assignment allowed?") lives in data["valid"] for the success-envelope cases;
  a False business outcome is still success=True at the envelope level (these
  endpoints return OperationResult.ok with valid=False for *expected* invalid
  inputs, and OperationResult.fail only on unexpected exceptions).
"""

import frappe

from verenigingen.api.chapter_validation import (
    update_publication_status,
    validate_board_member,
    validate_board_removal,
    validate_chapter_head,
    validate_region,
)
from verenigingen.tests.fixtures.enhanced_test_factory import allocate_free_region_code
from verenigingen.tests.utils.base import VereningingenTestCase


class TestChapterValidation(VereningingenTestCase):
    # ------------------------------------------------------------------ #
    # Helpers (factory-backed; no insert/save(ignore_permissions) in test
    # method bodies — see test-quality-enforcer rules).
    # ------------------------------------------------------------------ #

    def _make_chapter(self, **kwargs):
        """Create a tracked test Chapter."""
        return self.create_test_chapter(**kwargs)

    def _make_member(self, **kwargs):
        """Create a tracked test Member (no chapter assignment by default)."""
        kwargs.setdefault("chapter", False)  # skip auto chapter assignment
        return self.create_test_member(**kwargs)

    def _make_volunteer(self, member=None, **kwargs):
        """Create a tracked test Volunteer linked to a member."""
        if member is None:
            member = self._make_member()
        return self.create_test_volunteer(member=member, **kwargs)

    def _ensure_chapter_role(self, role_name="Test Board Role"):
        """Idempotently ensure a Chapter Role master exists for board tests."""
        if frappe.db.exists("Chapter Role", role_name):
            return role_name
        role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": role_name,
                "permissions_level": "Basic",
                "is_active": 1,
            }
        )
        role.insert(ignore_permissions=True)
        self.track_doc("Chapter Role", role.name)
        return role.name

    def _append_board_member(self, chapter, volunteer, role_name, is_active=1):
        """Append a board member row to a Chapter and persist it.

        Done on the Chapter doc (the parent owns the child rows). Uses the
        ChapterController save path, not a child-table insert in a test body.
        """
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": role_name,
                "from_date": frappe.utils.today(),
                "is_active": is_active,
            },
        )
        chapter_doc.save()
        return chapter_doc

    # ------------------------------------------------------------------ #
    # validate_chapter_head
    # ------------------------------------------------------------------ #

    def test_chapter_head_empty_is_valid(self):
        """Empty chapter_head -> valid 'no head assigned'."""
        chapter = self._make_chapter()
        result = validate_chapter_head(chapter.name, "")
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["valid"])
        self.assertEqual(result["data"]["message"], "No chapter head assigned")

    def test_chapter_head_active_volunteer_is_valid(self):
        """An Active member who is a registered volunteer is a valid head, and
        the returned data echoes the resolved volunteer name."""
        member = self._make_member(status="Active")
        volunteer = self._make_volunteer(member=member)

        result = validate_chapter_head("any-chapter", member.name)
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["valid"])
        # The endpoint resolves the Volunteer linked to the member and returns it.
        self.assertEqual(result["data"]["volunteer"], volunteer.name)

    def test_chapter_head_inactive_member_is_invalid(self):
        """A non-Active member cannot be chapter head."""
        member = self._make_member(status="Suspended")
        # Even with a volunteer, the status check short-circuits first.
        self._make_volunteer(member=member)

        result = validate_chapter_head("any-chapter", member.name)
        self.assertTrue(result["success"])  # expected-invalid -> still ok envelope
        self.assertFalse(result["data"]["valid"])
        self.assertEqual(result["data"]["message"], "Selected member is not active")
        self.assertTrue(result["data"].get("warning"))

    def test_chapter_head_member_without_volunteer_is_invalid(self):
        """An Active member who is NOT a volunteer cannot be chapter head."""
        member = self._make_member(status="Active")
        # No volunteer created for this member.

        result = validate_chapter_head("any-chapter", member.name)
        self.assertTrue(result["success"])
        self.assertFalse(result["data"]["valid"])
        self.assertEqual(
            result["data"]["message"], "Chapter head must be a registered volunteer"
        )
        self.assertTrue(result["data"].get("error"))

    def test_chapter_head_nonexistent_member_returns_failure_envelope(self):
        """A non-existent member id triggers DoesNotExistError -> fail envelope."""
        result = validate_chapter_head("any-chapter", "NO-SUCH-MEMBER-XYZ")
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertIn("Error validating chapter head", result["error"]["message"])

    # ------------------------------------------------------------------ #
    # validate_region
    # ------------------------------------------------------------------ #

    def test_region_empty_is_valid(self):
        """Empty region -> valid 'no region assigned', no suggestions."""
        result = validate_region("any-chapter", "")
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["valid"])
        self.assertEqual(result["data"]["message"], "No region assigned")

    def test_region_suggests_postal_codes_from_sibling_chapter(self):
        """When another chapter in the same region has postal codes, they are
        returned as suggestions; the chapter being validated is excluded."""
        region = self.get_test_region_name()
        sibling = self._make_chapter(region=region, postal_codes="2000-2099")
        target = self._make_chapter(region=region, postal_codes="3000-3099")

        result = validate_region(target.name, region)
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["valid"])
        self.assertEqual(result["data"]["region"], region)

        suggested_chapters = {s["chapter"] for s in result["data"]["suggestions"]}
        # Sibling (same region, has postal codes) must be suggested...
        self.assertIn(sibling.name, suggested_chapters)
        # ...and the chapter under validation must be excluded from its own suggestions.
        self.assertNotIn(target.name, suggested_chapters)

        # The suggestion payload carries the sibling's actual postal codes.
        sibling_suggestion = next(
            s for s in result["data"]["suggestions"] if s["chapter"] == sibling.name
        )
        self.assertEqual(sibling_suggestion["postal_codes"], "2000-2099")

    def test_region_with_no_siblings_returns_empty_suggestions(self):
        """A region whose only chapter is the one being validated yields no
        suggestions (the self-exclusion filter removes the only candidate)."""
        # Use a fresh, unique region so no other test chapters pollute results.
        region_name = f"Iso Region {frappe.generate_hash(length=6)}"
        region_doc = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": region_name,
                # unchecked hex slice -> allocate one verified free instead
                "region_code": allocate_free_region_code(),
                "country": "Netherlands",
                "is_active": 1,
            }
        )
        region_doc.insert(ignore_permissions=True)
        self.track_doc("Region", region_doc.name)

        target = self._make_chapter(region=region_doc.name, postal_codes="4000-4099")
        result = validate_region(target.name, region_doc.name)
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["valid"])
        self.assertEqual(result["data"]["suggestions"], [])

    # ------------------------------------------------------------------ #
    # update_publication_status
    # ------------------------------------------------------------------ #

    def test_publish_requires_postal_codes(self):
        """Publishing a chapter without postal codes is blocked with a warning
        and the chapter is NOT persisted as published."""
        chapter = self._make_chapter(postal_codes="", introduction="Has intro")

        result = update_publication_status(chapter.name, 1)
        self.assertTrue(result["success"])
        self.assertFalse(result["data"]["valid"])
        self.assertIn("postal codes", result["data"]["message"])
        self.assertTrue(result["data"].get("warning"))

        # Guard actually prevented the write.
        self.assertEqual(frappe.db.get_value("Chapter", chapter.name, "published"), 0)

    def test_publish_requires_introduction(self):
        """With postal codes but no introduction, publishing is blocked.

        NOTE: Chapter's validate hook (chapter_validation_service) auto-fills an
        `introduction` for test chapters, so we must blank it directly in the DB
        AFTER creation to exercise the guard. update_publication_status reads the
        chapter via frappe.get_doc (DB-backed) and returns before any save on the
        invalid path, so the blanked value is what the guard sees.
        """
        chapter = self._make_chapter(postal_codes="5000-5099")
        frappe.db.set_value("Chapter", chapter.name, "introduction", "")

        result = update_publication_status(chapter.name, 1)
        self.assertTrue(result["success"])
        self.assertFalse(result["data"]["valid"])
        self.assertIn("introduction", result["data"]["message"])
        self.assertEqual(frappe.db.get_value("Chapter", chapter.name, "published"), 0)

    def test_publish_succeeds_and_persists_when_complete(self):
        """A chapter with postal codes + introduction can be published, and the
        published flag is persisted to the DB."""
        chapter = self._make_chapter(
            postal_codes="6000-6099", introduction="A complete chapter", published=0
        )

        result = update_publication_status(chapter.name, 1)
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["valid"])
        self.assertTrue(result["data"]["published"])
        self.assertEqual(result["data"]["chapter"], chapter.name)

        self.assertEqual(frappe.db.get_value("Chapter", chapter.name, "published"), 1)

    def test_unpublish_persists(self):
        """Unpublishing (published=0) is always allowed and persists, even
        though the publish-guards reference postal_codes/introduction."""
        chapter = self._make_chapter(
            postal_codes="7000-7099", introduction="Intro", published=1
        )

        result = update_publication_status(chapter.name, 0)
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["valid"])
        self.assertFalse(result["data"]["published"])
        self.assertEqual(frappe.db.get_value("Chapter", chapter.name, "published"), 0)

    # ------------------------------------------------------------------ #
    # validate_board_member
    # ------------------------------------------------------------------ #

    def test_board_member_empty_volunteer_is_valid(self):
        """No volunteer -> trivially valid."""
        result = validate_board_member("any-chapter", "", "any-role")
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["valid"])
        self.assertEqual(result["data"]["message"], "No volunteer specified")

    def test_board_member_inactive_volunteer_is_invalid(self):
        """A non-Active volunteer cannot be assigned to the board."""
        member = self._make_member(status="Active")
        volunteer = self._make_volunteer(member=member, status="Inactive")
        chapter = self._make_chapter()

        result = validate_board_member(chapter.name, volunteer.name, "any-role")
        self.assertTrue(result["success"])
        self.assertFalse(result["data"]["valid"])
        self.assertEqual(result["data"]["message"], "Selected volunteer is not active")
        self.assertTrue(result["data"].get("warning"))

    def test_board_member_active_volunteer_not_on_board_is_valid(self):
        """An Active volunteer not yet on the board is a valid assignment, and
        the role echoes back."""
        member = self._make_member(status="Active")
        volunteer = self._make_volunteer(member=member, status="Active")
        chapter = self._make_chapter()
        role_name = self._ensure_chapter_role()

        result = validate_board_member(chapter.name, volunteer.name, role_name)
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["valid"])
        self.assertEqual(result["data"]["volunteer"], volunteer.name)
        self.assertEqual(result["data"]["role"], role_name)

    def test_board_member_already_on_board_is_rejected(self):
        """A volunteer already on the active board (is_active=1 row) is rejected
        as a duplicate.

        The duplicate check filters Chapter Board Member on the real
        `is_active` check field (there is no `status` column). With an active
        seat persisted for this volunteer, validate_board_member must detect it
        and return a success envelope carrying valid=False plus an
        "already on the chapter board" message.

        We also prove the board_members row actually persisted (count==1) so a
        valid=False result reflects real duplicate detection, not a failed seed.
        """
        member = self._make_member(status="Active")
        volunteer = self._make_volunteer(member=member, status="Active")
        chapter = self._make_chapter()
        role_name = self._ensure_chapter_role()
        # Put the volunteer on the board (is_active row) and prove it persisted.
        self._append_board_member(chapter, volunteer, role_name, is_active=1)
        self.assertEqual(
            frappe.db.count("Chapter Board Member", {"parent": chapter.name, "is_active": 1}),
            1,
            "Active board member row should have persisted (guards against a false-positive claim)",
        )

        result = validate_board_member(chapter.name, volunteer.name, role_name)

        # is_active filter now detects the existing seat -> success envelope with
        # valid=False and an "already on the board" message.
        self.assertTrue(result["success"])
        self.assertFalse(result["data"]["valid"])
        self.assertEqual(
            result["data"]["message"],
            "Volunteer is already on the chapter board",
        )

    def test_board_member_nonexistent_volunteer_returns_failure(self):
        """A non-existent volunteer id -> DoesNotExistError -> fail envelope."""
        chapter = self._make_chapter()
        result = validate_board_member(chapter.name, "NO-SUCH-VOLUNTEER", "role")
        self.assertFalse(result["success"])
        self.assertIn("Error validating board member", result["error"]["message"])

    # ------------------------------------------------------------------ #
    # validate_board_removal
    # ------------------------------------------------------------------ #

    def test_board_removal_with_multiple_members_is_valid(self):
        """Removing a board member is valid when more than one active board
        member remains.

        board_count is computed with the real `is_active` check field. With two
        active seats, the "at least one board member" guard does not trip:
        validate_board_removal returns a success envelope with valid=True and
        current_board_size==2.
        """
        chapter = self._make_chapter()
        role_name = self._ensure_chapter_role()
        v1 = self._make_volunteer(member=self._make_member(status="Active"), status="Active")
        v2 = self._make_volunteer(member=self._make_member(status="Active"), status="Active")
        chapter_doc = self._append_board_member(chapter, v1, role_name, is_active=1)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": v2.name,
                "chapter_role": role_name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save(ignore_permissions=True)

        result = validate_board_removal(chapter.name)

        # is_active count == 2 -> guard not tripped -> valid removal.
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["valid"])
        self.assertEqual(result["data"]["current_board_size"], 2)

    def test_board_removal_last_member_blocked(self):
        """A chapter with a single active board member blocks removal.

        With one active seat (is_active=1), the count is 1, tripping the
        "must have at least one board member" guard: a success envelope with
        valid=False.
        """
        chapter = self._make_chapter()
        role_name = self._ensure_chapter_role()
        v1 = self._make_volunteer(member=self._make_member(status="Active"), status="Active")
        self._append_board_member(chapter, v1, role_name, is_active=1)

        result = validate_board_removal(chapter.name)

        # is_active count == 1 -> guard trips -> removal blocked.
        self.assertTrue(result["success"])
        self.assertFalse(result["data"]["valid"])
        self.assertIn("at least one board member", result["data"]["message"])

    def test_board_removal_empty_chapter(self):
        """A chapter with no board members.

        board_count is 0 (no is_active rows), which is <= 1, so the guard trips:
        a success envelope with valid=False and the "at least one board member"
        message.
        """
        chapter = self._make_chapter()
        result = validate_board_removal(chapter.name)

        self.assertTrue(result["success"])
        self.assertFalse(result["data"]["valid"])
        self.assertIn("at least one board member", result["data"]["message"])
