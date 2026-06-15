"""
Tests for the eBoekhouden transaction-processor base class and TransactionCoordinator.

Covers the shared helper surface in
``e_boekhouden/utils/processors/base_processor.py`` (amount/date/description
extraction, duplicate checking, row/JE amount validation, error formatting) and
the routing/statistics/prerequisite logic in
``e_boekhouden/utils/processors/transaction_coordinator.py``.

These are real integration tests: a concrete ``StockProcessor`` is used to exercise
the abstract ``BaseTransactionProcessor`` and a real EUR company is used so that
``_get_default_cost_center`` and ``validate_prerequisites`` hit the database.

Run with:
    bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.e_boekhouden.test_processors_base
"""

import frappe

from verenigingen.e_boekhouden.utils.processors.stock_processor import StockProcessor
from verenigingen.e_boekhouden.utils.processors.transaction_coordinator import (
    TransactionCoordinator,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _persist_eur_company():
    """Return a EUR company name, creating a dedicated test company if needed.

    eBoekhouden is a Dutch (EUR) integration; the default ``_Test Company`` on the
    test sites is INR, which would break currency-sensitive logic.
    """
    existing = frappe.db.get_value("Company", {"default_currency": "EUR"}, "name")
    if existing:
        return existing

    company = frappe.new_doc("Company")
    company.company_name = "EBKH EUR Test Co"
    company.abbr = "EETC"
    company.default_currency = "EUR"
    company.country = "Netherlands"
    company.insert(ignore_permissions=True)
    return company.name


class TestBaseProcessorHelpers(EnhancedTestCase):
    """Exercise the shared helpers on BaseTransactionProcessor via StockProcessor."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()

    def _processor(self):
        return StockProcessor(self.company)

    # ---- construction / cost center ----

    def test_default_cost_center_resolved(self):
        """A processor without an explicit cost center resolves one from the company."""
        p = self._processor()
        # May be None if company has no non-group cost center, but attribute is set.
        self.assertTrue(hasattr(p, "cost_center"))

    def test_explicit_cost_center_preserved(self):
        p = StockProcessor(self.company, cost_center="My CC")
        self.assertEqual(p.cost_center, "My CC")

    def test_overwrite_flag_default_false(self):
        self.assertFalse(self._processor().overwrite_existing)

    # ---- debug info ----

    def test_debug_info_add_get_clear(self):
        p = self._processor()
        p.add_debug_info("hello")
        self.assertIn("hello", p.get_debug_info())
        p.clear_debug_info()
        self.assertEqual(p.get_debug_info(), [])

    # ---- validate_mutation (Dutch SOAP field names) ----

    def test_validate_mutation_ok(self):
        ok, msg = self._processor().validate_mutation(
            {"MutatieNr": 1, "Datum": "2025-01-01", "Omschrijving": "x"}
        )
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_validate_mutation_missing_field(self):
        ok, msg = self._processor().validate_mutation({"MutatieNr": 1})
        self.assertFalse(ok)
        self.assertIn("Datum", msg)

    def test_validate_mutation_empty_value(self):
        ok, msg = self._processor().validate_mutation({"MutatieNr": 1, "Datum": "", "Omschrijving": "x"})
        self.assertFalse(ok)

    # ---- check_duplicate ----

    def test_check_duplicate_not_found(self):
        result = self._processor().check_duplicate("ZZ-DOES-NOT-EXIST-123", "Sales Invoice")
        self.assertIsNone(result)

    # ---- get_posting_date / normalize_date wiring ----

    def test_get_posting_date_yyyymmdd(self):
        self.assertEqual(self._processor().get_posting_date({"Datum": "20250110"}), "2025-01-10")

    def test_get_posting_date_iso(self):
        self.assertEqual(self._processor().get_posting_date({"Datum": "2025-01-10T00:00:00"}), "2025-01-10")

    def test_get_posting_date_lowercase_date_field(self):
        self.assertEqual(self._processor().get_posting_date({"date": "2025-01-10"}), "2025-01-10")

    def test_get_posting_date_missing_returns_empty(self):
        """No date field at all -> normalize_date('') is falsy -> empty string."""
        p = self._processor()
        self.assertEqual(p.get_posting_date({}), "")

    # ---- get_description ----

    def test_get_description_appends_mutation_nr(self):
        result = self._processor().get_description({"Omschrijving": "Hi", "MutatieNr": "7"})
        self.assertEqual(result, "Hi (Mutation: 7)")

    def test_get_description_does_not_duplicate_nr(self):
        result = self._processor().get_description({"Omschrijving": "Payment 7 done", "MutatieNr": "7"})
        self.assertEqual(result, "Payment 7 done")

    def test_get_description_empty_falls_back(self):
        result = self._processor().get_description({"Omschrijving": "", "MutatieNr": "7"})
        self.assertIn("7", result)

    def test_get_description_int_mutation_nr(self):
        """Regression: integer MutatieNr must not crash.

        get_description() used to do ``mutation_nr not in description`` with an int
        MutatieNr, raising ``TypeError: 'in <string>' requires string as left
        operand, not int``. MutatieNr is now coerced to str.
        """
        result = self._processor().get_description({"Omschrijving": "Hi", "MutatieNr": 7})
        self.assertEqual(result, "Hi (Mutation: 7)")

    # ---- get_amount ----

    def test_get_amount_bedrag(self):
        self.assertEqual(self._processor().get_amount({"Bedrag": "12.5"}), 12.5)

    def test_get_amount_priority_and_fallthrough(self):
        # Bedrag invalid -> falls through to next field name
        self.assertEqual(self._processor().get_amount({"Bedrag": "x", "amount": 5}), 5.0)

    def test_get_amount_none(self):
        p = self._processor()
        self.assertEqual(p.get_amount({}), 0.0)
        self.assertTrue(any("No valid amount" in m for m in p.get_debug_info()))

    # ---- validate_row_amounts ----

    def test_validate_row_amounts_ok(self):
        rows = [{"amount": 100}, {"amount": 50}]
        ok, msg, diff = self._processor().validate_row_amounts({"id": 1}, rows, 150.0)
        self.assertTrue(ok)
        self.assertEqual(diff, 0.0)

    def test_validate_row_amounts_mismatch(self):
        rows = [{"amount": 100}, {"amount": 50}]
        ok, msg, diff = self._processor().validate_row_amounts({"id": 2}, rows, 200.0)
        self.assertFalse(ok)
        self.assertEqual(diff, 50.0)
        self.assertIn("mismatch", msg.lower())

    def test_validate_row_amounts_skips_near_zero(self):
        rows = [{"amount": 100}, {"amount": 0.001}]
        ok, _, diff = self._processor().validate_row_amounts({"id": 3}, rows, 100.0)
        self.assertTrue(ok)

    def test_validate_row_amounts_net_mode(self):
        rows = [{"amount": 100}, {"amount": -40}]
        ok, _, diff = self._processor().validate_row_amounts({"id": 4}, rows, 60.0, use_net_amount=True)
        self.assertTrue(ok)

    def test_validate_row_amounts_absolute_uses_abs(self):
        # Absolute mode sums abs(row); mutation amount sign ignored via abs()
        rows = [{"amount": -100}, {"amount": -50}]
        ok, _, _ = self._processor().validate_row_amounts({"id": 5}, rows, -150.0)
        self.assertTrue(ok)

    # ---- validate_journal_entry_net_amount ----

    def test_validate_je_net_ok(self):
        ok, _, diff = self._processor().validate_journal_entry_net_amount({"id": 6}, 100.0, 40.0, 60.0)
        self.assertTrue(ok)
        self.assertEqual(diff, 0.0)

    def test_validate_je_net_mismatch(self):
        ok, msg, diff = self._processor().validate_journal_entry_net_amount({"id": 7}, 100.0, 40.0, 10.0)
        self.assertFalse(ok)
        self.assertEqual(diff, 50.0)
        self.assertIn("mismatch", msg.lower())

    # ---- format_error ----

    def test_format_error(self):
        p = self._processor()
        p.add_debug_info("trace line")
        result = p.format_error(
            {"MutatieNr": "9", "Datum": "2025-01-01", "Omschrijving": "desc"},
            ValueError("boom"),
        )
        self.assertEqual(result["mutation_id"], "9")
        self.assertEqual(result["error_type"], "ValueError")
        self.assertEqual(result["error_message"], "boom")
        self.assertIn("trace line", result["debug_info"])


class TestTransactionCoordinator(EnhancedTestCase):
    """Routing, statistics, processor filtering and prerequisite validation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()

    def test_all_processors_initialized_without_type(self):
        tc = TransactionCoordinator(self.company)
        names = {type(p).__name__ for p in tc.processors}
        self.assertEqual(
            names,
            {
                "InvoiceProcessor",
                "PaymentProcessor",
                "StockProcessor",
                "JournalProcessor",
                "OpeningBalanceProcessor",
            },
        )

    def test_processor_filter_type5_payment_only(self):
        tc = TransactionCoordinator(self.company, mutation_type=5)
        self.assertEqual([type(p).__name__ for p in tc.processors], ["PaymentProcessor"])

    def test_processor_filter_type1_invoice_only(self):
        tc = TransactionCoordinator(self.company, mutation_type=1)
        self.assertEqual([type(p).__name__ for p in tc.processors], ["InvoiceProcessor"])

    def test_processor_filter_type3_payment_and_journal(self):
        tc = TransactionCoordinator(self.company, mutation_type=3)
        names = [type(p).__name__ for p in tc.processors]
        self.assertIn("PaymentProcessor", names)
        self.assertIn("JournalProcessor", names)

    def test_unknown_mutation_type_uses_all_processors(self):
        tc = TransactionCoordinator(self.company, mutation_type=42)
        self.assertEqual(len(tc.processors), 5)

    def test_initial_statistics_zero(self):
        tc = TransactionCoordinator(self.company)
        stats = tc.get_statistics()
        self.assertEqual(stats["total_processed"], 0)
        self.assertEqual(stats["successfully_created"], 0)

    def test_route_unknown_type_is_skipped(self):
        tc = TransactionCoordinator(self.company)
        result = tc.process_mutation({"id": 999, "type": 99})
        self.assertIsNone(result)
        stats = tc.get_statistics()
        self.assertEqual(stats["total_processed"], 1)
        self.assertEqual(stats["skipped"], 1)

    def test_reset_statistics(self):
        tc = TransactionCoordinator(self.company)
        tc.process_mutation({"id": 999, "type": 99})
        tc.reset_statistics()
        self.assertEqual(tc.get_statistics()["total_processed"], 0)

    def test_process_batch_counts(self):
        tc = TransactionCoordinator(self.company)
        seen = []
        stats = tc.process_batch(
            [{"id": 1, "type": 99}, {"id": 2, "type": 99}],
            progress_callback=lambda i, total: seen.append((i, total)),
        )
        self.assertEqual(stats["total_processed"], 2)
        self.assertEqual(stats["skipped"], 2)
        # callback fires at index 0 (i % 10 == 0)
        self.assertTrue(seen)

    def test_validate_prerequisites_bad_company(self):
        tc = TransactionCoordinator("Nonexistent Company XYZ")
        result = tc.validate_prerequisites()
        self.assertFalse(result["valid"])
        self.assertTrue(any("does not exist" in i for i in result["issues"]))

    def test_validate_prerequisites_runs_for_real_company(self):
        tc = TransactionCoordinator(self.company)
        result = tc.validate_prerequisites()
        # Structure is always present; validity depends on custom fields configured.
        self.assertIn("valid", result)
        self.assertIn("issues", result)
