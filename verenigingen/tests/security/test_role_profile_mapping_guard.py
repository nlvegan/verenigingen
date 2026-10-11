"""
Who may map which Role Profile onto a chapter board or a team (#1616).

A chapter's board members can edit their own chapter, including the board's role
profile mapping, and the next profile sync applies whatever is mapped. With no check
on the mapping, a board member could map "Verenigingen Administrator" (System
Manager) onto their own board. The rules:

- a newly mapped profile must not grant a role the editor does not hold
  (System Manager / Administrator exempt), so a board member cannot map one that
  grants System Manager. Mappings already in place do not block an unrelated save;
- the national board / treasurer profiles only on Verenigingen Settings'
  national_board_chapter (never on a team), whoever maps them.

A System Manager may map a profile granting System Manager: the association-wide
"Landelijk Beheer" team is wired to "Verenigingen Administrator" on purpose.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

SYSTEM_PROFILE = "Verenigingen Administrator"  # grants System Manager
NATIONAL_PROFILE = "Verenigingen National Board Member"
PLAIN_PROFILE = "Verenigingen Auditor"  # neither system nor national


class TestChapterBoardProfileMapping(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter()
        old = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        self.addCleanup(frappe.db.set_single_value, "Verenigingen Settings", "national_board_chapter", old)
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", None)

    def _save_default(self, profile, chapter=None):
        doc = frappe.get_doc("Chapter", (chapter or self.chapter).name)
        doc.default_board_role_profile = profile
        doc.save()

    def test_control_fixture_profiles_grant_what_the_tests_assume(self):
        def roles(profile):
            return set(frappe.get_all("Has Role", filters={"parent": profile, "parenttype": "Role Profile"}, pluck="role"))

        self.assertIn("System Manager", roles(SYSTEM_PROFILE))
        self.assertNotIn("System Manager", roles(PLAIN_PROFILE))
        self.assertNotIn("System Manager", roles(NATIONAL_PROFILE))

    def test_board_member_cannot_map_a_profile_granting_system_manager(self):
        seat = self.create_test_board_member(self.chapter.name)

        with self.as_user(seat.user):
            with self.assertRaisesRegex(frappe.ValidationError, "System Manager"):
                self._save_default(SYSTEM_PROFILE)

        self.assertFalse(frappe.db.get_value("Chapter", self.chapter.name, "default_board_role_profile"))

    def test_board_member_cannot_map_it_in_a_role_specific_row_either(self):
        seat = self.create_test_board_member(self.chapter.name)
        role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Guard Test Role {frappe.generate_hash(length=6)}",
                "permissions_level": "Basic",
                "is_active": 1,
            }
        ).insert()
        with self.as_user(seat.user):
            doc = frappe.get_doc("Chapter", self.chapter.name)
            doc.enable_board_role_specific_profiles = 1
            doc.append(
                "board_role_specific_profiles", {"chapter_role": role.name, "role_profile": SYSTEM_PROFILE}
            )
            with self.assertRaisesRegex(frappe.ValidationError, "System Manager"):
                doc.save()

    def test_national_profile_is_refused_outside_the_national_chapter(self):
        with self.assertRaisesRegex(frappe.ValidationError, "national"):
            self._save_default(NATIONAL_PROFILE)

    def test_national_profile_is_allowed_on_the_national_chapter(self):
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", self.chapter.name)

        self._save_default(NATIONAL_PROFILE)

        self.assertEqual(
            frappe.db.get_value("Chapter", self.chapter.name, "default_board_role_profile"), NATIONAL_PROFILE
        )

    def test_plain_profile_is_allowed_for_administrator(self):
        self._save_default(PLAIN_PROFILE)

        self.assertEqual(
            frappe.db.get_value("Chapter", self.chapter.name, "default_board_role_profile"), PLAIN_PROFILE
        )

    def test_board_member_cannot_map_a_profile_granting_roles_they_lack(self):
        seat = self.create_test_board_member(self.chapter.name)

        with self.as_user(seat.user):
            self.assertNotIn("Verenigingen Auditor", frappe.get_roles())
            with self.assertRaisesRegex(frappe.ValidationError, "Verenigingen Auditor"):
                self._save_default(PLAIN_PROFILE)

        self.assertFalse(frappe.db.get_value("Chapter", self.chapter.name, "default_board_role_profile"))

    def test_board_member_may_map_a_profile_within_their_own_roles(self):
        seat = self.create_test_board_member(self.chapter.name)

        with self.as_user(seat.user):
            self._save_default("Verenigingen Chapter Board Member")

        self.assertEqual(
            frappe.db.get_value("Chapter", self.chapter.name, "default_board_role_profile"),
            "Verenigingen Chapter Board Member",
        )

    def test_existing_mapping_does_not_block_a_board_members_unrelated_save(self):
        seat = self.create_test_board_member(self.chapter.name)
        self._save_default(PLAIN_PROFILE)  # set by Administrator
        # Control: the mapping is really in place, and the board member really lacks its roles.
        self.assertEqual(
            frappe.db.get_value("Chapter", self.chapter.name, "default_board_role_profile"), PLAIN_PROFILE
        )

        with self.as_user(seat.user):
            self.assertNotIn("Verenigingen Auditor", frappe.get_roles())
            doc = frappe.get_doc("Chapter", self.chapter.name)
            doc.introduction = "Edited by the board"
            doc.save()

        self.assertEqual(frappe.db.get_value("Chapter", self.chapter.name, "introduction"), "Edited by the board")


    def test_existing_national_mapping_does_not_block_a_save_after_the_national_chapter_moves(self):
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", self.chapter.name)
        self._save_default(NATIONAL_PROFILE)
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", None)

        doc = frappe.get_doc("Chapter", self.chapter.name)
        doc.introduction = "Edited after the national chapter moved"
        doc.save()

        self.assertEqual(
            frappe.db.get_value("Chapter", self.chapter.name, "default_board_role_profile"), NATIONAL_PROFILE
        )

    def test_provisioning_by_a_non_system_manager_still_creates_the_chapter(self):
        """ensure_chapter maps a fixed profile of its own; the caller's roles do not matter."""
        from verenigingen.services.chapter.chapter_provisioning_service import ensure_chapter

        email = f"staff-{frappe.generate_hash(length=8)}@example.com"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Staff",
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Staff"}],
            }
        ).insert()
        name = f"Guard Provisioned {frappe.generate_hash(length=6)}"

        with self.as_user(email):
            self.assertNotIn("System Manager", frappe.get_roles())
            created = ensure_chapter(name, default_region=self.chapter.region)

        if created:
            self.addCleanup(frappe.delete_doc, "Chapter", created, force=True)
        self.assertEqual(created, name)
        self.assertEqual(
            frappe.db.get_value("Chapter", name, "default_board_role_profile"), "Verenigingen Chapter Board Member"
        )


