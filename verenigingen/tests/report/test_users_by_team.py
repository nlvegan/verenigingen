"""
Real-integration tests for the *Users by Team* script report
(``verenigingen/verenigingen/report/users_by_team/``).

This report was at 0% coverage. It is a LIVE standard Script Report
(ref_doctype Team, linked from the Verenigingen workspace) that lists, across
all Teams, the user behind each Team Member (Team -> Team Member -> Volunteer
-> Member -> User), with active_only / team / user / team_role filters.

Tests seed real Teams / Volunteers (whose Members have linked Users) / Team
Members via the factory; all auto-cleaned.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.users_by_team import users_by_team as report


class TestUsersByTeamReport(VereningingenTestCase):
    # ------------------------------------------------------------- helpers

    def _team_member(self, *, team_role_name="Team Member", is_active=1, member=None):
        """Seed Team + Member(with user) + Volunteer + Team Member.

        ``role_type`` (queried by the report as ``team_role``) is read-only and
        fetched from the Team Role's ``role_name``, so it is driven via
        ``team_role_name``.
        """
        if member is None:
            email = f"teamuser.{frappe.generate_hash(length=6)}@test.invalid"
            member = self.create_test_member(
                first_name="Teamuser",
                last_name=f"M{frappe.generate_hash(length=4)}",
                email=email,
            )
            # Link a real User so the report's m.user column is populated and
            # user-based assertions are meaningful.
            user = self.create_test_user(email)
            frappe.db.set_value("Member", member.name, "user", user.name)
            member.reload()
        volunteer = self.create_test_volunteer(member=member)
        team = self.factory.create_test_team()
        self.track_doc("Team", team.name)
        self.factory.create_test_team_member(
            team=team,
            volunteer=volunteer,
            volunteer_name=volunteer.volunteer_name,
            team_role_name=team_role_name,
            is_active=is_active,
            status="Active" if is_active else "Inactive",
            from_date=today(),
        )
        return team, member, volunteer

    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(len(columns), 9)
        for expected in (
            "team",
            "team_lead",
            "user",
            "user_full_name",
            "team_role",
            "from_date",
            "is_active",
        ):
            self.assertIn(expected, fieldnames)

    def test_execute_empty_filters_returns_columns(self):
        with self.assertNoErrorLog():
            columns, data = report.execute({})
        self.assertEqual(len(columns), 9)
        self.assertIsInstance(data, list)

    def test_execute_none_filters(self):
        with self.assertNoErrorLog():
            columns, data = report.execute(None)
        self.assertEqual(len(columns), 9)

    # ------------------------------------------------------------- data

    def test_seeded_member_appears(self):
        team, member, _vol = self._team_member(team_role_name="Team Leader")
        with self.assertNoErrorLog():
            _columns, data = report.execute({"team": team.name})
        row = next((r for r in data if r["team"] == team.name), None)
        self.assertIsNotNone(row, "seeded team must appear")
        self.assertEqual(row["user"], member.user)
        self.assertEqual(row["team_role"], "Team Leader")
        self.assertIn(member.first_name, row["user_full_name"])

    # ------------------------------------------------------------- filters

    def test_team_filter_restricts(self):
        team_a, _m_a, _v_a = self._team_member()
        team_b, _m_b, _v_b = self._team_member()
        with self.assertNoErrorLog():
            _columns, data = report.execute({"team": team_a.name})
        teams = {r["team"] for r in data}
        self.assertIn(team_a.name, teams)
        self.assertNotIn(team_b.name, teams)

    def test_active_only_filter(self):
        team = self.factory.create_test_team()
        self.track_doc("Team", team.name)
        active_member = self.create_test_member(
            first_name="Activeuser",
            last_name=f"M{frappe.generate_hash(length=4)}",
            email=f"active.{frappe.generate_hash(length=6)}@test.invalid",
        )
        inactive_member = self.create_test_member(
            first_name="Inactiveuser",
            last_name=f"M{frappe.generate_hash(length=4)}",
            email=f"inactive.{frappe.generate_hash(length=6)}@test.invalid",
        )
        active_vol = self.create_test_volunteer(member=active_member)
        inactive_vol = self.create_test_volunteer(member=inactive_member)
        self.factory.create_test_team_member(
            team=team, volunteer=active_vol, volunteer_name=active_vol.volunteer_name,
            team_role_name="Team Member", is_active=1, from_date=today(),
        )
        self.factory.create_test_team_member(
            team=team, volunteer=inactive_vol, volunteer_name=inactive_vol.volunteer_name,
            team_role_name="Team Member", is_active=0, status="Inactive", from_date=today(),
        )

        # Without active_only both team members are returned.
        with self.assertNoErrorLog():
            _columns, all_rows = report.execute({"team": team.name})
        self.assertEqual(len(all_rows), 2, "both members returned without active_only")

        # With active_only the inactive (is_active=0) member is dropped.
        with self.assertNoErrorLog():
            _columns, active_rows = report.execute({"team": team.name, "active_only": 1})
        self.assertEqual(len(active_rows), 1, "active_only must drop the inactive member")
        self.assertTrue(all(r["is_active"] == 1 for r in active_rows))

    def test_user_filter(self):
        team, member, _vol = self._team_member()
        with self.assertNoErrorLog():
            _columns, data = report.execute({"user": member.user})
        self.assertTrue(data, "filtering by the seeded user must return the row")
        self.assertTrue(all(r["user"] == member.user for r in data))

    def test_team_role_filter(self):
        team_lead, _m1, _v1 = self._team_member(team_role_name="Team Leader")
        team_member, _m2, _v2 = self._team_member(team_role_name="Team Member")
        with self.assertNoErrorLog():
            _columns, data = report.execute({"team_role": "Team Leader"})
        self.assertTrue(all(r["team_role"] == "Team Leader" for r in data))
        teams = {r["team"] for r in data}
        self.assertIn(team_lead.name, teams)
        self.assertNotIn(team_member.name, teams)
