"""Gap-fill tests for the *Chapter Expense Report* script report
(``verenigingen/verenigingen/report/chapter_expense_report/``).

The existing suite (``tests/backend/components/test_chapter_expense_report_unit.py``)
covers ``get_summary``, ``get_chart_data``, ``get_approval_level_for_amount``,
the ``build_expense_row`` status indicators and the basic ``get_data`` filter
mocked at the ``get_erpnext_expense_data`` seam. This file adds the previously
uncovered branches of ``get_data`` -- the per-expense access-filtering loop and
the explicit status / organization_type / chapter / team filters -- plus the
``build_expense_row`` approved-date branch.

``get_data`` calls ``get_erpnext_expense_data`` (a function the report module
defines) and ``get_user_accessible_chapters``. We patch those at the report's
OWN module boundary -- not at any ``frappe.db`` call -- so the access-control and
filtering logic runs against real, in-memory expense rows. No business logic is
mocked.
"""

from unittest.mock import patch

from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.chapter_expense_report import chapter_expense_report as report

MODULE = "verenigingen.verenigingen.report.chapter_expense_report.chapter_expense_report"


def _expense(name, amount=100.0, organization_type="Chapter", chapter=None, team=None, status="Approved"):
    return {
        "name": name,
        "volunteer_name": "Vol",
        "description": "desc",
        "amount": amount,
        "expense_date": today(),
        "category_name": "Travel",
        "organization_type": organization_type,
        "organization_name": organization_name(organization_type),
        "chapter": chapter,
        "team": team,
        "status": status,
    }


def organization_name(organization_type):
    return organization_type or "Unknown"


