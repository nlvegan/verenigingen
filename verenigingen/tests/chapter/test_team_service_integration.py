# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Real-DB integration coverage for the team domain.

Targets:
- verenigingen/services/team_service.py
    TeamService: sync_with_volunteers, add_assignment_history,
    complete_assignment_history, _get_role_description_for_history,
    validate_team_member_changes, handle_member_role_change,
    validate_unique_roles, _validate_unique_roles_globally
    TeamValidationService: validate_team_members,
    validate_role_profile_configuration, validate_dates
- verenigingen/api/team_management.py
    get_team_members, sync_team_with_volunteers,
    get_role_profile_preview, bulk_apply_team_role_profiles

All fixtures are real Member/Volunteer/Team/Team Member/Team Role rows created
via the canonical EnhancedTestCase factories; expected values are derived from
the data created. No business-logic mocking.
"""

import frappe

from verenigingen.services.team_service import (
    get_team_service,
    get_team_validation_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TeamDomainTestBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Team Member rows reference Team Role masters by literal name. The
        # before_tests seeding hook is unreliable for single-module runs, so
        # seed the standard Team Roles here to make this module pass in isolation.
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()

    def setUp(self):
        super().setUp()
        # Saving a Team enqueues an async notification subscriber. Under the
        # test harness it can run after the fixture team is rolled back and log
        # "Team ... not found" — a harness race, not a product error. Tolerate it.
        self.expectErrorLog("Team Notification Error", "Team Assignment History Error")

    def _make_volunteer(self):
        member = self.create_test_member()
        return self.create_test_volunteer(member_name=member.name)

    def _append_member(self, team, volunteer, **overrides):
        data = {
            "volunteer": volunteer.name,
            "volunteer_name": volunteer.volunteer_name,
            "team_role": "Team Member",
            "from_date": frappe.utils.today(),
            "is_active": 1,
            "status": "Active",
        }
        data.update(overrides)
        team.append("team_members", data)
        return data

    def _unique_team_role(self, label, **attrs):
        """Create a Team Role with a unique name and given attributes."""
        name = self.factory.force_unique_name(label, "Team Role")
        role = frappe.get_doc(
            {
                "doctype": "Team Role",
                "role_name": name,
                "is_active": 1,
                "permissions_level": "Basic",
                **attrs,
            }
        )
        role.insert()
        self.factory.track_document("Team Role", role.name, priority=2)
        return role


class TestTeamServiceAssignmentHistory(TeamDomainTestBase):
    def setUp(self):
        super().setUp()
        # Run enqueued assignment-history subscribers inline for determinism.
        self._prev_sync = getattr(frappe.flags, "run_events_synchronously", False)
        frappe.flags.run_events_synchronously = True
        self.svc = get_team_service()

    def tearDown(self):
        frappe.flags.run_events_synchronously = self._prev_sync
        super().tearDown()

    def test_sync_with_volunteers_invokes_controller_hook(self):
        """sync_with_volunteers triggers the Team controller's change handler and returns True."""
        volunteer = self._make_volunteer()
        team = self.create_test_team()
        self._append_member(team, volunteer, role="Builder")
        team.save()

        result = self.svc.sync_with_volunteers(team)
        self.assertTrue(result)

        # sync_with_volunteers calls the controller's handle_team_member_changes,
        # which drives assignment history. Assert the observable side effect: the
        # team member now has an Active assignment row on the volunteer.
        vol = frappe.get_doc("Volunteer", volunteer.name)
        active = [
            a
            for a in vol.assignment_history or []
            if a.reference_name == team.name and a.status == "Active"
        ]
        self.assertTrue(active, "sync should have produced an Active assignment row")

    def test_add_assignment_history_creates_active_row(self):
        """add_assignment_history finds the member and creates an Active assignment."""
        volunteer = self._make_volunteer()
        team = self.create_test_team()
        start = frappe.utils.today()
        self._append_member(team, volunteer, role="Builder", from_date=start)
        team.save()

        result = self.svc.add_assignment_history(team, volunteer.name, "Team Member", start)
        self.assertTrue(result)

        vol = frappe.get_doc("Volunteer", volunteer.name)
        active = [
            a
            for a in vol.assignment_history or []
            if a.reference_name == team.name and a.status == "Active"
        ]
        self.assertTrue(active, "Active assignment row should exist")
        # role_description = Team Role role_name ("Team Member") + " - Builder"
        self.assertEqual(active[0].role, "Team Member - Builder")

    def test_add_assignment_history_member_not_found_returns_false(self):
        """When no matching team member exists, returns False without raising."""
        volunteer = self._make_volunteer()
        team = self.create_test_team()
        team.save()

        # No team_members at all → cannot find member for this volunteer/date.
        result = self.svc.add_assignment_history(
            team, volunteer.name, "Team Member", frappe.utils.today()
        )
        self.assertFalse(result)

    def test_complete_assignment_history_found_in_current(self):
        """complete_assignment_history finds the member in current members and completes the row."""
        volunteer = self._make_volunteer()
        team = self.create_test_team()
        start = frappe.utils.today()
        self._append_member(team, volunteer, role="Builder", from_date=start)
        team.save()
        self.svc.add_assignment_history(team, volunteer.name, "Team Member", start)

        end = frappe.utils.today()
        result = self.svc.complete_assignment_history(
            team, volunteer.name, "Team Member", start, end
        )
        self.assertTrue(result)

        vol = frappe.get_doc("Volunteer", volunteer.name)
        completed = [
            a
            for a in vol.assignment_history or []
            if a.reference_name == team.name and a.status == "Completed"
        ]
        self.assertTrue(completed, "Completed assignment row should exist")
        self.assertEqual(completed[0].role, "Team Member - Builder")
        self.assertIsNotNone(completed[0].end_date)

    def test_complete_assignment_history_member_not_found_uses_fallback(self):
        """When the member can't be found, falls back to the passed team_role string."""
        volunteer = self._make_volunteer()
        team = self.create_test_team()
        team.save()
        # Pre-create an Active row directly so there is something to complete.
        from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

        start = frappe.utils.today()
        AssignmentHistoryManager.add_assignment_history(
            volunteer_id=volunteer.name,
            assignment_type="Team",
            reference_doctype="Team",
            reference_name=team.name,
            role="Special Coordinator",
            start_date=start,
        )

        # team has no team_members → member-not-found path; role_description = team_role arg.
        result = self.svc.complete_assignment_history(
            team, volunteer.name, "Special Coordinator", start, frappe.utils.today()
        )
        self.assertTrue(result)

        vol = frappe.get_doc("Volunteer", volunteer.name)
        completed = [
            a
            for a in vol.assignment_history or []
            if a.reference_name == team.name and a.status == "Completed"
        ]
        self.assertTrue(completed)
        self.assertEqual(completed[0].role, "Special Coordinator")

    def test_complete_assignment_history_member_not_found_empty_team_role(self):
        """member-not-found + empty team_role string falls back to 'Team Member'."""
        volunteer = self._make_volunteer()
        team = self.create_test_team()
        team.save()
        from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

        start = frappe.utils.today()
        AssignmentHistoryManager.add_assignment_history(
            volunteer_id=volunteer.name,
            assignment_type="Team",
            reference_doctype="Team",
            reference_name=team.name,
            role="Team Member",
            start_date=start,
        )

        result = self.svc.complete_assignment_history(
            team, volunteer.name, "", start, frappe.utils.today()
        )
        self.assertTrue(result)

        vol = frappe.get_doc("Volunteer", volunteer.name)
        completed = [
            a
            for a in vol.assignment_history or []
            if a.reference_name == team.name and a.status == "Completed"
        ]
        self.assertTrue(completed)
        self.assertEqual(completed[0].role, "Team Member")


