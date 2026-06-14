"""
Real-integration tests for
``verenigingen/services/member/account/user_role_profile_calculator.py``.

The calculator derives the *correct* Frappe Role Profile for a User from their
current organisational assignments (board positions, team leadership, team
memberships, active-volunteer status) using a priority ladder, and can sync that
profile onto the User. It was ~51% covered.

No business-logic mocking: real Members, Volunteers, Chapters, Teams, Chapter
Board Members, Team Members and Role Profiles are created via the factory /
``frappe.get_doc().insert()``. Tests run as Administrator.

Coverage focus: get_profile_priority_for_role, is_active_board_member,
is_team_leader, is_active_volunteer, calculate_user_role_profile,
calculate_all_user_role_profiles, get_board_member_profiles, get_team_profiles,
sync_user_role_profile, and the whitelisted endpoints recalculate_user_role_profile,
bulk_recalculate_role_profiles, validate_role_profile_data_integrity.

IMPORTANT (v16): role-profile assignment lands in the User ``role_profiles`` child
table, not the deprecated ``role_profile_name`` Link column. Assertions read the
child table.
"""

import frappe

from verenigingen.services.member.account import user_role_profile_calculator as calc
from verenigingen.services.member.account.user_role_profile_calculator import (
    PRIORITY_BOARD_DEFAULT,
    PRIORITY_BOARD_ROLE_SPECIFIC,
    PRIORITY_MEMBER,
    PRIORITY_SPECIAL_ACCOUNTING,
    PRIORITY_TEAM_LEADER,
    PRIORITY_VOLUNTEER,
    PROFILE_BOARD_MEMBER,
    PROFILE_MEMBER,
    PROFILE_TEAM_LEADER,
    PROFILE_VOLUNTEER,
    bulk_recalculate_role_profiles,
    calculate_all_user_role_profiles,
    calculate_user_role_profile,
    get_board_member_profiles,
    get_profile_priority_for_role,
    get_team_profiles,
    is_active_board_member,
    is_active_volunteer,
    is_team_leader,
    recalculate_user_role_profile,
    sync_user_role_profile,
    validate_role_profile_data_integrity,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestUserRoleProfileCalculator(VereningingenTestCase):
    """Exercise the role-profile calculator end to end with real records."""

    def setUp(self):
        super().setUp()
        self.h = frappe.generate_hash(length=6)
        # Profile-config cache is module-global; clear it so config set in one
        # test never leaks into another (the calculator caches per chapter/team).
        calc.invalidate_profile_config_cache()
        self.addCleanup(calc.invalidate_profile_config_cache)

    # ------------------------------------------------------------------ helpers

    def _make_role_profile(self, label, roles=("Verenigingen Volunteer",)):
        """Create a real Role Profile with a unique name and the given roles."""
        name = f"URPC {label} {frappe.generate_hash(length=6)}"
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

    def _make_member_user(self, status="Active"):
        """Create a Member linked to an enabled System User; return (user, member)."""
        email = f"urpc.{frappe.generate_hash(length=8)}@test.invalid"
        member = self.create_test_member(
            first_name="Roleprof",
            last_name=f"M{frappe.generate_hash(length=5)}",
            email=email,
            status=status,
        )
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        self.track_doc("User", user.name)
        # Link the Member to the User (set_value bypasses hooks; allowed in tests).
        frappe.db.set_value("Member", member.name, "user", user.name)
        return user.name, member.name

    def _make_volunteer(self, member, status="Active"):
        vol = self.create_test_volunteer(member=member, status=status)
        return vol.name

    def _ensure_chapter_role(self, role_name):
        if not frappe.db.exists("Chapter Role", role_name):
            frappe.get_doc(
                {"doctype": "Chapter Role", "role_name": role_name, "is_active": 1}
            ).insert()
            self.track_doc("Chapter Role", role_name)

    def _add_board_position(self, chapter_name, volunteer, role="Bestuurslid"):
        self._ensure_chapter_role(role)
        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer,
                "chapter_role": role,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save()

    def _ensure_team_roles(self):
        # "Team Leader" (is_team_leader=1) and "Team Member" are the seeded roles;
        # the Team controller derives team_lead from an active member holding a
        # role whose is_team_leader flag is set, so they must exist.
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()

    def _make_team(self, default_profile=None, enable_specific=0, is_association_wide=0):
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"URPC Team {frappe.generate_hash(length=6)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today(),
                "default_role_profile": default_profile,
                "enable_role_specific_profiles": enable_specific,
                "is_association_wide": is_association_wide,
            }
        )
        team.insert()
        self.track_doc("Team", team.name)
        return team.name

    def _make_team_with_leader(self, lead_volunteer, default_profile=None):
        """Create a Team whose derived team_lead resolves to lead_volunteer's user.

        team_lead is read-only and auto-populated by Team._update_team_lead from
        an active member holding a role with is_team_leader=1 — so we add the
        leader as a "Team Leader" team member rather than setting team_lead.
        """
        self._ensure_team_roles()
        team_name = self._make_team(default_profile=default_profile)
        self._add_team_member(team_name, lead_volunteer, role="Team Leader")
        return team_name

    def _add_team_member(self, team_name, volunteer, role="Team Member"):
        team_doc = frappe.get_doc("Team", team_name)
        team_doc.append(
            "team_members",
            {
                "volunteer": volunteer,
                "team_role": role,
                "from_date": frappe.utils.today(),
                "status": "Active",
            },
        )
        team_doc.save()

    # =================================================================
    # get_profile_priority_for_role (pure)
    # =================================================================

    def test_priority_english_accounting_role(self):
        self.assertEqual(
            get_profile_priority_for_role("Treasurer", "Some Profile"),
            PRIORITY_SPECIAL_ACCOUNTING,
        )

    def test_priority_dutch_accounting_role(self):
        self.assertEqual(
            get_profile_priority_for_role("Penningmeester", "Bestuur"),
            PRIORITY_SPECIAL_ACCOUNTING,
        )

    def test_priority_accounting_keyword_in_profile(self):
        # The role name is neutral but the profile name carries the keyword.
        self.assertEqual(
            get_profile_priority_for_role("Lid", "Verenigingen Finance Profile"),
            PRIORITY_SPECIAL_ACCOUNTING,
        )

    def test_priority_non_accounting_role(self):
        self.assertEqual(
            get_profile_priority_for_role("Secretary", "Board Member"),
            PRIORITY_BOARD_ROLE_SPECIFIC,
        )

    def test_priority_handles_none(self):
        # Defensive: None role/profile must not raise.
        self.assertEqual(
            get_profile_priority_for_role(None, None), PRIORITY_BOARD_ROLE_SPECIFIC
        )

    # =================================================================
    # is_active_volunteer / is_active_board_member / is_team_leader
    # =================================================================

    def test_is_active_volunteer_true(self):
        user, member = self._make_member_user()
        self._make_volunteer(member, status="Active")
        self.assertTrue(is_active_volunteer(user, member))

    def test_is_active_volunteer_onboarding_counts(self):
        user, member = self._make_member_user()
        self._make_volunteer(member, status="Onboarding")
        self.assertTrue(is_active_volunteer(user, member))

    def test_is_active_volunteer_inactive_status_false(self):
        user, member = self._make_member_user()
        vol = self._make_volunteer(member, status="Active")
        frappe.db.set_value("Volunteer", vol, "status", "Inactive")
        self.assertFalse(is_active_volunteer(user, member))

    def test_is_active_volunteer_no_volunteer_false(self):
        user, member = self._make_member_user()
        self.assertFalse(is_active_volunteer(user, member))

    def test_is_active_board_member_true(self):
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        chapter = self.create_test_chapter()
        self._add_board_position(chapter.name, vol)
        self.assertTrue(is_active_board_member(user, member))

    def test_is_active_board_member_no_volunteer_false(self):
        user, member = self._make_member_user()
        self.assertFalse(is_active_board_member(user, member))

    def test_is_active_board_member_inactive_position_false(self):
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        chapter = self.create_test_chapter()
        self._add_board_position(chapter.name, vol)
        # Deactivate the board position.
        bm = frappe.db.get_value("Chapter Board Member", {"volunteer": vol}, "name")
        frappe.db.set_value("Chapter Board Member", bm, "is_active", 0)
        self.assertFalse(is_active_board_member(user, member))

    def test_is_team_leader_true(self):
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        self._make_team_with_leader(vol)
        self.assertTrue(is_team_leader(user, member))

    def test_is_team_leader_false(self):
        user, member = self._make_member_user()
        self.assertFalse(is_team_leader(user, member))

    def test_is_team_leader_inactive_team_false(self):
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        team = self._make_team_with_leader(vol)
        frappe.db.set_value("Team", team, "status", "Completed")
        self.assertFalse(is_team_leader(user, member))

    # =================================================================
    # calculate_user_role_profile - priority ladder
    # =================================================================

    def test_calculate_guest_returns_none(self):
        self.assertIsNone(calculate_user_role_profile("Guest"))
        self.assertIsNone(calculate_user_role_profile(""))

    def test_calculate_non_member_returns_none(self):
        # A User with no backing Member record.
        email = f"urpc.nonmember.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        self.assertIsNone(calculate_user_role_profile(user.name))

    def test_calculate_plain_member_returns_member_profile(self):
        user, _member = self._make_member_user()
        self.assertEqual(calculate_user_role_profile(user), PROFILE_MEMBER)

    def test_calculate_active_volunteer_returns_volunteer_profile(self):
        user, member = self._make_member_user()
        self._make_volunteer(member)
        self.assertEqual(calculate_user_role_profile(user), PROFILE_VOLUNTEER)

    def test_calculate_team_leader_default_profile(self):
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        self._make_team_with_leader(vol)  # no default_role_profile -> hardcoded fallback
        self.assertEqual(calculate_user_role_profile(user), PROFILE_TEAM_LEADER)

    def test_calculate_team_leader_custom_default_profile(self):
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        profile = self._make_role_profile("TeamLead")
        self._make_team_with_leader(vol, default_profile=profile)
        self.assertEqual(calculate_user_role_profile(user), profile)

    def test_calculate_board_member_beats_volunteer(self):
        # Board default (70) outranks active volunteer (30).
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        chapter = self.create_test_chapter()
        self._add_board_position(chapter.name, vol)
        self.assertEqual(calculate_user_role_profile(user), PROFILE_BOARD_MEMBER)

    def test_calculate_board_specific_profile_used(self):
        # Chapter with role-specific profile mapping -> that profile wins.
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        self._ensure_chapter_role("Secretaris")
        profile = self._make_role_profile("BoardSpecific")
        chapter = self.create_test_chapter(
            default_board_role_profile=None,
            enable_board_role_specific_profiles=1,
        )
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append(
            "board_role_specific_profiles",
            {"chapter_role": "Secretaris", "role_profile": profile},
        )
        chapter_doc.append(
            "board_members",
            {
                "volunteer": vol,
                "chapter_role": "Secretaris",
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save()
        self.assertEqual(calculate_user_role_profile(user), profile)

    def test_calculate_accounting_board_role_highest_priority(self):
        # A "Penningmeester" (treasurer) board role earns PRIORITY_SPECIAL_ACCOUNTING,
        # which outranks every other candidate.
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        profile = self._make_role_profile("Treasurer")
        chapter = self.create_test_chapter(
            default_board_role_profile=None,
            enable_board_role_specific_profiles=1,
        )
        self._ensure_chapter_role("Penningmeester")
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append(
            "board_role_specific_profiles",
            {"chapter_role": "Penningmeester", "role_profile": profile},
        )
        chapter_doc.append(
            "board_members",
            {
                "volunteer": vol,
                "chapter_role": "Penningmeester",
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save()
        all_profiles = calculate_all_user_role_profiles(user)
        self.assertEqual(all_profiles[0], (PRIORITY_SPECIAL_ACCOUNTING, profile))
        self.assertEqual(calculate_user_role_profile(user), profile)

    # =================================================================
    # calculate_all_user_role_profiles
    # =================================================================

    def test_calculate_all_empty_for_non_member(self):
        email = f"urpc.none.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        self.assertEqual(calculate_all_user_role_profiles(user.name), [])

    def test_calculate_all_sorted_descending_with_member_floor(self):
        user, member = self._make_member_user()
        self._make_volunteer(member)
        result = calculate_all_user_role_profiles(user)
        priorities = [p for p, _name in result]
        # Always includes the Member floor and is sorted high-to-low.
        self.assertEqual(priorities, sorted(priorities, reverse=True))
        self.assertIn((PRIORITY_MEMBER, PROFILE_MEMBER), result)
        self.assertIn((PRIORITY_VOLUNTEER, PROFILE_VOLUNTEER), result)

    # =================================================================
    # get_board_member_profiles / get_team_profiles (direct)
    # =================================================================

    def test_get_board_member_profiles_no_volunteer_empty(self):
        user, member = self._make_member_user()
        self.assertEqual(get_board_member_profiles(user, member), [])

    def test_get_board_member_profiles_default(self):
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        chapter = self.create_test_chapter()
        self._add_board_position(chapter.name, vol)
        profiles = get_board_member_profiles(user, member)
        self.assertIn((PRIORITY_BOARD_DEFAULT, PROFILE_BOARD_MEMBER), profiles)

    def test_get_team_profiles_leader_and_member(self):
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        # Leadership entry (hardcoded team-leader fallback) via a "Team Leader" role.
        self._make_team_with_leader(vol)
        # Separate team membership with a default profile.
        profile = self._make_role_profile("TeamMember")
        team2 = self._make_team(default_profile=profile)
        self._add_team_member(team2, vol)
        profiles = get_team_profiles(user, member)
        self.assertIn((PRIORITY_TEAM_LEADER, PROFILE_TEAM_LEADER), profiles)
        self.assertTrue(any(p[1] == profile for p in profiles))

    # =================================================================
    # sync_user_role_profile + recalculate_user_role_profile (@whitelist)
    # =================================================================

    def _assigned_profiles(self, user):
        user_doc = frappe.get_doc("User", user)
        return [rp.role_profile for rp in (user_doc.role_profiles or [])]

    def test_sync_nonexistent_user(self):
        result = sync_user_role_profile("ghost@nope.invalid")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])

    def test_sync_non_member_user_fails(self):
        email = f"urpc.syncnon.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        result = sync_user_role_profile(user.name)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "User is not a member")

    def test_sync_dry_run_does_not_apply(self):
        user, member = self._make_member_user()
        self._make_volunteer(member)
        result = sync_user_role_profile(user, dry_run=True)
        self.assertTrue(result["success"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["new_profile"], PROFILE_VOLUNTEER)
        # Dry run must not write the role_profiles child table.
        self.assertNotIn(PROFILE_VOLUNTEER, self._assigned_profiles(user))

    def test_sync_applies_profile_to_child_table(self):
        user, member = self._make_member_user()
        self._make_volunteer(member)
        result = sync_user_role_profile(user, dry_run=False)
        self.assertTrue(result["success"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["new_profile"], PROFILE_VOLUNTEER)
        # The canonical v16 store must carry the new profile.
        self.assertIn(PROFILE_VOLUNTEER, self._assigned_profiles(user))

    def test_sync_idempotent_second_run_unchanged(self):
        user, member = self._make_member_user()
        self._make_volunteer(member)
        sync_user_role_profile(user, dry_run=False)
        result = sync_user_role_profile(user, dry_run=False)
        self.assertTrue(result["success"])
        self.assertFalse(result["changed"])

    def test_recalculate_endpoint_dry_run(self):
        # @whitelist @high_security_api(ADMIN); tests run as Administrator so the
        # security tier passes and we reach sync_user_role_profile.
        user, member = self._make_member_user()
        self._make_volunteer(member)
        result = recalculate_user_role_profile(user, dry_run=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["new_profile"], PROFILE_VOLUNTEER)

    # =================================================================
    # bulk_recalculate_role_profiles (@whitelist) - guarded/dry-run only
    # =================================================================

    def test_bulk_recalculate_dry_run_targeted_filter(self):
        # Drive only OUR user via an explicit name filter (no process-all) in
        # dry_run mode so nothing global is written.
        user, member = self._make_member_user()
        self._make_volunteer(member)
        result = bulk_recalculate_role_profiles(filters={"name": user}, dry_run=True)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["changed"], 1)
        self.assertEqual(result["changes"][0]["user"], user)
        self.assertEqual(result["changes"][0]["new_role"], PROFILE_VOLUNTEER)
        # Dry run: nothing applied.
        self.assertNotIn(PROFILE_VOLUNTEER, self._assigned_profiles(user))

    def test_bulk_recalculate_empty_filter_result(self):
        # A filter matching no users returns zero totals (no global scan side-effects).
        result = bulk_recalculate_role_profiles(
            filters={"name": "no.such.user.zzz@nope.invalid"}, dry_run=True
        )
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["changed"], 0)

    # =================================================================
    # validate_role_profile_data_integrity (@whitelist)
    # =================================================================

    def test_validate_data_integrity_shape(self):
        result = validate_role_profile_data_integrity()
        self.assertTrue(result["success"])
        issues = result["issues"]
        for key in (
            "orphaned_board_members",
            "orphaned_team_members",
            "invalid_chapter_profiles",
            "invalid_team_profiles",
            "profile_mismatches",
            "summary",
        ):
            self.assertIn(key, issues)
        self.assertIn("total_issues", issues["summary"])

    def test_validate_data_integrity_flags_invalid_chapter_profile(self):
        # A chapter pointing at a non-existent default profile must be reported.
        chapter = self.create_test_chapter()
        frappe.db.set_value(
            "Chapter", chapter.name, "default_board_role_profile", "Ghost Profile ZZZ"
        )
        result = validate_role_profile_data_integrity()
        self.assertTrue(result["success"])
        flagged = [
            i["chapter"] for i in result["issues"]["invalid_chapter_profiles"]
        ]
        self.assertIn(chapter.name, flagged)

    def test_validate_data_integrity_flags_invalid_team_profile(self):
        team = self._make_team(default_profile=self._make_role_profile("Temp"))
        frappe.db.set_value("Team", team, "default_role_profile", "Ghost Team Profile ZZZ")
        result = validate_role_profile_data_integrity()
        self.assertTrue(result["success"])
        flagged = [i["team"] for i in result["issues"]["invalid_team_profiles"]]
        self.assertIn(team, flagged)
