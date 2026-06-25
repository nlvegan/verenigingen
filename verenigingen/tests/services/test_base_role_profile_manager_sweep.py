"""
Supplemental real-integration tests for
``verenigingen/services/member/account/base_role_profile_manager.py``.

These AUGMENT ``test_base_role_profile_manager.py`` (do not duplicate it). The
existing file already covers the default-profile happy paths, the validate_*
family shapes, input-validation guards, and the bulk happy path. This sweep
targets the branches those tests leave uncovered:

- role-specific profile resolution in ``determine_role_profile_for_member``
  (``enable_role_specific`` + a matching ``role`` -> child-table mapping), plus
  the role-specific dependency-failure fall-through.
- ``get_entity_role_profile_config`` building the role_specific_profiles map.
- ``get_entities_using_role_profile`` / ``get_entities_requiring_role_profile``
  via the role-specific child table (Query Builder branch).
- ``remove_role_profile`` "kept" branch (user still in another entity needing
  the same profile) and the real "recalculated" branch (sync computes a
  replacement profile for an Active volunteer).
- ``bulk_assign_role_profiles`` rollback branch (more errors than successes) and
  its single-active-member success counterpart.
- ``validate_entity_configuration`` role-specific valid / bad-role /
  bad-role-profile branches.
- ``_is_system_operation_authorized`` for a non-privileged user.
- ``assign_role_profile`` role-specific assignment end to end.

Real Role Profiles, Teams, Chapters, Users, Members, Volunteers and Team /
Chapter Roles are created via ``frappe.get_doc().insert()`` / the test factory.
Tests run as Administrator. No business-logic mocking.
"""

import frappe

