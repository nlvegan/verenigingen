"""
Tests for the volunteer skills directory portal page
(verenigingen.templates.pages.volunteer.skills).

Access is restricted to chapter board members. get_context() must:
- raise PermissionError for Guest (require_login)
- set no_access=True + error_message for a logged-in NON-board member
- for a board member: expose user_chapters, skills_by_category, skills_stats
- run a filtered search when form_dict carries skill/category/min_level

The helper functions (get_user_board_chapters, get_chapter_member_ids,
get_skills_grouped_by_category, get_skills_statistics,
search_volunteers_by_skill_filtered) are exercised against real
Chapter/Chapter Board Member/Volunteer Skill data.
"""

import frappe
from frappe.utils import today

from verenigingen.templates.pages.volunteer import skills
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerSkillsPage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._ensure_chapter_role("Test Board Role")
        self.user_email = f"skills-{frappe.generate_hash()[:8]}@test.invalid"
        self.member = self._make_member_with_user(self.user_email)
        self.volunteer = self.create_test_volunteer(
            member=self.member.name, volunteer_name="Skills Board Volunteer"
        )
        self.chapter = self._make_board_chapter(self.member.name, self.volunteer.name)
        self._add_skill(self.volunteer.name, "Technical", "Python Programming", "4 - Advanced")

    def _ensure_chapter_role(self, role_name):
        """Ensure the Chapter Role master exists (board_members.chapter_role links
        to it). It is seeded on long-lived sites but absent on a fresh CI site,
        where its absence made the board fixture raise LinkValidationError in
        setUp and failed every test in this class."""
        if not frappe.db.exists("Chapter Role", role_name):
            frappe.get_doc({"doctype": "Chapter Role", "role_name": role_name, "is_active": 1}).insert(
                ignore_permissions=True
            )

    def _make_member_with_user(self, email):
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Skill",
                    "last_name": "User",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        member = self.create_test_member(
            first_name="Skill", last_name="Member", email=email, birth_date="1990-01-01"
        )
        member.db_set("user", email)
        return member

    def _make_board_chapter(self, member_name, volunteer_name):
        chapter = self.create_test_chapter(chapter_name=f"Skills Chapter {frappe.generate_hash()[:6]}")
        chapter.append(
            "members",
            {"member": member_name, "enabled": 1, "status": "Active", "chapter_join_date": today()},
        )
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer_name,
                "chapter_role": "Test Board Role",
                "from_date": today(),
                "is_active": 1,
            },
        )
        chapter.save()
        return chapter

    def _add_skill(self, volunteer_name, category, skill_name, level):
        vol = frappe.get_doc("Volunteer", volunteer_name)
        vol.append(
            "skills_and_qualifications",
            {"skill_category": category, "volunteer_skill": skill_name, "proficiency_level": level},
        )
        vol.save()

    # ---- get_context branches ------------------------------------------

    def test_guest_is_rejected(self):
        with self.as_user("Guest"):
            ctx = {}
            with self.assertRaises(frappe.PermissionError):
                skills.get_context(ctx)

    def test_non_board_member_is_denied(self):
        other_email = f"skills-nonboard-{frappe.generate_hash()[:8]}@test.invalid"
        self._make_member_with_user(other_email)
        with self.as_user(other_email):
            ctx = {}
            skills.get_context(ctx)
        self.assertTrue(ctx["no_access"])
        self.assertIn("chapter board member", ctx["error_message"])

    def test_board_member_sees_directory(self):
        with self.as_user(self.user_email):
            ctx = {}
            # Own the "no search params" precondition: get_context() reads
            # skill/category/min_level off frappe.form_dict and runs a filtered
            # search when any is present. A sibling test in another module can
            # leave those keys in frappe.local.form_dict (the setUp proxy re-bind
            # does NOT clear stale keys), which would make search_results non-None
            # and break the assertIsNone below only inside a CI shard. Pin an
            # empty form_dict so this test does not depend on leaked request state.
            original = frappe.form_dict
            frappe.form_dict = frappe._dict({})
            try:
                skills.get_context(ctx)
            finally:
                frappe.form_dict = original
        self.assertFalse(ctx["no_access"])
        self.assertTrue(any(c.get("chapter_name") == self.chapter.name for c in ctx["user_chapters"]))
        # Our seeded board member's own member id is in scope
        self.assertIn(self.member.name, ctx["chapter_member_ids"])
        # The seeded skill appears grouped under its category
        self.assertIn("Technical", ctx["skills_by_category"])
        self.assertGreaterEqual(ctx["skills_stats"]["total_unique_skills"], 1)
        self.assertIsNone(ctx["search_results"])

    def test_context_exposes_the_logo_variable_the_template_reads(self):
        """skills.html renders the header logo from context.organization_logo.

        It previously read `brand_logo`, which no controller in the app ever set
        (every other page uses organization_logo). Jinja renders an undefined name
        as falsy, so the logo silently never appeared and nothing failed. Assert on
        the key's presence, not its value: it is None unless Brand Settings has a
        logo configured, and the template guards with {% if %}.
        """
        with self.as_user(self.user_email):
            ctx = {}
            original = frappe.form_dict
            frappe.form_dict = frappe._dict({})
            try:
                skills.get_context(ctx)
            finally:
                frappe.form_dict = original

        self.assertIn("organization_logo", ctx)
        self.assertNotIn("brand_logo", ctx)

    def test_board_member_search_filters_results(self):
        with self.as_user(self.user_email):
            ctx = {}
            original = frappe.form_dict
            frappe.form_dict = frappe._dict({"skill": "Python", "category": "", "min_level": ""})
            try:
                skills.get_context(ctx)
            finally:
                frappe.form_dict = original
        self.assertIsNotNone(ctx["search_results"])
        self.assertTrue(any("Python" in r["volunteer_skill"] for r in ctx["search_results"]))

    # ---- helper functions ----------------------------------------------

    def test_get_user_board_chapters(self):
        with self.as_user(self.user_email):
            chapters = skills.get_user_board_chapters()
        self.assertTrue(any(c["chapter_name"] == self.chapter.name for c in chapters))

    def test_get_chapter_member_ids(self):
        ids = skills.get_chapter_member_ids([self.chapter.name])
        self.assertIn(self.member.name, ids)

    def test_get_chapter_member_ids_empty(self):
        self.assertEqual(skills.get_chapter_member_ids([]), [])

    def test_search_filtered_requires_member_ids(self):
        self.assertEqual(skills.search_volunteers_by_skill_filtered(member_ids=None), [])

    def test_search_filtered_with_min_level(self):
        results = skills.search_volunteers_by_skill_filtered(
            skill_name="Python", min_level=3, member_ids=[self.member.name]
        )
        self.assertTrue(any(r["volunteer_id"] == self.volunteer.name for r in results))

    def test_get_skills_statistics_empty_for_no_members(self):
        stats = skills.get_skills_statistics(member_ids=[])
        self.assertEqual(stats["total_unique_skills"], 0)

    def test_get_skills_grouped_empty_for_no_members(self):
        self.assertEqual(skills.get_skills_grouped_by_category(member_ids=[]), {})
