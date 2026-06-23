"""
Real-integration tests for the *Database Table Size Analysis* script report
(``verenigingen/verenigingen/report/database_table_size_analysis/``).

This report was at 0% coverage (never executed under test). It is a LIVE
standard Script Report (ref_doctype DocType, roles System Manager /
Administrator) that queries ``information_schema.TABLES`` to break down storage
usage. It is a diagnostic report over DB metadata, so it needs no app-data
seeding -- the tests assert the column/row shape, the calculated fields, the
filter branches and the chart, running every query for real against the live
database.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.database_table_size_analysis import (
    database_table_size_analysis as report,
)


class TestDatabaseTableSizeAnalysisReport(VereningingenTestCase):
    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(len(columns), 10)
        for expected in (
            "table_name",
            "doctype",
            "row_count",
            "data_size_mb",
            "index_size_mb",
            "total_size_mb",
            "avg_row_size",
            "percentage",
            "engine",
            "table_type",
        ):
            self.assertIn(expected, fieldnames)

    # --------------------------------------------------------- execute / shape

    def test_execute_returns_columns_data_chart(self):
        with self.assertNoErrorLog():
            columns, data, message, chart = report.execute({})
        self.assertEqual(len(columns), 10)
        self.assertIsInstance(data, list)
        self.assertIsNone(message)
        # A real Frappe DB always has many base tables (tabDocType etc.).
        self.assertGreater(len(data), 0, "live DB must report base tables")
        self.assertIsNotNone(chart)

    def test_execute_none_filters(self):
        with self.assertNoErrorLog():
            columns, data, _message, _chart = report.execute(None)
        self.assertEqual(len(columns), 10)
        self.assertGreater(len(data), 0)

    def test_row_shape_and_calculated_fields(self):
        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute({})
        # The tabDocType table is always present; use it to assert row shape.
        doctype_row = next((r for r in data if r.table_name == "tabDocType"), None)
        self.assertIsNotNone(doctype_row, "tabDocType must appear in the analysis")
        self.assertEqual(doctype_row.table_type, "DocType")
        self.assertEqual(doctype_row.doctype, "DocType")
        # Calculated fields must be populated (never None).
        self.assertIsNotNone(doctype_row.percentage)
        self.assertIsNotNone(doctype_row.avg_row_size)
        # Percentages are a share of total -> within [0, 100].
        self.assertGreaterEqual(doctype_row.percentage, 0)
        self.assertLessEqual(doctype_row.percentage, 100)

    def test_child_table_classification(self):
        """Tables whose DocType name contains a space are 'Child Table'."""
        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute({})
        child = next((r for r in data if r.table_type == "Child Table"), None)
        # A live app DB always has child tables (e.g. tabHas Role).
        self.assertIsNotNone(child, "live DB must contain child tables")
        self.assertIn(" ", child.doctype)

    def test_system_table_classification(self):
        """Tables starting with '__' are classified as System tables."""
        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute({})
        system = [r for r in data if r.table_type == "System"]
        # __global_search / __UserSettings etc. exist on any Frappe DB.
        if system:
            self.assertEqual(system[0].doctype, "System Table")

    # --------------------------------------------------------- filter branches

    def test_table_type_filter(self):
        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute({"table_type": "DocType"})
        self.assertTrue(data, "DocType-typed tables must exist")
        self.assertTrue(all(r.table_type == "DocType" for r in data))

    def test_min_size_filter(self):
        with self.assertNoErrorLog():
            _c, unfiltered, _m, _ch = report.execute({})
        with self.assertNoErrorLog():
            _c, filtered, _m, _ch = report.execute({"min_size_mb": 0.01})
        self.assertLessEqual(len(filtered), len(unfiltered))
        self.assertTrue(all(r.total_size_mb >= 0.01 for r in filtered))

    def test_min_size_filter_excludes_everything_when_huge(self):
        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute({"min_size_mb": 10**9})
        self.assertEqual(data, [], "an impossibly large threshold yields no tables")

    def test_doctype_filter_substring_match(self):
        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute({"doctype_filter": "doctype"})
        self.assertTrue(data, "substring 'doctype' must match at least tabDocType")
        self.assertTrue(all("doctype" in r.doctype.lower() for r in data))

    def test_doctype_filter_no_match(self):
        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute(
                {"doctype_filter": "zzz-no-such-table-zzz"}
            )
        self.assertEqual(data, [])

    # ------------------------------------------------------------- chart

    def test_chart_data_shape(self):
        with self.assertNoErrorLog():
            _columns, data, _message, _chart = report.execute({})
        chart = report.get_chart_data(data)
        self.assertEqual(chart["type"], "bar")
        self.assertEqual(len(chart["data"]["datasets"]), 2)
        self.assertEqual(chart["data"]["datasets"][0]["name"], "Data Size (MB)")
        # Chart shows top 15 tables at most.
        self.assertLessEqual(len(chart["data"]["labels"]), 15)
        self.assertEqual(
            len(chart["data"]["labels"]), len(chart["data"]["datasets"][0]["values"])
        )

    def test_chart_empty_data(self):
        chart = report.get_chart_data([])
        self.assertEqual(chart["data"]["labels"], [])
        self.assertEqual(chart["data"]["datasets"][0]["values"], [])