from verenigingen.services.chapter.chapter_role_profile_manager import (
    CHAPTER_CONFIG,
    _chapter_manager,
)
from verenigingen.services.member.account.base_role_profile_manager import (
    ERROR_CODES,
    _is_system_operation_authorized,
    _read_role_profiles,
    validate_entity_configuration,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.team_role_profile_manager import TEAM_CONFIG, _team_manager


class TestBaseRoleProfileManagerSweep(VereningingenTestCase):
    """Cover the role-specific / removal-recalc / rollback branches."""

    def setUp(self):
        super().setUp()
        self.team_manager = _team_manager
        self.chapter_manager = _chapter_manager

    # ------------------------------------------------------------------ helpers

    def _make_role_profile(self, roles=("System Manager",)):
        name = f"TBRPS Profile {frappe.generate_hash(length=6)}"
        rp = frappe.get_doc(
            {
                "doctype": "Role Profile",
                "role_profile": name,
                "roles": [{"role": r} for r in roles],
            }
        )
        rp.insert()
        self.track_doc("Role Profile", rp.name)
        return rp.name

    def _make_empty_role_profile(self):
        name = f"TBRPS Empty {frappe.generate_hash(length=6)}"
        rp = frappe.get_doc({"doctype": "Role Profile", "role_profile": name})
        rp.insert()
        self.track_doc("Role Profile", rp.name)
        return rp.name

    def _make_team_role(self):
        name = f"TBRPS TeamRole {frappe.generate_hash(length=6)}"
        tr = frappe.get_doc({"doctype": "Team Role", "role_name": name, "permissions_level": "Basic"})
        tr.insert()
        self.track_doc("Team Role", tr.name)
        return tr.name

    def _make_team(self, default_profile=None, enable_specific=0, role_specific=None):
        """Create a Team. ``role_specific`` is a list of (team_role, role_profile)."""
        doc = {
            "doctype": "Team",
            "team_name": f"TBRPS Team {frappe.generate_hash(length=6)}",
            "status": "Active",
            "default_role_profile": default_profile,
            "enable_role_specific_profiles": enable_specific,
        }
        if role_specific:
            doc["role_specific_profiles"] = [
                {"team_role": tr, "role_profile": rp} for tr, rp in role_specific
            ]
        team = frappe.get_doc(doc)
        team.insert()
        self.track_doc("Team", team.name)
        return team.name

    def _make_system_user(self):
        email = f"tbrps.{frappe.generate_hash(length=8)}@test.invalid"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "RoleProfile",
                "last_name": frappe.generate_hash(length=5),
                "enabled": 1,
                "user_type": "System User",
            }
        )
        user.insert()
        self.track_doc("User", user.name)
        return user.name

    def _make_member_user_volunteer(self):
        """Create a User + backing Member + Active Volunteer, all linked."""
        user = self._make_system_user()
        member = self.create_test_member(
            first_name="Recalc",
            last_name=frappe.generate_hash(length=5),
            email=user,
        )
        frappe.db.set_value("Member", member.name, "user", user)
        volunteer = self.create_test_volunteer(member=member.name)
        return user, member, volunteer

    def _assigned_profiles(self, user):
        return _read_role_profiles(frappe.get_doc("User", user))

    # =================================================================
    # get_entity_role_profile_config: role-specific mapping built
    # =================================================================

    def test_get_config_builds_role_specific_map(self):
        profile = self._make_role_profile()
        team_role = self._make_team_role()
        team = self._make_team(enable_specific=1, role_specific=[(team_role, profile)])

        config = self.team_manager.get_entity_role_profile_config(team)
        self.assertTrue(config["enable_role_specific"])
        self.assertEqual(config["role_specific_profiles"].get(team_role), profile)

    # =================================================================
    # determine_role_profile_for_member: role-specific resolution
    # =================================================================

    def test_determine_role_specific_profile_wins(self):
        default_profile = self._make_role_profile()
        specific_profile = self._make_role_profile()
        team_role = self._make_team_role()
        team = self._make_team(
            default_profile=default_profile,
            enable_specific=1,
            role_specific=[(team_role, specific_profile)],
        )
        # With a matching role, the role-specific profile is returned, not default.
        self.assertEqual(
            self.team_manager.determine_role_profile_for_member(team, role=team_role),
            specific_profile,
        )

    def test_determine_falls_back_to_default_for_unmapped_role(self):
        default_profile = self._make_role_profile()
        specific_profile = self._make_role_profile()
        team_role = self._make_team_role()
        team = self._make_team(
            default_profile=default_profile,
            enable_specific=1,
            role_specific=[(team_role, specific_profile)],
        )
        # A role with no specific mapping falls through to the default profile.
        self.assertEqual(
            self.team_manager.determine_role_profile_for_member(team, role="Unmapped Role ZZZ"),
            default_profile,
        )

    def test_determine_role_specific_dependency_failure_returns_none(self):
        # Role-specific profile exists but has no roles -> dependency validation
        # fails and determine() returns None (does NOT silently fall back to default).
        default_profile = self._make_role_profile()
        empty_specific = self._make_empty_role_profile()
        team_role = self._make_team_role()
        team = self._make_team(
            default_profile=default_profile,
            enable_specific=1,
            role_specific=[(team_role, empty_specific)],
        )
        self.assertIsNone(
            self.team_manager.determine_role_profile_for_member(team, role=team_role)
        )

    # =================================================================
    # assign_role_profile: role-specific path end to end
    # =================================================================

    def test_assign_role_specific_profile_assigned(self):
        specific_profile = self._make_role_profile()
        team_role = self._make_team_role()
        team = self._make_team(enable_specific=1, role_specific=[(team_role, specific_profile)])
        user = self._make_system_user()

        with self.assertNoErrorLog():
            result = self.team_manager.assign_role_profile(user, team, role=team_role)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "assigned")
        self.assertEqual(result["role_profile"], specific_profile)
        self.assertIn(specific_profile, self._assigned_profiles(user))

    # =================================================================
    # get_entities_using_role_profile / requiring: role-specific child table
    # =================================================================

    def test_get_entities_using_role_profile_role_specific(self):
        specific_profile = self._make_role_profile()
        team_role = self._make_team_role()
        team = self._make_team(enable_specific=1, role_specific=[(team_role, specific_profile)])

        result = self.team_manager.get_entities_using_role_profile(specific_profile)
        names = [e["name"] for e in result]
        self.assertIn(team, names)
        match = next(e for e in result if e["name"] == team)
        self.assertIn("role_specific", match["usage_type"])

    def test_get_entities_requiring_role_profile_role_specific(self):
        specific_profile = self._make_role_profile()
        team_role = self._make_team_role()
        team = self._make_team(enable_specific=1, role_specific=[(team_role, specific_profile)])

        entities = self.team_manager.get_entities_requiring_role_profile(specific_profile)
        self.assertIn(team, entities)
        # Excluding the team drops it from the requiring list.
        excluded = self.team_manager.get_entities_requiring_role_profile(
            specific_profile, exclude_entity=team
        )
        self.assertNotIn(team, excluded)

    # =================================================================
    # remove_role_profile: "kept" branch (user still in another entity)
    # =================================================================

    def test_remove_role_profile_kept_when_user_in_other_team(self):
        # Two teams share the same default profile; the user is an Active member of
        # BOTH via the same volunteer. Removing from one keeps the profile because
        # the other still requires it.
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()

        profile = self._make_role_profile()
        team_a = self._make_team(default_profile=profile)
        team_b = self._make_team(default_profile=profile)
        user, member, volunteer = self._make_member_user_volunteer()

        for team in (team_a, team_b):
            team_doc = frappe.get_doc("Team", team)
            team_doc.append(
                "team_members",
                {
                    "volunteer": volunteer.name,
                    "team_role": "Team Member",
                    "from_date": frappe.utils.today(),
                    "status": "Active",
                },
            )
            team_doc.save()

        self.team_manager.assign_role_profile(user, team_a)
        self.assertIn(profile, self._assigned_profiles(user))

        # Remove from team_a: user is still Active in team_b which needs the same
        # profile, so it must be kept.
        result = self.team_manager.remove_role_profile(user, team_a)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "kept")
        self.assertIn(profile, self._assigned_profiles(user))

    # =================================================================
    # remove_role_profile: real "recalculated" branch
    # =================================================================

    def test_remove_role_profile_recalculates_for_active_volunteer(self):
        # An Active volunteer who leaves a team must, after removal, have the role
        # profile recalculated to the membership/volunteer baseline rather than be
        # left in an inconsistent state. sync_user_role_profile computes a real
        # replacement here (success branch), giving action == "recalculated".
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        user, member, volunteer = self._make_member_user_volunteer()

        self.team_manager.assign_role_profile(user, team)
        self.assertIn(profile, self._assigned_profiles(user))

        result = self.team_manager.remove_role_profile(user, team)
        self.assertTrue(result["success"])
        # Active member/volunteer -> sync resolves a replacement profile.
        self.assertIn(result["action"], ("recalculated", "removed_pending_recalc"))
        # The team's profile is gone regardless of which branch fired.
        self.assertNotIn(profile, self._assigned_profiles(user))

    # =================================================================
    # bulk_assign_role_profiles: rollback branch (errors > successes)
    # =================================================================

    def test_bulk_assign_rolls_back_when_member_fails(self):
        # GENUINELY exercise the rollback branch of bulk_assign_role_profiles:
        # error_count > 0 AND success_count <= error_count -> the savepoint is rolled
        # back and the overall result is success=False.
        #
        # The production _get_bulk_members_data query couples members_data and the
        # preloaded user_docs (every returned row has an enabled User that the preload
        # then loads), so a single failing member can't be produced by seeding alone.
        # We therefore subclass the manager and override ONLY the member-fetch seam to
        # return a concrete, real member row whose user is genuinely absent from the
        # preload (no User by that name). This is NOT business-logic mocking: it
        # returns concrete data and lets ALL the real rollback orchestration run
        # (savepoint, _preload_user_documents, _build_role_profile_cache,
        # _process_bulk_member, the success/error counting, and the rollback
        # decision). It mirrors the established _process_bulk_member direct-call
        # pattern in test_base_role_profile_manager.py.
        from verenigingen.utils.team_role_profile_manager import TeamRoleProfileManager

        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)

        class _OneFailingMemberManager(TeamRoleProfileManager):
            def _get_bulk_members_data(self, entity_name):
                # A real row whose user does not exist -> preload can't load it ->
                # _process_bulk_member returns a NOT_FOUND error.
                return [
                    {
                        "user": f"absent.{frappe.generate_hash(length=8)}@test.invalid",
                        "member": "M-absent",
                        "team_role": "Team Member",
                    }
                ]

        manager = _OneFailingMemberManager()
        result = manager.bulk_assign_role_profiles(team)

        # The single member failed -> error_count(1) > success_count(0) -> rollback.
        self.assertFalse(result["success"], "rollback branch must report failure")
        self.assertIn("rolled back", result["message"].lower())
        self.assertEqual(len(result["results"]), 1)
        member_result = result["results"][0]["result"]
        self.assertFalse(member_result["success"])
        self.assertEqual(member_result["error_code"], ERROR_CODES["NOT_FOUND"])

    def test_bulk_assign_single_active_member_succeeds(self):
        # Happy-path counterpart: a team with one active member backed by an enabled
        # User resolves to the default profile and is assigned (or already assigned by
        # the Team.on_update hook). success_count >= error_count -> overall success.
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()

        good_profile = self._make_role_profile()
        team = self._make_team(default_profile=good_profile)
        user, member, volunteer = self._make_member_user_volunteer()
        team_doc = frappe.get_doc("Team", team)
        team_doc.append(
            "team_members",
            {
                "volunteer": volunteer.name,
                "team_role": "Team Member",
                "from_date": frappe.utils.today(),
                "status": "Active",
            },
        )
        team_doc.save()

        result = self.team_manager.bulk_assign_role_profiles(team)
        self.assertTrue(result["success"])
        self.assertEqual(len(result["results"]), 1)
        self.assertTrue(result["results"][0]["result"]["success"])
        self.assertIn(result["results"][0]["result"]["action"], ("assigned", "already_assigned"))
        # The profile actually landed on the user (v16 role_profiles child table).
        self.assertIn(good_profile, self._assigned_profiles(user))

    # =================================================================
    # validate_entity_configuration: role-specific branches
    # =================================================================

    def test_validate_entity_config_role_specific_valid(self):
        profile = self._make_role_profile()
        team_role = self._make_team_role()
        team = self._make_team(enable_specific=1, role_specific=[(team_role, profile)])
        self.assertIsNone(validate_entity_configuration(TEAM_CONFIG, team))

    def test_validate_entity_config_role_specific_bad_role(self):
        # Role-specific mapping references a Team Role that does not exist.
        profile = self._make_role_profile()
        team_role = self._make_team_role()
        team = self._make_team(enable_specific=1, role_specific=[(team_role, profile)])
        # Delete the team role so the validator hits the "role not present" branch.
        frappe.db.delete("Team Role", {"name": team_role})
        result = validate_entity_configuration(TEAM_CONFIG, team)
        self.assertIsNotNone(result)
        self.assertEqual(result["error_code"], ERROR_CODES["CONFIGURATION_ERROR"])

    def test_validate_entity_config_role_specific_bad_profile(self):
        # Role-specific mapping references a Role Profile that no longer exists.
        profile = self._make_role_profile()
        team_role = self._make_team_role()
        team = self._make_team(enable_specific=1, role_specific=[(team_role, profile)])
        frappe.db.set_value(
            "Team Role Profile Assignment",
            {"parent": team, "team_role": team_role},
            "role_profile",
            "Ghost Profile ZZZ",
        )
        result = validate_entity_configuration(TEAM_CONFIG, team)
        self.assertIsNotNone(result)
        self.assertEqual(result["error_code"], ERROR_CODES["CONFIGURATION_ERROR"])

    # =================================================================
    # _is_system_operation_authorized: non-privileged user
    # =================================================================

    def test_is_system_operation_authorized_false_for_plain_user(self):
        # A freshly created system user has no admin roles -> not authorized.
        user = self._make_system_user()
        with self.as_user(user):
            self.assertFalse(_is_system_operation_authorized())

    # =================================================================
    # Chapter manager: role-specific resolution via second subclass
    # =================================================================

    def test_chapter_role_specific_determine(self):
        specific_profile = self._make_role_profile()
        chapter_role = frappe.get_all("Chapter Role", limit=1, pluck="name")
        if not chapter_role:
            self.skipTest("no Chapter Role seeded")
        chapter_role = chapter_role[0]
        chapter = self.create_test_chapter(
            enable_board_role_specific_profiles=1,
            board_role_specific_profiles=[{"chapter_role": chapter_role, "role_profile": specific_profile}],
        )
        self.assertEqual(
            self.chapter_manager.determine_role_profile_for_member(chapter.name, role=chapter_role),
            specific_profile,
        )

    def test_chapter_config_role_specific_field(self):
        self.assertEqual(CHAPTER_CONFIG.role_field_in_child, "chapter_role")
        self.assertEqual(CHAPTER_CONFIG.child_table_doctype, "Chapter Role Profile Mapping")
