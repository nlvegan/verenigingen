# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""
Coverage-focused real-DB integration tests for the Team DocType controller
(verenigingen/verenigingen/doctype/team/team.py).

These complement the behavioural tests in test_team.py by exercising the
controller's OWN logic (not the parts delegated wholesale to TeamService):

  * _update_team_lead          -> team_lead auto-populated from active leader's member.user
  * handle_team_member_changes -> Volunteer Assignment history rows created/completed on
                                  add / remove / role-change / deactivate / reactivate
  * _validate_assignment_history_consistency (auto-fix path)
  * _get_member_snapshot
  * _emit_team_change_events + _detect_and_emit_* (membership/settings/leadership)
  * get_team_permission_query_conditions (admin vs member with/without volunteer/team)

All tests build real records via the enhanced factory and assert MEANINGFUL
side effects.

NOTE on the Error Log guard: saving a Team emits team_* events
(team_events.py) whose subscribers (team_subscribers.py) are ENQUEUED with a
delay. Under the in-process test runner those enqueued jobs run after the team
is created but in a context that does not yet see the uncommitted Team, so they
log a benign "Team ... not found". That noise originates in the event-subscriber
layer, NOT in team.py. We therefore (a) wrap the team.py methods under test in
their own explicit assertNoErrorLog() blocks (separate from the save that emits
events), and (b) declare the subscriber-noise titles via expectErrorLog() in
setUp so the automatic tearDown check ignores only that known-benign noise.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.team.team import get_team_permission_query_conditions


