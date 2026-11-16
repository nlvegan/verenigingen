"""#2669: _sync_team_lead_role must not swallow 1213/1205 (#1888 sibling).

``Team.on_update -> on_team_lead_change`` runs ``auto_sync_on_role_change`` (which re-raises lock
errors since #1888) and then ``_sync_team_lead_role``, whose own ``except Exception`` + log_error
used to eat a deadlock/lock-wait timeout, so the Team save carried on after MariaDB had already
rolled the transaction back (1213) or left it half-applied (1205). Any other error keeps the
log-and-continue contract.

The lock errors are injected, not provoked (a real deadlock needs a second connection). The
injection is placed INSIDE _sync_team_lead_role (the Team Lead row being saved on the User, the
direct Has Role insert, the Has Role delete), and each test asserts from the traceback that the
error escaped from that function, so a neighbour re-raising cannot make it pass.
"""

import traceback
from unittest.mock import patch

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils import user_role_grant
from verenigingen.utils.team_role_profile_hooks import _sync_team_lead_role

ACR_AUTO_SYNC = "verenigingen.utils.user_role_profile_calculator.auto_sync_on_role_change"
USER_SAVE = "frappe.core.doctype.user.user.User.save"
ROLE_SYNC_TITLE = "Team Lead Role Sync"
LOCK_ERRORS = (frappe.QueryDeadlockError, frappe.QueryTimeoutError)


class TestTeamLeadRoleSyncLockErrors2669(VereningingenTestCase):
    def _leader_team(self):
        """A saved Team plus a pending (unsaved) Team Leader row for a user-bearing volunteer."""
        member = self.create_test_member(
            first_name="LeadErr",
            last_name="Sync",
            email=f"leaderr.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        user = self.create_test_user(member.email)
        self.track_doc("User", user.name)
        member.db_set("user", user.name, update_modified=False)
        volunteer = self.create_test_volunteer(member=member.name)
        suffix = frappe.generate_hash(length=6)
        role = frappe.get_doc(
            {
                "doctype": "Team Role",
                "role_name": f"LeadErr Leader {suffix}",
                "permissions_level": "Basic",
                "is_team_leader": 1,
                "is_unique": 0,
                "is_active": 1,
            }
        ).insert()
        self.track_doc("Team Role", role.name)
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"LeadErr Team {suffix}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today(),
                "description": "#2669",
            }
        ).insert()
        self.track_doc("Team", team.name)
        row = {
            "volunteer": volunteer.name,
            "team_role": role.name,
            "from_date": frappe.utils.today(),
            "is_active": 1,
            "status": "Active",
        }
        return team, user.name, row

    def _has_team_lead_role(self, user):
        return bool(frappe.db.exists("Has Role", {"parent": user, "role": "Team Lead"}))

    def _raising_on_team_lead_row(self, error):
        """User.save that raises only when it is persisting the freshly appended Team Lead row.

        The earlier saves of the same user (auto_sync_on_role_change) carry no such row, so the
        injection lands inside _sync_team_lead_role and nowhere above it.
        """
        real_save = frappe.get_doc("User", "Administrator").__class__.save

        def save(doc, *args, **kwargs):
            if doc.doctype == "User" and any(r.role == "Team Lead" and not r.name for r in doc.roles):
                raise error("injected in _sync_team_lead_role")
            return real_save(doc, *args, **kwargs)

        return patch(USER_SAVE, save)

    def _save_expecting(self, team, error):
        """Save and return the frame names of the escaping error, asserting it came out of
        _sync_team_lead_role. assertRaises strips ``__traceback__``, hence the manual catch."""
        try:
            team.save()
        except error as exc:
            frames = [f.name for f in traceback.extract_tb(exc.__traceback__)]
            self.assertIn("_sync_team_lead_role", frames, frames)
            return
        self.fail(f"{error.__name__} did not escape the Team save")

    # --------------------------------------------------- user_doc.save() inside the sync

    def test_team_save_aborts_when_the_team_lead_role_save_hits_a_lock_error(self):
        for error in LOCK_ERRORS:
            with self.subTest(error=error.__name__):
                team, user, row = self._leader_team()
                team.append("team_members", row)
                with self._raising_on_team_lead_row(error):
                    self._save_expecting(team, error)

    # ------------------------------------------ ensure_role_survives_profile_resync inside it

    def test_team_save_aborts_when_the_has_role_fallback_hits_a_lock_error(self):
        for error in LOCK_ERRORS:
            with self.subTest(error=error.__name__):
                team, user, row = self._leader_team()
                team.append("team_members", row)
                with patch.object(
                    user_role_grant, "ensure_role_survives_profile_resync", side_effect=error("injected")
                ):
                    self._save_expecting(team, error)

    # --------------------------------------------------------- the role-removal branch

    def test_removing_the_team_lead_role_propagates_a_lock_error(self):
        """The elif branch: the user no longer leads any Team but still holds the role.

        PROBE SHORTCUT: with the real flow, ``auto_sync_on_role_change`` (run just before the
        sync) re-derives the user's roles and already strips Team Lead, so the branch sees no
        role to delete (measured: has_role is None at that point). ``auto_sync_on_role_change``
        is therefore stubbed to a no-op to stand in for a user whose profile sync leaves the
        role alone; the claim here is only about _sync_team_lead_role's own handler.
        """
        team, user, row = self._leader_team()
        team.append("team_members", row)
        team.save()
        self.assertEqual(frappe.db.get_value("Team", team.name, "team_lead"), user)
        self.assertTrue(self._has_team_lead_role(user))
        team = frappe.get_doc("Team", team.name)
        team.team_members[0].is_active = 0
        team.team_members[0].status = "Inactive"
        with patch(ACR_AUTO_SYNC), patch.object(
            frappe, "delete_doc", side_effect=frappe.QueryDeadlockError("injected")
        ):
            self._save_expecting(team, frappe.QueryDeadlockError)

    # ------------------------------------------------------------------- controls

    def test_ordinary_error_in_the_sync_is_still_logged_and_the_save_completes(self):
        team, user, row = self._leader_team()
        team.append("team_members", row)
        self.expectErrorLog(ROLE_SYNC_TITLE)
        with self.assertErrorLog(ROLE_SYNC_TITLE):
            with patch.object(
                user_role_grant, "ensure_role_survives_profile_resync", side_effect=ValueError("boom")
            ):
                team.save()
        self.assertEqual(frappe.db.get_value("Team", team.name, "team_lead"), user)

    def test_unpatched_team_save_still_grants_the_team_lead_role(self):
        """Control for the injection: the real flow reaches the grant, so the tests above
        injected on a path that is actually exercised."""
        team, user, row = self._leader_team()
        team.append("team_members", row)
        team.save()
        self.assertTrue(self._has_team_lead_role(user))

    def test_direct_call_reraises_a_lock_error(self):
        with patch.object(frappe.db, "exists", side_effect=frappe.QueryTimeoutError("injected")):
            with self.assertRaises(frappe.QueryTimeoutError):
                _sync_team_lead_role("nobody@test.invalid")
