"""
Integration tests for verenigingen/api/dashboard_charts.py

Covers get_member_age_distribution_chart(), a @standard_api(REPORTING) +
@frappe.whitelist() endpoint that returns an OperationResult.

IMPORTANT — return shape: the @standard_api decorator converts the returned
OperationResult into a NESTED dict for JSON serialisation. Calling the function
directly (as these tests do) therefore yields:

    {"success": True, "timestamp": ..., "data": {...}, "meta": {...}}

on success, where the chart payload lives under "data". These tests assert
against that real, observed shape (not a flat dict, not a bare OperationResult).
"""

import frappe
from frappe.utils import add_years, today

from verenigingen.api.dashboard_charts import get_member_age_distribution_chart
from verenigingen.tests.utils.base import VereningingenTestCase


class TestMemberAgeDistributionChart(VereningingenTestCase):
    """Real integration tests for the member age distribution chart endpoint."""

    def _bucket_value(self, chart_data, bucket_label):
        """Return the count for a given age bucket in a chart payload, or 0.

        The chart payload only lists non-empty buckets (labels/values are
        filtered), so an absent bucket means a count of zero.
        """
        labels = chart_data["labels"]
        values = chart_data["datasets"][0]["values"]
        if bucket_label in labels:
            return values[labels.index(bucket_label)]
        return 0

    def _get_chart_data(self):
        """Call the endpoint and assert the nested-dict success envelope."""
        result = get_member_age_distribution_chart()
        # Decorator serialises OperationResult -> nested dict
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"], f"Chart endpoint failed: {result}")
        self.assertIn("data", result)
        return result["data"]

    def test_returns_nested_success_envelope(self):
        """Endpoint returns the nested success envelope, not a flat dict/OperationResult."""
        result = get_member_age_distribution_chart()
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertIn("data", result)
        # Failure-only keys must be absent on success
        self.assertNotIn("error", result)
        # Message is carried as metadata under "meta"
        self.assertIn("meta", result)
        self.assertIn("message", result["meta"])

    def test_chart_payload_structure(self):
        """Chart payload has the shape the frontend (member_age_chart.js) consumes."""
        chart_data = self._get_chart_data()
        self.assertEqual(chart_data["type"], "bar")
        self.assertIn("labels", chart_data)
        self.assertIn("datasets", chart_data)
        self.assertEqual(len(chart_data["datasets"]), 1)
        dataset = chart_data["datasets"][0]
        self.assertEqual(dataset["name"], "Members")
        # labels and values must stay aligned (parallel arrays)
        self.assertEqual(len(chart_data["labels"]), len(dataset["values"]))

    def test_active_member_counted_in_correct_bucket(self):
        """An Active member of known age increments exactly the matching bucket.

        Born 30 years ago -> integer age 29 -> falls in the '28-32' bucket.
        Measuring the before/after delta makes this robust against the large
        pre-existing member population.
        """
        before = self._bucket_value(self._get_chart_data(), "28-32")

        member = self.create_test_member(
            first_name="ChartAge",
            last_name="Bucket2832",
            birth_date=add_years(today(), -30),
        )
        self.assertEqual(member.status, "Active")

        after = self._bucket_value(self._get_chart_data(), "28-32")
        self.assertEqual(
            after,
            before + 1,
            "Active member aged 29 should add exactly one to the 28-32 bucket",
        )

    def test_under_18_bucket(self):
        """A member born ~17 years ago lands in the 'Under 18' bucket.

        Uses age ~17 (not <16) to satisfy the Member minimum-age business rule
        while still resolving to an integer age below 18.
        """
        before = self._bucket_value(self._get_chart_data(), "Under 18")

        self.create_test_member(
            first_name="ChartAge",
            last_name="Minor",
            birth_date=add_years(today(), -17),
        )

        after = self._bucket_value(self._get_chart_data(), "Under 18")
        self.assertEqual(after, before + 1)

    def test_non_active_non_pending_member_excluded(self):
        """Members whose status is not Active/Pending must NOT be counted.

        The SQL filters `status IN ('Active','Pending')`; a Terminated member
        must leave the bucket count unchanged.
        """
        before = self._bucket_value(self._get_chart_data(), "48-52")

        member = self.create_test_member(
            first_name="ChartAge",
            last_name="Excluded",
            birth_date=add_years(today(), -50),
        )
        # Move out of the counted statuses (raw column write; query reads it directly)
        frappe.db.set_value("Member", member.name, "status", "Terminated")

        after = self._bucket_value(self._get_chart_data(), "48-52")
        self.assertEqual(
            after,
            before,
            "Terminated member must be excluded from the age distribution",
        )

    def test_all_labels_are_known_buckets(self):
        """Every returned label is one of the defined ordered age groups."""
        chart_data = self._get_chart_data()
        known = {
            "Under 18", "18-22", "23-27", "28-32", "33-37", "38-42",
            "43-47", "48-52", "53-57", "58-62", "63-67", "68+", "Unknown",
        }
        for label in chart_data["labels"]:
            self.assertIn(label, known)

    def test_no_zero_valued_buckets_returned(self):
        """Empty buckets are filtered out; every returned value is positive."""
        chart_data = self._get_chart_data()
        for value in chart_data["datasets"][0]["values"]:
            self.assertGreater(value, 0)
