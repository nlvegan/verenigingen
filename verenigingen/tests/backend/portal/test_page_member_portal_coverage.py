"""
Tests for the member portal landing page
(verenigingen.templates.pages.member_portal).

get_context() reads the member record for the logged-in user (via the `user`
link on Member) and populates the page context with membership, payment status,
quick actions, recent activity, board-member flag and chapter info.

Coverage focus:
- get_context: Guest rejected, logged-in member with record, user without a
  member record (graceful no_member_record), member with/without a volunteer.
- helper functions: get_member_activity, get_quick_actions, get_payment_status,
  get_user_teams, is_user_board_member, get_member_chapter_info,
  get_all_member_chapters, _build_chapter_info, has_website_permission.
"""

import frappe
from frappe.utils import today

from verenigingen.templates.pages import member_portal
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberPortalPage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.user_email = f"portal-{frappe.generate_hash()[:8]}@test.invalid"
        self.member = self._make_member_with_user(self.user_email)

    # ---- fixture helpers (writes allowed here, not in test bodies) ------

    def _make_member_with_user(self, email):
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Portal",
                    "last_name": "User",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        member = self.create_test_member(
            first_name="Portal", last_name="Member", email=email, birth_date="1990-01-01"
        )
        member.db_set("user", email)
        return member

    def _make_user_without_member(self):
        email = f"portal-nomember-{frappe.generate_hash()[:8]}@test.invalid"
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "No",
                    "last_name": "Member",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        return email

    def _ensure_chapter_role(self):
        name = "Member Portal Board Role"
        if not frappe.db.exists("Chapter Role", name):
            frappe.get_doc(
                {
                    "doctype": "Chapter Role",
                    "role_name": name,
                    "permissions_level": "Basic",
                    "is_active": 1,
                }
            ).insert(ignore_permissions=True)
        return name

    def _make_volunteer(self):
        return self.create_test_volunteer(member=self.member.name, volunteer_name="Portal Volunteer")

    def _make_chapter(self):
        return self.create_test_chapter()

    def _persist_chapter_membership(self, chapter):
        """Attach self.member to the chapter via the Chapter Member child table."""
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append(
            "members",
            {
                "member": self.member.name,
                "chapter_join_date": today(),
                "enabled": 1,
                "status": "Active",
            },
        )
        chapter_doc.save(ignore_permissions=True)
        return chapter_doc

    def _persist_board_member(self, chapter, volunteer):
        chapter_role = self._ensure_chapter_role()
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "volunteer_name": volunteer.volunteer_name,
                "email": getattr(volunteer, "email", None) or self.user_email,
                "chapter_role": chapter_role,
                "from_date": today(),
                "is_active": 1,
            },
        )
        chapter_doc.save(ignore_permissions=True)
        return chapter_doc

    def _get_context_as(self, email):
        with self.as_user(email):
            ctx = frappe._dict()
            with self.assertNoErrorLog():
                member_portal.get_context(ctx)
        return ctx

    # ---- get_context branches -------------------------------------------

    def test_guest_is_rejected(self):
        with self.as_user("Guest"):
            ctx = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                member_portal.get_context(ctx)

    def test_member_with_record_populates_context(self):
        ctx = self._get_context_as(self.user_email)
        self.assertFalse(ctx.no_member_record)
        self.assertEqual(ctx.member.name, self.member.name)
        self.assertTrue(ctx.title)
        # payment_status is a dict (member has a record); quick_actions a list
        self.assertIsInstance(ctx.quick_actions, list)
        self.assertGreater(len(ctx.quick_actions), 0)
        self.assertIsInstance(ctx.recent_activity, list)
        self.assertIsInstance(ctx.is_board_member, bool)
        self.assertIsInstance(ctx.chapters_info, list)
        # No volunteer record yet
        self.assertIsNone(ctx.volunteer)
        self.assertEqual(ctx.volunteer_hours, 0)
        self.assertEqual(ctx.user_teams, [])

    def test_user_without_member_record_graceful(self):
        email = self._make_user_without_member()
        ctx = self._get_context_as(email)
        self.assertTrue(ctx.no_member_record)
        self.assertTrue(ctx.error_title)
        self.assertTrue(ctx.error_message)
        # support_email key is always set (value may be None depending on settings)
        self.assertIn("support_email", ctx)
        # short-circuit return: member context never set
        self.assertIsNone(ctx.get("member"))

    def test_member_with_volunteer_on_team(self):
        # Saving a team with members enqueues team-history / notification jobs
        # that run after the test rollback and log "Team ... not found"
        # (a known async-after-rollback fixture artifact, not under test here).
        self.expectErrorLog("Team Assignment History", "Team Notification")
        volunteer = self._make_volunteer()
        team = self.create_test_team(team_name="Portal Page Team")
        team.append(
            "team_members",
            {
                "volunteer": volunteer.name,
                "volunteer_name": volunteer.volunteer_name,
                "team_role": "Team Member",
                "role_type": "Team Member",
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        team.save()

        ctx = self._get_context_as(self.user_email)
        self.assertIsNotNone(ctx.volunteer)
        self.assertEqual(ctx.volunteer.name, volunteer.name)
        # volunteer_hours computed from Volunteer Assignment sum -> numeric
        self.assertIsInstance(ctx.volunteer_hours, (int, float))
        self.assertEqual(ctx.volunteer_hours, 0)
        self.assertTrue(any(t.name == team.name for t in ctx.user_teams))

    def test_member_without_volunteer_has_empty_teams(self):
        ctx = self._get_context_as(self.user_email)
        self.assertIsNone(ctx.volunteer)
        self.assertEqual(ctx.user_teams, [])

    # ---- has_website_permission -----------------------------------------

    def test_website_permission_denies_guest(self):
        self.assertFalse(member_portal.has_website_permission(None, "read", "Guest"))

    def test_website_permission_requires_member_email(self):
        # The helper looks up Member by its `email` field. Assert against the
        # member's *persisted* email — the factory may append a uniqueness suffix
        # to the requested email (when the local part lacks a trailing digit), so
        # self.user_email is not guaranteed to equal Member.email. Using
        # self.member.email keeps this deterministic instead of flaky ~0.7%/run.
        self.assertTrue(member_portal.has_website_permission(None, "read", self.member.email))
        self.assertFalse(member_portal.has_website_permission(None, "read", "nobody-portal@test.invalid"))

    # ---- get_member_activity --------------------------------------------

    def test_get_member_activity_returns_list(self):
        with self.assertNoErrorLog():
            activities = member_portal.get_member_activity(self.member.name)
        self.assertIsInstance(activities, list)
        # newly-created member: includes at least the "Profile updated" entry
        self.assertLessEqual(len(activities), 5)
        for act in activities:
            self.assertIn("description", act)
            self.assertIn("date", act)
            self.assertIn("icon", act)

    def test_get_member_activity_with_volunteer(self):
        volunteer = self._make_volunteer()
        with self.as_user(self.user_email):
            with self.assertNoErrorLog():
                activities = member_portal.get_member_activity(self.member.name)
        self.assertIsInstance(activities, list)
        self.assertTrue(volunteer.name)  # sanity: volunteer created

    # ---- get_quick_actions ----------------------------------------------

    def test_get_quick_actions_without_volunteer(self):
        member_doc = frappe.get_doc("Member", self.member.name)
        with self.assertNoErrorLog():
            actions = member_portal.get_quick_actions(member_doc, None, None)
        self.assertIsInstance(actions, list)
        routes = [a["route"] for a in actions]
        # Payment Dashboard, Documents and Contact Support are always present
        self.assertIn("/payment_dashboard", routes)
        self.assertIn("/board/document_browser", routes)
        self.assertIn("/contact_request", routes)
        # no volunteer -> no volunteer dashboard action
        self.assertNotIn("/volunteer/dashboard", routes)

    def test_get_quick_actions_with_volunteer(self):
        volunteer = self._make_volunteer()
        member_doc = frappe.get_doc("Member", self.member.name)
        volunteer_doc = frappe.get_doc("Volunteer", volunteer.name)
        with self.assertNoErrorLog():
            actions = member_portal.get_quick_actions(member_doc, None, volunteer_doc)
        routes = [a["route"] for a in actions]
        self.assertIn("/volunteer/dashboard", routes)
        for a in actions:
            self.assertIn("title", a)
            self.assertIn("class", a)
            self.assertIn("icon", a)

    # ---- get_payment_status ---------------------------------------------

    def test_get_payment_status_returns_none_for_missing_member(self):
        self.assertIsNone(member_portal.get_payment_status(None, None))

    def test_get_payment_status_dict_for_member(self):
        member_doc = frappe.get_doc("Member", self.member.name)
        with self.assertNoErrorLog():
            status = member_portal.get_payment_status(member_doc, None)
        # member with no membership / no invoices -> up to date, zero outstanding
        self.assertIsInstance(status, dict)
        self.assertIn("current_fee", status)
        self.assertIn("billing_frequency", status)
        self.assertIn("outstanding_amount", status)
        self.assertIn("outstanding_invoices", status)
        self.assertIn("payment_up_to_date", status)
        self.assertEqual(status["outstanding_amount"], 0)
        self.assertTrue(status["payment_up_to_date"])
        self.assertFalse(status["has_overdue"])

    # ---- get_user_teams --------------------------------------------------

    def test_get_user_teams_empty_for_unassigned_volunteer(self):
        volunteer = self._make_volunteer()
        teams = member_portal.get_user_teams(volunteer.name)
        self.assertIsInstance(teams, list)
        self.assertEqual(teams, [])

    def test_get_user_teams_returns_active_team(self):
        # See note in test_member_with_volunteer_on_team: team save enqueues
        # bg jobs that log post-rollback. Register them as expected fixture noise.
        self.expectErrorLog("Team Assignment History", "Team Notification")
        volunteer = self._make_volunteer()
        team = self.create_test_team(team_name="Portal Teams Helper")
        team.append(
            "team_members",
            {
                "volunteer": volunteer.name,
                "volunteer_name": volunteer.volunteer_name,
                "team_role": "Team Member",
                "role_type": "Team Member",
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        team.save()
        teams = member_portal.get_user_teams(volunteer.name)
        self.assertTrue(any(t.name == team.name for t in teams))

    # ---- is_user_board_member -------------------------------------------

    def test_is_user_board_member_false_for_plain_member(self):
        with self.as_user(self.user_email):
            self.assertFalse(member_portal.is_user_board_member())

    def test_is_user_board_member_true_for_board_volunteer(self):
        volunteer = self._make_volunteer()
        chapter = self._make_chapter()
        self._persist_board_member(chapter, volunteer)
        with self.as_user(self.user_email):
            with self.assertNoErrorLog():
                self.assertTrue(member_portal.is_user_board_member())

    def test_is_user_board_member_true_for_admin(self):
        # Administrator holds System Manager -> admin short-circuit
        with self.as_user("Administrator"):
            self.assertTrue(member_portal.is_user_board_member())

    # ---- get_member_chapter_info ----------------------------------------

    def test_get_member_chapter_info_with_chapter(self):
        volunteer = self._make_volunteer()
        chapter = self._make_chapter()
        self._persist_chapter_membership(chapter)
        self._persist_board_member(chapter, volunteer)
        with self.as_user(self.user_email):
            with self.assertNoErrorLog():
                info = member_portal.get_member_chapter_info(self.member.name)
        self.assertIsInstance(info, dict)
        self.assertEqual(info["chapter_name"], chapter.name)
        self.assertIn("board_members", info)
        self.assertIn("is_national", info)
        self.assertTrue(any(bm["volunteer"] == volunteer.name for bm in info["board_members"]))

    def test_get_member_chapter_info_no_chapter_no_national(self):
        # Member belongs to no chapter; if no national chapter configured -> None.
        national = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        info = member_portal.get_member_chapter_info(self.member.name)
        if national:
            self.assertIsInstance(info, dict)
        else:
            self.assertIsNone(info)

    # ---- get_all_member_chapters ----------------------------------------

    def test_get_all_member_chapters_returns_list(self):
        chapter = self._make_chapter()
        self._persist_chapter_membership(chapter)
        with self.as_user(self.user_email):
            with self.assertNoErrorLog():
                chapters = member_portal.get_all_member_chapters(self.member.name)
        self.assertIsInstance(chapters, list)
        self.assertTrue(any(c["chapter_name"] == chapter.name for c in chapters))
        for c in chapters:
            self.assertIn("board_members", c)
            self.assertIn("documents", c)
            self.assertIn("is_national", c)

    # ---- _build_chapter_info --------------------------------------------

    def test_build_chapter_info_for_chapter(self):
        volunteer = self._make_volunteer()
        chapter = self._make_chapter()
        self._persist_board_member(chapter, volunteer)
        with self.assertNoErrorLog():
            info = member_portal._build_chapter_info(chapter.name, False, self.user_email)
        self.assertIsInstance(info, dict)
        self.assertEqual(info["chapter_name"], chapter.name)
        self.assertFalse(info["is_national"])
        self.assertEqual(info["total_count"], len(info["board_members"]))
        self.assertTrue(any(bm["volunteer"] == volunteer.name for bm in info["board_members"]))

    def test_build_chapter_info_nonexistent_chapter_returns_none(self):
        # logs an error internally -> register it as expected so tearDown ignores it
        self.expectErrorLog("Error building chapter info")
        info = member_portal._build_chapter_info("Nonexistent-Chapter-XYZ", False, self.user_email)
        self.assertIsNone(info)
