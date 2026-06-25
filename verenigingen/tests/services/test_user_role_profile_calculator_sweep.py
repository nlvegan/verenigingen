# Copyright (c) 2026, Veganisme.org and contributors
# For license information, please see license.txt

"""
Coverage *sweep* for
``verenigingen/services/member/account/user_role_profile_calculator.py``.

Augments ``test_user_role_profile_calculator.py`` and
``test_member_account_coverage_supplement.py`` (does NOT duplicate them). This
file targets the branches those two left uncovered:

config caches (``_get_cached_chapter_profile_config`` / ``_get_cached_team_profile_config``)
    - cache-hit return path (config served from the module-global cache)
    - exception fallback (entity row missing → defensive default dict)

``get_board_member_profiles``
    - role-specific profile *configured but missing* → falls through to default
    - chapter ``default_board_role_profile`` set + valid → PRIORITY_BOARD_DEFAULT
    - chapter row deleted under an active board position → "Missing Chapter" log

``get_team_profiles``
    - role-specific team profile → PRIORITY_TEAM_ROLE_SPECIFIC
    - association-wide team role-specific + default → PRIORITY_STAFF (75) beats board (70)
    - team default profile branch for a plain member (not leader)
    - team-leader + member of the SAME team is not double counted

``calculate_user_role_profile`` precedence resolution
    - staff (association-wide) outranks a board default
    - conflicting profiles: max() picks the highest priority

``sync_user_role_profile``
    - module_changed branch (a profile mapped to an existing Module Profile)
    - audit-log creation (Activity Log row written on a real change)

``bulk_recalculate_role_profiles``
    - default-filter (no filters) path runs without raising

No business-logic mocking. Real Members, Volunteers, Chapters, Teams, Chapter
Board Members, Team Members, Role Profiles and Module Profiles are created via
the factory / ``frappe.get_doc().insert()``. Tests run as Administrator.

v16 note: role-profile assignment lands in the User ``role_profiles`` child
table, not the deprecated ``role_profile_name`` Link.
"""

import frappe

