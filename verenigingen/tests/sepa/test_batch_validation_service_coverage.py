"""
Tests for BatchValidationService (verenigingen_payments/services/batch_validation_service.py).

This service validates SEPA Direct Debit batch creation requirements *before* a
batch is built: invoice-level field/amount/currency/status checks, collection-date
SEPA notice-window rules, batch size/total limits, and mandate coverage.

Most of the logic is pure (operates on plain invoice dicts), so it is exercised
with real dicts rather than mocks. The two DB-backed paths are:

- validate_batch_creation() first calls config_service.validate_sepa_configuration().
  On the bare test site the SEPA company config is incomplete, so that returns
  is_valid=False and validate_batch_creation short-circuits with CONFIG_ERROR(s)
  before touching invoices. We assert that documented early-return contract, and
  exercise the per-section validators (_validate_invoices, _validate_collection_date,
  _validate_batch_limits) directly to cover the invoice/date/limit branches.

- _check_customer_mandate()/validate_mandate_coverage() query the SEPA Mandate
  doctype by columns (customer/valid_from/valid_until) THAT DO NOT EXIST on it
  (it links to `member`, not `customer`, and has no valid_from/valid_until). The
  query therefore raises OperationalError 1054, which the method swallows and
  reports as "missing mandate". This is a real money-path bug (every invoice is
  reported as having no mandate) and is FLAGGED in the agent report; the tests
  below pin the current swallow behaviour so a regression in the error contract
  is caught, and document the bug inline.
"""

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.services.batch_validation_service import (
    BatchValidationService,
    ValidationResult,
    batch_validation_service,
)


def _invoice(**overrides):
    """A minimal SEPA-valid invoice dict; override fields to drive failure branches."""
    base = {
        "name": "ACC-SINV-0001",
        "customer": "CUST-0001",
        "outstanding_amount": 25.0,
        "currency": "EUR",
        "status": "Unpaid",
    }
    base.update(overrides)
    return base


class TestValidationResultContainer(EnhancedTestCase):
    """The ValidationResult value object: error flips validity, warnings don't."""

    def test_fresh_result_is_valid(self):
        r = ValidationResult()
        self.assertTrue(r.is_valid)
        self.assertEqual(r.errors, [])
        self.assertEqual(r.warnings, [])

    def test_add_error_invalidates_and_records_code(self):
        r = ValidationResult()
        r.add_error("boom", "CODE_X")
        self.assertFalse(r.is_valid)
        self.assertEqual(r.errors[0]["message"], "boom")
        self.assertEqual(r.errors[0]["code"], "CODE_X")

    def test_add_warning_keeps_valid(self):
        r = ValidationResult()
        r.add_warning("heads up")
        self.assertTrue(r.is_valid)
        self.assertEqual(r.warnings[0]["message"], "heads up")
        self.assertNotIn("code", r.warnings[0])

    def test_to_dict_round_trips_state(self):
        r = ValidationResult()
        r.add_error("e", "EC")
        r.add_warning("w")
        r.add_detail("k", 7)
        d = r.to_dict()
        self.assertFalse(d["is_valid"])
        self.assertEqual(d["details"]["k"], 7)
        self.assertEqual(len(d["errors"]), 1)
        self.assertEqual(len(d["warnings"]), 1)