class TestChapterExpenseReportGapfill(VereningingenTestCase):
    # ---------------------------------------------------- admin sees everything

    def test_admin_access_returns_all_rows(self):
        rows = [
            _expense("E1", organization_type="Chapter", chapter="Chapter-A"),
            _expense("E2", organization_type="Team", team="Team-A"),
            _expense("E3", organization_type="National"),
        ]
        with patch(f"{MODULE}.get_erpnext_expense_data", return_value=rows), patch(
            f"{MODULE}.get_user_accessible_chapters", return_value=None
        ):
            data = report.get_data({"from_date": "2024-01-01", "to_date": "2030-12-31"})
        self.assertEqual({r["name"] for r in data}, {"E1", "E2", "E3"})

    # --------------------------------------------- non-admin chapter filtering

    def test_non_admin_only_sees_accessible_chapter(self):
        rows = [
            _expense("OK", organization_type="Chapter", chapter="Chapter-A"),
            _expense("NO", organization_type="Chapter", chapter="Chapter-B"),
        ]
        with patch(f"{MODULE}.get_erpnext_expense_data", return_value=rows), patch(
            f"{MODULE}.get_user_accessible_chapters", return_value=["Chapter-A"]
        ):
            data = report.get_data({})
        names = {r["name"] for r in data}
        self.assertIn("OK", names)
        self.assertNotIn("NO", names)

    def test_non_admin_skips_unassigned_chapter_expense(self):
        rows = [_expense("UNASSIGNED", organization_type="Chapter", chapter=None)]
        with patch(f"{MODULE}.get_erpnext_expense_data", return_value=rows), patch(
            f"{MODULE}.get_user_accessible_chapters", return_value=["Chapter-A"]
        ):
            data = report.get_data({})
        self.assertEqual(data, [], "unassigned-chapter expense is hidden from non-admins")

    def test_non_admin_skips_other_org_types(self):
        rows = [_expense("NATIONAL", organization_type="National")]
        with patch(f"{MODULE}.get_erpnext_expense_data", return_value=rows), patch(
            f"{MODULE}.get_user_accessible_chapters", return_value=["Chapter-A"]
        ):
            data = report.get_data({})
        self.assertEqual(data, [], "non-Chapter/Team org types are hidden from non-admins")

    def test_non_admin_skips_unassigned_team_expense(self):
        rows = [_expense("NOTEAM", organization_type="Team", team=None)]
        with patch(f"{MODULE}.get_erpnext_expense_data", return_value=rows), patch(
            f"{MODULE}.get_user_accessible_chapters", return_value=["Chapter-A"]
        ):
            data = report.get_data({})
        self.assertEqual(data, [], "unassigned-team expense is hidden from non-admins")

    def test_non_admin_team_expense_with_accessible_chapter(self):
        # A real Team whose chapter is accessible should be visible. Create a real
        # Chapter + Team so the report's frappe.db.get_value("Team", ...) lookup
        # hits real data.
        chapter = self.create_test_chapter()
        team = self._make_team(chapter.name)

        rows = [_expense("TEAMOK", organization_type="Team", team=team)]
        with patch(f"{MODULE}.get_erpnext_expense_data", return_value=rows), patch(
            f"{MODULE}.get_user_accessible_chapters", return_value=[chapter.name]
        ):
            data = report.get_data({})
        self.assertEqual({r["name"] for r in data}, {"TEAMOK"})

    def test_non_admin_team_expense_with_inaccessible_chapter_is_hidden(self):
        chapter = self.create_test_chapter()
        team = self._make_team(chapter.name)

        rows = [_expense("TEAMNO", organization_type="Team", team=team)]
        with patch(f"{MODULE}.get_erpnext_expense_data", return_value=rows), patch(
            f"{MODULE}.get_user_accessible_chapters", return_value=["Some-Other-Chapter"]
        ):
            data = report.get_data({})
        self.assertEqual(data, [], "team whose chapter is not accessible is hidden")

    # ---------------------------------------------------- explicit filters

    def test_status_filter(self):
        rows = [
            _expense("APP", status="Approved"),
            _expense("REJ", status="Rejected"),
        ]
        with patch(f"{MODULE}.get_erpnext_expense_data", return_value=rows), patch(
            f"{MODULE}.get_user_accessible_chapters", return_value=None
        ):
            data = report.get_data({"status": "Approved"})
        self.assertEqual({r["name"] for r in data}, {"APP"})

    def test_organization_type_filter(self):
        rows = [
            _expense("CH", organization_type="Chapter", chapter="C"),
            _expense("TM", organization_type="Team", team="T"),
        ]
        with patch(f"{MODULE}.get_erpnext_expense_data", return_value=rows), patch(
            f"{MODULE}.get_user_accessible_chapters", return_value=None
        ):
            data = report.get_data({"organization_type": "Chapter"})
        self.assertEqual({r["name"] for r in data}, {"CH"})

    def test_specific_chapter_filter(self):
        rows = [
            _expense("A", organization_type="Chapter", chapter="Chapter-A"),
            _expense("B", organization_type="Chapter", chapter="Chapter-B"),
        ]
        with patch(f"{MODULE}.get_erpnext_expense_data", return_value=rows), patch(
            f"{MODULE}.get_user_accessible_chapters", return_value=None
        ):
            data = report.get_data({"chapter": "Chapter-A"})
        self.assertEqual({r["name"] for r in data}, {"A"})

    def test_specific_team_filter(self):
        rows = [
            _expense("T1", organization_type="Team", team="Team-1"),
            _expense("T2", organization_type="Team", team="Team-2"),
        ]
        with patch(f"{MODULE}.get_erpnext_expense_data", return_value=rows), patch(
            f"{MODULE}.get_user_accessible_chapters", return_value=None
        ):
            data = report.get_data({"team": "Team-1"})
        self.assertEqual({r["name"] for r in data}, {"T1"})

    # ---------------------------------------------------- build_expense_row

    def test_build_expense_row_with_approval_dates(self):
        # The approved_on + expense_date branch computes days_to_approval from the
        # approval, not from today(); approved_by resolves to a User full_name.
        row = report.build_expense_row(
            name="EXP-APPR",
            volunteer_name="Vol",
            description="d",
            amount=600.0,  # > 500 -> Admin level
            expense_date=add_days(today(), -5),
            category_name="Travel",
            organization_type="Chapter",
            organization_name="Chapter A",
            status="Approved",
            is_erpnext=True,
            expense_claim_id="EXP-APPR",
            approved_by="Administrator",
            approved_on=today(),
        )
        self.assertEqual(row["approval_level"], "Admin")
        self.assertEqual(row["days_to_approval"], 5)
        self.assertIsNotNone(row["approved_by_name"])
        self.assertIn("green", row["status_indicator"])

    # ---------------------------------------------------- helpers

    def _make_team(self, chapter_name):
        import frappe

        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"Team {frappe.generate_hash(length=6)}",
                "chapter": chapter_name,
                "status": "Active",
                "team_type": "Project Team",
                "start_date": today(),
            }
        )
        team.insert(ignore_permissions=True)
        self.track_doc("Team", team.name)
        return team.name
