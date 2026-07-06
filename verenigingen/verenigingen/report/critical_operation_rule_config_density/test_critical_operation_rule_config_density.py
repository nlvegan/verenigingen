# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Smoke tests for the Critical Operation Rule Config Density report.

The report is read-only and derives everything from existing COR rows, so these
tests assert the structural invariants of execute() rather than seeding data:
a valid Frappe 5-tuple, non-negative/bounded counts, monotonic cumulative
coverage that reaches ~100%, and correct filter narrowing.
"""

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.critical_operation_rule_config_density.critical_operation_rule_config_density import (  # noqa: E501
    execute,
)


class TestCriticalOperationRuleConfigDensity(VereningingenTestCase):
    def test_execute_returns_valid_frappe_tuple(self):
        result = execute({})
        self.assertEqual(len(result), 5, "report must return the 5-element Frappe tuple")
        columns, data, message, chart, summary = result
        self.assertIsInstance(columns, list)
        self.assertTrue(columns, "columns must be non-empty")
        for col in columns:
            self.assertIn("fieldname", col)
            self.assertIn("label", col)
        self.assertIsInstance(data, list)
        self.assertIsInstance(summary, list)

    def test_row_counts_are_bounded_and_coverage_completes(self):
        _cols, data, _m, _c, _s = execute({})
        if not data:
            self.skipTest("no Critical Operation Rule rows present on this site")
        prev_cumulative = 0.0
        prev_count = None
        for row in data:
            self.assertGreaterEqual(row["endpoints"], 1)
            self.assertGreaterEqual(row["pct"], 0)
            self.assertLessEqual(row["pct"], 100)
            # cumulative is monotonic non-decreasing
            self.assertGreaterEqual(row["cumulative_pct"] + 0.01, prev_cumulative)
            prev_cumulative = row["cumulative_pct"]
            # groups are sorted by endpoint count descending
            if prev_count is not None:
                self.assertLessEqual(row["endpoints"], prev_count)
            prev_count = row["endpoints"]
        # every enabled row is accounted for -> coverage reaches ~100%
        self.assertAlmostEqual(data[-1]["cumulative_pct"], 100.0, delta=0.5)

    def test_summary_reports_distinct_le_endpoints(self):
        _cols, data, _m, _c, summary = execute({})
        if not data:
            self.skipTest("no Critical Operation Rule rows present on this site")
        cards = {c["label"]: c["value"] for c in summary}
        # distinct configs can never exceed the endpoint count
        self.assertLessEqual(cards["Distinct configs"], cards["Endpoints"])
        # the report collapses rows: #rows returned == #distinct configs
        self.assertEqual(len(data), cards["Distinct configs"])

    def test_filter_narrows_result(self):
        _cols, all_data, _m, _c, all_summary = execute({})
        if not all_data:
            self.skipTest("no Critical Operation Rule rows present on this site")
        _fc, f_data, _fm, _fc2, f_summary = execute({"security_level": "critical"})
        all_endpoints = {c["label"]: c["value"] for c in all_summary}["Endpoints"]
        if f_summary:
            f_endpoints = {c["label"]: c["value"] for c in f_summary}["Endpoints"]
            self.assertLessEqual(f_endpoints, all_endpoints)
            for row in f_data:
                self.assertEqual(row["security_level"], "critical")
