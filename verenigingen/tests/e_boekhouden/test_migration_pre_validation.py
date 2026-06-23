"""
Coverage tests for verenigingen/utils/migration/migration_pre_validation.py

PreImportValidator runs doctype-specific validators (Account, Customer, Supplier,
Sales/Purchase Invoice, Payment Entry, Journal Entry) over dict records BEFORE
import. The validators are pure predicate logic over plain dicts; the only DB
touches are frappe.db.exists() lookups for parent accounts / party existence,
which run for real here.

Includes a regression test for the dead-validator bug: BaseValidator.validate()
previously hard-coded ``result = None`` instead of calling each ``validate_*``
method, so every record was reported "passed" regardless of content. validate_batch
likewise short-circuited with a placeholder "passed". Both are now wired up.

Run with:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_pre_validation
"""

import unittest

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.migration.migration_pre_validation import (
    AccountValidator,
    JournalEntryValidator,
    PaymentEntryValidator,
    PreImportValidator,
    SalesInvoiceValidator,
    SupplierValidator,
)


class TestBaseValidatorWiring(EnhancedTestCase):
    """Regression: validators must actually run their validate_* methods."""

    def test_account_validator_catches_missing_name(self):
        # account_name is required; an empty record must FAIL, not silently pass.
        result = AccountValidator().validate({})
        self.assertEqual(result["status"], "failed")
        types = [e["type"] for e in result["errors"]]
        self.assertIn("missing_required_field", types)

    def test_account_validator_passes_valid_record(self):
        result = AccountValidator().validate({"account_name": "Sales", "account_type": "Income Account"})
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["errors"], [])

    def test_account_validator_flags_invalid_type(self):
        result = AccountValidator().validate({"account_name": "Weird", "account_type": "Not A Real Type"})
        self.assertEqual(result["status"], "failed")
        self.assertIn("invalid_account_type", [e["type"] for e in result["errors"]])

    def test_account_name_too_long_is_error(self):
        result = AccountValidator().validate({"account_name": "X" * 200})
        self.assertEqual(result["status"], "failed")
        self.assertIn("field_too_long", [e["type"] for e in result["errors"]])


class TestSupplierValidator(EnhancedTestCase):
    def test_invalid_iban_is_warning_not_failure(self):
        result = SupplierValidator().validate({"supplier_name": "ACME", "iban": "GB00BADIBAN0000"})
        # IBAN problems are warnings, so overall status is "warning", not "failed".
        self.assertEqual(result["status"], "warning")
        self.assertIn("invalid_iban", [w["type"] for w in result["warnings"]])

    def test_valid_dutch_iban_passes(self):
        result = SupplierValidator().validate({"supplier_name": "ACME", "iban": "NL91ABNA0417164300"})
        self.assertEqual(result["status"], "passed")

    def test_missing_supplier_name_is_error(self):
        result = SupplierValidator().validate({"iban": "NL91ABNA0417164300"})
        self.assertEqual(result["status"], "failed")


