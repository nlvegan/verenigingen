"""
Supplemental real-DB coverage tests for the chapter ``ChapterValidator``
(``verenigingen/verenigingen/doctype/chapter/validators/chapter_validator.py``).

The existing ``test_chapter_validator.py`` covers the happy path, duplicate-member
detection, route generation, postal matching and the publication-readiness summary.
This file targets the branches that file leaves uncovered:

* the board-change / role-assignment delegators (``validate_board_member_change``,
  ``validate_role_assignment``)
* the chapter-head <-> chair-role mismatch warning
* the "active board member is not listed as a chapter member" warning
  (``_validate_member_management`` cross-check, which does a real Volunteer->Member
  lookup)
* ``_validate_for_publication`` with region present + the "no board/members" warning
* ``_is_chair_role`` true / false / does-not-exist
* ``_check_publication_readiness`` with a sufficient, chaired board (the "ready" path)

All board/role rows are built as real documents so the DB-backed lookups
(Chapter Role.is_chair, Volunteer.member) execute for real.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.chapter.validators.chapter_validator import (
    ChapterValidator,
)


class TestChapterValidatorCoverage(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"CVC Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-2000",
            published=0,
        )

    # ----------------------------------------------------------------- helpers

    def _make_role(self, is_chair=0, is_active=1):
        role_name = f"CVCRole{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": role_name,
                "permissions_level": "Admin" if is_chair else "Basic",
                "is_chair": is_chair,
                "is_active": is_active,
            }
        ).insert()
        self.track_doc("Chapter Role", role_name)
        return role_name

    def _make_volunteer(self, first="CVC"):
        member = self.create_test_member(
            first_name=first,
            last_name="Coverage",
            email=f"cvc.{first.lower()}.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        vol = self.create_test_volunteer(member=member.name)
        return member, vol

    def _append_board(self, vol_name, role, is_active=1):
        self.chapter.append(
            "board_members",
            {
                "volunteer": vol_name,
                "chapter_role": role,
                "from_date": frappe.utils.today(),
                "is_active": is_active,
            },
        )

    # ------------------------------------------------- delegator: role assignment

    def test_validate_role_assignment_unique_ok(self):
        """A role not yet held by anyone is a valid assignment."""
        member, vol = self._make_volunteer(first="RoleA")
        role = self._make_role(is_chair=0)
        active_members = [{"volunteer": vol.name, "chapter_role": role, "is_active": True}]
        v = ChapterValidator(self.chapter)
        # Assigning the SAME member to that role is fine (it's their own row),
        # assigning a DIFFERENT member to a unique role should also pass.
        result = v.validate_role_assignment(role, member.name, [])
        self.assertTrue(result.is_valid, result.errors)

    def test_validate_board_member_change_delegates(self):
        """validate_board_member_change returns a ValidationResult from the board validator."""
        _m, vol = self._make_volunteer(first="ChgA")
        role = self._make_role(is_chair=0)
        old = []
        new = [
            {
                "volunteer": vol.name,
                "chapter_role": role,
                "is_active": True,
                "from_date": frappe.utils.today(),
            }
        ]
        v = ChapterValidator(self.chapter)
        result = v.validate_board_member_change(old, new)
        # The result must be a real ValidationResult with the standard attributes.
        self.assertTrue(hasattr(result, "is_valid"))
        self.assertTrue(hasattr(result, "errors"))

    # ------------------------------------- chapter-head / chair-role mismatch warn

    def test_chapter_head_not_chair_warns(self):
        """chapter_head set, board has a chair, but head != that chair's member -> warning."""
        chair_member, chair_vol = self._make_volunteer(first="RealChair")
        other_member, _other_vol = self._make_volunteer(first="NotChair")
        chair_role = self._make_role(is_chair=1)

        self._append_board(chair_vol.name, chair_role, is_active=1)
        # Point the head at someone who is NOT the chair's member.
        self.chapter.chapter_head = other_member.name

        v = ChapterValidator(self.chapter)
        result = v.validate_all()
        self.assertTrue(
            any(
                "not associated with any active board member with a chair role" in w for w in result.warnings
            ),
            result.warnings,
        )

    # ----------------------------- active board member not in chapter member list

    def test_active_board_member_not_in_member_list_warns(self):
        """An active board member whose member is not an enabled chapter member -> warning."""
        member, vol = self._make_volunteer(first="BoardOnly")
        role = self._make_role(is_chair=0)
        self._append_board(vol.name, role, is_active=1)
        # Deliberately do NOT add `member` to chapter.members.
        self.chapter.members = []

        v = ChapterValidator(self.chapter)
        result = v.validate_all()
        self.assertTrue(
            any("not listed as an active chapter member" in w for w in result.warnings),
            result.warnings,
        )

    def test_active_board_member_in_member_list_no_warn(self):
        """When the board member IS an enabled chapter member, no such warning."""
        member, vol = self._make_volunteer(first="BoardAndMember")
        role = self._make_role(is_chair=0)
        self._append_board(vol.name, role, is_active=1)
        self.chapter.members = []
        self.chapter.append("members", {"member": member.name, "enabled": 1})

        v = ChapterValidator(self.chapter)
        result = v.validate_all()
        self.assertFalse(
            any("not listed as an active chapter member" in w for w in result.warnings),
            result.warnings,
        )

    # --------------------------------------------------- publication validation

    def test_publication_no_board_or_members_warns(self):
        """A published chapter with a long intro + region but no board/members -> warning (not error)."""
        self.chapter.published = 1
        self.chapter.introduction = "x" * 150  # satisfies the >=100 char rule
        # region is set by the factory; ensure it exists
        self.assertTrue(self.chapter.region)
        self.chapter.board_members = []
        self.chapter.members = []

        v = ChapterValidator(self.chapter)
        result = v.validate_before_submit()
        # No publication ERROR (intro long enough, region present)...
        self.assertFalse(any("at least 100 characters" in e for e in result.errors), result.errors)
        self.assertFalse(any("must have a region" in e for e in result.errors), result.errors)
        # ...but a warning about empty board/members.
        self.assertTrue(
            any("no board members or regular members" in w for w in result.warnings),
            result.warnings,
        )

    # ----------------------------------------------------------- _is_chair_role

    def test_is_chair_role_true(self):
        role = self._make_role(is_chair=1, is_active=1)
        v = ChapterValidator(self.chapter)
        self.assertTrue(v._is_chair_role(role))

    def test_is_chair_role_false_for_non_chair(self):
        role = self._make_role(is_chair=0, is_active=1)
        v = ChapterValidator(self.chapter)
        self.assertFalse(v._is_chair_role(role))

    def test_is_chair_role_false_for_missing_role(self):
        v = ChapterValidator(self.chapter)
        self.assertFalse(v._is_chair_role("Nonexistent-Role-xyz"))
        self.assertFalse(v._is_chair_role(None))

    # ------------------------------------------- publication readiness "ready"

    def test_publication_readiness_ready_with_chaired_board(self):
        """Long intro + region + 2 active board members incl. a chair -> ready=True, score 100."""
        chair_member, chair_vol = self._make_volunteer(first="RChair")
        _m2, vol2 = self._make_volunteer(first="RMember")
        chair_role = self._make_role(is_chair=1)
        plain_role = self._make_role(is_chair=0)

        self.chapter.introduction = "y" * 120
        self.assertTrue(self.chapter.region)
        self.chapter.address = "Ready Street 1"
        self._append_board(chair_vol.name, chair_role, is_active=1)
        self._append_board(vol2.name, plain_role, is_active=1)

        v = ChapterValidator(self.chapter)
        summary = v.get_validation_summary()
        readiness = summary["ready_for_publication"]
        self.assertEqual(readiness["issues"], [])
        self.assertTrue(readiness["ready"])
        self.assertEqual(readiness["score"], 100)


if __name__ == "__main__":
    import unittest

    unittest.main()
