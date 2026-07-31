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
from verenigingen.utils.constants import Roles


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
            frappe.get_doc({"doctype": "Chapter Role", "role_name": role_name, "is_active": 1}).insert()
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
        self.assertEqual(get_profile_priority_for_role(None, None), PRIORITY_BOARD_ROLE_SPECIFIC)

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
        # Read via the version-robust helper: v16 exposes a `role_profiles` child
        # table while v15 (and fresh CI sites) only have the `role_profile_name`
        # Link. Reading `user_doc.role_profiles` directly raises AttributeError on v15.
        return calc.get_user_role_profiles(user)

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
        frappe.db.set_value("Chapter", chapter.name, "default_board_role_profile", "Ghost Profile ZZZ")
        result = validate_role_profile_data_integrity()
        self.assertTrue(result["success"])
        flagged = [i["chapter"] for i in result["issues"]["invalid_chapter_profiles"]]
        self.assertIn(chapter.name, flagged)

    def test_validate_data_integrity_flags_invalid_team_profile(self):
        team = self._make_team(default_profile=self._make_role_profile("Temp"))
        frappe.db.set_value("Team", team, "default_role_profile", "Ghost Team Profile ZZZ")
        result = validate_role_profile_data_integrity()
        self.assertTrue(result["success"])
        flagged = [i["team"] for i in result["issues"]["invalid_team_profiles"]]
        self.assertIn(team, flagged)


class TestBulkRecalculationDowngradeIsAPrivilegeChange(VereningingenTestCase):
    """
    What a bulk recalculation would actually DO, asserted at the level an operator
    has to reason about before running it without dry_run.

    The existing coverage pins the building blocks (is_active_volunteer across
    statuses) and that dry_run applies nothing. What it does not pin is the shape a
    real site presents: users already HOLDING a profile that the current data no
    longer justifies. On veg11, 564 users hold Verenigingen Volunteer while 7
    Volunteer records exist, none Active and none linked to a user - so a
    recalculation proposes Member for 438 of them.

    Reading `changed: 438` tells you nothing about whether that is a relabel or a
    permission withdrawal. These tests make it answerable from the suite.
    """

    def _attach_profile(self, user, profile):
        """Attach a profile the way production does.

        Mirrors sync_user_role_profile: on v16 the profiles live in the
        `role_profiles` child table and setting `role_profile_name` alone is a
        no-op, because User.move_role_profile_name_to_role_profiles discards it.
        """
        user_doc = frappe.get_doc("User", user)
        if calc._has_multi_profile_support():
            user_doc.set("role_profiles", [{"role_profile": profile}])
        else:
            user_doc.role_profile_name = profile
        user_doc.save()
        frappe.clear_cache(user=user)
        self.assertIn(profile, calc.get_user_role_profiles(user), "fixture failed to attach")

    def _member_user(self):
        email = f"urpcbulk.{frappe.generate_hash(length=8)}@test.invalid"
        member = self.create_test_member(
            first_name="BulkRecalc",
            last_name=f"M{frappe.generate_hash(length=5)}",
            email=email,
            status="Active",
        )
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        self.track_doc("User", user.name)
        frappe.db.set_value("Member", member.name, "user", user.name)
        return user.name, member.name

    def test_downgrade_from_volunteer_withdraws_privileges_not_just_the_label(self):
        """
        The roles the Volunteer profile confers and the Member profile does not are
        withdrawn with it. This is the assertion that makes `changed: N` interpretable:
        N is not a relabel, it is N users losing Employee, Employee Self Service and
        Projects User.

        Derived from the Role Profile documents rather than hardcoded, so it keeps
        telling the truth when someone edits either profile.
        """
        volunteer_roles = {
            r.role for r in frappe.get_doc("Role Profile", PROFILE_VOLUNTEER).roles
        }
        member_roles = {r.role for r in frappe.get_doc("Role Profile", PROFILE_MEMBER).roles}
        withdrawn = volunteer_roles - member_roles

        # Guard the thesis, not just the arithmetic. `withdrawn` shrinking to nothing
        # would make the assertions below vacuous; shrinking to the profile's OWN
        # namesake role would make them near-tautological (swapping the profile
        # obviously removes the role it is named after) while this test still claimed
        # to prove a privilege change. Fail loudly in both cases.
        self.assertTrue(
            withdrawn - {Roles.VOLUNTEER},
            f"Volunteer confers nothing over Member beyond its namesake role ({withdrawn}) - "
            "the downgrade really would be a relabel, so revisit this test",
        )

        user, member = self._member_user()
        vol = self.create_test_volunteer(member=member, status="Active").name
        sync_user_role_profile(user, dry_run=False)
        self.assertIn(PROFILE_VOLUNTEER, calc.get_user_role_profiles(user))
        for role in withdrawn:
            self.assertIn(role, frappe.get_roles(user), f"baseline: {role} should be held")

        # The volunteer stops being active - the veg11 shape. No cache clear needed:
        # is_active_volunteer() queries Volunteer directly and caches nothing per user.
        frappe.db.set_value("Volunteer", vol, "status", "Inactive")

        result = bulk_recalculate_role_profiles(filters={"name": user}, dry_run=False)

        self.assertEqual(result["changed"], 1, result)
        self.assertEqual(result["changes"][0]["new_role"], PROFILE_MEMBER)
        self.assertNotIn(PROFILE_VOLUNTEER, calc.get_user_role_profiles(user))
        frappe.clear_cache(user=user)
        for role in withdrawn:
            self.assertNotIn(
                role, frappe.get_roles(user), f"{role} survived the downgrade to Member"
            )

    def test_holding_a_profile_with_no_volunteer_record_at_all_is_downgraded(self):
        """
        The exact production shape: the profile is held, the Volunteer record does not
        exist. is_active_volunteer's no-record case is already pinned; this pins that
        the bulk tool acts on it rather than leaving the stale profile alone.
        """
        user, _member = self._member_user()
        self._attach_profile(user, PROFILE_VOLUNTEER)

        result = bulk_recalculate_role_profiles(filters={"name": user}, dry_run=True)

        self.assertEqual(result["changed"], 1, result)
        self.assertEqual(result["changes"][0]["old_role"], PROFILE_VOLUNTEER)
        self.assertEqual(result["changes"][0]["new_role"], PROFILE_MEMBER)
        # dry_run: still held.
        self.assertIn(PROFILE_VOLUNTEER, calc.get_user_role_profiles(user))

    def test_a_user_who_is_not_a_member_is_counted_as_an_error_and_left_untouched(self):
        """
        126 of veg11's 564 land here. An operator reading the summary needs to know
        these are SKIPPED, not silently downgraded - they keep whatever they hold.
        """
        email = f"urpcbulk.nonmember.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        self.track_doc("User", user.name)
        self._attach_profile(user.name, PROFILE_VOLUNTEER)
        before = calc.get_user_role_profiles(user.name)
        # A disabled user takes sync_user_role_profile's skip branch, which lands in
        # `unchanged` rather than `errors` - that would fail below as a bare `1 != 0`.
        # Test users have landed disabled before (the in_import/_set_defaults bug), so
        # name the cause here rather than leaving the next reader to rediscover it.
        self.assertTrue(
            frappe.db.get_value("User", user.name, "enabled"), "fixture: user must be enabled"
        )

        result = bulk_recalculate_role_profiles(filters={"name": user.name}, dry_run=False)

        self.assertEqual(result["errors"], 1, result)
        self.assertEqual(result["changed"], 0, result)
        self.assertIn("not a member", result["errors_list"][0]["error"].lower())
        self.assertEqual(calc.get_user_role_profiles(user.name), before)
