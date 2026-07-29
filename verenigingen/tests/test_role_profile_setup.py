# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Real integration tests for verenigingen/setup/role_profile_setup.py

These are true integration tests: real User / Member / Volunteer / Team / Role Profile
documents are created in the test DB (no mocking of business logic).

HISTORY — bugs found while writing these tests, now FIXED in the module (tests
below assert the corrected behaviour):
  * role_profile_name persistence: assign_role_profile_to_user() /
    auto_assign_role_profiles() / setup_role_profiles_cli() wrote the deprecated
    User.role_profile_name Link field, which Frappe v16 wipes to None on save
    when the role_profiles child table is empty. Now they append to the
    role_profiles child table (which persists).
  * Treasurer branch: a staff member who is also an Accounts User was shadowed by
    the plain-staff branch and could never be recommended "Verenigingen
    Treasurer". The treasurer check now precedes the plain-staff branch.
  * Team-leader detection: the code queried Team Member.role_type == "Leader",
    which never matches real data. Leadership is now determined by the linked
    Team Role's is_team_leader flag (via _is_team_leader).

KNOWN DEAD CODE still present (flagged in the module, asserted here as-is):
  * setup_role_profiles() / setup_role_profiles_cli() set
    `role_profile.module_profile`, but Role Profile has no such field — a silent
    no-op (see test_setup_role_profiles_runs_and_module_profile_is_noop).
  * install_fixtures() raises ImportError on current Frappe and has no callers
    (see test_install_fixtures_broken_import_raises).

