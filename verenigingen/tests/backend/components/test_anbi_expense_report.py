"""
Unit tests for ANBI Expense Report

Tests the ANBI compliance reporting functionality that combines:
- Personnel cost allocations from Staff ANBI Allocation
- GL expenses from ANBI parent accounts (61, 62, 63)

The report produces a summary showing expense breakdown by ANBI category
for Dutch non-profit regulatory compliance.
"""

from unittest.mock import patch, MagicMock

import frappe
from frappe import _dict
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen.report.anbi_expense_report.anbi_expense_report import (
    ANBI_EXPENSE_CATEGORIES,
    ANBI_ACCOUNT_NUMBERS,
    execute,
    get_columns,
    get_data,
    get_gl_expenses_by_anbi_parent,
    get_personnel_allocations,
    get_default_company,
    get_chart,
    get_summary,
)


class TestANBIExpenseReportConstants(FrappeTestCase):
    """Test ANBI expense report constants"""

    def test_anbi_categories_defined(self):
        """Test that ANBI categories are properly defined"""
        self.assertIn("61", ANBI_EXPENSE_CATEGORIES)
        self.assertIn("62", ANBI_EXPENSE_CATEGORIES)
        self.assertIn("63", ANBI_EXPENSE_CATEGORIES)

    def test_anbi_category_61_is_doelstelling(self):
        """Test that account 61 maps to program costs"""
        cat = ANBI_EXPENSE_CATEGORIES["61"]
        self.assertEqual(cat["name"], "Besteed aan doelstellingen")
        self.assertEqual(cat["description"], "Program costs")

    def test_anbi_category_62_is_werving(self):
        """Test that account 62 maps to fundraising costs"""
        cat = ANBI_EXPENSE_CATEGORIES["62"]
        self.assertEqual(cat["name"], "Kosten werving baten")
        self.assertEqual(cat["description"], "Fundraising costs")

    def test_anbi_category_63_is_beheer(self):
        """Test that account 63 maps to administration costs"""
        cat = ANBI_EXPENSE_CATEGORIES["63"]
        self.assertEqual(cat["name"], "Beheer en administratie")
        self.assertEqual(cat["description"], "Administration costs")

    def test_anbi_account_numbers_list(self):
        """Test that account numbers list matches categories"""
        self.assertEqual(ANBI_ACCOUNT_NUMBERS, ["61", "62", "63"])
        self.assertEqual(set(ANBI_ACCOUNT_NUMBERS), set(ANBI_EXPENSE_CATEGORIES.keys()))


class TestANBIExpenseReportColumns(FrappeTestCase):
    """Test report column definitions"""

    def test_get_columns_returns_list(self):
        """Test that get_columns returns a list"""
        columns = get_columns()
        self.assertIsInstance(columns, list)

    def test_get_columns_has_required_fields(self):
        """Test that columns include required fields"""
        columns = get_columns()
        fieldnames = [col["fieldname"] for col in columns]

        required = ["category", "account_number", "personnel_costs",
                    "other_expenses", "total", "percentage"]
        for field in required:
            self.assertIn(field, fieldnames)

    def test_columns_have_proper_structure(self):
        """Test that each column has required properties"""
        columns = get_columns()

        for col in columns:
            self.assertIn("fieldname", col)
            self.assertIn("label", col)
            self.assertIn("fieldtype", col)
            self.assertIn("width", col)


