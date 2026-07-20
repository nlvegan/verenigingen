"""
Integration coverage for the team event chain.

Exercises:
  * ``verenigingen/events/team_events.py`` — emit_* helpers + the per-event
    subscriber registry + dispatch through ``event_emitter.emit_event``.
  * ``verenigingen/events/subscribers/team_subscribers.py`` — the background
    job handlers (assignment history, notifications, cache, permissions).

Every ``handle_*`` subscriber wraps its body in a bare ``try/except`` +
``frappe.log_error`` and swallows. A naive "did not raise" smoke test cannot
fail even when the product is broken, so two hardening techniques are used:

1. ``self.assertNoErrorLog()`` (from ErrorLogGuardMixin) around the happy path:
   ``frappe.log_error`` commits independently of the test transaction, so a
   swallowed exception flips a silent green pass into a real failure.

2. Real side-effect assertions — Volunteer Assignment history rows, cache
   keys, User Permission rows — not just "the handler returned".

The EmailService factory is the only boundary mocked (never product logic);
mocking it also bypasses the test-site "email disabled" short-circuit so the
handler's reaching of the send boundary is observable.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.events import team_events as te
from verenigingen.events.subscribers import team_subscribers as ts
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

EMAIL_FACTORY = "verenigingen.services.communication.email_service.get_email_service"


class TestTeamEventsCoverage(EnhancedTestCase):
    """Real integration coverage for team_events + team_subscribers."""

    # ------------------------------------------------------------------ helpers
    @contextmanager
    def _patch_email_service(self):
        service = MagicMock(name="EmailService")
        with patch(EMAIL_FACTORY, return_value=service):
            yield service

    @staticmethod
    def _send_kwargs(mock_service):
        return mock_service.send_templated_email.call_args.kwargs

    def _make_member_with_email(self, prefix="team"):
        member = self.create_test_member(first_name="TeamSub", last_name="Member", birth_date="1990-01-01")
        email = f"{prefix}.{frappe.generate_hash(length=8)}@example.invalid"
        member.db_set("email", email, update_modified=False)
        member.reload()
        return member, email

    def _make_volunteer(self, member):
        return self.create_test_volunteer(member_name=member.name)

    def _make_user(self, prefix="lead"):
        """Create a real, tracked User account (factory helper)."""
        email = f"{prefix}.user.{frappe.generate_hash(length=8)}@example.invalid"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": prefix.title(),
                "last_name": "User",
                "send_welcome_email": 0,
                "enabled": 1,
            }
        )
        user.insert(ignore_permissions=True)
        self._track_test_document("User", user.name, priority=2)
        return user

    def _make_team_with_member(self, volunteer, team_role_name="Team Member", from_date=None):
        """Create a Team with one active team member; return (team_doc, from_date)."""
        team = self.create_test_team()
        from_date = from_date or frappe.utils.today()
        self.factory.create_team_member(
            team.name, volunteer.name, team_role_name=team_role_name, from_date=from_date
        )
        team.reload()
        return team, from_date

    def _make_team_member_role(self, team_name, team_role_name):
        """Set the first team member's team_role (factory/setup helper)."""
        team_doc = frappe.get_doc("Team", team_name)
        team_doc.team_members[0].team_role = team_role_name
        team_doc.save(ignore_permissions=True)
        return team_doc

    def _active_team_assignments(self, volunteer_name, team_name):
        """Active Volunteer Assignment rows for (volunteer, team)."""
        return frappe.get_all(
            "Volunteer Assignment",
            filters={
                "parent": volunteer_name,
                "parenttype": "Volunteer",
                "reference_doctype": "Team",
                "reference_name": team_name,
                "status": "Active",
            },
            fields=["name", "role", "start_date", "end_date", "status"],
        )

    def _completed_team_assignments(self, volunteer_name, team_name):
        return frappe.get_all(
            "Volunteer Assignment",
            filters={
                "parent": volunteer_name,
                "parenttype": "Volunteer",
                "reference_doctype": "Team",
                "reference_name": team_name,
                "status": "Completed",
            },
            fields=["name", "role", "start_date", "end_date", "status"],
        )

    # ============================================================ emitters
    def test_get_team_event_subscribers_registry(self):
        """The registry must map each event to importable handler functions."""
        import importlib

        for event in (
            "team_membership_changed",
            "team_settings_changed",
            "team_leadership_changed",
        ):
            subs = te._get_team_event_subscribers(event)
            self.assertTrue(subs, f"no subscribers registered for {event}")
            for dotted in subs:
                module_path, func = dotted.rsplit(".", 1)
                mod = importlib.import_module(module_path)
                self.assertTrue(
                    callable(getattr(mod, func, None)),
                    f"registry points at missing/non-callable {dotted}",
                )

    def test_get_team_event_subscribers_unknown_event(self):
        self.assertEqual(te._get_team_event_subscribers("does_not_exist"), [])

    def test_emit_membership_changed_dispatches_to_subscriber_synchronously(self):
        """End-to-end: emit_team_membership_changed -> emit_event -> real handler
        runs inline and writes the Active assignment history row.

        ``run_events_synchronously`` makes emit_event call the subscriber inline
        (see event_emitter.emit_event) so the side effect is observable without
        a worker.
        """
        member, _ = self._make_member_with_email("emit-add")
        volunteer = self._make_volunteer(member)
        team, from_date = self._make_team_with_member(volunteer)

        # No assignment rows yet for this freshly built team member path.
        # (create_team_member appends the row but does not run the event handler.)
        saved = getattr(frappe.flags, "run_events_synchronously", None)
        frappe.flags.run_events_synchronously = True
        try:
            with self.assertNoErrorLog():
                te.emit_team_membership_changed(
                    team.name,
                    {
                        "volunteer": volunteer.name,
                        "action": "added",
                        "role": "Team Member",
                        "from_date": from_date,
                    },
                )
        finally:
            frappe.flags.run_events_synchronously = saved

        active = self._active_team_assignments(volunteer.name, team.name)
        self.assertEqual(len(active), 1, "membership_changed/added must create one Active assignment")

    def test_emit_membership_changed_emitter_swallows_dispatch_failure(self):
        """The emitter's own try/except must not propagate (logs instead).

        Force the internal dispatch to raise and assert the emitter logs an
        error rather than bubbling — this is the emitter's documented contract.
        """
        self.expectErrorLog("Team Event Emission Error")
        before = frappe.db.count("Error Log")
        with patch.object(te, "_emit_team_event", side_effect=RuntimeError("boom")):
            # Must NOT raise.
            te.emit_team_membership_changed("Nonexistent-Team", {"volunteer": "x", "action": "added"})
        self.assertGreater(
            frappe.db.count("Error Log"), before, "emitter should log the swallowed dispatch failure"
        )

    # ===================================== bulk-operation guard (parity with member/chapter)
    def test_team_emitters_skipped_during_bulk_import(self):
        """Bulk team operations must not flood the event bus.

        member_events/chapter_events both short-circuit their emit_* wrappers
        under in_bulk_import / bulk_*_operations so a bulk load doesn't queue a
        large after-commit closure set. team_events lacked this guard; assert it
        now has parity by confirming dispatch is skipped entirely.
        """
        saved = getattr(frappe.flags, "in_bulk_import", False)
        frappe.flags.in_bulk_import = True
        try:
            with patch.object(te, "_emit_team_event") as mock_emit:
                te.emit_team_membership_changed("T-1", {"volunteer": "V-1", "action": "added"})
                te.emit_team_settings_changed("T-1", {"foo": "bar"})
                te.emit_team_leadership_changed("T-1", {"new_lead": "V-2"})
            mock_emit.assert_not_called()
        finally:
            frappe.flags.in_bulk_import = saved

    def test_team_dispatch_forwards_bulk_flag_to_emitter(self):
        """team dispatch forwards a bulk_flag so subscribers receive is_bulk_import
        (parity with member_events/chapter_events)."""
        captured = {}
        import verenigingen.events.event_emitter as ee

        def fake_emit(event_name, event_data, subscribers, **kw):
            captured.update(kw)

        ee.emit_event, saved = fake_emit, ee.emit_event
        try:
            te.emit_team_membership_changed("T-1", {"volunteer": "V-1", "action": "added"})
        finally:
            ee.emit_event = saved
        self.assertEqual(captured.get("bulk_flag"), "bulk_team_operations")
        self.assertEqual(captured.get("entity_key"), "team")
        self.assertEqual(captured.get("job_prefix"), "team")

    # ===================================== handle_assignment_history_updates
    def test_assignment_history_added_creates_active_row(self):
        member, _ = self._make_member_with_email("hist-add")
        volunteer = self._make_volunteer(member)
        team, from_date = self._make_team_with_member(volunteer)

        with self.assertNoErrorLog():
            ts.handle_assignment_history_updates(
                "team_membership_changed",
                {
                    "team": team.name,
                    "volunteer": volunteer.name,
                    "action": "added",
                    "role": "Team Member",
                    "from_date": from_date,
                },
            )
        active = self._active_team_assignments(volunteer.name, team.name)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].status, "Active")

    def test_assignment_history_removed_completes_row(self):
        member, _ = self._make_member_with_email("hist-rm")
        volunteer = self._make_volunteer(member)
        team, from_date = self._make_team_with_member(volunteer)

        # First add the Active row.
        with self.assertNoErrorLog():
            ts.handle_assignment_history_updates(
                "team_membership_changed",
                {
                    "team": team.name,
                    "volunteer": volunteer.name,
                    "action": "added",
                    "role": "Team Member",
                    "from_date": from_date,
                },
            )
        self.assertEqual(len(self._active_team_assignments(volunteer.name, team.name)), 1)

        # Now remove it -> the Active row becomes Completed with an end_date.
        end_date = frappe.utils.today()
        with self.assertNoErrorLog():
            ts.handle_assignment_history_updates(
                "team_membership_changed",
                {
                    "team": team.name,
                    "volunteer": volunteer.name,
                    "action": "removed",
                    "old_role": "Team Member",
                    "from_date": from_date,
                    "to_date": end_date,
                },
            )
        self.assertEqual(
            len(self._active_team_assignments(volunteer.name, team.name)),
            0,
            "removed action must leave no Active assignment",
        )
        completed = self._completed_team_assignments(volunteer.name, team.name)
        self.assertEqual(len(completed), 1)
        self.assertEqual(str(completed[0].end_date), str(end_date))

    def test_assignment_history_role_changed_completes_old_and_adds_new(self):
        """role_changed completes the previously-stored role and re-adds the
        team member's CURRENT role.

        NOTE: the stored role is derived from the Team Member row's ``team_role``
        field, not from the event_data ``role``/``old_role`` (see
        test_assignment_history_role_arg_is_ignored). To exercise the
        complete-old + add-new branches with two distinct roles, seed an Active
        "Coordinator" row via the AssignmentHistoryManager directly, then flip
        the team member's role to a new Team Role before firing role_changed.
        """
        coordinator_role = self.factory.ensure_team_role("Coordinator").name
        member, _ = self._make_member_with_email("hist-role")
        volunteer = self._make_volunteer(member)
        team, from_date = self._make_team_with_member(volunteer, team_role_name=coordinator_role)

        # Seed an Active "Coordinator" assignment row directly (role label =
        # the Team Role's role_name) to stand in for the prior role.
        from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

        coord_label = frappe.db.get_value("Team Role", coordinator_role, "role_name")
        AssignmentHistoryManager.add_assignment_history(
            volunteer_id=volunteer.name,
            assignment_type="Team",
            reference_doctype="Team",
            reference_name=team.name,
            role=coord_label,
            start_date=from_date,
        )
        self.assertEqual(len(self._active_team_assignments(volunteer.name, team.name)), 1)

        # Flip the team member to a different Team Role so the new role differs.
        new_role = self.factory.ensure_team_role("Team Member").name
        new_label = frappe.db.get_value("Team Role", new_role, "role_name")
        self._make_team_member_role(team.name, new_role)

        with self.assertNoErrorLog():
            ts.handle_assignment_history_updates(
                "team_membership_changed",
                {
                    "team": team.name,
                    "volunteer": volunteer.name,
                    "action": "role_changed",
                    "old_role": coord_label,
                    "role": new_label,
                    "from_date": from_date,
                },
            )

        completed_roles = {c.role for c in self._completed_team_assignments(volunteer.name, team.name)}
        active_roles = {a.role for a in self._active_team_assignments(volunteer.name, team.name)}
        self.assertIn(coord_label, completed_roles, "prior role should be completed")
        self.assertIn(new_label, active_roles, f"new role should be Active; saw active={active_roles}")

    def test_assignment_history_role_arg_is_ignored(self):
        """Characterization: the event_data ``role`` does NOT determine the stored
        role for an 'added' action.

        ``Team.add_team_assignment_history(volunteer_id, team_role, start_date)``
        ignores its ``team_role`` argument — ``TeamService.add_assignment_history``
        looks the team member up by (volunteer, from_date) and derives the role
        description from the Team Member row's ``team_role`` field. So passing a
        bogus ``role`` in the event still records the team-row role, not the
        event role. Documents a real (latent) semantic foot-gun, not a crash.
        """
        member, _ = self._make_member_with_email("hist-ignore")
        volunteer = self._make_volunteer(member)
        team, from_date = self._make_team_with_member(volunteer, team_role_name="Team Member")
        team_label = frappe.db.get_value(
            "Team Role", frappe.get_doc("Team", team.name).team_members[0].team_role, "role_name"
        )

        with self.assertNoErrorLog():
            ts.handle_assignment_history_updates(
                "team_membership_changed",
                {
                    "team": team.name,
                    "volunteer": volunteer.name,
                    "action": "added",
                    "role": "TOTALLY-BOGUS-ROLE",  # ignored by the product
                    "from_date": from_date,
                },
            )
        active = self._active_team_assignments(volunteer.name, team.name)
        self.assertEqual(len(active), 1)
        self.assertEqual(
            active[0].role,
            team_label,
            "stored role is derived from the Team Member row, not the event 'role'",
        )

    def test_assignment_history_missing_keys_noops_without_error(self):
        """Missing team/volunteer must warn-and-return, not log an Error Log row."""
        with self.assertNoErrorLog():
            ts.handle_assignment_history_updates("e", {})
            ts.handle_assignment_history_updates("e", {"team": "X"})
            ts.handle_assignment_history_updates("e", {"volunteer": "V"})

    def test_assignment_history_nonexistent_team_noops_without_error(self):
        """A deleted/uncommitted Team is a benign race -> clean no-op, no Error Log.

        Background-job handlers can fire after the Team they reference was rolled
        back or deleted (or before its insert committed). The handler now guards
        with subscriber_utils.get_doc_if_exists (matching member/chapter
        subscribers), so the moot update returns quietly instead of polluting the
        Error Log — which previously leaked across test boundaries as a flaky
        assertNoErrorLog failure in unrelated tests.
        """
        before = frappe.db.count("Error Log")
        # Must NOT raise and must NOT log — graceful no-op for a missing Team.
        with self.assertNoErrorLog():
            ts.handle_assignment_history_updates(
                "e",
                {"team": "Team-does-not-exist-xyz", "volunteer": "Vol-x", "action": "added"},
            )
        self.assertEqual(
            frappe.db.count("Error Log"),
            before,
            "non-existent team should be a clean no-op (get_doc_if_exists guard)",
        )

    # ===================================== handle_membership_notifications
    def test_membership_notification_added_reaches_send_boundary(self):
        member, email = self._make_member_with_email("notify-add")
        volunteer = self._make_volunteer(member)
        team, _ = self._make_team_with_member(volunteer)

        with self._patch_email_service() as svc:
            with self.assertNoErrorLog():
                ts.handle_membership_notifications(
                    "team_membership_changed",
                    {
                        "team": team.name,
                        "volunteer": volunteer.name,
                        "action": "added",
                        "role": "Team Member",
                    },
                )
            svc.send_templated_email.assert_called_once()
            kwargs = self._send_kwargs(svc)
            self.assertEqual(kwargs.get("notification_key"), "team_member_added")
            self.assertEqual(kwargs.get("recipients"), [email])

    def test_membership_notification_removed_reaches_send_boundary(self):
        member, email = self._make_member_with_email("notify-rm")
        volunteer = self._make_volunteer(member)
        team, _ = self._make_team_with_member(volunteer)

        with self._patch_email_service() as svc:
            with self.assertNoErrorLog():
                ts.handle_membership_notifications(
                    "team_membership_changed",
                    {
                        "team": team.name,
                        "volunteer": volunteer.name,
                        "action": "removed",
                        "role": "Team Member",
                    },
                )
            svc.send_templated_email.assert_called_once()
            self.assertEqual(self._send_kwargs(svc).get("notification_key"), "team_member_removed")

    def test_membership_notification_role_changed_reaches_send_boundary(self):
        member, email = self._make_member_with_email("notify-role")
        volunteer = self._make_volunteer(member)
        team, _ = self._make_team_with_member(volunteer)

        with self._patch_email_service() as svc:
            with self.assertNoErrorLog():
                ts.handle_membership_notifications(
                    "team_membership_changed",
                    {
                        "team": team.name,
                        "volunteer": volunteer.name,
                        "action": "role_changed",
                        "role": "Coordinator",
                        "old_role": "Team Member",
                    },
                )
            svc.send_templated_email.assert_called_once()
            kwargs = self._send_kwargs(svc)
            self.assertEqual(kwargs.get("notification_key"), "team_role_changed")
            self.assertIn("Team Member", kwargs.get("context", {}).get("additional_message", ""))
            self.assertIn("Coordinator", kwargs.get("context", {}).get("additional_message", ""))

    def test_membership_notification_missing_keys_noops(self):
        with self._patch_email_service() as svc:
            with self.assertNoErrorLog():
                ts.handle_membership_notifications("e", {})
                ts.handle_membership_notifications("e", {"team": "X"})
            svc.send_templated_email.assert_not_called()

    def test_membership_notification_no_member_email_noop(self):
        """Volunteer's member without an email: no send, no error."""
        member = self.create_test_member(first_name="NoEmail", last_name="Team", birth_date="1990-01-01")
        member.db_set("email", None, update_modified=False)
        member.reload()
        volunteer = self._make_volunteer(member)
        team, _ = self._make_team_with_member(volunteer)
        with self._patch_email_service() as svc:
            with self.assertNoErrorLog():
                ts.handle_membership_notifications(
                    "e",
                    {"team": team.name, "volunteer": volunteer.name, "action": "added", "role": "X"},
                )
            svc.send_templated_email.assert_not_called()

    # ===================================== handle_settings_notifications
    def test_settings_notification_important_field_reaches_send_boundary(self):
        member, email = self._make_member_with_email("settings")
        volunteer = self._make_volunteer(member)
        team, _ = self._make_team_with_member(volunteer)

        with self._patch_email_service() as svc:
            with self.assertNoErrorLog():
                ts.handle_settings_notifications(
                    "team_settings_changed",
                    {"team": team.name, "changed_fields": ["is_active"]},
                )
            svc.send_templated_email.assert_called_once()
            kwargs = self._send_kwargs(svc)
            self.assertEqual(kwargs.get("notification_key"), "team_settings_changed")
            self.assertEqual(kwargs.get("recipients"), [email])

    def test_settings_notification_unimportant_field_noop(self):
        member, _ = self._make_member_with_email("settings-noop")
        volunteer = self._make_volunteer(member)
        team, _ = self._make_team_with_member(volunteer)
        with self._patch_email_service() as svc:
            with self.assertNoErrorLog():
                ts.handle_settings_notifications(
                    "team_settings_changed",
                    {"team": team.name, "changed_fields": ["some_random_field"]},
                )
            svc.send_templated_email.assert_not_called()

    def test_settings_notification_missing_data_noop(self):
        with self._patch_email_service() as svc:
            with self.assertNoErrorLog():
                ts.handle_settings_notifications("e", {})
                ts.handle_settings_notifications("e", {"team": "X"})  # no changed_fields
                ts.handle_settings_notifications("e", {"team": "X", "changed_fields": []})
            svc.send_templated_email.assert_not_called()

    # ===================================== handle_permissions_updates
    def test_permissions_update_role_field_runs(self):
        """A role-related changed field iterates active members without error."""
        member, _ = self._make_member_with_email("perm")
        volunteer = self._make_volunteer(member)
        team, _ = self._make_team_with_member(volunteer)
        with self.assertNoErrorLog():
            ts.handle_permissions_updates(
                "team_settings_changed",
                {"team": team.name, "changed_fields": ["enable_role_profiles"]},
            )

    def test_permissions_update_missing_team_noop(self):
        with self.assertNoErrorLog():
            ts.handle_permissions_updates("e", {})

    # ===================================== handle_cache_invalidation
    def test_cache_invalidation_clears_statistics_key(self):
        team = self.create_test_team()
        frappe.cache().set_value("team_statistics", {"x": 1})
        with self.assertNoErrorLog():
            ts.handle_cache_invalidation("team_settings_changed", {"team": team.name})
        self.assertIsNone(frappe.cache().get_value("team_statistics"))

    def test_cache_invalidation_missing_team_noop(self):
        with self.assertNoErrorLog():
            ts.handle_cache_invalidation("e", {})

    # ===================================== handle_leadership_notifications
    def test_leadership_notification_runs_with_real_team(self):
        member, email = self._make_member_with_email("lead")
        volunteer = self._make_volunteer(member)
        team, _ = self._make_team_with_member(volunteer)

        with self._patch_email_service() as svc:
            with self.assertNoErrorLog():
                ts.handle_leadership_notifications(
                    "team_leadership_changed",
                    {"team": team.name, "old_lead": None, "new_lead": None},
                )
            # One active team member with an email -> one notification sent.
            svc.send_templated_email.assert_called_once()
            self.assertEqual(self._send_kwargs(svc).get("notification_key"), "team_leadership_changed")

    def test_leadership_notification_missing_team_noop(self):
        with self.assertNoErrorLog():
            ts.handle_leadership_notifications("e", {})

    # ===================================== handle_team_lead_permissions
    def test_team_lead_permissions_grants_user_permission(self):
        """A real new_lead User gets a User Permission row for the Team."""
        member, _ = self._make_member_with_email("teamlead")
        user = self._make_user("teamlead")
        team = self.create_test_team()

        self.assertFalse(
            frappe.db.exists("User Permission", {"user": user.name, "allow": "Team", "for_value": team.name})
        )
        with self.assertNoErrorLog():
            ts.handle_team_lead_permissions(
                "team_leadership_changed",
                {"team": team.name, "new_lead": user.name},
            )
        self.assertTrue(
            frappe.db.exists("User Permission", {"user": user.name, "allow": "Team", "for_value": team.name}),
            "team lead should have a User Permission for the team",
        )

    def test_team_lead_permissions_missing_lead_noop(self):
        team = self.create_test_team()
        with self.assertNoErrorLog():
            ts.handle_team_lead_permissions("e", {"team": team.name})  # no new_lead
            ts.handle_team_lead_permissions("e", {"new_lead": "x@example.invalid"})  # no team