COMMIT / ISOLATION:
setup_role_profiles(), setup_role_profiles_cli(), deploy_role_profiles() and
install_fixtures() call frappe.db.commit() internally. Any test doc is tracked via
self.track_doc(...) so teardown deletes it; tests that trigger the internal commit
also frappe.db.rollback() in a finally to drop trailing uncommitted writes.
"""

import frappe
from frappe.utils import today

from verenigingen.setup.role_profile_setup import (
    assign_role_profile_to_user,
    auto_assign_role_profiles,
    deploy_role_profiles,
    get_recommended_role_profile,
    install_fixtures,
    setup_role_profiles,
    setup_role_profiles_cli,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.constants import Roles


class TestRoleProfileSetup(VereningingenTestCase):
    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _unique_email(self):
        return f"rp-test-{frappe.generate_hash(length=10)}@example.com"

    def _make_user(self, roles=None):
        email = self._unique_email()
        self.create_test_user(email, roles=roles or [])
        return email

    def _make_member_for_user(self, email):
        return self.create_test_member(user=email, chapter=False)

    def _ensure_role(self, role_name):
        if not frappe.db.exists("Role", role_name):
            role = frappe.get_doc({"doctype": "Role", "role_name": role_name})
            role.insert(ignore_permissions=True)
            self.track_doc("Role", role.name)

    def _persist_role_profile_child_table(self, email, role_profile):
        """Assign a role profile the way Frappe actually persists it (child table).

        Used to set up state the broken app path cannot produce.
        """
        user = frappe.get_doc("User", email)
        user.append("role_profiles", {"role_profile": role_profile})
        user.save(ignore_permissions=True)

    def _make_team_membership(self, volunteer_name, team_role="Team Leader", is_active=1):
        """Attach a volunteer to a team with the given team_role.

        Leadership is defined by the linked Team Role's is_team_leader flag, so a
        "Team Leader" team_role makes the volunteer a leader; any other role does
        not. Returns (team, team_member_row_name).
        """
        team = self.factory.create_test_team()
        self.track_doc("Team", team.name)
        self.factory.get_or_create_team_role(team_role)
        team_doc = frappe.get_doc("Team", team.name)
        team_doc.append(
            "team_members",
            {
                "volunteer": volunteer_name,
                "team_role": team_role,
                "from_date": today(),
                "is_active": is_active,
                "status": "Active" if is_active else "Inactive",
            },
        )
        team_doc.save(ignore_permissions=True)
        return team, team_doc.team_members[-1].name

    # ------------------------------------------------------------------ #
    # get_recommended_role_profile  (the real, working logic)
    # ------------------------------------------------------------------ #
    def test_recommend_none_when_user_has_no_member(self):
        email = self._make_user(roles=[Roles.VERENIGINGEN_MEMBER])
        self.assertIsNone(get_recommended_role_profile(email))

    def test_recommend_system_administrator(self):
        email = self._make_user(roles=["System Manager"])
        self._make_member_for_user(email)
        self.assertEqual(get_recommended_role_profile(email), "Verenigingen System Administrator")

    def test_recommend_staff(self):
        email = self._make_user(roles=[Roles.VERENIGINGEN_STAFF])
        self._make_member_for_user(email)
        self.assertEqual(get_recommended_role_profile(email), "Verenigingen Staff")

    def test_recommend_auditor(self):
        self._ensure_role("Verenigingen Governance Auditor")
        email = self._make_user(roles=["Verenigingen Governance Auditor"])
        self._make_member_for_user(email)
        self.assertEqual(get_recommended_role_profile(email), "Verenigingen Auditor")

    def test_recommend_chapter_board_member(self):
        email = self._make_user(roles=[Roles.CHAPTER_BOARD_MEMBER])
        self._make_member_for_user(email)
        self.assertEqual(get_recommended_role_profile(email), "Verenigingen Chapter Board Member")

    def test_recommend_volunteer(self):
        email = self._make_user(roles=[])
        member = self._make_member_for_user(email)
        self.create_test_volunteer(member=member.name)
        self.assertEqual(get_recommended_role_profile(email), "Verenigingen Volunteer")

    def test_recommend_team_leader_via_team_role_flag(self):
        """A volunteer on a team with a Team Role flagged is_team_leader is
        recommended 'Verenigingen Team Leader' (leadership comes from the linked
        Team Role, not the legacy role_type field)."""
        email = self._make_user(roles=[])
        member = self._make_member_for_user(email)
        volunteer = self.create_test_volunteer(member=member.name)
        self._make_team_membership(volunteer.name, team_role="Team Leader")
        self.assertEqual(get_recommended_role_profile(email), "Verenigingen Team Leader")

    def test_recommend_volunteer_when_team_role_is_not_leader(self):
        """A volunteer on a team with a non-leader Team Role falls back to
        'Verenigingen Volunteer'."""
        email = self._make_user(roles=[])
        member = self._make_member_for_user(email)
        volunteer = self.create_test_volunteer(member=member.name)
        self._make_team_membership(volunteer.name, team_role="Team Member")
        self.assertEqual(get_recommended_role_profile(email), "Verenigingen Volunteer")

    def test_recommend_volunteer_when_leadership_is_inactive(self):
        """An inactive Team Leader membership must NOT yield 'Team Leader' — parity
        with Team._update_team_lead, which only honours active leadership."""
        email = self._make_user(roles=[])
        member = self._make_member_for_user(email)
        volunteer = self.create_test_volunteer(member=member.name)
        self._make_team_membership(volunteer.name, team_role="Team Leader", is_active=0)
        self.assertEqual(get_recommended_role_profile(email), "Verenigingen Volunteer")

    def test_recommend_basic_member(self):
        email = self._make_user(roles=[Roles.VERENIGINGEN_MEMBER])
        self._make_member_for_user(email)
        self.assertEqual(get_recommended_role_profile(email), "Verenigingen Member")

    def test_recommend_precedence_staff_over_member(self):
        email = self._make_user(roles=[Roles.VERENIGINGEN_STAFF, Roles.VERENIGINGEN_MEMBER])
        self._make_member_for_user(email)
        self.assertEqual(get_recommended_role_profile(email), "Verenigingen Staff")

    def test_recommend_treasurer_for_staff_with_accounts_user(self):
        """A staff member who is also an Accounts User is recommended
        "Verenigingen Treasurer" (the treasurer check precedes the plain-staff
        branch)."""
        email = self._make_user(roles=[Roles.VERENIGINGEN_STAFF, "Accounts User"])
        self._make_member_for_user(email)
        self.assertEqual(get_recommended_role_profile(email), "Verenigingen Treasurer")

    def test_recommend_staff_without_accounts_user_is_not_treasurer(self):
        """Plain staff (no Accounts User) stays "Verenigingen Staff"."""
        email = self._make_user(roles=[Roles.VERENIGINGEN_STAFF])
        self._make_member_for_user(email)
        self.assertEqual(get_recommended_role_profile(email), "Verenigingen Staff")

    # ------------------------------------------------------------------ #
    # assign_role_profile_to_user
    # ------------------------------------------------------------------ #
    def test_assign_returns_none_and_does_not_raise(self):
        email = self._make_user(roles=[Roles.VERENIGINGEN_MEMBER])
        # @critical_api returns the raw value; this function returns None.
        self.assertIsNone(assign_role_profile_to_user(email, "Verenigingen Member"))
        # Repeated call must also not raise.
        self.assertIsNone(assign_role_profile_to_user(email, "Verenigingen Member"))

    def test_assign_persists_to_role_profiles_child_table(self):
        """assign_role_profile_to_user persists the profile via the role_profiles
        child table (Frappe v16), and role_profile_name is synced from it."""
        email = self._make_user(roles=[Roles.VERENIGINGEN_MEMBER])
        assign_role_profile_to_user(email, "Verenigingen Member")
        user = frappe.get_doc("User", email)
        self.assertIn("Verenigingen Member", [r.role_profile for r in user.role_profiles])
        self.assertEqual(user.role_profile_name, "Verenigingen Member")

    def test_assign_is_idempotent(self):
        """Assigning the same profile twice does not duplicate the child row."""
        email = self._make_user(roles=[Roles.VERENIGINGEN_MEMBER])
        assign_role_profile_to_user(email, "Verenigingen Member")
        assign_role_profile_to_user(email, "Verenigingen Member")
        user = frappe.get_doc("User", email)
        count = sum(1 for r in user.role_profiles if r.role_profile == "Verenigingen Member")
        self.assertEqual(count, 1)

    def test_assign_invalid_user_raises(self):
        with self.assertRaises(frappe.DoesNotExistError):
            assign_role_profile_to_user("definitely-not-a-user@example.invalid", "Verenigingen Member")

    def test_assign_invalid_profile_raises(self):
        email = self._make_user(roles=[])
        with self.assertRaises(frappe.DoesNotExistError):
            assign_role_profile_to_user(email, "No Such Role Profile 12345")

    # ------------------------------------------------------------------ #
    # auto_assign_role_profiles
    # ------------------------------------------------------------------ #
    def test_auto_assign_returns_contract(self):
        email = self._make_user(roles=[Roles.VERENIGINGEN_MEMBER])
        self._make_member_for_user(email)

        result = auto_assign_role_profiles()

        self.assertIsInstance(result, dict)
        self.assertIn("users_updated", result)
        self.assertIsInstance(result["users_updated"], int)
        self.assertIsInstance(result["errors"], list)
        # Our fresh member-user is recommendable and has no existing profile, so it
        # is counted as updated and the profile now actually persists.
        self.assertGreaterEqual(result["users_updated"], 1)
        user = frappe.get_doc("User", email)
        self.assertIn("Verenigingen Member", [r.role_profile for r in user.role_profiles])

    def test_auto_assign_skips_user_with_existing_verenigingen_profile(self):
        """
        The skip branch: a user that already holds a Verenigingen role profile must
        not be reassigned. State is seeded via the role_profiles child table (the
        only path that actually persists on this Frappe version).
        """
        email = self._make_user(roles=[Roles.VERENIGINGEN_MEMBER])
        self._make_member_for_user(email)
        self._persist_role_profile_child_table(email, "Verenigingen Volunteer")
        self.assertEqual(frappe.db.get_value("User", email, "role_profile_name"), "Verenigingen Volunteer")

        auto_assign_role_profiles()

        # Untouched: still the seeded Volunteer profile, not the recommended Member.
        user = frappe.get_doc("User", email)
        self.assertEqual(user.role_profile_name, "Verenigingen Volunteer")
        self.assertIn("Verenigingen Volunteer", [r.role_profile for r in user.role_profiles])

    # ------------------------------------------------------------------ #
    # setup_role_profiles  (commits internally; module_profile is a no-op)
    # ------------------------------------------------------------------ #
    def test_setup_role_profiles_runs_and_module_profile_is_noop(self):
        """
        Documents flagged dead code: Role Profile has no module_profile field, so
        the function's core action is a silent no-op. We assert it completes without
        error and that the phantom field genuinely does not exist on the DocType.
        """
        self.assertFalse(frappe.get_meta("Role Profile").has_field("module_profile"))
        try:
            self.assertIsNone(setup_role_profiles())
            self.assertTrue(frappe.db.exists("Role Profile", "Verenigingen Member"))
            # Still no such column after running.
            self.assertNotIn("module_profile", frappe.db.get_table_columns("Role Profile"))
        finally:
            frappe.db.rollback()

    def test_setup_role_profiles_cli_returns_success(self):
        try:
            result = setup_role_profiles_cli()
            self.assertTrue(result["success"])
            self.assertIn("users_updated", result)
            self.assertIsInstance(result["users_updated"], int)
            self.assertIsInstance(result["errors"], list)
        finally:
            frappe.db.rollback()

    # ------------------------------------------------------------------ #
    # deploy_role_profiles  (wrapper -> setup + auto_assign)
    # ------------------------------------------------------------------ #
    def test_deploy_role_profiles_returns_contract(self):
        try:
            result = deploy_role_profiles()
            self.assertTrue(result["success"])
            self.assertTrue(result["setup_completed"])
            self.assertIn("users_updated", result)
            self.assertIsInstance(result["errors"], list)
            self.assertIn("recommendation", result)
        finally:
            frappe.db.rollback()

    # ------------------------------------------------------------------ #
    # install_fixtures  (installs app fixtures + setup_role_profiles)
    # ------------------------------------------------------------------ #
    def test_install_fixtures_broken_import_raises(self):
        """
        Documents flagged dead code: install_fixtures() imports `install_fixtures`
        from frappe.desk.page.setup_wizard.install_fixtures, but that module now
        only exposes `install()`. The function therefore raises ImportError
        immediately and is entirely non-functional (and has no callers).
        """
        with self.assertRaises(ImportError):
            install_fixtures()


class TestSetupRoleProfilesCliLadder(VereningingenTestCase):
    """
    setup_role_profiles_cli() carries its OWN copy of the recommendation ladder
    (an if/elif chain) instead of calling get_recommended_role_profile(). That
    duplication is the risk this class exists for: the two ladders have already
    drifted once (the Treasurer branch was unreachable in both, fixed
    separately), and nothing else asserts they agree.

    One CLI run covers every branch of the duplicated ladder at once, because the
    function walks all Members that have a user. Each persona below is asserted
    to receive the SAME profile the live get_recommended_role_profile() would
    recommend for it.

    COMMIT / ISOLATION: setup_role_profiles_cli() commits internally; every doc
    is tracked for teardown and the test rolls back trailing writes.
    """

    def _persona(self, roles=None):
        email = f"rp-cli-{frappe.generate_hash(length=10)}@example.com"
        self.create_test_user(email, roles=roles or [])
        member = self.create_test_member(user=email, chapter=False)
        return email, member

    def _ensure_role(self, role_name):
        if not frappe.db.exists("Role", role_name):
            role = frappe.get_doc({"doctype": "Role", "role_name": role_name})
            role.insert(ignore_permissions=True)
            self.track_doc("Role", role.name)

    @staticmethod
    def _assigned_profiles(email):
        return [r.role_profile for r in frappe.get_doc("User", email).role_profiles]

    def _make_team_leadership(self, volunteer_name):
        """Put a volunteer on a team under a Team Role flagged is_team_leader."""
        team = self.factory.create_test_team()
        self.track_doc("Team", team.name)
        self.factory.get_or_create_team_role("Team Leader")
        team_doc = frappe.get_doc("Team", team.name)
        team_doc.append(
            "team_members",
            {
                "volunteer": volunteer_name,
                "team_role": "Team Leader",
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        team_doc.save(ignore_permissions=True)
        return team

    @staticmethod
    def _persist_role_profile(email, role_profile):
        """Seed a role profile the way Frappe actually persists it (child table)."""
        user = frappe.get_doc("User", email)
        user.append("role_profiles", {"role_profile": role_profile})
        user.save(ignore_permissions=True)

    def test_cli_ladder_matches_get_recommended_role_profile_for_every_branch(self):
        """Every branch of the CLI's inline ladder must produce the same profile
        as get_recommended_role_profile(), and must actually persist it."""
        self._ensure_role("Verenigingen Governance Auditor")

        admin_email, _ = self._persona(roles=["System Manager"])
        treasurer_email, _ = self._persona(roles=[Roles.VERENIGINGEN_STAFF, "Accounts User"])
        staff_email, _ = self._persona(roles=[Roles.VERENIGINGEN_STAFF])
        auditor_email, _ = self._persona(roles=["Verenigingen Governance Auditor"])
        board_email, _ = self._persona(roles=[Roles.CHAPTER_BOARD_MEMBER])
        member_email, _ = self._persona(roles=[Roles.VERENIGINGEN_MEMBER])

        volunteer_email, volunteer_member = self._persona(roles=[])
        self.create_test_volunteer(member=volunteer_member.name)

        leader_email, leader_member = self._persona(roles=[])
        leader_volunteer = self.create_test_volunteer(member=leader_member.name)
        self._make_team_leadership(leader_volunteer.name)

        expected = {
            admin_email: "Verenigingen System Administrator",
            treasurer_email: "Verenigingen Treasurer",
            staff_email: "Verenigingen Staff",
            auditor_email: "Verenigingen Auditor",
            board_email: "Verenigingen Chapter Board Member",
            leader_email: "Verenigingen Team Leader",
            volunteer_email: "Verenigingen Volunteer",
            member_email: "Verenigingen Member",
        }

        # Guard: the ladder can only assign profiles that exist as fixtures.
        for profile in set(expected.values()):
            self.assertTrue(frappe.db.exists("Role Profile", profile), f"Missing Role Profile: {profile}")

        # Parity must be measured BEFORE the run: assigning a role profile
        # re-syncs User.roles to exactly the profile's roles, which changes what
        # the ladder would recommend afterwards.
        for email, profile in expected.items():
            self.assertEqual(
                get_recommended_role_profile(email),
                profile,
                f"get_recommended_role_profile disagrees with the CLI ladder for {email}",
            )

        try:
            result = setup_role_profiles_cli()
            self.assertTrue(result["success"])

            for email, profile in expected.items():
                self.assertIn(
                    profile,
                    self._assigned_profiles(email),
                    f"CLI ladder did not assign {profile} to {email}",
                )
        finally:
            frappe.db.rollback()

    def test_cli_leaves_an_existing_verenigingen_profile_untouched(self):
        """The skip branch: a member-user that already holds a Verenigingen role
        profile must not be reassigned, even when the ladder recommends a
        different one."""
        email, _ = self._persona(roles=[Roles.VERENIGINGEN_MEMBER])
        self._persist_role_profile(email, "Verenigingen Volunteer")
        self.assertEqual(frappe.db.get_value("User", email, "role_profile_name"), "Verenigingen Volunteer")
        # The ladder would otherwise recommend a *different* profile.
        self.assertEqual(get_recommended_role_profile(email), "Verenigingen Member")

        try:
            setup_role_profiles_cli()
            self.assertEqual(
                self._assigned_profiles(email),
                ["Verenigingen Volunteer"],
                "An existing Verenigingen profile must not be replaced or appended to",
            )
        finally:
            frappe.db.rollback()

    def test_module_profile_assignment_persists_nothing_even_when_the_target_exists(self):
        """
        Sharpens the existing dead-code test: setup_role_profiles() only enters
        its assignment branch when the mapped Module Profile actually exists. It
        does here -- and the write is STILL a no-op, because Role Profile has no
        module_profile field for Frappe to persist.
        """
        # Site state, not a code property: the mapped Module Profile exists on some
        # sites and not others (present on test_site_2, absent on test_site_1/3), so
        # asserting it made this test's colour depend on which shard CI picked.
        if not frappe.db.exists("Module Profile", "Verenigingen Member"):
            self.skipTest(
                "Module Profile 'Verenigingen Member' is not installed on this site, "
                "so the assignment branch under test is unreachable here"
            )
        self.assertTrue(frappe.db.exists("Role Profile", "Verenigingen Member"))

        try:
            setup_role_profiles()
            self.assertNotIn("module_profile", frappe.db.get_table_columns("Role Profile"))
            self.assertIsNone(frappe.get_doc("Role Profile", "Verenigingen Member").get("module_profile"))
        finally:
            frappe.db.rollback()