class TestANBIExpenseReportData(FrappeTestCase):
    """Test report data generation"""

    def setUp(self):
        super().setUp()
        self.test_filters = {
            "company": "Test Company",
            "fiscal_year": "2024"
        }

    def test_get_data_returns_list(self):
        """Test that get_data returns a list"""
        with patch.object(frappe.db, "get_value", return_value=_dict(
            year_start_date="2024-01-01",
            year_end_date="2024-12-31"
        )):
            with patch(
                "verenigingen.verenigingen.report.anbi_expense_report.anbi_expense_report.get_gl_expenses_by_anbi_parent",
                return_value={"61": 0, "62": 0, "63": 0}
            ):
                with patch(
                    "verenigingen.verenigingen.report.anbi_expense_report.anbi_expense_report.get_personnel_allocations",
                    return_value={"61": 0, "62": 0, "63": 0}
                ):
                    data = get_data(self.test_filters)
                    self.assertIsInstance(data, list)

    def test_get_data_returns_three_categories_plus_total(self):
        """Test that data includes 3 ANBI categories plus total row"""
        with patch.object(frappe.db, "get_value", return_value=_dict(
            year_start_date="2024-01-01",
            year_end_date="2024-12-31"
        )):
            with patch(
                "verenigingen.verenigingen.report.anbi_expense_report.anbi_expense_report.get_gl_expenses_by_anbi_parent",
                return_value={"61": 1000, "62": 500, "63": 300}
            ):
                with patch(
                    "verenigingen.verenigingen.report.anbi_expense_report.anbi_expense_report.get_personnel_allocations",
                    return_value={"61": 5000, "62": 2000, "63": 1000}
                ):
                    data = get_data(self.test_filters)

                    # 3 categories + 1 total row
                    self.assertEqual(len(data), 4)

                    # Check category rows
                    categories = [row for row in data if not row.get("is_total")]
                    self.assertEqual(len(categories), 3)

                    # Check total row
                    total_row = next(row for row in data if row.get("is_total"))
                    self.assertTrue(total_row["is_total"])

    def test_get_data_calculates_totals_correctly(self):
        """Test that totals are calculated correctly"""
        with patch.object(frappe.db, "get_value", return_value=_dict(
            year_start_date="2024-01-01",
            year_end_date="2024-12-31"
        )):
            with patch(
                "verenigingen.verenigingen.report.anbi_expense_report.anbi_expense_report.get_gl_expenses_by_anbi_parent",
                return_value={"61": 10000, "62": 5000, "63": 3000}
            ):
                with patch(
                    "verenigingen.verenigingen.report.anbi_expense_report.anbi_expense_report.get_personnel_allocations",
                    return_value={"61": 50000, "62": 20000, "63": 10000}
                ):
                    data = get_data(self.test_filters)

                    # Find doelstelling row (account 61)
                    doelstelling = next(r for r in data if r.get("account_number") == "61")
                    self.assertEqual(doelstelling["personnel_costs"], 50000)
                    self.assertEqual(doelstelling["other_expenses"], 10000)
                    self.assertEqual(doelstelling["total"], 60000)

                    # Find total row
                    total_row = next(r for r in data if r.get("is_total"))
                    self.assertEqual(total_row["total"], 98000)  # 60000 + 25000 + 13000

    def test_get_data_calculates_percentages(self):
        """Test that percentages are calculated correctly"""
        with patch.object(frappe.db, "get_value", return_value=_dict(
            year_start_date="2024-01-01",
            year_end_date="2024-12-31"
        )):
            with patch(
                "verenigingen.verenigingen.report.anbi_expense_report.anbi_expense_report.get_gl_expenses_by_anbi_parent",
                return_value={"61": 0, "62": 0, "63": 0}
            ):
                with patch(
                    "verenigingen.verenigingen.report.anbi_expense_report.anbi_expense_report.get_personnel_allocations",
                    return_value={"61": 70000, "62": 20000, "63": 10000}  # 70/20/10 split
                ):
                    data = get_data(self.test_filters)

                    doelstelling = next(r for r in data if r.get("account_number") == "61")
                    self.assertAlmostEqual(doelstelling["percentage"], 70.0, places=1)

    def test_get_data_handles_missing_fiscal_year(self):
        """Test that missing fiscal year returns empty list"""
        with patch.object(frappe.db, "get_value", return_value=None):
            data = get_data(self.test_filters)
            self.assertEqual(data, [])