class TestSalesInvoiceValidator(EnhancedTestCase):
    def test_posting_date_validator_does_not_crash(self):
        # Regression: validate_posting_date referenced an undefined `result`
        # (commented assignment) -> NameError on every Sales Invoice validation.
        validator = SalesInvoiceValidator()
        # Missing posting_date -> required-field error returned, no NameError.
        res = validator.validate_posting_date({})
        self.assertIsNotNone(res)
        self.assertEqual(res["type"], "missing_required_field")
        # Valid date -> no error.
        self.assertIsNone(validator.validate_posting_date({"posting_date": "2024-01-01"}))
        # Invalid date string -> invalid_date error.
        bad = validator.validate_posting_date({"posting_date": "not-a-date"})
        self.assertEqual(bad["type"], "invalid_date")

    def test_invoice_without_items_fails(self):
        result = SalesInvoiceValidator().validate(
            {"customer": "Cust", "posting_date": "2024-01-01", "items": []}
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("no_items", [e["type"] for e in result["errors"]])

    def test_invoice_with_bad_item_qty_fails(self):
        result = SalesInvoiceValidator().validate(
            {
                "customer": "Cust",
                "posting_date": "2024-01-01",
                "items": [{"qty": 0, "rate": 10}],
            }
        )
        self.assertIn("invalid_item_qty", [e["type"] for e in result["errors"]])


class TestPaymentEntryValidator(EnhancedTestCase):
    def test_invalid_party_type_is_error(self):
        result = PaymentEntryValidator().validate({"party": "X", "party_type": "Alien", "paid_amount": 5})
        self.assertIn("invalid_party_type", [e["type"] for e in result["errors"]])

    def test_non_positive_amount_is_error(self):
        result = PaymentEntryValidator().validate({"party": "X", "party_type": "Customer", "paid_amount": 0})
        self.assertIn("invalid_amount", [e["type"] for e in result["errors"]])

    def test_receive_without_paid_to_is_error(self):
        result = PaymentEntryValidator().validate(
            {
                "party": "X",
                "party_type": "Customer",
                "paid_amount": 50,
                "payment_type": "Receive",
            }
        )
        self.assertIn("missing_account", [e["type"] for e in result["errors"]])


class TestJournalEntryValidator(EnhancedTestCase):
    def test_unbalanced_entry_is_error(self):
        result = JournalEntryValidator().validate(
            {
                "posting_date": "2024-01-01",
                "accounts": [
                    {"account": "A", "debit_in_account_currency": 100},
                    {"account": "B", "credit_in_account_currency": 90},
                ],
            }
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("unbalanced_entry", [e["type"] for e in result["errors"]])

    def test_balanced_entry_passes(self):
        result = JournalEntryValidator().validate(
            {
                "posting_date": "2024-01-01",
                "accounts": [
                    {"account": "A", "debit_in_account_currency": 100},
                    {"account": "B", "credit_in_account_currency": 100},
                ],
            }
        )
        self.assertEqual(result["status"], "passed")

    def test_entry_without_accounts_fails(self):
        result = JournalEntryValidator().validate({"posting_date": "2024-01-01", "accounts": []})
        self.assertIn("no_accounts", [e["type"] for e in result["errors"]])

    def test_both_debit_and_credit_on_one_line_fails(self):
        result = JournalEntryValidator().validate(
            {
                "posting_date": "2024-01-01",
                "accounts": [
                    {
                        "account": "A",
                        "debit_in_account_currency": 50,
                        "credit_in_account_currency": 50,
                    }
                ],
            }
        )
        self.assertIn("both_debit_credit", [e["type"] for e in result["errors"]])


class TestPreImportValidatorBatch(EnhancedTestCase):
    def test_unknown_doctype_returns_error(self):
        validator = PreImportValidator()
        out = validator.validate_batch("Not A Doctype", [{}])
        self.assertIn("error", out)

    def test_batch_summary_counts_failures(self):
        # Regression: validate_batch previously returned a hard-coded "passed"
        # placeholder, so the summary never reflected real failures.
        validator = PreImportValidator()
        records = [
            {"account_name": "Good", "account_type": "Income Account"},  # passes
            {"account_type": "Income Account"},  # missing name -> fails
            {"account_name": "Y", "account_type": "Bogus Type"},  # fails
        ]
        with self.assertNoErrorLog():
            out = validator.validate_batch("Account", records)

        self.assertEqual(out["total_records"], 3)
        self.assertEqual(validator.validation_summary["total_validated"], 3)
        self.assertEqual(validator.validation_summary["failed"], 2)
        self.assertEqual(validator.validation_summary["passed"], 1)
        # Error types tallied.
        self.assertGreater(sum(validator.validation_summary["errors_by_type"].values()), 0)

    def test_validation_report_lists_failed_records(self):
        validator = PreImportValidator()
        validator.validate_batch("Account", [{"account_type": "Income Account"}] * 12)  # all missing name
        report = validator.get_validation_report()
        self.assertEqual(len(report["failed_records"]), 12)
        # >10% failure rate -> a high_failure_rate recommendation is generated.
        rec_types = [r["type"] for r in report["recommendations"]]
        self.assertIn("high_failure_rate", rec_types)

    def test_record_identifier_uses_fstring(self):
        # Regression: the identifier lambdas were missing the f-prefix and emitted
        # the literal "{r.get('customer')}". Now they interpolate.
        validator = PreImportValidator()
        ident = validator._get_record_identifier(
            "Sales Invoice", {"customer": "ACME", "posting_date": "2024-01-01"}
        )
        self.assertEqual(ident, "ACME - 2024-01-01")
        self.assertNotIn("{", ident)


if __name__ == "__main__":
    unittest.main()
