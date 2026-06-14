"""
Real-integration tests for
``verenigingen/services/member/account/base_role_profile_manager.py``.

The BaseRoleProfileManager assigns/removes Role Profiles to Users when they
join/leave organizational entities (Teams, Chapters). It is abstract; tests
exercise it through the concrete ``TeamRoleProfileManager`` (``_team_manager``)
and ``ChapterRoleProfileManager`` (``_chapter_manager``) singletons, plus the
module-level validation/reporting functions.

No business-logic mocking: real Role Profiles, Teams, Chapters, Users, Members
and Volunteers are created via ``frappe.get_doc().insert()`` / the test factory.
Tests run as Administrator.

Coverage focus (previously ~54%): assign_role_profile, remove_role_profile,
the validate_* family, get_entities_using_role_profile, bulk_assign_role_profiles
/ _process_bulk_member, _validate_role_assignment_inputs, _strip_role_profile,
_is_system_operation_authorized and safe_hook_execution.
"""

import frappe

from verenigingen.services.chapter.chapter_role_profile_manager import (
    CHAPTER_CONFIG,
    _chapter_manager,
)
from verenigingen.services.member.account.base_role_profile_manager import (
    ERROR_CODES,
    EntityConfig,
    _is_system_operation_authorized,
    safe_hook_execution,
    validate_all_role_profiles,
    validate_doctype_fields,
    validate_entity_configuration,
    validate_role_profile_dependencies,
    validate_system_configuration,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.team_role_profile_manager import TEAM_CONFIG, _team_manager


class TestBaseRoleProfileManager(VereningingenTestCase):
    """Exercise the shared role-profile manager logic end to end."""

    def setUp(self):
        super().setUp()
        self.h = frappe.generate_hash(length=6)
        self.team_manager = _team_manager
        self.chapter_manager = _chapter_manager

    # ------------------------------------------------------------------ helpers

    def _make_role_profile(self, roles=("System Manager",)):
        """Create a real Role Profile with the given roles and track it."""
        name = f"TBRP Profile {frappe.generate_hash(length=6)}"
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
        """Create a Role Profile with no roles (invalid for assignment)."""
        name = f"TBRP Empty {frappe.generate_hash(length=6)}"
        rp = frappe.get_doc({"doctype": "Role Profile", "role_profile": name})
        rp.insert()
        self.track_doc("Role Profile", rp.name)
        return rp.name

    def _make_team(self, default_profile=None, enable_specific=0):
        """Create a real Team optionally configured with a default role profile."""
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"TBRP Team {frappe.generate_hash(length=6)}",
                "status": "Active",
                "default_role_profile": default_profile,
                "enable_role_specific_profiles": enable_specific,
            }
        )
        team.insert()
        self.track_doc("Team", team.name)
        return team.name

    def _make_chapter(self, default_profile=None, enable_specific=0):
        chapter = self.create_test_chapter(
            default_board_role_profile=default_profile,
            enable_board_role_specific_profiles=enable_specific,
        )
        return chapter.name

    def _make_system_user(self):
        """Create an enabled System User with a backing Member record."""
        email = f"tbrp.{frappe.generate_hash(length=8)}@test.invalid"
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

    # =================================================================
    # validate_doctype_fields
    # =================================================================

    def test_validate_doctype_fields_all_present(self):
        self.assertIsNone(validate_doctype_fields("User", ["email", "enabled", "first_name"]))

    def test_validate_doctype_fields_missing(self):
        result = validate_doctype_fields("User", ["email", "does_not_exist_field"])
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], ERROR_CODES["CONFIGURATION_ERROR"])
        self.assertIn("does_not_exist_field", result["error"])

    def test_validate_doctype_fields_bad_doctype(self):
        result = validate_doctype_fields("No Such DocType ZZZ", ["x"])
        self.assertIsNotNone(result)
        self.assertEqual(result["error_code"], ERROR_CODES["SYSTEM_ERROR"])

    # =================================================================
    # validate_role_profile_dependencies
    # =================================================================

    def test_validate_role_profile_dependencies_ok(self):
        profile = self._make_role_profile(roles=("System Manager",))
        self.assertIsNone(validate_role_profile_dependencies(profile, TEAM_CONFIG))

    def test_validate_role_profile_dependencies_missing_profile(self):
        result = validate_role_profile_dependencies("Nonexistent Profile ZZZ", TEAM_CONFIG)
        self.assertIsNotNone(result)
        self.assertEqual(result["error_code"], ERROR_CODES["NOT_FOUND"])
        self.assertIn("does not exist", result["error"])

    def test_validate_role_profile_dependencies_no_roles(self):
        profile = self._make_empty_role_profile()
        result = validate_role_profile_dependencies(profile, TEAM_CONFIG)
        self.assertIsNotNone(result)
        self.assertEqual(result["error_code"], ERROR_CODES["CONFIGURATION_ERROR"])
        self.assertIn("no roles configured", result["error"])

    # =================================================================
    # validate_entity_configuration
    # =================================================================

    def test_validate_entity_configuration_nonexistent_entity(self):
        result = validate_entity_configuration(TEAM_CONFIG, "No Such Team ZZZ")
        self.assertIsNotNone(result)
        self.assertEqual(result["error_code"], ERROR_CODES["NOT_FOUND"])

    def test_validate_entity_configuration_no_config(self):
        team = self._make_team(default_profile=None, enable_specific=0)
        result = validate_entity_configuration(TEAM_CONFIG, team)
        self.assertIsNotNone(result)
        self.assertEqual(result["error_code"], ERROR_CODES["CONFIGURATION_ERROR"])
        self.assertIn("No role profile configuration", result["error"])

    def test_validate_entity_configuration_valid_default(self):
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        self.assertIsNone(validate_entity_configuration(TEAM_CONFIG, team))

    def test_validate_entity_configuration_default_profile_missing(self):
        # Configure a team to point at a profile, then delete the profile so the
        # validator hits the "default role profile does not exist" branch.
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        frappe.db.set_value("Team", team, "default_role_profile", "Ghost Profile ZZZ")
        result = validate_entity_configuration(TEAM_CONFIG, team)
        self.assertIsNotNone(result)
        self.assertEqual(result["error_code"], ERROR_CODES["CONFIGURATION_ERROR"])
        self.assertIn("does not exist", result["error"])

    def test_validate_entity_configuration_specific_enabled_no_mappings(self):
        # enable_role_specific_profiles=1 but no child rows -> configuration error.
        team = self._make_team(default_profile=None, enable_specific=1)
        result = validate_entity_configuration(TEAM_CONFIG, team)
        self.assertIsNotNone(result)
        self.assertEqual(result["error_code"], ERROR_CODES["CONFIGURATION_ERROR"])
        self.assertIn("no mappings configured", result["error"])

    # =================================================================
    # validate_system_configuration / validate_all_role_profiles (whitelisted)
    # =================================================================

    def test_validate_system_configuration_shape(self):
        result = validate_system_configuration()
        for key in ("success", "errors", "warnings", "teams_checked", "chapters_checked", "summary"):
            self.assertIn(key, result)
        self.assertIsInstance(result["errors"], list)
        self.assertGreaterEqual(result["teams_checked"], 0)
        self.assertGreaterEqual(result["chapters_checked"], 0)

    def test_validate_system_configuration_counts_configured_team(self):
        # A team with a valid default profile must be counted and not error.
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        result = validate_system_configuration()
        self.assertGreaterEqual(result["teams_checked"], 1)
        # Our well-configured team must not appear in the error list.
        self.assertFalse(any(team in e for e in result["errors"]))

    def test_validate_all_role_profiles_shape(self):
        # Seed at least one valid profile so the system has something to check.
        self._make_role_profile()
        result = validate_all_role_profiles()
        for key in ("success", "errors", "profiles_checked", "summary"):
            self.assertIn(key, result)
        self.assertGreaterEqual(result["profiles_checked"], 1)

    def test_validate_all_role_profiles_flags_empty_profile(self):
        empty = self._make_empty_role_profile()
        result = validate_all_role_profiles()
        # An empty (no-roles) profile is a dependency error and must be reported.
        self.assertFalse(result["success"])
        self.assertTrue(any(empty in e for e in result["errors"]))

    # =================================================================
    # determine_role_profile_for_member
    # =================================================================

    def test_determine_role_profile_default(self):
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        self.assertEqual(self.team_manager.determine_role_profile_for_member(team), profile)

    def test_determine_role_profile_no_config_returns_none(self):
        team = self._make_team(default_profile=None)
        self.assertIsNone(self.team_manager.determine_role_profile_for_member(team))

    def test_determine_role_profile_nonexistent_entity_returns_none(self):
        self.assertIsNone(self.team_manager.determine_role_profile_for_member("No Such Team ZZZ"))

    def test_determine_role_profile_default_fails_dependency(self):
        # Default profile exists but has no roles -> determine returns None.
        empty = self._make_empty_role_profile()
        team = self._make_team(default_profile=empty)
        self.assertIsNone(self.team_manager.determine_role_profile_for_member(team))

    # =================================================================
    # _validate_role_assignment_inputs (via assign_role_profile guard paths)
    # =================================================================

    def test_assign_empty_user_rejected(self):
        team = self._make_team(default_profile=self._make_role_profile())
        result = self.team_manager.assign_role_profile("   ", team)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], ERROR_CODES["VALIDATION_ERROR"])

    def test_assign_empty_entity_rejected(self):
        user = self._make_system_user()
        result = self.team_manager.assign_role_profile(user, "")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], ERROR_CODES["VALIDATION_ERROR"])

    def test_assign_nonexistent_user_rejected(self):
        team = self._make_team(default_profile=self._make_role_profile())
        result = self.team_manager.assign_role_profile("ghost@nope.invalid", team)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], ERROR_CODES["NOT_FOUND"])
        self.assertIn("does not exist", result["error"])

    def test_assign_nonexistent_entity_rejected(self):
        user = self._make_system_user()
        result = self.team_manager.assign_role_profile(user, "No Such Team ZZZ")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], ERROR_CODES["NOT_FOUND"])

    def test_assign_overlong_role_rejected(self):
        user = self._make_system_user()
        team = self._make_team(default_profile=self._make_role_profile())
        result = self.team_manager.assign_role_profile(user, team, role="x" * 101)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], ERROR_CODES["VALIDATION_ERROR"])
        self.assertIn("maximum 100 characters", result["error"])

    # =================================================================
    # assign_role_profile - happy and edge paths
    # =================================================================

    def test_assign_role_profile_happy_path(self):
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        user = self._make_system_user()

        result = self.team_manager.assign_role_profile(user, team)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "assigned")
        self.assertEqual(result["role_profile"], profile)

        user_doc = frappe.get_doc("User", user)
        assigned = [rp.role_profile for rp in (user_doc.role_profiles or [])]
        self.assertIn(profile, assigned)

    def test_assign_role_profile_idempotent(self):
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        user = self._make_system_user()

        self.team_manager.assign_role_profile(user, team)
        result = self.team_manager.assign_role_profile(user, team)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "already_assigned")

    def test_assign_role_profile_no_config(self):
        team = self._make_team(default_profile=None)
        user = self._make_system_user()
        result = self.team_manager.assign_role_profile(user, team)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "no_config")

    def test_assign_role_profile_disabled_user_rejected(self):
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        user = self._make_system_user()
        frappe.db.set_value("User", user, "enabled", 0)

        result = self.team_manager.assign_role_profile(user, team)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], ERROR_CODES["VALIDATION_ERROR"])
        self.assertIn("disabled user", result["error"])

    def test_assign_role_profile_deleted_profile_falls_through_to_no_config(self):
        # If a team's configured Role Profile is deleted, determine() can no longer
        # resolve it (dependency validation fails) and assign() reports no_config
        # rather than crashing.
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        user = self._make_system_user()
        frappe.delete_doc("Role Profile", profile, force=True)
        result = self.team_manager.assign_role_profile(user, team)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "no_config")

    # =================================================================
    # remove_role_profile
    # =================================================================

    def test_remove_role_profile_no_config(self):
        team = self._make_team(default_profile=None)
        user = self._make_system_user()
        result = self.team_manager.remove_role_profile(user, team)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "no_config")

    def test_remove_role_profile_not_assigned(self):
        # Team has a configured profile but the user was never assigned it.
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        user = self._make_system_user()
        result = self.team_manager.remove_role_profile(user, team)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "not_assigned")

    def test_remove_role_profile_after_assign(self):
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        user = self._make_system_user()

        self.team_manager.assign_role_profile(user, team)
        result = self.team_manager.remove_role_profile(user, team)
        self.assertTrue(result["success"])
        # Recalculation runs; for a user with no remaining positions sync cannot
        # compute a replacement so the profile is stripped pending recalc.
        self.assertIn(result["action"], ("recalculated", "removed_pending_recalc"))

        user_doc = frappe.get_doc("User", user)
        assigned = [rp.role_profile for rp in (user_doc.role_profiles or [])]
        self.assertNotIn(profile, assigned)

    def test_remove_role_profile_disabled_user_rejected(self):
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        user = self._make_system_user()
        self.team_manager.assign_role_profile(user, team)
        frappe.db.set_value("User", user, "enabled", 0)

        result = self.team_manager.remove_role_profile(user, team)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], ERROR_CODES["VALIDATION_ERROR"])
        self.assertIn("disabled user", result["error"])

    # =================================================================
    # _strip_role_profile (direct)
    # =================================================================

    def test_strip_role_profile_removes_single(self):
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        user = self._make_system_user()
        self.team_manager.assign_role_profile(user, team)

        self.team_manager._strip_role_profile(user, profile)

        user_doc = frappe.get_doc("User", user)
        assigned = [rp.role_profile for rp in (user_doc.role_profiles or [])]
        self.assertNotIn(profile, assigned)

    # =================================================================
    # get_entities_requiring_role_profile / get_entities_using_role_profile
    # =================================================================

    def test_get_entities_requiring_role_profile_default(self):
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        entities = self.team_manager.get_entities_requiring_role_profile(profile)
        self.assertIn(team, entities)

    def test_get_entities_requiring_role_profile_excludes(self):
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        entities = self.team_manager.get_entities_requiring_role_profile(profile, exclude_entity=team)
        self.assertNotIn(team, entities)

    def test_get_entities_using_role_profile_default(self):
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        result = self.team_manager.get_entities_using_role_profile(profile)
        names = [e["name"] for e in result]
        self.assertIn(team, names)
        match = next(e for e in result if e["name"] == team)
        self.assertEqual(match["usage_type"], "default")
        self.assertIn("entity_label", match)

    def test_get_entities_using_role_profile_none_when_unused(self):
        profile = self._make_role_profile()
        # Profile configured on no entity.
        result = self.team_manager.get_entities_using_role_profile(profile)
        self.assertEqual(result, [])

    # =================================================================
    # bulk_assign_role_profiles / _process_bulk_member
    # =================================================================

    def test_bulk_assign_no_configuration(self):
        team = self._make_team(default_profile=None)
        result = self.team_manager.bulk_assign_role_profiles(team)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], ERROR_CODES["CONFIGURATION_ERROR"])

    def test_bulk_assign_empty_team(self):
        # Configured team but no members -> succeeds with empty results.
        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        result = self.team_manager.bulk_assign_role_profiles(team)
        self.assertTrue(result["success"])
        self.assertEqual(result["results"], [])

    def test_bulk_assign_with_member(self):
        # Seed a team with one active member that has a backing User.
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()

        profile = self._make_role_profile()
        team = self._make_team(default_profile=profile)
        user = self._make_system_user()
        member = self.create_test_member(
            first_name="Bulk",
            last_name=frappe.generate_hash(length=5),
            email=user,
        )
        frappe.db.set_value("Member", member.name, "user", user)
        volunteer = self.create_test_volunteer(member=member.name)

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
        member_result = result["results"][0]["result"]
        self.assertTrue(member_result["success"])
        self.assertIn(member_result["action"], ("assigned", "already_assigned"))

        # Assert the role profile actually landed in the v16 role_profiles child
        # table (roles derive from it). The old set_value path left this empty.
        user_doc = frappe.get_doc("User", user)
        self.assertIn(profile, [rp.role_profile for rp in user_doc.role_profiles])

    def test_process_bulk_member_user_not_loaded(self):
        # _process_bulk_member returns a NOT_FOUND error when the user is missing
        # from the preloaded user_docs map.
        result = self.team_manager._process_bulk_member(
            member_data={"user": "missing@nope.invalid", "member": "M-1", "team_role": "Team Member"},
            user_docs={},
            role_profile_cache={},
            entity_name="Whatever",
        )
        self.assertFalse(result["result"]["success"])
        self.assertEqual(result["result"]["error_code"], ERROR_CODES["NOT_FOUND"])

    def test_process_bulk_member_no_role_profile(self):
        # When the role has no resolved profile, the member is a successful no-op.
        result = self.team_manager._process_bulk_member(
            member_data={"user": "u@x.invalid", "member": "M-1", "team_role": "Team Member"},
            user_docs={"u@x.invalid": frappe._dict(role_profile_name=None)},
            role_profile_cache={"Team Member": None},
            entity_name="Whatever",
        )
        self.assertTrue(result["result"]["success"])
        self.assertEqual(result["result"]["action"], "no_config")

    def test_process_bulk_member_assigns(self):
        profile = self._make_role_profile()
        user = self._make_system_user()
        result = self.team_manager._process_bulk_member(
            member_data={"user": user, "member": "M-1", "team_role": "Team Member"},
            user_docs={user: frappe._dict(role_profile_name=None)},
            role_profile_cache={"Team Member": profile},
            entity_name="Whatever",
        )
        self.assertTrue(result["result"]["success"])
        self.assertEqual(result["result"]["action"], "assigned")
        # Assert the real grant via the v16 role_profiles child table (not just the
        # deprecated role_profile_name column, which the old code wrote as a no-op).
        user_doc = frappe.get_doc("User", user)
        self.assertIn(profile, [rp.role_profile for rp in user_doc.role_profiles])

    def test_process_bulk_member_already_assigned(self):
        profile = self._make_role_profile()
        user = self._make_system_user()
        member_data = {"user": user, "member": "M-1", "team_role": "Team Member"}
        cache = {"Team Member": profile}
        # First call assigns it (writes the role_profiles child table).
        first = self.team_manager._process_bulk_member(
            member_data, {user: frappe._dict(role_profile_name=None)}, cache, "Whatever"
        )
        self.assertEqual(first["result"]["action"], "assigned")
        # Second call must detect the existing assignment via the child table.
        second = self.team_manager._process_bulk_member(
            member_data, {user: frappe._dict(role_profile_name=profile)}, cache, "Whatever"
        )
        self.assertTrue(second["result"]["success"])
        self.assertEqual(second["result"]["action"], "already_assigned")

    # =================================================================
    # _log_role_assignment (smoke - must not raise)
    # =================================================================

    def test_log_role_assignment_smoke(self):
        # Pure audit-log helper; just ensure it executes without raising.
        self.team_manager._log_role_assignment(
            "assigned", "Some Profile", "user@x.invalid", "Some Team", "Team Member"
        )

    # =================================================================
    # module-level helpers: _is_system_operation_authorized / safe_hook_execution
    # =================================================================

    def test_is_system_operation_authorized_as_administrator(self):
        # Tests run as Administrator, which must be authorized.
        self.assertTrue(_is_system_operation_authorized())

    def test_safe_hook_execution_returns_result(self):
        self.assertEqual(safe_hook_execution(lambda a, b: a + b, 2, 3), 5)

    def test_safe_hook_execution_swallows_exception(self):
        def boom():
            raise ValueError("kaboom")

        # Errors are isolated and return None rather than propagating.
        self.assertIsNone(safe_hook_execution(boom))

    # =================================================================
    # get_entity_role_profile_config edge: nonexistent entity returns defaults
    # =================================================================

    def test_get_entity_role_profile_config_missing_entity(self):
        config = self.team_manager.get_entity_role_profile_config("No Such Team ZZZ")
        self.assertIsNone(config["default_profile"])
        self.assertFalse(config["enable_role_specific"])
        self.assertEqual(config["role_specific_profiles"], {})

    # =================================================================
    # Chapter manager: cross-check the same base logic via a second subclass
    # =================================================================

    def test_chapter_determine_and_use_default_profile(self):
        profile = self._make_role_profile()
        chapter = self._make_chapter(default_profile=profile)
        self.assertEqual(self.chapter_manager.determine_role_profile_for_member(chapter), profile)
        result = self.chapter_manager.get_entities_using_role_profile(profile)
        self.assertIn(chapter, [e["name"] for e in result])

    def test_chapter_assign_role_profile_happy_path(self):
        profile = self._make_role_profile()
        chapter = self._make_chapter(default_profile=profile)
        user = self._make_system_user()
        result = self.chapter_manager.assign_role_profile(user, chapter)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "assigned")
        user_doc = frappe.get_doc("User", user)
        assigned = [rp.role_profile for rp in (user_doc.role_profiles or [])]
        self.assertIn(profile, assigned)

    def test_chapter_config_constants(self):
        # Sanity: the two configs differ in entity_type, proving both subclasses
        # drive the same base code with distinct EntityConfig values.
        self.assertEqual(CHAPTER_CONFIG.entity_type, "chapter")
        self.assertEqual(TEAM_CONFIG.entity_type, "team")
        self.assertIsInstance(CHAPTER_CONFIG, EntityConfig)