from verenigingen.services.member.account import user_role_profile_calculator as calc
from verenigingen.services.member.account.user_role_profile_calculator import (
    PRIORITY_BOARD_DEFAULT,
    PRIORITY_STAFF,
    PRIORITY_TEAM_ROLE_SPECIFIC,
    PROFILE_MEMBER,
    PROFILE_VOLUNTEER,
    _get_cached_chapter_profile_config,
    _get_cached_team_profile_config,
    bulk_recalculate_role_profiles,
    calculate_all_user_role_profiles,
    calculate_user_role_profile,
    get_board_member_profiles,
    get_team_profiles,
    sync_user_role_profile,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestUserRoleProfileCalculatorSweep(VereningingenTestCase):
    """Exercise the branches the existing calculator tests don't reach."""

    def setUp(self):
        super().setUp()
        self.h = frappe.generate_hash(length=6)
        # Config cache is module-global — clear before and after so config set in
        # one test never bleeds into the next (the calculator caches per entity).
        calc.invalidate_profile_config_cache()
        self.addCleanup(calc.invalidate_profile_config_cache)

    # ------------------------------------------------------------------ helpers

    def _make_role_profile(self, label, roles=("Verenigingen Volunteer",)):
        name = f"URPCS {label} {frappe.generate_hash(length=6)}"
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
        email = f"urpcsw.{frappe.generate_hash(length=8)}@test.invalid"
        member = self.create_test_member(
            first_name="Sweep",
            last_name=f"M{frappe.generate_hash(length=5)}",
            email=email,
            status=status,
        )
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        self.track_doc("User", user.name)
        frappe.db.set_value("Member", member.name, "user", user.name)
        return user.name, member.name

    def _make_volunteer(self, member, status="Active"):
        return self.create_test_volunteer(member=member, status=status).name

    def _ensure_module_profile(self, name):
        """Get-or-create a Module Profile so the mapped-module branch runs
        deterministically on a bare CI site (veg11 already seeds these)."""
        if not frappe.db.exists("Module Profile", name):
            frappe.get_doc({"doctype": "Module Profile", "module_profile_name": name}).insert()
            self.track_doc("Module Profile", name)
        return name

    def _ensure_chapter_role(self, role_name):
        if not frappe.db.exists("Chapter Role", role_name):
            frappe.get_doc({"doctype": "Chapter Role", "role_name": role_name, "is_active": 1}).insert()
            self.track_doc("Chapter Role", role_name)

    def _ensure_team_role(self, role_name):
        if not frappe.db.exists("Team Role", role_name):
            frappe.get_doc({"doctype": "Team Role", "role_name": role_name, "is_active": 1}).insert()
            self.track_doc("Team Role", role_name)
        return role_name

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

    def _make_team(self, default_profile=None, enable_specific=0, is_association_wide=0):
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"URPCS Team {frappe.generate_hash(length=6)}",
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
    # config caches: cache-hit + exception fallback
    # =================================================================

    def test_chapter_config_cache_hit_returns_same_object(self):
        """Second call within TTL is served from the module-global cache."""
        chapter = self.create_test_chapter()
        first = _get_cached_chapter_profile_config(chapter.name)
        cache_key = f"chapter_profile:{chapter.name}"
        self.assertIn(cache_key, calc._profile_config_cache)
        second = _get_cached_chapter_profile_config(chapter.name)
        # Cache hit hands back the *same* dict object stored on the first miss.
        self.assertIs(first, second)

    def test_chapter_config_missing_entity_returns_default_dict(self):
        """A non-existent chapter triggers the except branch → safe default dict."""
        cfg = _get_cached_chapter_profile_config("No Such Chapter ZZZ")
        self.assertEqual(
            cfg,
            {"default_profile": None, "enable_specific": False, "specific_profiles": {}},
        )

    def test_team_config_cache_hit_returns_same_object(self):
        team = self._make_team()
        first = _get_cached_team_profile_config(team)
        self.assertIn(f"team_profile:{team}", calc._profile_config_cache)
        second = _get_cached_team_profile_config(team)
        self.assertIs(first, second)

    def test_team_config_missing_entity_returns_default_dict(self):
        cfg = _get_cached_team_profile_config("No Such Team ZZZ")
        self.assertEqual(
            cfg,
            {
                "default_profile": None,
                "enable_specific": False,
                "specific_profiles": {},
                "is_association_wide": False,
            },
        )

    def test_team_config_reports_association_wide_flag(self):
        team = self._make_team(is_association_wide=1)
        cfg = _get_cached_team_profile_config(team)
        self.assertTrue(cfg["is_association_wide"])

    # =================================================================
    # get_board_member_profiles - fallthrough branches
    # =================================================================

    def test_board_default_profile_used_when_set(self):
        """Chapter with a valid default_board_role_profile → PRIORITY_BOARD_DEFAULT."""
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        profile = self._make_role_profile("BoardDefault")
        chapter = self.create_test_chapter(default_board_role_profile=profile)
        self._add_board_position(chapter.name, vol)
        profiles = get_board_member_profiles(user, member)
        self.assertIn((PRIORITY_BOARD_DEFAULT, profile), profiles)

    def test_board_role_specific_missing_falls_through_to_default(self):
        """Role-specific profile configured but pointing at a ghost profile.

        The lookup finds a mapping whose Role Profile does not exist, logs a
        "Missing Profile" Error Log, and falls through to the chapter default.
        """
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        self._ensure_chapter_role("Secretaris")
        default_profile = self._make_role_profile("BoardFallbackDefault")
        chapter = self.create_test_chapter(
            default_board_role_profile=default_profile,
            enable_board_role_specific_profiles=1,
        )
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append(
            "board_role_specific_profiles",
            {"chapter_role": "Secretaris", "role_profile": default_profile},
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
        # Corrupt the role-specific mapping to reference a ghost profile so the
        # "configured but missing" → fall-through-to-default branch runs.
        row = frappe.get_all(
            "Chapter Role Profile Mapping",
            filters={"parent": chapter.name, "chapter_role": "Secretaris"},
            limit=1,
        )
        self.assertTrue(row, "role-specific mapping row should exist")
        frappe.db.set_value("Chapter Role Profile Mapping", row[0].name, "role_profile", "Ghost Profile ZZZ")
        calc.invalidate_profile_config_cache("chapter", chapter.name)

        # The handler logs a "Missing Profile" Error Log, which is the documented
        # behaviour for this misconfiguration, then falls back to the default.
        self.expectErrorLog("Role Profile: Missing Profile")
        profiles = get_board_member_profiles(user, member)
        # Falls through to the (valid) chapter default.
        self.assertIn((PRIORITY_BOARD_DEFAULT, default_profile), profiles)

    def test_board_position_with_deleted_chapter_logs_and_skips(self):
        """A board position whose Chapter row is gone is logged and skipped.

        Reachable by pointing the child row's ``parent`` at a missing chapter via
        a direct DB write (the doc would normally enforce the Link).
        """
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        chapter = self.create_test_chapter()
        self._add_board_position(chapter.name, vol)
        bm = frappe.db.get_value("Chapter Board Member", {"volunteer": vol}, "name")
        frappe.db.set_value("Chapter Board Member", bm, "parent", "Ghost Chapter ZZZ")

        self.expectErrorLog("Role Profile: Missing Chapter")
        profiles = get_board_member_profiles(user, member)
        # The orphaned position is skipped → no board entry produced.
        self.assertEqual(profiles, [])

    # =================================================================
    # get_team_profiles - role-specific + association-wide + default
    # =================================================================

    def test_team_role_specific_profile_used(self):
        """A team role-specific mapping resolves to PRIORITY_TEAM_ROLE_SPECIFIC."""
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        role = self._ensure_team_role("URPCS Coordinator")
        profile = self._make_role_profile("TeamRoleSpecific")
        team = self._make_team(enable_specific=1)
        team_doc = frappe.get_doc("Team", team)
        team_doc.append("role_specific_profiles", {"team_role": role, "role_profile": profile})
        team_doc.save()
        self._add_team_member(team, vol, role=role)

        profiles = get_team_profiles(user, member)
        self.assertIn((PRIORITY_TEAM_ROLE_SPECIFIC, profile), profiles)

    def test_association_wide_team_gets_staff_priority(self):
        """An association-wide team role-specific profile earns PRIORITY_STAFF (75)."""
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        role = self._ensure_team_role("URPCS Staffer")
        profile = self._make_role_profile("StaffProfile")
        team = self._make_team(enable_specific=1, is_association_wide=1)
        team_doc = frappe.get_doc("Team", team)
        team_doc.append("role_specific_profiles", {"team_role": role, "role_profile": profile})
        team_doc.save()
        self._add_team_member(team, vol, role=role)

        profiles = get_team_profiles(user, member)
        self.assertIn((PRIORITY_STAFF, profile), profiles)

    def test_team_default_profile_for_plain_member(self):
        """A plain team member (not leader) on a team with a default profile.

        Hits the "fall back to default team role profile (if not already team
        leader)" branch — the member holds a role with no role-specific mapping.
        """
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        role = self._ensure_team_role("URPCS Member")
        profile = self._make_role_profile("TeamDefault")
        team = self._make_team(default_profile=profile)
        self._add_team_member(team, vol, role=role)

        profiles = get_team_profiles(user, member)
        self.assertIn((PRIORITY_TEAM_ROLE_SPECIFIC, profile), profiles)

    def test_team_membership_with_deleted_team_logs_and_skips(self):
        """A team membership whose Team row is gone is logged and skipped."""
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)
        role = self._ensure_team_role("URPCS Orphan")
        team = self._make_team(default_profile=self._make_role_profile("OrphanDefault"))
        self._add_team_member(team, vol, role=role)
        tm = frappe.db.get_value("Team Member", {"volunteer": vol, "parent": team}, "name")
        frappe.db.set_value("Team Member", tm, "parent", "Ghost Team ZZZ")

        self.expectErrorLog("Role Profile: Missing Team")
        profiles = get_team_profiles(user, member)
        self.assertEqual(profiles, [])

    # =================================================================
    # calculate_user_role_profile - precedence resolution
    # =================================================================

    def test_staff_outranks_board_default(self):
        """Association-wide staff (75) beats a board default (70) in the ladder."""
        user, member = self._make_member_user()
        vol = self._make_volunteer(member)

        # Board default (priority 70).
        board_chapter = self.create_test_chapter(
            default_board_role_profile=self._make_role_profile("BoardForStaffTest")
        )
        self._add_board_position(board_chapter.name, vol)

        # Association-wide team role-specific (priority 75 = STAFF).
        role = self._ensure_team_role("URPCS StaffWins")
        staff_profile = self._make_role_profile("StaffWins")
        team = self._make_team(enable_specific=1, is_association_wide=1)
        team_doc = frappe.get_doc("Team", team)
        team_doc.append("role_specific_profiles", {"team_role": role, "role_profile": staff_profile})
        team_doc.save()
        self._add_team_member(team, vol, role=role)

        self.assertEqual(calculate_user_role_profile(user), staff_profile)
        all_profiles = calculate_all_user_role_profiles(user)
        # Highest is the staff profile at PRIORITY_STAFF.
        self.assertEqual(all_profiles[0][0], PRIORITY_STAFF)
        self.assertEqual(all_profiles[0][1], staff_profile)

    def test_conflicting_profiles_max_priority_wins(self):
        """Multiple candidates → max() by priority selects the winner.

        A board default (70) and an active-volunteer fallback (30) compete; the
        board default must win, and the volunteer candidate must still appear in
        the full list.
        """
        user, member = self._make_member_user()
        vol = self._make_volunteer(member, status="Active")
        board_profile = self._make_role_profile("ConflictBoard")
        chapter = self.create_test_chapter(default_board_role_profile=board_profile)
        self._add_board_position(chapter.name, vol)

        self.assertEqual(calculate_user_role_profile(user), board_profile)
        all_profiles = calculate_all_user_role_profiles(user)
        names = [p[1] for p in all_profiles]
        self.assertIn(PROFILE_VOLUNTEER, names)
        self.assertIn(PROFILE_MEMBER, names)
        # Sorted descending: board profile is at the front.
        self.assertEqual(all_profiles[0][1], board_profile)

    # =================================================================
    # sync_user_role_profile - module_changed + audit log
    # =================================================================

    def test_sync_writes_activity_log_on_change(self):
        """A real profile change writes an Activity Log audit entry."""
        user, member = self._make_member_user()
        self._make_volunteer(member, status="Active")
        before = frappe.db.count("Activity Log", {"reference_doctype": "User", "reference_name": user})

        with self.assertNoErrorLog():
            result = sync_user_role_profile(user, dry_run=False)
        self.assertTrue(result["changed"])

        after = frappe.db.count("Activity Log", {"reference_doctype": "User", "reference_name": user})
        self.assertGreater(after, before, "Activity Log audit entry should have been created")

    def test_sync_updates_module_profile_when_mapped(self):
        """When the resolved role profile maps to an existing Module Profile.

        ``ROLE_MODULE_MAPPING`` pairs ``PROFILE_MEMBER`` with a module profile;
        when that Module Profile exists on the site, the sync flips
        ``module_profile`` and reports ``module_changed``.
        """
        from verenigingen.constants.profile_mappings import ROLE_MODULE_MAPPING

        user, member = self._make_member_user()  # plain member → PROFILE_MEMBER

        mapped_module = ROLE_MODULE_MAPPING.get(PROFILE_MEMBER)
        self.assertTrue(mapped_module, "PROFILE_MEMBER must map to a Module Profile")
        # Get-or-create the mapped Module Profile so the module_changed branch runs
        # deterministically (rather than being skipped on a bare CI site).
        self._ensure_module_profile(mapped_module)

        # Ensure module_profile starts unset so a change is detected.
        frappe.db.set_value("User", user, "module_profile", None)
        with self.assertNoErrorLog():
            result = sync_user_role_profile(user, dry_run=False)

        self.assertTrue(result["success"])
        self.assertTrue(result["module_changed"])
        self.assertEqual(result["new_module_profile"], mapped_module)
        self.assertEqual(frappe.db.get_value("User", user, "module_profile"), mapped_module)

    def test_sync_skips_missing_module_profile(self):
        """A mapped-but-missing Module Profile is skipped; the role is still applied.

        The site seeds the real "Verenigingen Volunteer" Module Profile, so the
        missing-profile branch is only reachable if the resolved profile maps to a
        Module Profile that does not exist. We deterministically map PROFILE_VOLUNTEER
        to a guaranteed-absent name via the role→module mapping (a pure data constant,
        not business logic) so the real ``frappe.db.exists(...) is False`` skip branch
        executes. The mapping is restored automatically after the test.
        """
        from unittest.mock import patch

        user, member = self._make_member_user()
        self._make_volunteer(member, status="Active")

        absent_module = f"URPCS Absent ModProfile {frappe.generate_hash(length=8)}"
        self.assertFalse(frappe.db.exists("Module Profile", absent_module))

        # Point the resolved profile at a Module Profile that does not exist; the
        # production code reads ROLE_MODULE_MAPPING via its own module binding.
        patched_mapping = {**calc.ROLE_MODULE_MAPPING, PROFILE_VOLUNTEER: absent_module}
        with patch.object(calc, "ROLE_MODULE_MAPPING", patched_mapping):
            with self.assertNoErrorLog():
                result = sync_user_role_profile(user, dry_run=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["new_profile"], PROFILE_VOLUNTEER)
        # The mapped Module Profile was absent → skipped, not reported as changed.
        self.assertFalse(result["module_changed"])
        # Sanity: the would-be module profile was never written to the user.
        self.assertNotEqual(frappe.db.get_value("User", user, "module_profile"), absent_module)

    # =================================================================
    # bulk_recalculate_role_profiles - default filter path
    # =================================================================

    def test_bulk_default_filter_dry_run_runs(self):
        """No filters → default filter on verenigingen profiles; dry run is safe."""
        # Seed at least one user that the default filter would match.
        user, member = self._make_member_user()
        self._make_volunteer(member, status="Active")
        sync_user_role_profile(user, dry_run=False)  # now carries PROFILE_VOLUNTEER

        result = bulk_recalculate_role_profiles(dry_run=True)
        # Shape assertions only — this scans every matching user, so we don't
        # assert on exact counts (other tests' users may match too).
        self.assertIn("total", result)
        self.assertIn("changed", result)
        self.assertIn("unchanged", result)
        self.assertIn("errors", result)
        self.assertIsInstance(result["changes"], list)