class TestTeamProfileMapping(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.team = self.create_test_team()

    def _save_team_default(self, profile):
        doc = frappe.get_doc("Team", self.team.name)
        doc.default_role_profile = profile
        doc.save()

    def test_administrator_may_map_a_system_profile_as_landelijk_beheer_does(self):
        self._save_team_default(SYSTEM_PROFILE)

        self.assertEqual(frappe.db.get_value("Team", self.team.name, "default_role_profile"), SYSTEM_PROFILE)

    def test_default_mijnrood_teams_are_created_by_a_non_system_manager(self):
        """_ensure_default_teams maps fixed profiles (Landelijk Beheer -> Verenigingen
        Administrator); a Verenigingen Administrator without System Manager runs it."""
        self.assertFalse(frappe.db.exists("Team", "Landelijk Beheer"))
        email = f"vadmin-{frappe.generate_hash(length=8)}@example.com"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "VAdmin",
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Administrator"}],
            }
        ).insert()

        with self.as_user(email):
            self.assertNotIn("System Manager", frappe.get_roles())
            frappe.get_doc("MijnRood Sync Settings")._ensure_default_teams()

        self.assertEqual(frappe.db.get_value("Team", "Landelijk Beheer", "default_role_profile"), SYSTEM_PROFILE)

    def test_team_editor_cannot_map_a_profile_granting_roles_they_lack(self):
        # A Verenigingen Administrator without System Manager may edit any team.
        email = f"team-editor-{frappe.generate_hash(length=8)}@example.com"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Editor",
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Administrator"}],
            }
        ).insert()
        with self.as_user(email):
            self.assertNotIn("System Manager", frappe.get_roles())
            self.assertTrue(frappe.has_permission("Team", "write", doc=self.team.name))
            with self.assertRaisesRegex(frappe.ValidationError, "Verenigingen Auditor"):
                self._save_team_default(PLAIN_PROFILE)

    def test_national_profile_is_refused_on_a_team(self):
        with self.assertRaisesRegex(frappe.ValidationError, "national"):
            self._save_team_default(NATIONAL_PROFILE)

    def test_plain_profile_is_allowed_for_administrator(self):
        self._save_team_default(PLAIN_PROFILE)

        self.assertEqual(frappe.db.get_value("Team", self.team.name, "default_role_profile"), PLAIN_PROFILE)