class TestRoleDescriptionForHistory(TeamDomainTestBase):
    def setUp(self):
        super().setUp()
        self.svc = get_team_service()

    def _member_row(self, **fields):
        """Build an in-memory Team Member child row (not saved)."""
        team = self.create_test_team()
        defaults = {
            "volunteer_name": "Someone",
            "from_date": frappe.utils.today(),
            "is_active": 1,
        }
        defaults.update(fields)
        team.append("team_members", defaults)
        return team.team_members[-1]

    def test_uses_team_role_role_name(self):
        """Uses Team Role.role_name when team_role is set and exists."""
        role = self._unique_team_role("Custom Lead", is_team_leader=1)
        m = self._member_row(team_role=role.name)
        desc = self.svc._get_role_description_for_history(m)
        self.assertEqual(desc, role.role_name)

    def test_team_role_with_extra_role_suffix(self):
        """Appends the free-text role field when present."""
        role = self._unique_team_role("Custom Coord")
        m = self._member_row(team_role=role.name, role="Logistics")
        desc = self.svc._get_role_description_for_history(m)
        self.assertEqual(desc, f"{role.role_name} - Logistics")

    def test_falls_back_to_role_type_when_team_role_missing(self):
        """When team_role doesn't resolve, falls back to role_type."""
        m = self._member_row(team_role=None, role_type="Legacy Type")
        desc = self.svc._get_role_description_for_history(m)
        self.assertEqual(desc, "Legacy Type")

    def test_default_team_member_when_nothing_set(self):
        """No team_role and no role_type → default 'Team Member'."""
        m = self._member_row(team_role=None, role_type=None)
        desc = self.svc._get_role_description_for_history(m)
        self.assertEqual(desc, "Team Member")