class TestValidateInvoices(EnhancedTestCase):
    """_validate_invoices: required fields, amount bounds, currency, status."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.svc = BatchValidationService()

    def test_empty_list_is_rejected(self):
        result = self.svc._validate_invoices([])
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0]["code"], "NO_INVOICES")

    def test_all_valid_invoices_pass(self):
        result = self.svc._validate_invoices([_invoice(), _invoice(name="ACC-SINV-0002")])
        self.assertTrue(result.is_valid)
        self.assertEqual(result.details["valid_invoices"], 2)
        self.assertEqual(result.details["total_invoices"], 2)

    def test_missing_required_field_flags_invoice(self):
        # No customer -> the invoice is collected as invalid.
        result = self.svc._validate_invoices([_invoice(customer=None)])
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0]["code"], "INVALID_INVOICES")
        invalid = result.details["invalid_invoices"]
        self.assertEqual(len(invalid), 1)
        self.assertTrue(any("customer" in e for e in invalid[0]["errors"]))

    def test_amount_below_minimum_is_flagged(self):
        # min_amount_per_transaction is 0.01 when zero-amounts disallowed; 0.0 < min.
        result = self.svc._validate_invoices([_invoice(outstanding_amount=0.0)])
        self.assertFalse(result.is_valid)
        # outstanding_amount=0.0 is falsy -> caught as BOTH missing field and too-small.
        errs = result.details["invalid_invoices"][0]["errors"]
        self.assertTrue(any("too small" in e.lower() or "missing" in e.lower() for e in errs))

    def test_amount_above_maximum_is_flagged(self):
        result = self.svc._validate_invoices([_invoice(outstanding_amount=10_000_000.0)])
        self.assertFalse(result.is_valid)
        errs = result.details["invalid_invoices"][0]["errors"]
        self.assertTrue(any("too large" in e.lower() for e in errs))

    def test_non_numeric_amount_is_flagged(self):
        result = self.svc._validate_invoices([_invoice(outstanding_amount="not-a-number")])
        self.assertFalse(result.is_valid)
        errs = result.details["invalid_invoices"][0]["errors"]
        self.assertTrue(any("invalid amount" in e.lower() for e in errs))

    def test_non_eur_currency_is_flagged(self):
        result = self.svc._validate_invoices([_invoice(currency="USD")])
        self.assertFalse(result.is_valid)
        errs = result.details["invalid_invoices"][0]["errors"]
        self.assertTrue(any("currency" in e.lower() for e in errs))

    def test_invalid_status_is_flagged(self):
        result = self.svc._validate_invoices([_invoice(status="Paid")])
        self.assertFalse(result.is_valid)
        errs = result.details["invalid_invoices"][0]["errors"]
        self.assertTrue(any("status" in e.lower() for e in errs))

    def test_partly_paid_status_is_accepted(self):
        result = self.svc._validate_invoices([_invoice(status="Partly Paid")])
        self.assertTrue(result.is_valid)


class TestValidateCollectionDate(EnhancedTestCase):
    """_validate_collection_date: SEPA notice window + weekend warning + format."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.svc = BatchValidationService()

    def _date(self, days):
        from datetime import datetime, timedelta

        return (datetime.now().date() + timedelta(days=days)).strftime("%Y-%m-%d")

    def test_invalid_format_is_rejected(self):
        result = self.svc._validate_collection_date("31-12-2026")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0]["code"], "INVALID_DATE_FORMAT")

    def test_too_early_is_error(self):
        # min notice is 1 day; today (0 days) is before the earliest allowed date.
        result = self.svc._validate_collection_date(self._date(0))
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0]["code"], "DATE_TOO_EARLY")

    def test_within_window_is_valid(self):
        # 10 days ahead is inside [min=1, max=35]; record days_from_today detail.
        result = self.svc._validate_collection_date(self._date(10))
        self.assertTrue(result.is_valid)
        self.assertEqual(result.details["days_from_today"], 10)

    def test_far_future_is_warning_not_error(self):
        # >35 days ahead -> warning DATE_FAR_FUTURE, but still is_valid (warnings don't flip).
        result = self.svc._validate_collection_date(self._date(60))
        self.assertTrue(result.is_valid)
        self.assertTrue(any(w["code"] == "DATE_FAR_FUTURE" for w in result.warnings))

    def test_weekend_adds_warning(self):
        from datetime import datetime, timedelta

        # Find the first Saturday at least 2 days out (inside the notice window).
        d = datetime.now().date() + timedelta(days=2)
        while d.weekday() != 5:  # Saturday
            d += timedelta(days=1)
        result = self.svc._validate_collection_date(d.strftime("%Y-%m-%d"))
        self.assertTrue(any(w["code"] == "WEEKEND_COLLECTION" for w in result.warnings))


