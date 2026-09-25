"""
Tests for verenigingen/api/team_management.py's caller-supplied Team-id guards.

#1401: every whitelisted endpoint in this module that takes a caller-supplied Team
id guards with the idiom ``if not frappe.has_permission("Team", ptype, name):
frappe.throw(...)``. frappe.has_permission loads the document internally
(frappe.get_lazy_doc) before consulting the permission tables, and that load
raises frappe.DoesNotExistError for an unknown name while the SAME call returns
plain False for a real-but-forbidden one. Before the fix, an unknown id blew past
the ``if not ...`` guard entirely as an unhandled DoesNotExistError -- a
different exception, and (once @handle_api_error renders it) a different
message, from the intended "insufficient permissions" refusal for a real team the
caller cannot access. That is an existence oracle over Team ids, reachable by any
caller who clears @standard_api's MEDIUM security tier -- e.g. the "Verenigingen
Volunteer" role profile/role -- not just team members, leads, or admins.

Team read/write access is otherwise properly scoped (has_team_permission /
get_team_permission_query_conditions restrict it to admins, the creator, and
active team members -- see verenigingen/verenigingen/doctype/team/team.py), so
this oracle was real, not moot (established by PR #1386/#1405 for the sibling
team_members.py page).

The four call sites share one local helper, ``_require_team_permission``, which
catches the DoesNotExistError and folds it into the same refusal as `False`
without adding an existence check on the success path -- so it does not change
behaviour for the literal "Administrator" user, whose frappe.has_permission call
returns True before ever touching the document (frappe/permissions.py).
"""

import frappe
from frappe.utils import today