class TestANBIExpenseReportGLExpenses(FrappeTestCase):
    """Test GL expense retrieval"""

    def test_get_gl_expenses_returns_dict(self):
        """Test that get_gl_expenses returns a dictionary"""
        with patch.object(frappe.db, "get_value", return_value=None):
            result = get_gl_expenses_by_anbi_parent(
                "Test Company", "2024-01-01", "2024-12-31"
            )
            self.assertIsInstance(result, dict)

    def test_get_gl_expenses_returns_zero_for_missing_accounts(self):
        """Test that missing accounts return zero"""
        with patch.object(frappe.db, "get_value", return_value=None):
            result = get_gl_expenses_by_anbi_parent(
                "Test Company", "2024-01-01", "2024-12-31"
            )

            for acc_num in ANBI_ACCOUNT_NUMBERS:
                self.assertEqual(result[acc_num], 0)

    def test_get_gl_expenses_uses_nested_set_model(self):
        """Test that GL query uses nested set lft/rgt bounds"""
        mock_parent = _dict(name="61 - ANBI", lft=10, rgt=20)

        with patch.object(frappe.db, "get_value", return_value=mock_parent):
            with patch.object(frappe.db, "sql", return_value=[_dict(total_expense=5000)]) as mock_sql:
                result = get_gl_expenses_by_anbi_parent(
                    "Test Company", "2024-01-01", "2024-12-31"
                )

                # Verify SQL was called with lft/rgt bounds
                call_args = mock_sql.call_args
                sql_query = call_args[0][0]
                self.assertIn("acc.lft >", sql_query)
                self.assertIn("acc.rgt <", sql_query)


class TestANBIExpenseReportPersonnelAllocations(FrappeTestCase):
    """Test personnel allocation retrieval"""

    def test_get_personnel_allocations_returns_dict(self):
        """Test that get_personnel_allocations returns a dictionary"""
        with patch.object(frappe, "get_all", return_value=[]):
            result = get_personnel_allocations("2024")
            self.assertIsInstance(result, dict)

    def test_get_personnel_allocations_initializes_all_categories(self):
        """Test that all ANBI categories are initialized"""
        with patch.object(frappe, "get_all", return_value=[]):
            result = get_personnel_allocations("2024")

            for acc_num in ANBI_ACCOUNT_NUMBERS:
                self.assertIn(acc_num, result)
                self.assertEqual(result[acc_num], 0)

    def test_get_personnel_allocations_sums_correctly(self):
        """Test that personnel allocations are summed correctly"""
        mock_allocations = [
            _dict(amount_doelstelling=35000, amount_werving=10000, amount_beheer=5000),
            _dict(amount_doelstelling=24000, amount_werving=12000, amount_beheer=4000),
        ]

        with patch.object(frappe, "get_all", return_value=mock_allocations):
            result = get_personnel_allocations("2024")

            self.assertEqual(result["61"], 59000)  # 35000 + 24000
            self.assertEqual(result["62"], 22000)  # 10000 + 12000
            self.assertEqual(result["63"], 9000)   # 5000 + 4000

    def test_get_personnel_allocations_handles_null_values(self):
        """Test that null allocation amounts are treated as zero"""
        mock_allocations = [
            _dict(amount_doelstelling=35000, amount_werving=None, amount_beheer=None),
        ]

        with patch.object(frappe, "get_all", return_value=mock_allocations):
            result = get_personnel_allocations("2024")

            self.assertEqual(result["61"], 35000)
            self.assertEqual(result["62"], 0)
            self.assertEqual(result["63"], 0)