class TestValidateBatchLimits(EnhancedTestCase):
    """_validate_batch_limits: batch size and total-amount caps."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.svc = BatchValidationService()

    def test_normal_batch_passes(self):
        result = self.svc._validate_batch_limits([_invoice(), _invoice(name="X2")])
        self.assertTrue(result.is_valid)
        self.assertEqual(result.details["batch_size"], 2)
        self.assertAlmostEqual(result.details["total_amount"], 50.0)

    def test_total_amount_accumulates_skipping_bad_values(self):
        # A non-numeric outstanding_amount is skipped, not counted, not fatal here.
        invoices = [_invoice(outstanding_amount=10.0), _invoice(outstanding_amount="bad")]
        result = self.svc._validate_batch_limits(invoices)
        self.assertAlmostEqual(result.details["total_amount"], 10.0)

    def test_batch_total_over_cap_is_error(self):
        # max_total_batch_amount is 999,999,999.99; two huge invoices exceed it.
        big = _invoice(outstanding_amount=900_000_000.0)
        big2 = _invoice(name="B2", outstanding_amount=900_000_000.0)
        result = self.svc._validate_batch_limits([big, big2])
        self.assertFalse(result.is_valid)
        self.assertTrue(any(e["code"] == "BATCH_AMOUNT_TOO_LARGE" for e in result.errors))


class TestValidateBatchCreationOrchestration(EnhancedTestCase):
    """validate_batch_creation: the top-level orchestrator and its config short-circuit."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.svc = BatchValidationService()

    def test_config_branch_drives_either_short_circuit_or_full_path(self):
        """validate_batch_creation first validates SEPA config. If config is INVALID
        it short-circuits with CONFIG_ERROR(s) before touching invoices; if VALID it
        proceeds to invoice validation. Assert whichever branch this site exercises,
        and that the orchestrator never raises."""
        config = self.svc.config_service.validate_sepa_configuration()
        result = self.svc.validate_batch_creation([_invoice()], collection_date=None)
        if not config["is_valid"]:
            self.assertFalse(result.is_valid)
            self.assertTrue(any(e["code"] == "CONFIG_ERROR" for e in result.errors))
        else:
            # Valid config + one valid invoice + no date + within limits -> overall valid.
            self.assertTrue(result.is_valid)

    def test_valid_config_collects_invoice_and_date_errors(self):
        """With valid config, an invalid invoice AND a too-early collection date both
        surface (the orchestrator aggregates the per-section errors rather than
        stopping at the first), AND the aggregate result.is_valid is flipped False.

        Regression guard for the fix: previously validate_batch_creation extend()-ed
        the section errors but never set result.is_valid=False, so the orchestration
        gate (business_logic_orchestration_service) admitted batches with bad
        invoices/dates/limits."""
        config = self.svc.config_service.validate_sepa_configuration()
        if not config["is_valid"]:
            self.skipTest("SEPA config invalid on this site; orchestrator short-circuits at config")
        from datetime import datetime

        today_str = datetime.now().date().strftime("%Y-%m-%d")  # 0 days notice -> too early
        result = self.svc.validate_batch_creation(
            [_invoice(currency="USD")], collection_date=today_str
        )
        self.assertFalse(result.is_valid)
        codes = {e.get("code") for e in result.errors}
        # Invoice section flags the bad currency; date section flags too-early.
        self.assertIn("INVALID_INVOICES", codes)
        self.assertIn("DATE_TOO_EARLY", codes)

    def test_is_valid_flips_false_on_section_errors_regardless_of_site_config(self):
        """SITE-INDEPENDENT regression guard for the validate_batch_creation fix.

        The other orchestration tests skip (or take the short-circuit branch) when the
        site's SEPA config is incomplete, so on a bare CI site the fix itself -- the
        per-section `result.is_valid = False` merge -- would otherwise be unguarded.
        Here we override ONLY the config-validation boundary (a config/IO seam, not
        frappe.db) so the orchestrator always reaches the invoice/date/limit merge,
        then prove that collected section errors flip the aggregate is_valid False.

        Before the fix, extend()-ing the error lists left is_valid True, so this
        asserts the exact observable effect of the fix."""

        class _ValidConfig:
            def validate_sepa_configuration(self):
                return {"is_valid": True, "errors": [], "warnings": []}

            # _validate_invoices / _validate_batch_limits read these real limits.
            def get_batch_processing_limits(self):
                return {
                    "max_batch_size": 1000,
                    "max_amount_per_transaction": 999999.99,
                    "max_total_batch_amount": 999999999.99,
                    "min_amount_per_transaction": 0.01,
                }

            def get_collection_date_settings(self):
                return {"minimum_notice_days": 1, "maximum_notice_days": 35}

        svc = BatchValidationService()
        svc.config_service = _ValidConfig()

        from datetime import datetime

        today_str = datetime.now().date().strftime("%Y-%m-%d")  # 0 days notice -> too early
        result = svc.validate_batch_creation([_invoice(currency="USD")], collection_date=today_str)

        # The fix: section errors must flip the aggregate result.is_valid False.
        self.assertFalse(result.is_valid)
        codes = {e.get("code") for e in result.errors}
        self.assertIn("INVALID_INVOICES", codes)  # bad currency, from _validate_invoices
        self.assertIn("DATE_TOO_EARLY", codes)  # 0-day notice, from _validate_collection_date

    def test_batch_size_over_cap_is_flagged(self):
        """_validate_batch_limits BATCH_TOO_LARGE branch (size cap, distinct from the
        amount cap covered elsewhere)."""

        class _SmallLimitConfig:
            def get_batch_processing_limits(self):
                return {
                    "max_batch_size": 1,
                    "max_amount_per_transaction": 999999.99,
                    "max_total_batch_amount": 999999999.99,
                    "min_amount_per_transaction": 0.01,
                }

        svc = BatchValidationService()
        svc.config_service = _SmallLimitConfig()
        result = svc._validate_batch_limits([_invoice(name="A"), _invoice(name="B")])
        self.assertFalse(result.is_valid)
        self.assertTrue(any(e["code"] == "BATCH_TOO_LARGE" for e in result.errors))

    def test_singleton_is_the_service_instance(self):
        self.assertIsInstance(batch_validation_service, BatchValidationService)


