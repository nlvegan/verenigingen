"""
Real-integration tests for the *Team Members* script report
(``verenigingen/verenigingen/report/team_members/``).

This report was at 0% coverage. It is a LIVE standard Script Report
(ref_doctype Team Member) used from the Team form to list the active members
of a single team. It requires a ``team`` filter, enforces a security check
(Administrators / staff see any team; ordinary users only their own team) and
returns active ``Team Member`` rows joined to ``Volunteer`` for the email.

Tests run as Administrator and seed real Teams / Volunteers / Team Members via
the factory; all are auto-cleaned.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.team_members import team_members as report


class TestTeamMembersReport(VereningingenTestCase):
    # ------------------------------------------------------------- helpers

    def _team_with_member(self, *, team_role_name="Team Member", role="Coordinator", is_active=1):
        # role_type is read-only and fetched from team_role.role_name, so it is
        # controlled via the Team Role (team_role_name), not set directly.
        team = self.factory.create_test_team()
        self.track_doc("Team", team.name)
        volunteer = self.create_test_volunteer()
        team_member = self.factory.create_test_team_member(
            team=team,
            volunteer=volunteer,
            team_role_name=team_role_name,
            role=role,
            volunteer_name=volunteer.volunteer_name,
            is_active=is_active,
            from_date=today(),
        )
        return team, volunteer, team_member

    # ------------------------------------------------------------- guard

    def test_missing_team_filter_throws(self):
        with self.assertRaises(Exception):
            report.execute({})

    def test_missing_team_filter_throws_none(self):
        with self.assertRaises(Exception):
            report.execute(None)

    # ------------------------------------------------------------- data

    def test_active_member_appears(self):
        team, volunteer, _tm = self._team_with_member(team_role_name="Team Leader", role="Chair")

        with self.assertNoErrorLog():
            columns, data = report.execute({"team": team.name})

        self.assertEqual(len(columns), 8)
        row = next((r for r in data if r["volunteer"] == volunteer.name), None)
        self.assertIsNotNone(row, "active team member must appear in the report")
        self.assertEqual(row["role_type"], "Team Leader")
        self.assertEqual(row["role"], "Chair")
        self.assertEqual(row["email"], volunteer.email)
        self.assertEqual(row["status"], "Active")

    def test_inactive_member_excluded(self):
        team = self.factory.create_test_team()
        self.track_doc("Team", team.name)
        active_vol = self.create_test_volunteer()
        inactive_vol = self.create_test_volunteer()
        self.factory.create_test_team_member(
            team=team, volunteer=active_vol, volunteer_name=active_vol.volunteer_name,
            team_role_name="Team Member", is_active=1, from_date=today(),
        )
        self.factory.create_test_team_member(
            team=team, volunteer=inactive_vol, volunteer_name=inactive_vol.volunteer_name,
            team_role_name="Team Member", is_active=0, status="Inactive", from_date=today(),
        )

        with self.assertNoErrorLog():
            _columns, data = report.execute({"team": team.name})
        ids = {r["volunteer"] for r in data}
        self.assertIn(active_vol.name, ids)
        self.assertNotIn(inactive_vol.name, ids, "inactive members must be excluded")

    def test_other_team_members_excluded(self):
        team_a, vol_a, _ = self._team_with_member()
        team_b, vol_b, _ = self._team_with_member()

        with self.assertNoErrorLog():
            _columns, data = report.execute({"team": team_a.name})
        ids = {r["volunteer"] for r in data}
        self.assertIn(vol_a.name, ids)
        self.assertNotIn(vol_b.name, ids, "members of another team must not leak in")

    def test_empty_team_returns_no_rows(self):
        team = self.factory.create_test_team()
        self.track_doc("Team", team.name)
        with self.assertNoErrorLog():
            columns, data = report.execute({"team": team.name})
        self.assertEqual(len(columns), 8)
        self.assertEqual(data, [])

    def test_columns_structure(self):
        team, _vol, _tm = self._team_with_member()
        with self.assertNoErrorLog():
            columns, _data = report.execute({"team": team.name})
        fieldnames = [c["fieldname"] for c in columns]
        for expected in (
            "volunteer",
            "volunteer_name",
            "role_type",
            "role",
            "email",
            "from_date",
            "to_date",
            "status",
        ):
            self.assertIn(expected, fieldnames)
