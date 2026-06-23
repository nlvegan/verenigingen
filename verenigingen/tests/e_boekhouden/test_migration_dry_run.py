"""
Coverage tests for verenigingen/utils/migration/migration_dry_run.py

DryRunSimulator simulates migration record creation/update WITHOUT writing to the
DB, accumulating statistics, financial impact and a report. The financial-impact
math, statistics roll-ups, report generation and recommendation logic are pure;
record validation calls frappe.new_doc(...)._validate() and frappe.db.exists for
real, which we drive with simple Account/Customer dicts.

Run with:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_dry_run
"""

import unittest

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.migration.migration_dry_run import DryRunSimulator


class TestStatKeysAndFinancialImpact(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.sim = DryRunSimulator()

    def test_stat_key_mapping(self):
        self.assertEqual(self.sim._get_stat_key("Sales Invoice"), "sales_invoices")
        self.assertEqual(self.sim._get_stat_key("Payment Entry"), "payment_entries")
        self.assertIsNone(self.sim._get_stat_key("Not A Doctype"))

    def test_sales_invoice_financial_impact(self):
        impact = self.sim._calculate_financial_impact(
            "Sales Invoice", {"grand_total": 121.0, "debit_to": "Debtors"}
        )
        self.assertEqual(impact["debit"], 121.0)
        self.assertEqual(impact["credit"], 121.0)
        # Running totals updated on the simulator.
        self.assertEqual(self.sim.financial_impact["total_debit"], 121.0)
        self.assertEqual(self.sim.financial_impact["gl_entries_count"], 1)
        self.assertIn("Debtors", self.sim.financial_impact["accounts_affected"])

    def test_journal_entry_financial_impact_sums_lines(self):
        impact = self.sim._calculate_financial_impact(
            "Journal Entry",
            {
                "accounts": [
                    {"account": "A", "debit_in_account_currency": 50},
                    {"account": "B", "credit_in_account_currency": 50},
                ]
            },
        )
        self.assertEqual(impact["debit"], 50)
        self.assertEqual(impact["credit"], 50)
        self.assertEqual(set(impact["accounts"]), {"A", "B"})

    def test_would_create_gl_entries(self):
        self.assertTrue(self.sim._would_create_gl_entries("Sales Invoice", {}))
        self.assertFalse(self.sim._would_create_gl_entries("Customer", {}))

    def test_record_exists_or_simulated_finds_simulated_customer(self):
        # A customer "created" in the simulation should be discoverable by name.
        self.sim.simulated_records["Customer"] = [
            {"name": "SIM-Customer-0", "data": {"customer_name": "ACME"}}
        ]
        self.assertTrue(self.sim._record_exists_or_simulated("Customer", "ACME"))
        self.assertFalse(self.sim._record_exists_or_simulated("Customer", "Nonexistent Co XYZ"))


class TestSimulateCreation(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.sim = DryRunSimulator()

    def test_simulate_valid_customer_creation(self):
        # A Customer needs only a customer_name to validate -> would_create path.
        with self.assertNoErrorLog():
            result = self.sim.simulate_record_creation("Customer", {"customer_name": "Sim Test Customer"})
        self.assertTrue(result["success"], result)
        # simulated_name must be interpolated (regression: was a literal f-less str).
        self.assertTrue(result["simulated_name"].startswith("SIM-Customer-"))
        self.assertNotIn("{", result["simulated_name"])
        self.assertEqual(self.sim.statistics["customers"]["would_create"], 1)

    def test_simulate_invalid_record_records_failure(self):
        # A bogus doctype cannot build a document -> validation fails, would_fail
        # path runs and a validation error is recorded.
        result = self.sim.simulate_record_creation("Not A Real Doctype", {"x": 1})
        self.assertFalse(result["success"])
        self.assertTrue(self.sim.validation_errors)


class TestReportGeneration(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.sim = DryRunSimulator()

    def test_empty_report_recommends_no_data(self):
        # Regression: generate_dry_run_report -> _generate_recommendations raised
        # KeyError("would_fail") on the customers/suppliers buckets, so NO report
        # could ever be produced. It must now build cleanly.
        with self.assertNoErrorLog():
            report = self.sim.generate_dry_run_report()
        self.assertEqual(report["summary"]["total_records_analyzed"], 0)
        rec_types = [r["type"] for r in report["recommendations"]]
        self.assertIn("no_data", rec_types)

    def test_unbalanced_impact_triggers_recommendation(self):
        # Skew the financial impact so debit != credit.
        self.sim.financial_impact["total_debit"] = 100
        self.sim.financial_impact["total_credit"] = 40
        # Also give it some processed records so "no_data" doesn't dominate.
        self.sim.statistics["accounts"]["would_create"] = 1
        recs = self.sim._generate_recommendations()
        types = [r["type"] for r in recs]
        self.assertIn("unbalanced_entries", types)
        # Message must be interpolated (regression: was f-less).
        msg = next(r["message"] for r in recs if r["type"] == "unbalanced_entries")
        self.assertNotIn("{balance}", msg)

    def test_high_failure_rate_recommendation(self):
        self.sim.statistics["sales_invoices"]["would_fail"] = 9
        self.sim.statistics["sales_invoices"]["would_create"] = 1
        recs = self.sim._generate_recommendations()
        self.assertIn("high_failure_rate", [r["type"] for r in recs])

    def test_report_financial_balance_calculation(self):
        self.sim.financial_impact["total_debit"] = 75
        self.sim.financial_impact["total_credit"] = 75
        report = self.sim.generate_dry_run_report()
        self.assertEqual(report["financial_impact"]["balance"], 0)
        self.assertEqual(report["financial_impact"]["total_debit"], 75)

    def test_extract_warnings_collects_from_simulated_records(self):
        self.sim.simulated_records["Account"] = [
            {
                "name": "SIM-Account-0",
                "validation": {"warnings": ["parent may not exist"]},
            }
        ]
        warnings = self.sim._extract_warnings()
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["doctype"], "Account")
        self.assertEqual(warnings[0]["warning"], "parent may not exist")


if __name__ == "__main__":
    unittest.main()
