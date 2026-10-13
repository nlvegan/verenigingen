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

    def _editor_holding_all_but_employee_roles(self, profile, also_lacking=()):
        """A board member holding every role of `profile` except the two that
        erpnext's validate_employee_role strips from a user with no Employee record
        (measured: this editor has none, so the roles cannot be kept on them)."""
        seat = self.create_test_board_member(self.chapter.name)
        stripped = {"Employee", "Employee Self Service"}
        granted = set(
            frappe.get_all("Has Role", filters={"parent": profile, "parenttype": "Role Profile"}, pluck="role")
        )
        self.assertIn("Employee", granted, "control: the profile must grant a stripped role")
        # Probe shortcut: the fixture's real flow gives the seat holder an Employee record
        # (user_role_profile_calculator._ensure_employee_for_profile), so real seat holders
        # normally HOLD Employee/ESS and are not refused. The refusal only hits an editor
        # with NO Employee record (disabled user, no linked Member, no Verenigingen
        # Settings.company, hand-built user). Unlinking with db.set_value stands in for
        # that; the premise is established for such editors, not for typical seat holders.
        frappe.db.set_value("Employee", {"user_id": seat.user}, "user_id", None)
        user = frappe.get_doc("User", seat.user)
        user.add_roles(*sorted(granted - stripped - set(also_lacking) - {"All"}))
        user.remove_roles(*stripped)
        self.assertFalse(frappe.db.get_value("Employee", {"user_id": seat.user}), "control: no Employee record")
        return seat

    def test_employee_roles_stripped_from_users_without_an_employee_record_do_not_block_mapping(self):
        """#1649: Employee / Employee Self Service can never be held by an editor with
        no Employee record, so requiring them refused every non-System-Manager editor."""
        profile = "Verenigingen Chapter Board Member"
        seat = self._editor_holding_all_but_employee_roles(profile)

        with self.as_user(seat.user):
            self.assertNotIn("Employee", frappe.get_roles())
            self._save_default(profile)

        self.assertEqual(frappe.db.get_value("Chapter", self.chapter.name, "default_board_role_profile"), profile)

    def test_employee_role_exemption_does_not_hide_a_real_missing_role(self):
        """PLAIN_PROFILE grants Employee AND Auditor. Only Auditor is a real gap. The
        editor has no Employee record (probe shortcut, see the helper) so the message
        would name Employee if the exemption were missing."""
        seat = self._editor_holding_all_but_employee_roles(PLAIN_PROFILE, also_lacking=("Auditor",))

        with self.as_user(seat.user):
            self.assertNotIn("Auditor", frappe.get_roles())
            self.assertNotIn("Employee", frappe.get_roles())
            with self.assertRaises(frappe.ValidationError) as ctx:
                self._save_default(PLAIN_PROFILE)

        self.assertIn("grants roles you do not hold (Auditor", str(ctx.exception))
        self.assertNotIn("Employee", str(ctx.exception))
        self.assertFalse(frappe.db.get_value("Chapter", self.chapter.name, "default_board_role_profile"))

    def test_exemption_is_not_a_substring_match_on_employee(self):
        """A real role whose name merely contains 'Employee' is still required."""
        role = frappe.get_doc(
            {"doctype": "Role", "role_name": f"Employee Manager Guard {frappe.generate_hash(length=6)}"}
        ).insert()
        profile = frappe.get_doc(
            {
                "doctype": "Role Profile",
                "role_profile": f"Guard Employee Mgr {frappe.generate_hash(length=6)}",
                "roles": [{"role": role.name}],
            }
        ).insert()
        seat = self.create_test_board_member(self.chapter.name)

        with self.as_user(seat.user):
            self.assertNotIn(role.name, frappe.get_roles())
            with self.assertRaisesRegex(frappe.ValidationError, role.name):
                self._save_default(profile.name)

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


    def test_board_member_cannot_widen_an_existing_mapping_to_the_default_slot(self):
        """An admin mapped PLAIN_PROFILE to one chapter role only. Moving it to the
        default slot hands its roles to the whole board, the editor included."""
        seat = self.create_test_board_member(self.chapter.name)
        other_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Guard Narrow Role {frappe.generate_hash(length=6)}",
                "permissions_level": "Basic",
                "is_active": 1,
            }
        ).insert()
        doc = frappe.get_doc("Chapter", self.chapter.name)
        doc.enable_board_role_specific_profiles = 1
        doc.append("board_role_specific_profiles", {"chapter_role": other_role.name, "role_profile": PLAIN_PROFILE})
        doc.save()

        with self.as_user(seat.user):
            self.assertNotIn("Verenigingen Auditor", frappe.get_roles())
            with self.assertRaisesRegex(frappe.ValidationError, "Verenigingen Auditor"):
                self._save_default(PLAIN_PROFILE)

        self.assertFalse(frappe.db.get_value("Chapter", self.chapter.name, "default_board_role_profile"))

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

    def _role_profile_granting(self, *roles):
        profile = frappe.get_doc(
            {
                "doctype": "Role Profile",
                "role_profile": f"Guard Payroll {frappe.generate_hash(length=6)}",
                "roles": [{"role": r} for r in roles],
            }
        ).insert()
        self.addCleanup(frappe.delete_doc, "Role Profile", profile.name, force=True)
        return profile.name

    def test_a_holder_of_hr_manager_cannot_map_a_profile_granting_it(self):
        """#1606: HR Manager is the Treasurer's alone. Holding it (so the roles-held rule is
        satisfied) must not let an editor map it onto a team.

        Probe shortcut, stated: the guard is called directly as the Treasurer-role user, with the
        arguments Team.validate passes (team_service), because no stock Team DocPerm lets that
        role save a Team it does not lead; the Team-save wiring is covered by the other tests here.
        """
        from verenigingen.services.member.account.role_profile_mapping_guard import validate_mapped_profiles

        email = f"treasurer-editor-{frappe.generate_hash(length=8)}@example.com"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Treas",
                "send_welcome_email": 0,
                "roles": [{"role": r} for r in ("Verenigingen Staff", "HR Manager", "Projects User")],
            }
        ).insert()
        payroll = self._role_profile_granting("HR Manager")
        harmless = self._role_profile_granting("Projects User")
        with self.as_user(email):
            self.assertIn("HR Manager", frappe.get_roles())  # control: roles-held would allow it
            with self.assertRaisesRegex(frappe.ValidationError, "payroll access"):
                validate_mapped_profiles({("default", payroll)}, set(), national_allowed=False)
            # control: the same editor may still map a profile within their roles
            validate_mapped_profiles({("default", harmless)}, set(), national_allowed=False)

    def test_national_profile_is_refused_on_a_team(self):
        with self.assertRaisesRegex(frappe.ValidationError, "national"):
            self._save_team_default(NATIONAL_PROFILE)

    def test_plain_profile_is_allowed_for_administrator(self):
        self._save_team_default(PLAIN_PROFILE)

        self.assertEqual(frappe.db.get_value("Team", self.team.name, "default_role_profile"), PLAIN_PROFILE)