class TestValidateUniqueRoles(TeamDomainTestBase):
    def setUp(self):
        super().setUp()
        self.svc = get_team_service()

    def test_no_unique_roles_returns_true(self):
        """A team with only non-unique roles passes validation."""
        v1 = self._make_volunteer()
        team = self.create_test_team()
        self._append_member(team, v1, team_role="Team Member")
        team.save()
        self.assertTrue(self.svc.validate_unique_roles(team))

    def test_unique_role_no_conflict(self):
        """A single holder of a unique role passes."""
        role = self._unique_team_role("Sole Treasurer", is_unique=1)
        v1 = self._make_volunteer()
        team = self.create_test_team()
        self._append_member(team, v1, team_role=role.name)
        team.save()
        self.assertTrue(self.svc.validate_unique_roles(team))

    def test_unique_role_conflict_throws(self):
        """Two active holders of the same unique role within a team raises."""
        role = self._unique_team_role("Conflict Treasurer", is_unique=1)
        v1 = self._make_volunteer()
        v2 = self._make_volunteer()
        team = self.create_test_team()
        self._append_member(team, v1, team_role=role.name)
        self._append_member(team, v2, team_role=role.name)
        # validate_unique_roles is called on save() via the controller, so the
        # save itself should raise.
        with self.assertRaises(frappe.ValidationError):
            team.save()

    def test_inactive_member_with_unique_role_ignored(self):
        """An inactive holder of a unique role does not create a conflict."""
        role = self._unique_team_role("Quiet Treasurer", is_unique=1)
        v1 = self._make_volunteer()
        v2 = self._make_volunteer()
        team = self.create_test_team()
        self._append_member(team, v1, team_role=role.name)
        self._append_member(team, v2, team_role=role.name, is_active=0, status="Inactive")
        team.save()
        # Only one active holder → no conflict.
        self.assertTrue(self.svc.validate_unique_roles(team))


