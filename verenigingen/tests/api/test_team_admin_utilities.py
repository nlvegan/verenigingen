"""
Meaningful integration tests for verenigingen/api/team_admin_utilities.py

Covers the three whitelisted admin utilities:
  - fix_all_missing_assignment_history()
  - fix_missing_assignment_history(team_name, volunteer_name)
  - debug_team_assignments()

RETURN SHAPE
------------
These endpoints are decorated:

    @frappe.whitelist()
    @critical_api(operation_type=...)   # serialises OperationResult.to_dict, passes dicts through
    @handle_api_error                    # returns OperationResult on error, raw return on success
    @require_roles(list(Roles.ADMIN_PAIR))

Because the functions themselves return PLAIN dicts on their success paths, the
critical_api wrapper passes those dicts straight through (no to_dict conversion).
So a successful direct call returns the function's own dict, e.g.
    {"success": True, "message": ..., "teams_fixed": ..., "volunteers_fixed": ...}
An *error* path (an exception caught by handle_api_error) is returned as an
OperationResult and serialised by critical_api into the nested shape
    {"success": False, "error": {"message": ...}, "meta": {...}}.

ASSIGNMENT-HISTORY MODEL
------------------------
Volunteer assignment history is stored in the Volunteer's `assignment_history`
child table, whose child DocType is "Volunteer Assignment" (keyed by the parent
Volunteer -- there is NO standalone "Assignment History" doctype). Adding an
active Team member and saving the Team auto-creates a matching Active
Volunteer Assignment row (Team.handle_team_member_changes -> TeamService).

PRODUCTION BUG FOUND (fixed in target file)
-------------------------------------------
Both fix_* functions originally queried
    frappe.db.exists("Assignment History", {"volunteer": ..., ...})
"Assignment History" is not a DocType (no `tabAssignment History` table) and the
real child table has no `volunteer` column (it uses `parent`). Any call that
reached that check raised "table doesn't exist", which handle_api_error turned
into an error result -- so the fix utilities never worked. Corrected to query
"Volunteer Assignment" filtered by parent/parenttype. These tests assert the
corrected behaviour.
"""

import frappe

