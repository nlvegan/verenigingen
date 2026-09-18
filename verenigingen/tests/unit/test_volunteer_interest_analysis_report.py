"""
Tests for the *Volunteer Interest Analysis* script report
(``verenigingen/verenigingen/report/volunteer_interest_analysis/``).

Regression coverage for #1133: ``get_data()`` computed the member's chapter via
``get_member_chapters()`` (a real, working lookup) but stored the result under
the row key ``"chapter"``, while the report's own column definition declares
``"fieldname": "primary_chapter"``. Frappe renders a column by looking up its
fieldname in each row, so the "Chapter" column was always blank regardless of
the member's real chapter.

This lives under ``tests/unit/`` (Tier 1) rather than ``tests/report/`` (Tier 2,
which blocks database mocks) because isolating the fix under test genuinely
requires patching two unrelated things out of the way (see ``_get_data_for``
below): ``get_data()`` also queries the "Member Volunteer Interest" and
"Member Volunteer Skill" DocTypes for every matched row, and neither exists
anywhere in this app (confirmed: no doctype JSON under either name -- only
"Volunteer Interest Area"/"Volunteer Interest Category"/"Volunteer Skill" do).
That is a severe, pre-existing, unrelated defect -- the report cannot return
any row at all today without raising ``MySQLdb.ProgrammingError`` for a
missing table -- filed as a comment on #689, which already tracked this exact
report. The main member query is also not usable as-is here: it is a bare
``WHERE m.interested_in_volunteering = 1`` with no scoping to a single test
member, so it would pick up any pre-existing/leaked row on a shared test site.
The member/chapter fixtures and ``get_member_chapters()`` lookup this test
actually exercises are still real database operations against a real Member
and Chapter.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.volunteer_interest_analysis import (
    volunteer_interest_analysis as report,
)

_MODULE = "verenigingen.verenigingen.report.volunteer_interest_analysis.volunteer_interest_analysis"


class TestVolunteerInterestAnalysisReport(VereningingenTestCase):
    def _synthetic_member_row(self, member_name):
        return frappe._dict(
            {
                "name": member_name,
                "full_name": "Volly Test",
                "email": "volly@test.invalid",
                "member_since": None,
                "commitment_level": None,
                "experience_level": None,
                "volunteer_id": None,
                "volunteer_status": None,
            }
        )

    def _get_data_for(self, member_name, filters=None):
        # See module docstring: patch out the main query (leaked-data/shared-site
        # safe) and the "Member Volunteer Skill" lookup against a DocType that
        # does not exist, so only the row-key fix under test (get_member_chapters
        # -> "primary_chapter") runs against the real database.
        #
        # frappe.db.get_all() is a thin staticmethod alias for frappe.get_all()
        # (see frappe/database/database.py), and get_member_chapters() (the real
        # lookup this test exercises) calls it to read "Chapter Member" rows. A
        # blanket patch of frappe.get_all would silently break that lookup too,
        # so only "Member Volunteer Skill" is faked here; everything else falls
        # through to the real frappe.get_all.
        real_get_all = frappe.get_all
        real_sql = frappe.db.sql

        def _fake_get_all(doctype, *args, **kwargs):
            if doctype == "Member Volunteer Skill":
                return []
            return real_get_all(doctype, *args, **kwargs)

        def _fake_sql(query, *args, **kwargs):
            # frappe.get_all()/get_member_chapters() run their own SQL under the
            # hood via this SAME frappe.db.sql -- only fake the report's own
            # top-level member query (identified by its FROM/JOIN), and let
            # every other call (including the one behind get_member_chapters)
            # through to the real implementation.
            if "FROM `tabMember` m" in query and "LEFT JOIN `tabVolunteer` v" in query:
                return [self._synthetic_member_row(member_name)]
            return real_sql(query, *args, **kwargs)

        with (
            patch(f"{_MODULE}.frappe.db.sql", side_effect=_fake_sql),
            patch(f"{_MODULE}.QueryBuilder.get_all_active_records", return_value=[]),
            patch(f"{_MODULE}.frappe.get_all", side_effect=_fake_get_all),
        ):
            return report.get_data(filters or {})

    def test_chapter_column_is_populated(self):
        chapter = self.create_test_chapter()
        member = self.create_test_member(
            first_name="Volly",
            last_name=f"Test{frappe.generate_hash(length=4)}",
            email=f"volly.{frappe.generate_hash(length=6)}@test.invalid",
            interested_in_volunteering=1,
            chapter=chapter,
        )

        with self.assertNoErrorLog():
            data = self._get_data_for(member.name)

        self.assertEqual(len(data), 1)
        self.assertEqual(
            data[0]["primary_chapter"],
            chapter.name,
            "the report's Chapter column (fieldname=primary_chapter) must show the member's chapter",
        )

    def test_chapter_column_is_unassigned_when_no_chapter(self):
        member = self.create_test_member(
            first_name="Volly",
            last_name=f"Test{frappe.generate_hash(length=4)}",
            email=f"volly.{frappe.generate_hash(length=6)}@test.invalid",
            interested_in_volunteering=1,
            chapter=False,
        )

        with self.assertNoErrorLog():
            data = self._get_data_for(member.name)

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["primary_chapter"], "Unassigned")
