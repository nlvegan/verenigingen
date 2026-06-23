"""Real-integration tests for the *Volunteer Activity by Tag* script report
(``verenigingen/verenigingen/report/volunteer_activity_by_tag/``).

This "tag ecosystem" report was at 0% coverage. It groups Volunteer Activities
by their Activity Tags, joining to the Volunteer and (via Chapter Membership
History) the volunteer's chapters. These tests seed real Volunteers, Activity
Tags and tagged Volunteer Activities and call ``execute(filters)`` directly,
asserting the column structure, the tagged-row data, the chart, the summary
message, every filter branch (tag / activity_type / activity_scope / status /
from_date / to_date) and the empty-result branch.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.volunteer_activity_by_tag import (
    volunteer_activity_by_tag as report,
)


class TestVolunteerActivityByTagReport(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.suffix = frappe.generate_hash(length=6)
        # Creating a Volunteer enqueues an Account Creation Request whose async
        # processor runs after the test rolls back, logging a benign
        # "Account creation request ... not found". That noise is unrelated to
        # the report under test; mark it expected so the tearDown error-log guard
        # (and VERENIGINGEN_FAIL_ON_ERROR_LOG=1 on CI) does not flag it.
        self.expectErrorLog("Account Creation Request Processing Error")

    # ------------------------------------------------------------- helpers

    def _ensure_tag(self, tag_name):
        if not frappe.db.exists("Activity Tag", tag_name):
            doc = frappe.get_doc({"doctype": "Activity Tag", "tag_name": tag_name})
            doc.insert(ignore_permissions=True)
            self.track_doc("Activity Tag", doc.name)
        return tag_name

    def _make_volunteer(self):
        member = self.create_test_member(
            first_name="Vol",
            last_name=f"M{frappe.generate_hash(length=4)}",
            email=f"vol.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        volunteer = self.create_test_volunteer(member=member.name)
        return member, volunteer

    def _make_activity(
        self,
        volunteer,
        tags,
        activity_type="Project",
        activity_scope="Internal",
        status="Active",
        start_date=None,
        actual_hours=2.0,
        role="Coordinator",
    ):
        start_date = start_date or today()
        doc = frappe.get_doc(
            {
                "doctype": "Volunteer Activity",
                "volunteer": volunteer.name,
                "activity_type": activity_type,
                "activity_scope": activity_scope,
                "role": role,
                "status": status,
                "start_date": start_date,
                "actual_hours": actual_hours,
                "tags": [{"tag": self._ensure_tag(t)} for t in tags],
            }
        )
        doc.insert(ignore_permissions=True)
        self.track_doc("Volunteer Activity", doc.name)
        return doc

    def _rows_for_volunteer(self, data, volunteer_name):
        return [r for r in data if r.get("volunteer") == volunteer_name]

    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns()
        self.assertEqual(len(columns), 11)
        self.assertEqual(columns[0]["fieldname"], "tag")
        self.assertEqual(columns[0]["options"], "Activity Tag")
        self.assertEqual(columns[1]["fieldname"], "volunteer")

    # --------------------------------------------------------- basic data

    def test_tagged_activity_appears_with_its_tag(self):
        _member, volunteer = self._make_volunteer()
        tag = f"climate-{self.suffix}"
        self._make_activity(volunteer, [tag], actual_hours=3.0)

        with self.assertNoErrorLog():
            columns, data, message, chart = report.execute({})

        self.assertEqual(len(columns), 11)
        rows = self._rows_for_volunteer(data, volunteer.name)
        self.assertTrue(rows, "tagged activity must appear in the report")
        self.assertEqual(rows[0]["tag"], tag)
        self.assertEqual(float(rows[0]["actual_hours"]), 3.0)

    def test_activity_with_multiple_tags_yields_a_row_per_tag(self):
        _member, volunteer = self._make_volunteer()
        tag_a = f"tagA-{self.suffix}"
        tag_b = f"tagB-{self.suffix}"
        self._make_activity(volunteer, [tag_a, tag_b])

        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute({})
        tags = {r["tag"] for r in self._rows_for_volunteer(data, volunteer.name)}
        self.assertIn(tag_a, tags)
        self.assertIn(tag_b, tags)

    # --------------------------------------------------------- chart / summary

    def test_chart_reflects_tag_distribution(self):
        _member, volunteer = self._make_volunteer()
        tag = f"chart-{self.suffix}"
        self._make_activity(volunteer, [tag])

        with self.assertNoErrorLog():
            _columns, data, _message, chart = report.execute({"tag": tag})
        self.assertIsNotNone(chart)
        self.assertEqual(chart["type"], "bar")
        self.assertIn(tag, chart["data"]["labels"])

    def test_chart_none_when_no_data(self):
        self.assertIsNone(report.get_tag_distribution_chart([]))

    def test_summary_message_counts(self):
        _member, volunteer = self._make_volunteer()
        tag = f"sum-{self.suffix}"
        self._make_activity(volunteer, [tag], actual_hours=4.0)

        with self.assertNoErrorLog():
            _columns, data, message, _chart = report.execute({"tag": tag})
        self.assertIn("Tag Ecosystem Summary", message)
        self.assertIn("volunteers involved", message)

    def test_summary_message_empty(self):
        msg = report.get_summary_message([], {})
        self.assertIn("No activities found", msg)

    def test_summary_high_activity_tags_section(self):
        # 5+ activities on the same tag triggers the "High Activity Tags" hint
        # (only when no tag filter is applied).
        _member, volunteer = self._make_volunteer()
        tag = f"busy-{self.suffix}"
        for _ in range(5):
            self._make_activity(volunteer, [tag])

        with self.assertNoErrorLog():
            _columns, data, message, _chart = report.execute({})
        self.assertIn("High Activity Tags", message)
        self.assertIn(tag, message)

    # --------------------------------------------------------- filter branches

    def test_filter_by_tag(self):
        _member, volunteer = self._make_volunteer()
        wanted = f"wanted-{self.suffix}"
        other = f"other-{self.suffix}"
        self._make_activity(volunteer, [wanted])
        self._make_activity(volunteer, [other])

        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute({"tag": wanted})
        tags = {r["tag"] for r in data}
        self.assertIn(wanted, tags)
        self.assertNotIn(other, tags)

    def test_filter_by_activity_type(self):
        _member, volunteer = self._make_volunteer()
        tag = f"type-{self.suffix}"
        self._make_activity(volunteer, [tag], activity_type="Workshop")
        self._make_activity(volunteer, [tag], activity_type="Campaign")

        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute({"activity_type": "Workshop"})
        rows = self._rows_for_volunteer(data, volunteer.name)
        self.assertTrue(rows)
        self.assertTrue(all(r["activity_type"] == "Workshop" for r in rows))

    def test_filter_by_activity_scope(self):
        _member, volunteer = self._make_volunteer()
        tag = f"scope-{self.suffix}"
        self._make_activity(volunteer, [tag], activity_scope="External")
        self._make_activity(volunteer, [tag], activity_scope="Internal")

        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute({"activity_scope": "External"})
        rows = self._rows_for_volunteer(data, volunteer.name)
        self.assertTrue(rows)
        self.assertTrue(all(r["activity_scope"] == "External" for r in rows))

    def test_explicit_status_filter(self):
        _member, volunteer = self._make_volunteer()
        tag = f"status-{self.suffix}"
        self._make_activity(volunteer, [tag], status="Completed")
        self._make_activity(volunteer, [tag], status="Active")

        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute({"status": "Completed"})
        rows = self._rows_for_volunteer(data, volunteer.name)
        self.assertTrue(rows)
        self.assertTrue(all(r["status"] == "Completed" for r in rows))

    def test_default_status_excludes_cancelled_when_filters_present(self):
        # The default Active/Completed status restriction is only applied inside
        # the ``if filters:`` block, so it kicks in when *some* (non-status)
        # filter is supplied. Use a tag filter to reach that branch.
        _member, volunteer = self._make_volunteer()
        tag = f"cancel-{self.suffix}"
        self._make_activity(volunteer, [tag], status="Cancelled")

        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute({"tag": tag})
        rows = self._rows_for_volunteer(data, volunteer.name)
        self.assertEqual(rows, [], "Cancelled activities are excluded once a filter is applied")

    def test_empty_filters_dict_bypasses_default_status_restriction(self):
        # Quirk: report.execute({}) passes a falsy filters dict, so the whole
        # ``if filters:`` block (including the default Active/Completed status
        # restriction) is skipped -- Cancelled activities DO show. FLAGGED for the
        # caller; documented here so the behaviour is pinned rather than fixed.
        _member, volunteer = self._make_volunteer()
        tag = f"emptyfilter-{self.suffix}"
        self._make_activity(volunteer, [tag], status="Cancelled")

        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute({})
        rows = self._rows_for_volunteer(data, volunteer.name)
        self.assertTrue(
            any(r["status"] == "Cancelled" for r in rows),
            "empty filters dict shows all statuses (default restriction not applied)",
        )

    def test_filter_by_date_range(self):
        _member, volunteer = self._make_volunteer()
        tag = f"date-{self.suffix}"
        self._make_activity(volunteer, [tag], start_date=add_days(today(), -100))
        self._make_activity(volunteer, [tag], start_date=today())

        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute(
                {"from_date": add_days(today(), -10), "to_date": today()}
            )
        rows = self._rows_for_volunteer(data, volunteer.name)
        self.assertTrue(rows)
        self.assertTrue(all(str(r["start_date"]) >= str(add_days(today(), -10)) for r in rows))

    # --------------------------------------------------------- empty result

    def test_empty_result_returns_no_chart_and_message(self):
        # A tag that no activity carries -> empty data, None chart, no-match message.
        with self.assertNoErrorLog():
            columns, data, message, chart = report.execute({"tag": f"nonexistent-{self.suffix}"})
        self.assertEqual(data, [])
        self.assertIsNone(chart)
        self.assertIn("No activities found", message)