class TestANBIExpenseReportChart(FrappeTestCase):
    """Test chart generation"""

    def test_get_chart_returns_none_for_empty_data(self):
        """Test that empty data returns None chart"""
        chart = get_chart([])
        self.assertIsNone(chart)

    def test_get_chart_returns_none_for_insufficient_data(self):
        """Test that less than 3 rows returns None chart"""
        data = [{"category": "Test", "total": 100}]
        chart = get_chart(data)
        self.assertIsNone(chart)

    def test_get_chart_returns_pie_chart(self):
        """Test that chart is a pie chart"""
        data = [
            {"category": "Doelstelling", "account_number": "61", "total": 60000},
            {"category": "Werving", "account_number": "62", "total": 25000},
            {"category": "Beheer", "account_number": "63", "total": 15000},
            {"category": "TOTAL", "total": 100000, "is_total": True},
        ]
        chart = get_chart(data)

        self.assertIsNotNone(chart)
        self.assertEqual(chart["type"], "pie")

    def test_get_chart_excludes_total_row(self):
        """Test that total row is excluded from chart"""
        data = [
            {"category": "Doelstelling", "account_number": "61", "total": 60000},
            {"category": "Werving", "account_number": "62", "total": 25000},
            {"category": "Beheer", "account_number": "63", "total": 15000},
            {"category": "TOTAL", "total": 100000, "is_total": True},
        ]
        chart = get_chart(data)

        # Should have 3 labels, not 4
        self.assertEqual(len(chart["data"]["labels"]), 3)
        self.assertNotIn("TOTAL", chart["data"]["labels"])

    def test_get_chart_has_colors(self):
        """Test that chart has color configuration"""
        data = [
            {"category": "Doelstelling", "account_number": "61", "total": 60000},
            {"category": "Werving", "account_number": "62", "total": 25000},
            {"category": "Beheer", "account_number": "63", "total": 15000},
        ]
        chart = get_chart(data)

        self.assertIn("colors", chart)
        self.assertEqual(len(chart["colors"]), 3)


class TestANBIExpenseReportSummary(FrappeTestCase):
    """Test summary generation"""

    def test_get_summary_returns_empty_for_no_data(self):
        """Test that empty data returns empty summary"""
        summary = get_summary([])
        self.assertEqual(summary, [])

    def test_get_summary_returns_empty_for_no_total_row(self):
        """Test that missing total row returns empty summary"""
        data = [
            {"category": "Doelstelling", "account_number": "61", "total": 60000},
        ]
        summary = get_summary(data)
        self.assertEqual(summary, [])

    def test_get_summary_includes_required_cards(self):
        """Test that summary includes required summary cards"""
        data = [
            {"category": "Doelstelling", "account_number": "61", "total": 60000, "percentage": 70},
            {"category": "Werving", "account_number": "62", "total": 20000, "percentage": 20},
            {"category": "Beheer", "account_number": "63", "total": 10000, "percentage": 10},
            {
                "category": "TOTAL",
                "total": 90000,
                "personnel_costs": 70000,
                "other_expenses": 20000,
                "is_total": True
            },
        ]
        summary = get_summary(data)

        labels = [card["label"] for card in summary]
        self.assertIn("Total Expenses", labels)
        self.assertIn("Personnel Costs", labels)
        self.assertIn("Other Expenses", labels)

    def test_get_summary_includes_mission_percentage(self):
        """Test that summary includes % to Mission indicator"""
        data = [
            {"category": "Doelstelling", "account_number": "61", "total": 70000, "percentage": 70},
            {"category": "Werving", "account_number": "62", "total": 20000, "percentage": 20},
            {"category": "Beheer", "account_number": "63", "total": 10000, "percentage": 10},
            {
                "category": "TOTAL",
                "total": 100000,
                "personnel_costs": 80000,
                "other_expenses": 20000,
                "is_total": True
            },
        ]
        summary = get_summary(data)

        mission_card = next((c for c in summary if c["label"] == "% to Mission"), None)
        self.assertIsNotNone(mission_card)
        self.assertEqual(mission_card["value"], 70)

    def test_get_summary_green_indicator_for_high_mission(self):
        """Test that 70%+ to mission shows green indicator"""
        data = [
            {"category": "Doelstelling", "account_number": "61", "total": 75000, "percentage": 75},
            {"category": "Werving", "account_number": "62", "total": 15000, "percentage": 15},
            {"category": "Beheer", "account_number": "63", "total": 10000, "percentage": 10},
            {"category": "TOTAL", "total": 100000, "personnel_costs": 80000, "other_expenses": 20000, "is_total": True},
        ]
        summary = get_summary(data)

        mission_card = next((c for c in summary if c["label"] == "% to Mission"), None)
        self.assertEqual(mission_card["indicator"], "green")

    def test_get_summary_orange_indicator_for_low_mission(self):
        """Test that less than 70% to mission shows orange indicator"""
        data = [
            {"category": "Doelstelling", "account_number": "61", "total": 60000, "percentage": 60},
            {"category": "Werving", "account_number": "62", "total": 25000, "percentage": 25},
            {"category": "Beheer", "account_number": "63", "total": 15000, "percentage": 15},
            {"category": "TOTAL", "total": 100000, "personnel_costs": 80000, "other_expenses": 20000, "is_total": True},
        ]
        summary = get_summary(data)

        mission_card = next((c for c in summary if c["label"] == "% to Mission"), None)
        self.assertEqual(mission_card["indicator"], "orange")