class TestTeamCoverage(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Team Member rows reference Team Role records by their literal name. These
        # are seed data not guaranteed on a fresh CI-mirror test site; create them.
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()

    def setUp(self):
        super().setUp()
        # See module docstring: the async team-event subscribers can log a benign
        # "Team ... not found" against an uncommitted team under the in-process
        # test runner. Declare those subscriber-layer titles as expected so the
        # automatic tearDown Error Log check ignores ONLY that known noise. This
        # does NOT relax the explicit assertNoErrorLog() blocks around team.py.
        self.expectErrorLog(
            "Team Assignment History Error",
            "Team Notification Error",
            "Team Settings Notification Error",
            "Team Permissions Update Error",
            "Team Cache Invalidation Error",
            "Team Leadership Notification Error",
            "Team Lead Permission Error",
            "Team Event Emission Error",
        )

    # ------------------------------------------------------------------ helpers

    def _make_volunteer(self, with_user=False):
        """Create a Member + linked Volunteer. Optionally attach a real User to the
        Member so _update_team_lead has a user to resolve."""
        member = self.create_test_member()
        if with_user:
            user = self._make_user()
            frappe.db.set_value("Member", member.name, "user", user)
            member.reload()
        volunteer = self.create_test_volunteer(member_name=member.name)
        return member, volunteer

    def _make_user(self):
        email = f"teamlead_{frappe.generate_hash(length=10)}@test.invalid"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "TeamLead",
                "send_welcome_email": 0,
                "enabled": 1,
            }
        )
        user.insert()
        self.track_doc("User", user.name)
        return user.name

    def _new_team(self, **kwargs):
        """Return an UNINSERTED Team doc with a unique name. Callers append members
        then call .insert()/.save() themselves so they control the lifecycle hook
        (after_insert / on_update) under test. (The factory's create_team inserts
        immediately, which would double-insert here.)"""
        name = kwargs.pop("team_name", None) or f"Cov Team {frappe.generate_hash(length=10)}"
        data = {
            "doctype": "Team",
            "team_name": name,
            "status": "Active",
            "team_type": "Project Team",
            "start_date": today(),
            "description": "Team coverage test",
        }
        data.update(kwargs)
        return frappe.get_doc(data)

    def _append_member(self, team, volunteer, team_role="Team Member", role="", is_active=1, from_date=None):
        team.append(
            "team_members",
            {
                "volunteer": volunteer.name,
                "volunteer_name": volunteer.volunteer_name,
                "team_role": team_role,
                "role_type": team_role,
                "role": role,
                "from_date": from_date or today(),
                "is_active": is_active,
                "status": "Active" if is_active else "Inactive",
            },
        )

    def _active_history(self, volunteer_name, team_name):
        return frappe.get_all(
            "Volunteer Assignment",
            filters={
                "parent": volunteer_name,
                "reference_doctype": "Team",
                "reference_name": team_name,
                "status": "Active",
            },
            fields=["name", "role", "start_date", "end_date"],
        )

    def _completed_history(self, volunteer_name, team_name):
        return frappe.get_all(
            "Volunteer Assignment",
            filters={
                "parent": volunteer_name,
                "reference_doctype": "Team",
                "reference_name": team_name,
                "status": "Completed",
            },
            fields=["name", "role", "start_date", "end_date"],
        )

    # ------------------------------------------------------- _update_team_lead

    def test_team_lead_autopopulated_from_active_leader_user(self):
        """An active member holding a Team Leader role whose member has a User set
        causes _update_team_lead (called in validate) to populate team_lead."""
        _, leader_vol = self._make_volunteer(with_user=True)
        expected_user = frappe.db.get_value(
            "Member", frappe.db.get_value("Volunteer", leader_vol.name, "member"), "user"
        )
        self.assertTrue(expected_user, "precondition: leader member must have a user")

        team = self._new_team()
        self._append_member(team, leader_vol, team_role="Team Leader", role="Chair")
        team.save()
        team.reload()
        self.assertEqual(team.team_lead, expected_user, "team_lead must resolve to the leader's user")

    def test_team_lead_none_when_leader_has_no_user(self):
        """A Team Leader whose member has no User leaves team_lead empty (the branch
        that resolves volunteer.member but finds no user)."""
        _, leader_vol = self._make_volunteer(with_user=False)
        team = self._new_team()
        self._append_member(team, leader_vol, team_role="Team Leader", role="Chair")
        team.save()
        team.reload()
        self.assertFalse(team.team_lead, "team_lead stays empty when the leader has no user")

    def test_team_lead_ignores_non_leader_roles(self):
        """A team with only a (user-bearing) Team Member -- not a leader -- gets no
        team_lead, exercising the is_team_leader=False skip in _update_team_lead."""
        _, member_vol = self._make_volunteer(with_user=True)
        team = self._new_team()
        self._append_member(team, member_vol, team_role="Team Member", role="Helper")
        team.save()
        team.reload()
        self.assertFalse(team.team_lead, "non-leader roles must not set team_lead")

    # --------------------------------------------- assignment history on insert

    def test_after_insert_creates_active_history_for_active_members(self):
        """after_insert -> handle_team_member_changes adds an Active Volunteer
        Assignment row for each active member with a volunteer."""
        _, leader_vol = self._make_volunteer()
        _, member_vol = self._make_volunteer()
        team = self._new_team()
        self._append_member(team, leader_vol, team_role="Team Leader", role="Chair")
        self._append_member(team, member_vol, team_role="Team Member", role="Helper")
        team.insert()
        self.track_doc("Team", team.name)

        leader_hist = self._active_history(leader_vol.name, team.name)
        member_hist = self._active_history(member_vol.name, team.name)
        self.assertEqual(len(leader_hist), 1, "leader gets one active assignment")
        self.assertEqual(len(member_hist), 1, "member gets one active assignment")
        # role_description = Team Role name + " - " + role
        self.assertEqual(leader_hist[0].role, "Team Leader - Chair")
        self.assertEqual(member_hist[0].role, "Team Member - Helper")

    def test_inactive_member_on_insert_gets_no_history(self):
        """An inactive member at insert time produces NO assignment history."""
        _, member_vol = self._make_volunteer()
        team = self._new_team()
        self._append_member(team, member_vol, team_role="Team Member", role="Helper", is_active=0)
        team.insert()
        self.track_doc("Team", team.name)
        self.assertEqual(
            len(self._active_history(member_vol.name, team.name)), 0, "inactive member: no active history"
        )

    # ------------------------------------- assignment history on add / remove

    def test_adding_member_to_existing_team_creates_history(self):
        """Adding a new active member to a saved team creates an Active assignment via
        handle_team_member_changes (the new-member branch)."""
        _, leader_vol = self._make_volunteer()
        team = self._new_team()
        self._append_member(team, leader_vol, team_role="Team Leader", role="Chair")
        team.insert()
        self.track_doc("Team", team.name)

        _, new_vol = self._make_volunteer()
        team.reload()
        self._append_member(team, new_vol, team_role="Team Member", role="Newbie")
        team.save()  # populates _doc_before_save snapshot used below
        with self.assertNoErrorLog():
            team.handle_team_member_changes()

        hist = self._active_history(new_vol.name, team.name)
        self.assertEqual(len(hist), 1, "newly added member gets an active assignment")
        self.assertEqual(hist[0].role, "Team Member - Newbie")

    def test_removing_member_completes_history(self):
        """Removing a member from team_members completes (status=Completed, end_date
        set) the matching Active assignment via handle_team_member_changes."""
        _, leader_vol = self._make_volunteer()
        _, member_vol = self._make_volunteer()
        team = self._new_team()
        self._append_member(team, leader_vol, team_role="Team Leader", role="Chair")
        self._append_member(team, member_vol, team_role="Team Member", role="Helper")
        team.insert()
        self.track_doc("Team", team.name)
        self.assertEqual(len(self._active_history(member_vol.name, team.name)), 1)

        team.reload()
        team.team_members = [m for m in team.team_members if m.volunteer != member_vol.name]
        team.save()  # before_save snapshots _doc_before_save for change detection
        with self.assertNoErrorLog():
            team.handle_team_member_changes()

        self.assertEqual(
            len(self._active_history(member_vol.name, team.name)), 0, "active history closed after removal"
        )
        completed = self._completed_history(member_vol.name, team.name)
        self.assertEqual(len(completed), 1, "removal produces one Completed assignment")
        self.assertTrue(completed[0].end_date, "completed assignment has an end_date")

    def test_deactivating_member_completes_history(self):
        """Flipping a member to is_active=0 completes the active assignment (the
        was-active / now-inactive branch)."""
        _, leader_vol = self._make_volunteer()
        _, member_vol = self._make_volunteer()
        team = self._new_team()
        self._append_member(team, leader_vol, team_role="Team Leader", role="Chair")
        self._append_member(team, member_vol, team_role="Team Member", role="Helper")
        team.insert()
        self.track_doc("Team", team.name)

        team.reload()
        row = next(m for m in team.team_members if m.volunteer == member_vol.name)
        row.is_active = 0
        row.status = "Inactive"
        row.to_date = today()
        team.save()
        with self.assertNoErrorLog():
            team.handle_team_member_changes()

        self.assertEqual(len(self._active_history(member_vol.name, team.name)), 0)
        self.assertEqual(len(self._completed_history(member_vol.name, team.name)), 1)

    def test_reactivating_member_recreates_active_history(self):
        """Flipping an inactive member back to active recreates an Active assignment
        (the not-old-active / now-active branch)."""
        _, leader_vol = self._make_volunteer()
        _, member_vol = self._make_volunteer()
        team = self._new_team()
        self._append_member(team, leader_vol, team_role="Team Leader", role="Chair")
        self._append_member(team, member_vol, team_role="Team Member", role="Helper", is_active=0)
        team.insert()
        self.track_doc("Team", team.name)
        self.assertEqual(len(self._active_history(member_vol.name, team.name)), 0)

        team.reload()
        row = next(m for m in team.team_members if m.volunteer == member_vol.name)
        row.is_active = 1
        row.status = "Active"
        team.save()
        with self.assertNoErrorLog():
            team.handle_team_member_changes()

        self.assertEqual(
            len(self._active_history(member_vol.name, team.name)), 1, "reactivation creates active history"
        )

    def test_role_change_completes_old_and_starts_new(self):
        """Changing an active member's role completes the old assignment and starts a
        new one (the role_changed branch in handle_team_member_changes)."""
        _, leader_vol = self._make_volunteer()
        _, member_vol = self._make_volunteer()
        team = self._new_team()
        self._append_member(team, leader_vol, team_role="Team Leader", role="Chair")
        self._append_member(team, member_vol, team_role="Team Member", role="Helper")
        team.insert()
        self.track_doc("Team", team.name)

        team.reload()
        row = next(m for m in team.team_members if m.volunteer == member_vol.name)
        row.role = "Coordinator"  # role text change -> role_changed True
        team.save()
        with self.assertNoErrorLog():
            team.handle_team_member_changes()

        active = self._active_history(member_vol.name, team.name)
        completed = self._completed_history(member_vol.name, team.name)
        self.assertEqual(len(active), 1, "exactly one active assignment after role change")
        self.assertEqual(active[0].role, "Team Member - Coordinator", "new active reflects new role")
        self.assertGreaterEqual(len(completed), 1, "old assignment completed")
        self.assertTrue(
            any(c.role == "Team Member - Helper" for c in completed), "old role assignment was completed"
        )

    # -------------------------------------------------- _get_member_snapshot

    def test_get_member_snapshot_keys_and_values(self):
        """_get_member_snapshot builds a dict keyed by (volunteer, from_date) carrying
        role/team_role/role_type/is_active/volunteer_name."""
        _, leader_vol = self._make_volunteer()
        team = self._new_team()
        self._append_member(team, leader_vol, team_role="Team Leader", role="Chair")
        team.insert()
        self.track_doc("Team", team.name)
        team.reload()

        snap = team._get_member_snapshot()
        key = (leader_vol.name, str(today()))
        self.assertIn(key, snap, "snapshot keyed by (volunteer, from_date)")
        self.assertEqual(snap[key]["team_role"], "Team Leader")
        self.assertEqual(snap[key]["role"], "Chair")
        self.assertEqual(snap[key]["is_active"], 1)

    def test_get_member_snapshot_empty_for_no_members(self):
        team = self._new_team()
        team.insert()
        self.track_doc("Team", team.name)
        team.reload()
        self.assertEqual(team._get_member_snapshot(), {}, "no members -> empty snapshot")

    # ------------------------ _validate_assignment_history_consistency auto-fix

    def test_consistency_check_autofixes_missing_history(self):
        """When an active member has no Active assignment row,
        _validate_assignment_history_consistency recreates it automatically."""
        _, leader_vol = self._make_volunteer()
        team = self._new_team()
        self._append_member(team, leader_vol, team_role="Team Leader", role="Chair")
        team.insert()
        self.track_doc("Team", team.name)

        # Delete the auto-created history row to simulate the inconsistency.
        for row in self._active_history(leader_vol.name, team.name):
            vol = frappe.get_doc("Volunteer", leader_vol.name)
            vol.assignment_history = [a for a in vol.assignment_history if a.name != row.name]
            vol.save()
        self.assertEqual(len(self._active_history(leader_vol.name, team.name)), 0, "precondition: removed")

        team.reload()
        with self.assertNoErrorLog():
            team._validate_assignment_history_consistency()

        self.assertEqual(
            len(self._active_history(leader_vol.name, team.name)), 1, "consistency check recreated history"
        )

    # ------------------------------------------------- event emission via save

    def test_settings_change_save_runs_clean(self):
        """Changing a tracked settings field (team_type) on save triggers
        _detect_and_emit_settings_changes -> emit_team_settings_changed and persists."""
        _, leader_vol = self._make_volunteer()
        team = self._new_team(team_type="Committee")
        self._append_member(team, leader_vol, team_role="Team Leader", role="Chair")
        team.insert()
        self.track_doc("Team", team.name)

        team.reload()
        team.team_type = "Working Group"
        team.save()
        team.reload()
        self.assertEqual(team.team_type, "Working Group", "settings change persisted")

    def test_leadership_change_sets_team_lead(self):
        """Adding a user-bearing leader to a previously lead-less team changes team_lead
        between old_doc and new doc, exercising _detect_and_emit_leadership_changes."""
        _, member_vol = self._make_volunteer()
        team = self._new_team()
        self._append_member(team, member_vol, team_role="Team Member", role="Helper")
        team.insert()
        self.track_doc("Team", team.name)
        team.reload()
        self.assertFalse(team.team_lead)

        _, leader_vol = self._make_volunteer(with_user=True)
        expected_user = frappe.db.get_value(
            "Member", frappe.db.get_value("Volunteer", leader_vol.name, "member"), "user"
        )
        self._append_member(team, leader_vol, team_role="Team Leader", role="Chair")
        team.save()
        team.reload()
        self.assertEqual(team.team_lead, expected_user, "leadership change applied team_lead")

    def test_membership_added_and_removed_persist(self):
        """A save that both adds and removes a member exercises the added/removed
        branches of _detect_and_emit_membership_changes and persists the roster."""
        _, leader_vol = self._make_volunteer()
        _, member_vol = self._make_volunteer()
        team = self._new_team()
        self._append_member(team, leader_vol, team_role="Team Leader", role="Chair")
        self._append_member(team, member_vol, team_role="Team Member", role="Helper")
        team.insert()
        self.track_doc("Team", team.name)

        team.reload()
        team.team_members = [m for m in team.team_members if m.volunteer != member_vol.name]
        _, new_vol = self._make_volunteer()
        self._append_member(team, new_vol, team_role="Team Member", role="Fresh")
        team.save()
        team.reload()
        vols = {m.volunteer for m in team.team_members}
        self.assertIn(new_vol.name, vols, "added member present")
        self.assertNotIn(member_vol.name, vols, "removed member gone")

    # --------------------------------- get_team_permission_query_conditions

    def test_perm_conditions_admin_returns_empty(self):
        """System Manager / admin gets no restriction ('')."""
        with self.assertNoErrorLog():
            cond = get_team_permission_query_conditions("Administrator")
        self.assertEqual(cond, "", "admin sees all teams")

    def test_perm_conditions_user_without_member_blocked(self):
        """A user with no Member record is fully blocked."""
        user = self._make_user()
        with self.assertNoErrorLog():
            cond = get_team_permission_query_conditions(user)
        self.assertEqual(cond, "`tabTeam`.name = ''", "no member -> blocked")

    def test_perm_conditions_member_without_volunteer_blocked(self):
        """A user with a Member but no Volunteer is blocked."""
        user = self._make_user()
        member = self.create_test_member()
        frappe.db.set_value("Member", member.name, "user", user)
        with self.assertNoErrorLog():
            cond = get_team_permission_query_conditions(user)
        self.assertEqual(cond, "`tabTeam`.name = ''", "member without volunteer -> blocked")

    def test_perm_conditions_volunteer_without_team_blocked(self):
        """A volunteer not on any active team is blocked."""
        user = self._make_user()
        member = self.create_test_member()
        frappe.db.set_value("Member", member.name, "user", user)
        self.create_test_volunteer(member_name=member.name)
        with self.assertNoErrorLog():
            cond = get_team_permission_query_conditions(user)
        self.assertEqual(cond, "`tabTeam`.name = ''", "volunteer without team -> blocked")

    def test_perm_conditions_team_member_scoped_to_their_teams(self):
        """A volunteer who is an active member of a team gets a condition naming that
        team (the team_memberships branch)."""
        user = self._make_user()
        member = self.create_test_member()
        frappe.db.set_value("Member", member.name, "user", user)
        volunteer = self.create_test_volunteer(member_name=member.name)

        team = self._new_team()
        self._append_member(team, volunteer, team_role="Team Member", role="Helper")
        team.insert()
        self.track_doc("Team", team.name)

        with self.assertNoErrorLog():
            cond = get_team_permission_query_conditions(user)
        self.assertIn("`tabTeam`.name in (", cond, "scoped condition produced")
        self.assertIn(team.name, cond, "the user's team appears in the condition")