class TestValidateUniqueRolesGlobally(TeamDomainTestBase):
    """_validate_unique_roles_globally is currently unused by the controller but
    remains in the service; cover its DB-query behaviour directly."""

    def setUp(self):
        super().setUp()
        self.svc = get_team_service()

    def test_empty_set_is_noop(self):
        team = self.create_test_team()
        team.save()
        # No assertion target other than: returns None and does not raise.
        self.assertIsNone(self.svc._validate_unique_roles_globally(team, set(), {}))

    def test_conflict_with_other_team_is_swallowed(self):
        """Characterizes a latent bug in the (currently unused) global validator.

        When a unique role is already held in another team, the method calls
        frappe.throw("'X' already assigned to ... in <team>."), but its own
        broad ``except Exception`` re-raise guard only re-raises when the
        message contains "Unique role" or "conflict" (case-insensitive). The
        actual message contains neither, so the conflict is SWALLOWED (logged,
        not raised). FLAG: the re-raise guard does not match the thrown message.
        """
        role = self._unique_team_role("Global Treasurer", is_unique=1)
        v1 = self._make_volunteer()
        other_team = self.create_test_team()
        self._append_member(other_team, v1, team_role=role.name)
        other_team.save()

        v2 = self._make_volunteer()
        this_team = self.create_test_team()
        self._append_member(this_team, v2, team_role=role.name)
        this_team.save()

        role_assignments = {role.role_name: [{"volunteer_name": v2.volunteer_name, "team_role": role.name}]}
        # The conflict is logged (Python logger) and swallowed; returns None.
        # (The async "Team ... not found" notification logs are tolerated in the
        # base setUp.)
        result = self.svc._validate_unique_roles_globally(this_team, {role.name}, role_assignments)
        self.assertIsNone(result)


class TestHandleMemberRoleChange(TeamDomainTestBase):
    def setUp(self):
        super().setUp()
        self._prev_sync = getattr(frappe.flags, "run_events_synchronously", False)
        frappe.flags.run_events_synchronously = True
        self.svc = get_team_service()

    def tearDown(self):
        frappe.flags.run_events_synchronously = self._prev_sync
        super().tearDown()

    def test_none_member_is_noop(self):
        """Passing a None old/new member returns without error."""
        team = self.create_test_team()
        team.save()
        self.assertIsNone(self.svc.handle_member_role_change(team, None, None))

    def test_role_change_drives_complete_and_add(self):
        """A role change on an active member runs the complete+add history path.

        When old and new share the same from_date (the common same-day edit case),
        the manager's same-day reactivation logic completes then reactivates the
        single row, leaving exactly one Active assignment for the team. This test
        characterizes that real behavior: the path runs without error and does
        not duplicate the team's assignment row.
        """
        volunteer = self._make_volunteer()
        team = self.create_test_team()
        start = frappe.utils.today()
        self._append_member(team, volunteer, role="Old Role", from_date=start)
        team.save()
        self.svc.add_assignment_history(team, volunteer.name, "Team Member", start)

        old_member = team.team_members[0]
        # Build a "new" member view with a changed free-text role.
        new_member = frappe._dict(
            volunteer=volunteer.name,
            role="New Role",
            team_role=old_member.team_role,
            role_type=old_member.role_type,
            is_active=1,
            from_date=start,
        )
        self.svc.handle_member_role_change(team, old_member, new_member)

        vol = frappe.get_doc("Volunteer", volunteer.name)
        rows = [a for a in vol.assignment_history or [] if a.reference_name == team.name]
        self.assertEqual(len(rows), 1, "Same-day role change must not duplicate the assignment row")
        self.assertEqual(rows[0].status, "Active")

    def test_no_role_change_is_noop(self):
        """Identical old/new members produce no history changes."""
        volunteer = self._make_volunteer()
        team = self.create_test_team()
        self._append_member(team, volunteer, role="Same")
        team.save()
        member = team.team_members[0]
        # Same fields → role_changed False → noop.
        result = self.svc.handle_member_role_change(team, member, member)
        self.assertIsNone(result)