class TestMandateCoverageBugCharacterization(EnhancedTestCase):
    """validate_mandate_coverage / _check_customer_mandate.

    FLAGGED BUG: SEPA Mandate has NO customer/valid_from/valid_until columns (it
    links to `member`). The mandate lookup query therefore raises OperationalError
    1054, which _check_customer_mandate swallows and reports as has_mandate=False.
    Consequence: validate_mandate_coverage reports EVERY invoice as "missing
    mandate", even when the member has a perfectly valid active mandate. These
    tests pin that behaviour so a fix (or a regression in the swallow contract) is
    detectable, and they assert the bookkeeping details remain consistent.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.svc = BatchValidationService()

    def test_check_customer_mandate_swallows_phantom_column_error(self):
        # The phantom-column query raises OperationalError 1054; the except returns a
        # no-mandate dict with the error captured in 'reason'. Assert the reason names
        # the SWALLOWED ERROR specifically (not the benign "No active mandate found"
        # path), so this test would fail if the columns were added / the query stopped
        # raising -- pinning the actual bug, not just a no-rows result.
        res = self.svc._check_customer_mandate("ANY-CUSTOMER")
        self.assertFalse(res["has_mandate"])
        self.assertFalse(res["is_valid"])
        self.assertIn("Error checking mandate", res["reason"])

    def test_invoices_without_customer_are_skipped(self):
        # validate_mandate_coverage `continue`s past invoices lacking a customer, so
        # they are not counted as missing mandates.
        result = self.svc.validate_mandate_coverage([_invoice(customer=None)])
        self.assertTrue(result.is_valid)
        self.assertEqual(result.details["total_checked"], 1)
        self.assertEqual(result.details["valid_mandates"], 1)

    def test_all_invoices_reported_missing_mandate_due_to_phantom_columns(self):
        # Every invoice with a customer is reported missing because the lookup
        # always fails (the FLAGGED bug). Detail bookkeeping must stay consistent.
        invoices = [_invoice(name="I1"), _invoice(name="I2", customer="CUST-0002")]
        result = self.svc.validate_mandate_coverage(invoices)
        self.assertFalse(result.is_valid)
        self.assertTrue(any(e["code"] == "MISSING_MANDATES" for e in result.errors))
        self.assertEqual(len(result.details["missing_mandates"]), 2)
        self.assertEqual(result.details["total_checked"], 2)
        self.assertEqual(result.details["valid_mandates"], 0)