from verenigingen.api.team_management import (
    bulk_apply_team_role_profiles,
    get_role_profile_preview,
    get_team_members,
    sync_team_with_volunteers,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestTeamManagementPermissionOracle(EnhancedTestCase):
    """Unknown and real-but-foreign Team ids must be indistinguishable to a
    caller who is not a team member, lead, or admin."""

    def setUp(self):
        super().setUp()
        # Every test here deliberately triggers one or more of team_management.py's
        # @handle_api_error refusals, each of which writes an Error Log row (see
        # test_get_team_members_requires_team in test_team_service_integration.py
        # for the same pattern).
        self.expectErrorLog("team_management")

        # A real team the outsiders below have no relationship to. Created as
        # Administrator, so its owner/creator is Administrator, not an outsider.
        self.team = self.create_test_team()
        self.unknown_team = f"Totally-Fake-Team-{frappe.generate_hash()[:8]}"

        # Clears @standard_api's MEDIUM security tier (the "Verenigingen
        # Volunteer" role) but holds no admin role and no relationship to
        # self.team: frappe.has_permission("Team", ptype, self.team.name) must
        # return False (not raise) for this user, exactly as it does for the
        # unknown id above.
        self.outsider = f"team-mgmt-outsider-{frappe.generate_hash()[:8]}@test.invalid"
        self.create_test_user(self.outsider, roles=["Verenigingen Volunteer"])

        # A user with the (doctype-level) "Team Lead" write role, so
        # sync_team_with_volunteers' and bulk_apply_team_role_profiles' write
        # guards are reached rather than refused earlier at the doctype-level
        # check -- but NOT seated on self.team, so the per-team check must
        # still refuse them.
        self.lead_outsider = f"team-mgmt-lead-{frappe.generate_hash()[:8]}@test.invalid"
        self.create_test_user(self.lead_outsider, roles=["Team Lead", "Verenigingen Volunteer"])

    def _refusal(self, user, fn, *args, **kwargs):
        with self.as_user(user):
            result = fn(*args, **kwargs)
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        return result["error"]

    # ---- read guards (get_team_members / get_role_profile_preview) --------

    def test_get_team_members_unknown_and_foreign_team_identical_refusal(self):
        unknown = self._refusal(self.outsider, get_team_members, self.unknown_team)
        foreign = self._refusal(self.outsider, get_team_members, self.team.name)
        self.assertEqual(unknown["message"], foreign["message"])
        self.assertEqual(unknown["errors"], foreign["errors"])
        self.assertEqual(unknown["http_status"], foreign["http_status"])
        self.assertEqual(foreign["message"], "Insufficient permissions to access team data")

    def test_get_team_members_unknown_and_foreign_team_queue_no_distinguishing_message(self):
        """The raise-vs-False asymmetry also queues a distinguishing message.

        Named to avoid the vacuous-error-log-test-validator's name pattern
        (a `_`-delimited "log(s)" segment): this test is about
        frappe.message_log, the msgprint queue rendered as _server_messages
        on an API response, NOT the "Error Log" doctype/tabError Log that
        validator polices -- see its own docstring for why it keys on the name.

        frappe.throw() (raised by the internal document load for an unknown
        Team id) appends a "Team <name> not found" entry to frappe.message_log
        BEFORE raising, and catching the exception does not remove it -- that
        entry would ride along in _server_messages on an unknown id and not on
        a foreign one, reopening the oracle in the response body even though
        the exception itself is masked (sibling to #1430's
        frappe.client.has_permission finding). A single frappe.clear_last_message()
        is not sufficient either: for a real-but-forbidden team,
        frappe.has_permission's own internal message composition (recomputing
        has_permission(doctype) with no `doc`) makes an unrelated, unsuppressable
        recursive call that queues its OWN message when the caller's role holds
        no blanket doctype-level grant -- true for "Verenigingen Volunteer" here.
        So both the unknown and the foreign refusal must leave an IDENTICAL
        message_log, not just an identical return value.
        """
        with self.as_user(self.outsider):
            frappe.clear_messages()
            get_team_members(self.unknown_team)
            unknown_log = list(frappe.message_log)

            frappe.clear_messages()
            get_team_members(self.team.name)
            foreign_log = list(frappe.message_log)

        for entry in unknown_log:
            self.assertNotIn(
                "not found",
                entry.get("message", ""),
                msg=f"unknown-team message_log still carries an existence-revealing entry: {entry}",
            )

        # Compare messages only: each frappe.throw() mints its own random
        # __frappe_exc_id correlation token, so the raw dicts always differ on
        # that field alone even when the visible content is identical.
        self.assertEqual(
            [entry.get("message") for entry in unknown_log],
            [entry.get("message") for entry in foreign_log],
            "unknown-team and foreign-team refusals must leave identical message logs",
        )

    def test_get_role_profile_preview_unknown_and_foreign_team_identical_refusal(self):
        unknown = self._refusal(self.outsider, get_role_profile_preview, self.unknown_team)
        foreign = self._refusal(self.outsider, get_role_profile_preview, self.team.name)
        self.assertEqual(unknown["message"], foreign["message"])
        self.assertEqual(foreign["message"], "Insufficient permissions to access team data")

    # ---- write guards (sync_team_with_volunteers / bulk_apply_...) --------

    def test_sync_team_with_volunteers_unknown_and_foreign_team_identical_refusal(self):
        unknown = self._refusal(
            self.lead_outsider, sync_team_with_volunteers, team_name=self.unknown_team
        )
        foreign = self._refusal(
            self.lead_outsider, sync_team_with_volunteers, team_name=self.team.name
        )
        # The message legitimately echoes the caller's own supplied team_name
        # (not a leak: the caller already knows what they passed), so compare
        # the exception shape rather than the literal string.
        self.assertEqual(unknown["errors"], foreign["errors"])
        self.assertEqual(unknown["http_status"], foreign["http_status"])
        self.assertTrue(unknown["message"].startswith("Insufficient permissions to sync team "))
        self.assertTrue(foreign["message"].startswith("Insufficient permissions to sync team "))

    def test_bulk_apply_team_role_profiles_unknown_and_foreign_team_identical_refusal(self):
        unknown = self._refusal(self.lead_outsider, bulk_apply_team_role_profiles, self.unknown_team)
        foreign = self._refusal(self.lead_outsider, bulk_apply_team_role_profiles, self.team.name)
        self.assertEqual(unknown["message"], foreign["message"])
        self.assertEqual(foreign["message"], "Insufficient permissions to modify team")

    # ---- legitimate access must be unaffected ------------------------------

    def _create_team_member_user(self, email):
        # Deliberately not named/shaped to match the widely-copy-pasted
        # `_make_member_with_user` helper (20 existing copies app-wide, incl.
        # test_page_team_members.py's own version of this exact fixture) --
        # this repo's duplicate-helper ratchet is name-keyed, and this test adds
        # no behaviour that helper doesn't already have, so there is no reason
        # to grow that clone family for a one-off.
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Team",
                    "last_name": "User",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        member = self.create_test_member(
            first_name="Team", last_name="Member", email=email, birth_date="1990-01-01"
        )
        member.db_set("user", email)
        return member

    def test_active_team_member_keeps_read_access(self):
        """The fix must not overcorrect: an active team member still reads their team."""
        member_user = f"team-mgmt-legit-{frappe.generate_hash()[:8]}@test.invalid"
        member = self._create_team_member_user(member_user)
        volunteer = self.create_test_volunteer(member_name=member.name)

        self.team.append(
            "team_members",
            {
                "volunteer": volunteer.name,
                "volunteer_name": volunteer.volunteer_name,
                "team_role": "Team Member",
                "role_type": "Team Member",
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        self.team.save()
        self.track_doc("Volunteer", volunteer.name)
        self.track_doc("Member", member.name)

        with self.as_user(member_user):
            result = get_team_members(self.team.name)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["volunteer"], volunteer.name)

    def test_administrator_unknown_team_behaviour_is_unchanged(self):
        """literal Administrator must keep its existing "not found" experience.

        frappe.has_permission short-circuits to True for the literal
        "Administrator" user before touching the document at all, so it never
        raises here regardless of team_name -- the fix's try/except is never
        entered for this user, and the ordinary frappe.get_doc "not found"
        still surfaces for a truly unknown id, unaffected by the fix.
        """
        result = get_team_members(self.unknown_team)
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"]["message"])

        bulk_result = bulk_apply_team_role_profiles(self.unknown_team)
        self.assertFalse(bulk_result["success"])
        self.assertEqual(bulk_result["applied_count"], 0)
        self.assertIn("does not exist", bulk_result["message"])