class TestTeamValidationService(TeamDomainTestBase):
    def setUp(self):
        super().setUp()
        self.svc = get_team_validation_service()

    def test_validate_dates_rejects_end_before_start(self):
        team = self.create_test_team()
        team.start_date = "2026-01-10"
        team.end_date = "2026-01-05"
        with self.assertRaises(frappe.ValidationError):
            self.svc.validate_dates(team)

    def test_validate_dates_accepts_valid_range(self):
        team = self.create_test_team()
        team.start_date = "2026-01-05"
        team.end_date = "2026-01-10"
        self.assertTrue(self.svc.validate_dates(team))

    def test_validate_team_members_with_leader(self):
        """A team with an active team-leader role validates True."""
        leader_role = self._unique_team_role("Active Lead", is_team_leader=1)
        v1 = self._make_volunteer()
        team = self.create_test_team()
        self._append_member(team, v1, team_role=leader_role.name)
        team.save()
        self.assertTrue(self.svc.validate_team_members(team))

    def test_validate_team_members_without_leader_warns(self):
        """An active team with no leader still returns True (warning only)."""
        v1 = self._make_volunteer()
        team = self.create_test_team()
        self._append_member(team, v1, team_role="Team Member")
        team.save()
        # No leader, status Active, has members → msgprint warning, returns True.
        self.assertTrue(self.svc.validate_team_members(team))

    def test_validate_role_profile_missing_default_throws(self):
        team = self.create_test_team()
        team.default_role_profile = "No-Such-Profile-XYZ"
        with self.assertRaises(frappe.ValidationError):
            self.svc.validate_role_profile_configuration(team)

    def test_validate_role_profile_duplicate_assignment_throws(self):
        """Two role_specific_profiles rows for the same team_role raises."""
        role = self._unique_team_role("Dup Role")
        profile = self._ensure_role_profile()
        team = self.create_test_team()
        team.enable_role_specific_profiles = 1
        team.default_role_profile = profile
        team.append("role_specific_profiles", {"team_role": role.name, "role_profile": profile})
        team.append("role_specific_profiles", {"team_role": role.name, "role_profile": profile})
        with self.assertRaises(frappe.ValidationError):
            self.svc.validate_role_profile_configuration(team)

    def test_validate_role_profile_unknown_role_profile_throws(self):
        """A role_specific_profiles row pointing at a missing Role Profile raises."""
        role = self._unique_team_role("Real Role")
        default_profile = self._ensure_role_profile()
        team = self.create_test_team()
        team.enable_role_specific_profiles = 1
        team.default_role_profile = default_profile
        team.append(
            "role_specific_profiles",
            {"team_role": role.name, "role_profile": "Ghost-Profile-XYZ"},
        )
        with self.assertRaises(frappe.ValidationError):
            self.svc.validate_role_profile_configuration(team)

    def test_validate_role_profile_unknown_team_role_throws(self):
        """A role_specific_profiles row referencing a missing Team Role raises.

        Distinct from the missing-Role-Profile case: here the role_profile IS
        valid (so the profile-exists guard passes), but team_role points at a
        Team Role that does not exist, exercising the final
        ``frappe.db.exists("Team Role", ...)`` guard. The service method is
        called directly, so Frappe's link validation (which only runs on save)
        does not pre-empt the service's own existence check.
        """
        profile = self._ensure_role_profile()
        team = self.create_test_team()
        team.enable_role_specific_profiles = 1
        team.default_role_profile = profile
        team.append(
            "role_specific_profiles",
            {"team_role": "Ghost-Team-Role-XYZ", "role_profile": profile},
        )
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.svc.validate_role_profile_configuration(team)
        self.assertIn("Team Role", str(ctx.exception))
        self.assertIn("does not exist", str(ctx.exception))

    def test_validate_role_profile_valid_config(self):
        """A consistent role-profile configuration validates True."""
        role = self._unique_team_role("Valid Role")
        profile = self._ensure_role_profile()
        team = self.create_test_team()
        team.enable_role_specific_profiles = 1
        team.default_role_profile = profile
        team.append("role_specific_profiles", {"team_role": role.name, "role_profile": profile})
        self.assertTrue(self.svc.validate_role_profile_configuration(team))

    def _ensure_role_profile(self):
        """Return the name of an existing Role Profile, creating a unique one if needed."""
        name = self.factory.force_unique_name("Test Team Role Profile", "Role Profile")
        if not frappe.db.exists("Role Profile", name):
            rp = frappe.get_doc({"doctype": "Role Profile", "role_profile": name})
            rp.insert()
            self.factory.track_document("Role Profile", rp.name, priority=2)
        return name


