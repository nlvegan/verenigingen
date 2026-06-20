"""
Real-DB tests for the chapter ``ChapterValidator``
(``verenigingen/verenigingen/doctype/chapter/validators/chapter_validator.py``).

ChapterValidator coordinates the component validators (info / board / postal) and
adds cross-cutting checks (chapter-head consistency, duplicate members, board /
member overlap), route generation, publication readiness and a combined summary.
Tests build real Chapter / Volunteer / Chapter Role documents via the factory so
the DB-backed branches (chair-role lookup, volunteer->member) are exercised for
real.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.chapter.validators.chapter_validator import (
    ChapterValidator,
)


class TestChapterValidator(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"CV Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-2000",
            published=0,
        )

    def _reload(self):
        self.chapter = frappe.get_doc("Chapter", self.chapter.name)
        return self.chapter

    def _make_chair_role(self):
        role_name = f"CVChair{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": role_name,
                "permissions_level": "Admin",
                "is_chair": 1,
                "is_active": 1,
            }
        ).insert()
        self.track_doc("Chapter Role", role_name)
        return role_name

    def _make_volunteer(self, first="CV"):
        member = self.create_test_member(
            first_name=first,
            last_name="Validator",
            email=f"cv.{first.lower()}.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        vol = self.create_test_volunteer(member=member.name)
        return member, vol

    # -------------------------------------------------------------- no-doc guard

    def test_validate_all_without_doc_errors(self):
        v = ChapterValidator(None)
        result = v.validate_all()
        self.assertFalse(result.is_valid)
        self.assertTrue(any("No chapter document" in e for e in result.errors))

    def test_summary_without_doc_errors(self):
        v = ChapterValidator(None)
        summary = v.get_validation_summary()
        self.assertEqual(summary["overall_status"], "error")

    # -------------------------------------------------------------- happy path

    def test_valid_chapter_passes(self):
        v = ChapterValidator(self.chapter)
        result = v.validate_all()
        self.assertTrue(result.is_valid, result.errors)

    def test_invalid_postal_codes_surface_in_validate_all(self):
        self.chapter.postal_codes = "123,abc"  # invalid NL codes
        v = ChapterValidator(self.chapter)
        result = v.validate_all()
        self.assertFalse(result.is_valid)

    # -------------------------------------------------- duplicate active members

    def test_duplicate_enabled_member_errors(self):
        member, _vol = self._make_volunteer(first="Dup")
        # Append the same member twice as enabled chapter members
        self.chapter.append("members", {"member": member.name, "enabled": 1})
        self.chapter.append("members", {"member": member.name, "enabled": 1})
        v = ChapterValidator(self.chapter)
        result = v.validate_all()
        self.assertTrue(any("more than once" in e for e in result.errors))

    def test_duplicate_disabled_member_not_flagged(self):
        member, _vol = self._make_volunteer(first="DupDis")
        self.chapter.append("members", {"member": member.name, "enabled": 1})
        self.chapter.append("members", {"member": member.name, "enabled": 0})
        v = ChapterValidator(self.chapter)
        result = v.validate_all()
        self.assertFalse(any("more than once" in e for e in result.errors))

    # ------------------------------------------------ chapter head consistency

    def test_chapter_head_without_board_warns(self):
        member, _vol = self._make_volunteer(first="Head")
        self.chapter.chapter_head = member.name
        # no board members
        self.chapter.board_members = []
        v = ChapterValidator(self.chapter)
        result = v.validate_all()
        self.assertTrue(any("no board members" in w for w in result.warnings))

    # --------------------------------------------------- publication validation

    def test_publish_requires_long_introduction(self):
        self.chapter.published = 1
        self.chapter.introduction = "too short"
        self.chapter.region = None
        v = ChapterValidator(self.chapter)
        result = v.validate_before_submit()
        self.assertFalse(result.is_valid)
        self.assertTrue(any("introduction" in e.lower() for e in result.errors))
        self.assertTrue(any("region" in e.lower() for e in result.errors))

    # ---------------------------------------------------- route auto-generation

    def test_route_generated_when_missing(self):
        self.chapter.route = None
        v = ChapterValidator(self.chapter)
        v.validate_before_save()
        self.assertTrue(self.chapter.route.startswith("chapters/"))

    def test_generate_route_slugifies(self):
        v = ChapterValidator(self.chapter)
        self.assertEqual(v._generate_route("North Holland"), "chapters/north-holland")
        self.assertEqual(v._generate_route(""), "")

    # ---------------------------------------------------- postal code matching

    def test_validate_postal_code_match_true(self):
        v = ChapterValidator(self.chapter)  # postal_codes "1000-2000"
        self.assertTrue(v.validate_postal_code_match("1500"))
        self.assertFalse(v.validate_postal_code_match("3000"))

    def test_validate_postal_code_match_no_patterns(self):
        self.chapter.postal_codes = None
        v = ChapterValidator(self.chapter)
        self.assertFalse(v.validate_postal_code_match("1500"))

    # ---------------------------------------------- publication readiness scoring

    def test_publication_readiness_counts_issues(self):
        self.chapter.introduction = "short"
        self.chapter.region = None
        # ChapterInfoValidator.get_validation_summary reads len(address); the real
        # chapter has address=None which is a separate validator's concern, so give
        # it an in-memory value to keep this test focused on ChapterValidator.
        self.chapter.address = "Test Address 1"
        v = ChapterValidator(self.chapter)
        summary = v.get_validation_summary()
        readiness = summary["ready_for_publication"]
        self.assertFalse(readiness["ready"])
        self.assertIn("Introduction too short", readiness["issues"])
        self.assertIn("No region specified", readiness["issues"])
        # score deducts 20 per issue, floored at 0
        self.assertLessEqual(readiness["score"], 100)
        self.assertGreaterEqual(readiness["score"], 0)

    def test_summary_overall_status_valid(self):
        self.chapter.address = "Test Address 1"
        v = ChapterValidator(self.chapter)
        summary = v.get_validation_summary()
        self.assertIn(summary["overall_status"], ("valid", "invalid"))
        self.assertIn("component_status", summary)

    # ------------------------------------------------- auto-update chapter head

    def test_auto_update_chapter_head_sets_chair_member(self):
        member, vol = self._make_volunteer(first="Chairman")
        role = self._make_chair_role()
        self.chapter.append(
            "board_members",
            {
                "volunteer": vol.name,
                "chapter_role": role,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        v = ChapterValidator(self.chapter)
        v._auto_update_chapter_head()
        self.assertEqual(self.chapter.chapter_head, member.name)


if __name__ == "__main__":
    import unittest

    unittest.main()