class TestANBIExpenseReportExecute(FrappeTestCase):
    """Test complete report execution"""

    def test_execute_returns_5_tuple(self):
        """Test that execute returns proper 5-tuple structure"""
        filters = {"company": "Test Company", "fiscal_year": "2024"}

        with patch.object(frappe.db, "get_value", return_value=_dict(
            year_start_date="2024-01-01",
            year_end_date="2024-12-31"
        )):
            with patch(
                "verenigingen.verenigingen.report.anbi_expense_report.anbi_expense_report.get_gl_expenses_by_anbi_parent",
                return_value={"61": 0, "62": 0, "63": 0}
            ):
                with patch(
                    "verenigingen.verenigingen.report.anbi_expense_report.anbi_expense_report.get_personnel_allocations",
                    return_value={"61": 0, "62": 0, "63": 0}
                ):
                    result = execute(filters)

                    self.assertIsInstance(result, tuple)
                    self.assertEqual(len(result), 5)

                    columns, data, message, chart, summary = result
                    self.assertIsInstance(columns, list)
                    self.assertIsInstance(data, list)
                    self.assertIsNone(message)

    def test_execute_with_real_data_structure(self):
        """Test execute with realistic data structure"""
        filters = {"company": "Test Company", "fiscal_year": "2024"}

        with patch.object(frappe.db, "get_value", return_value=_dict(
            year_start_date="2024-01-01",
            year_end_date="2024-12-31"
        )):
            with patch(
                "verenigingen.verenigingen.report.anbi_expense_report.anbi_expense_report.get_gl_expenses_by_anbi_parent",
                return_value={"61": 15000, "62": 8000, "63": 5000}
            ):
                with patch(
                    "verenigingen.verenigingen.report.anbi_expense_report.anbi_expense_report.get_personnel_allocations",
                    return_value={"61": 60000, "62": 25000, "63": 15000}
                ):
                    columns, data, message, chart, summary = execute(filters)

                    # Verify data structure
                    self.assertEqual(len(data), 4)  # 3 categories + total

                    # Verify totals
                    total_row = next(r for r in data if r.get("is_total"))
                    self.assertEqual(total_row["total"], 128000)

                    # Verify chart exists
                    self.assertIsNotNone(chart)
                    self.assertEqual(chart["type"], "pie")

                    # Verify summary exists
                    self.assertGreater(len(summary), 0)


class TestANBIExpenseReportDefaultCompany(FrappeTestCase):
    """Test default company retrieval"""

    def test_get_default_company_from_verenigingen_settings(self):
        """Test that default company comes from Verenigingen Settings"""
        with patch.object(frappe.db, "get_single_value", side_effect=["Test Company", None]):
            company = get_default_company()
            self.assertEqual(company, "Test Company")

    def test_get_default_company_fallback_to_global_defaults(self):
        """Test fallback to Global Defaults when Verenigingen Settings empty"""
        with patch.object(frappe.db, "get_single_value", side_effect=[None, "Fallback Company"]):
            company = get_default_company()
            self.assertEqual(company, "Fallback Company")


if __name__ == "__main__":
    import unittest
    unittest.main()