class TestTeamManagementAPI(TeamDomainTestBase):
    def setUp(self):
        super().setUp()
        self._prev_sync = getattr(frappe.flags, "run_events_synchronously", False)
        frappe.flags.run_events_synchronously = True

    def tearDown(self):
        frappe.flags.run_events_synchronously = self._prev_sync
        super().tearDown()

    def test_get_team_members_requires_team(self):
        """Missing team → the @handle_api_error wrapper returns a 400 error dict."""
        from verenigingen.api.team_management import get_team_members

        # @handle_api_error logs the caught ValidationError to Error Log.
        self.expectErrorLog("Team is required", "team_management")
        result = get_team_members(None)
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["http_status"], 400)
        self.assertIn("Team is required", result["error"]["message"])

    def test_get_team_members_returns_member_with_volunteer_info(self):
        from verenigingen.api.team_management import get_team_members

        volunteer = self._make_volunteer()
        team = self.create_test_team()
        self._append_member(team, volunteer, role="Builder")
        team.save()

        result = get_team_members(team.name)
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual(row["volunteer"], volunteer.name)
        self.assertEqual(row["role"], "Builder")
        # Volunteer info is merged in.
        self.assertEqual(row["email"], volunteer.email)
        self.assertIn("skills", row)

    def test_get_team_members_empty_team(self):
        from verenigingen.api.team_management import get_team_members

        team = self.create_test_team()
        team.save()
        result = get_team_members(team.name)
        self.assertEqual(result, [])

    def test_sync_team_with_volunteers_named_team(self):
        from verenigingen.api.team_management import sync_team_with_volunteers

        volunteer = self._make_volunteer()
        team = self.create_test_team()
        self._append_member(team, volunteer, role="Builder")
        team.save()

        result = sync_team_with_volunteers(team.name)
        self.assertEqual(result["updated_count"], 1)

    def test_get_role_profile_preview_with_and_without_mapping(self):
        from verenigingen.api.team_management import get_role_profile_preview

        role_mapped = self._unique_team_role("Preview Mapped")
        role_unmapped = self._unique_team_role("Preview Unmapped")
        profile = self._ensure_role_profile()

        v1 = self._make_volunteer()
        v2 = self._make_volunteer()
        team = self.create_test_team()
        team.enable_role_specific_profiles = 1
        team.default_role_profile = profile
        team.append("role_specific_profiles", {"team_role": role_mapped.name, "role_profile": profile})
        self._append_member(team, v1, team_role=role_mapped.name)
        self._append_member(team, v2, team_role=role_unmapped.name)
        team.save()

        preview = get_role_profile_preview(team.name)
        by_vol = {p["volunteer"]: p for p in preview}
        self.assertTrue(by_vol[v1.name]["would_be_assigned"])
        self.assertEqual(by_vol[v1.name]["current_role_profile"], profile)
        self.assertFalse(by_vol[v2.name]["would_be_assigned"])

    def test_get_role_profile_preview_skips_inactive(self):
        from verenigingen.api.team_management import get_role_profile_preview

        v1 = self._make_volunteer()
        team = self.create_test_team()
        self._append_member(team, v1, team_role="Team Member", is_active=0, status="Inactive")
        team.save()
        preview = get_role_profile_preview(team.name)
        self.assertEqual(preview, [])

    def test_bulk_apply_nonexistent_team(self):
        from verenigingen.api.team_management import bulk_apply_team_role_profiles

        result = bulk_apply_team_role_profiles("No-Such-Team-XYZ")
        self.assertFalse(result["success"])
        self.assertEqual(result["applied_count"], 0)

    def test_bulk_apply_empty_team_succeeds(self):
        from verenigingen.api.team_management import bulk_apply_team_role_profiles

        team = self.create_test_team()
        team.save()
        result = bulk_apply_team_role_profiles(team.name)
        # No active members with linked users → applied_count 0 but success (len==0 path).
        self.assertEqual(result["applied_count"], 0)
        self.assertTrue(result["success"])

    def _ensure_role_profile(self):
        name = self.factory.force_unique_name("Test Team Role Profile", "Role Profile")
        if not frappe.db.exists("Role Profile", name):
            rp = frappe.get_doc({"doctype": "Role Profile", "role_profile": name})
            rp.insert()
            self.factory.track_document("Role Profile", rp.name, priority=2)
        return name