from verenigingen.api.team_admin_utilities import (
    debug_team_assignments,
    fix_all_missing_assignment_history,
    fix_missing_assignment_history,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestTeamAdminUtilities(VereningingenTestCase):
    """Real integration tests for the team administration utilities API."""

    def setUp(self):
        super().setUp()
        # These endpoints are gated to admin roles; run as Administrator.
        frappe.set_user("Administrator")
        # Ensure the standard seeded Team Role records exist on fresh CI sites.
        self.ensure_team_roles()

    # ------------------------------------------------------------------ #
    # Helpers (persistence / privileged operations live here, not in tests)
    # ------------------------------------------------------------------ #
    def _make_team_with_member(self, role_name="Team Member", volunteer_name=None):
        """Create a tracked Team with one active volunteer team member.

        Saving the team auto-creates a matching Active Volunteer Assignment row.
        Returns (team_doc, volunteer_doc).
        """
        vol_kwargs = {}
        if volunteer_name:
            vol_kwargs["volunteer_name"] = volunteer_name
        volunteer = self.create_test_volunteer(**vol_kwargs)

        team = self.factory.create_test_team()
        self.track_doc("Team", team.name)

        # Adds the team member (with a real Team Role link) and saves the team,
        # which triggers on_update -> assignment-history creation.
        self.factory.create_test_team_member(
            team=team, volunteer=volunteer, team_role_name=role_name
        )

        team.reload()
        return team, volunteer

    def _persist_volunteer_without_team_history(self, volunteer_name, team_name):
        """Remove any Active Team assignment-history rows for this volunteer.

        Simulates the real-world condition the fix utilities exist for: an active
        team assignment that is missing its assignment-history entry.
        """
        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        volunteer.assignment_history = [
            row
            for row in (volunteer.assignment_history or [])
            if not (row.reference_doctype == "Team" and row.reference_name == team_name)
        ]
        volunteer.save()

    def _count_active_team_history(self, volunteer_name, team_name):
        return frappe.db.count(
            "Volunteer Assignment",
            {
                "parent": volunteer_name,
                "parenttype": "Volunteer",
                "reference_doctype": "Team",
                "reference_name": team_name,
                "status": "Active",
            },
        )

    def _make_lowpriv_user(self):
        """A logged-in user WITHOUT the admin roles these endpoints require."""
        email = f"team.admin.lowpriv.{frappe.generate_hash(length=6)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "LowPriv",
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Member"}],
            }
        )
        user.insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        return user

    # ------------------------------------------------------------------ #
    # fix_missing_assignment_history
    # ------------------------------------------------------------------ #
    def test_fix_missing_requires_both_arguments(self):
        """Missing team_name/volunteer_name is a validation error, not a crash."""
        result = fix_missing_assignment_history(team_name="Some Team", volunteer_name=None)
        # frappe.throw -> ValidationError -> handle_api_error -> nested error dict.
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))

    def test_fix_missing_unknown_team_is_validation_error(self):
        """A non-existent team is rejected by validate_document_exists."""
        volunteer = self.create_test_volunteer()
        result = fix_missing_assignment_history(
            team_name=f"No Such Team {frappe.generate_hash(length=6)}",
            volunteer_name=volunteer.name,
        )
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))

    def test_fix_missing_when_history_already_exists(self):
        """When the active assignment already has history, report it as existing.

        This exercises the corrected frappe.db.exists("Volunteer Assignment", ...)
        check -- pre-fix it raised "table doesn't exist" and returned an error.
        A first call establishes the history row (whether or not the team save
        already auto-created it); the second call must detect it and not duplicate.
        """
        team, volunteer = self._make_team_with_member()

        first = fix_missing_assignment_history(team_name=team.name, volunteer_name=volunteer.name)
        self.assertTrue(first.get("success"), msg=f"unexpected result: {first}")
        self.assertEqual(self._count_active_team_history(volunteer.name, team.name), 1)

        # Second call must recognise the existing history, not create a duplicate.
        result = fix_missing_assignment_history(team_name=team.name, volunteer_name=volunteer.name)

        self.assertTrue(result.get("success"), msg=f"unexpected result: {result}")
        self.assertIn("already exists", result.get("message", ""))
        self.assertEqual(self._count_active_team_history(volunteer.name, team.name), 1)

    def test_fix_missing_adds_history_when_absent(self):
        """The core purpose: recreate a missing active assignment-history row."""
        team, volunteer = self._make_team_with_member(role_name="Team Leader")

        # Remove the auto-created history to simulate the missing-history condition.
        self._persist_volunteer_without_team_history(volunteer.name, team.name)
        self.assertEqual(self._count_active_team_history(volunteer.name, team.name), 0)

        result = fix_missing_assignment_history(team_name=team.name, volunteer_name=volunteer.name)

        self.assertTrue(result.get("success"), msg=f"unexpected result: {result}")
        self.assertIn("added", result.get("message", "").lower())
        # History row must now exist again.
        self.assertEqual(self._count_active_team_history(volunteer.name, team.name), 1)

    def test_fix_missing_no_matching_active_assignment(self):
        """Volunteer not on the team -> 'No matching active assignment found'."""
        team, _member_vol = self._make_team_with_member()
        other_volunteer = self.create_test_volunteer()

        result = fix_missing_assignment_history(
            team_name=team.name, volunteer_name=other_volunteer.name
        )

        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        self.assertIn("No matching active assignment", result.get("error", ""))

    # ------------------------------------------------------------------ #
    # fix_all_missing_assignment_history
    # ------------------------------------------------------------------ #
    def test_fix_all_returns_summary_and_does_not_error(self):
        """Full-scan utility must complete cleanly across existing teams.

        Pre-fix this hit the broken exists() query for every active member and
        returned an error result; post-fix it returns the success summary.
        """
        # Ensure at least one team with an active member exists in scope.
        self._make_team_with_member()

        result = fix_all_missing_assignment_history()

        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("success"), msg=f"unexpected result: {result}")
        self.assertIn("teams_fixed", result)
        self.assertIn("volunteers_fixed", result)
        self.assertGreaterEqual(result["volunteers_fixed"], 0)

    def test_fix_all_recreates_stripped_history(self):
        """A volunteer with stripped history should get its row rebuilt by fix_all."""
        team, volunteer = self._make_team_with_member()
        self._persist_volunteer_without_team_history(volunteer.name, team.name)
        self.assertEqual(self._count_active_team_history(volunteer.name, team.name), 0)

        result = fix_all_missing_assignment_history()

        self.assertTrue(result.get("success"), msg=f"unexpected result: {result}")
        # The specific volunteer's active Team history must be restored.
        self.assertEqual(self._count_active_team_history(volunteer.name, team.name), 1)

    # ------------------------------------------------------------------ #
    # debug_team_assignments
    # ------------------------------------------------------------------ #
    def test_debug_team_assignments_structure_and_content(self):
        """Diagnostic returns teams (with member detail) and Test volunteers."""
        debug_name = f"Test Debug Vol {frappe.generate_hash(length=6)}"
        team, volunteer = self._make_team_with_member(volunteer_name=debug_name)

        result = debug_team_assignments()

        # Diagnostic returns its raw dict (no success wrapper).
        self.assertIsInstance(result, dict)
        self.assertIn("teams", result)
        self.assertIn("debug_volunteers", result)
        self.assertIsInstance(result["teams"], list)

        # Our team must appear with the expected member field structure.
        our_team = next((t for t in result["teams"] if t["name"] == team.name), None)
        self.assertIsNotNone(our_team, "created team missing from debug output")
        self.assertTrue(our_team["members"], "team should report its members")
        member_row = our_team["members"][0]
        for key in ("volunteer", "volunteer_name", "role", "team_role", "is_active", "from_date"):
            self.assertIn(key, member_row)
        self.assertEqual(member_row["volunteer"], volunteer.name)

        # The 'Test'-named volunteer must be listed with its assignment history.
        our_vol = next(
            (v for v in result["debug_volunteers"] if v["name"] == volunteer.name), None
        )
        self.assertIsNotNone(our_vol, "Test-named volunteer missing from debug output")
        self.assertIn("assignment_history", our_vol)

    # ------------------------------------------------------------------ #
    # Authorization
    # ------------------------------------------------------------------ #
    def test_non_admin_is_denied(self):
        """A user lacking the admin roles must not get a successful result."""
        user = self._make_lowpriv_user()

        with self.as_user(user.name):
            try:
                result = debug_team_assignments()
            except (frappe.PermissionError, PermissionError):
                return  # Hard denial is acceptable.

        # If it returned instead of raising, it must be a failure result --
        # never the diagnostic payload.
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success", False))
        self.assertNotIn("teams", result)
