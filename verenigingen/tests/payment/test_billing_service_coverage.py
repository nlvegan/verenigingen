# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Test coverage for 10 billing services in verenigingen/services/billing/.

Covers:
1. dues_schedule_auto_creator — helper functions and next-invoice-date logic
2. invoice_management — bulk invoice generation API (dry-run mode)
3. dues_schedule_validation_service — rate/date/boundary validation
4. dues_schedule_creation_service — retry logic, error categorization, circuit breaker
5. invoice_matcher — InvoiceMatchResult dataclass and find_matching_invoice
6. invoice_error_handler_service — error dedup, deadlock detection, recovery logic
7. template_creation_service — default template creation, template-based schedule creation
8. coverage_overlap_detector — overlap detection, gap analysis
9. fee_change_tracking_service — fee change detection, member sync
10. sales_invoice_account_handler — receivable account hook
"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


# ---------------------------------------------------------------------------
# 1. DuesScheduleAutoCreator helper functions
# ---------------------------------------------------------------------------
class TestDuesScheduleAutoCreator(EnhancedTestCase):
    """Tests for dues_schedule_auto_creator module-level helper functions."""

    def test_calculate_next_invoice_date_daily(self):
        from verenigingen.services.billing.dues_schedule_auto_creator import (
            _calculate_next_invoice_date,
        )

        result = getdate(_calculate_next_invoice_date("Daily"))
        expected = getdate(add_days(today(), 1))
        self.assertEqual(result, expected)

    def test_calculate_next_invoice_date_monthly(self):
        from verenigingen.services.billing.dues_schedule_auto_creator import (
            _calculate_next_invoice_date,
        )

        result = getdate(_calculate_next_invoice_date("Monthly"))
        expected = getdate(add_months(today(), 1))
        self.assertEqual(result, expected)

    def test_calculate_next_invoice_date_quarterly(self):
        from verenigingen.services.billing.dues_schedule_auto_creator import (
            _calculate_next_invoice_date,
        )

        result = getdate(_calculate_next_invoice_date("Quarterly"))
        expected = getdate(add_months(today(), 3))
        self.assertEqual(result, expected)

    def test_calculate_next_invoice_date_semi_annual(self):
        from verenigingen.services.billing.dues_schedule_auto_creator import (
            _calculate_next_invoice_date,
        )

        result = getdate(_calculate_next_invoice_date("Semi-Annual"))
        expected = getdate(add_months(today(), 6))
        self.assertEqual(result, expected)

    def test_calculate_next_invoice_date_annual(self):
        from frappe.utils import add_years

        from verenigingen.services.billing.dues_schedule_auto_creator import (
            _calculate_next_invoice_date,
        )

        result = getdate(_calculate_next_invoice_date("Annual"))
        expected = getdate(add_years(today(), 1))
        self.assertEqual(result, expected)

    def test_calculate_next_invoice_date_unknown_defaults_to_monthly(self):
        from verenigingen.services.billing.dues_schedule_auto_creator import (
            _calculate_next_invoice_date,
        )

        result = getdate(_calculate_next_invoice_date("Biweekly"))
        expected = getdate(add_months(today(), 1))
        self.assertEqual(result, expected)

    def test_get_template_dues_rate_suggested_amount(self):
        from verenigingen.services.billing.dues_schedule_auto_creator import (
            _get_template_dues_rate,
        )

        template = SimpleNamespace(name="TPL-001", suggested_amount=25.0, dues_rate=0)
        self.assertEqual(_get_template_dues_rate(template), 25.0)

    def test_get_template_dues_rate_fallback_to_dues_rate(self):
        from verenigingen.services.billing.dues_schedule_auto_creator import (
            _get_template_dues_rate,
        )

        template = SimpleNamespace(name="TPL-002", suggested_amount=0, dues_rate=30.0)
        self.assertEqual(_get_template_dues_rate(template), 30.0)

    def test_get_template_dues_rate_raises_when_no_rate(self):
        from verenigingen.services.billing.dues_schedule_auto_creator import (
            _get_template_dues_rate,
        )

        template = SimpleNamespace(name="TPL-003", suggested_amount=0, dues_rate=0)
        with self.assertRaises(ValueError):
            _get_template_dues_rate(template)

    def test_validate_final_dues_rate_with_template_rate(self):
        from verenigingen.services.billing.dues_schedule_auto_creator import (
            _validate_final_dues_rate,
        )

        mt_doc = SimpleNamespace(name="Standard", minimum_amount=5.0)
        self.assertEqual(_validate_final_dues_rate(20.0, mt_doc), 20.0)

    def test_validate_final_dues_rate_fallback_to_minimum(self):
        from verenigingen.services.billing.dues_schedule_auto_creator import (
            _validate_final_dues_rate,
        )

        mt_doc = SimpleNamespace(name="Standard", minimum_amount=10.0)
        self.assertEqual(_validate_final_dues_rate(0, mt_doc), 10.0)

    def test_validate_final_dues_rate_raises_when_all_zero(self):
        from verenigingen.services.billing.dues_schedule_auto_creator import (
            _validate_final_dues_rate,
        )

        mt_doc = SimpleNamespace(name="Standard", minimum_amount=0)
        with self.assertRaises(ValueError):
            _validate_final_dues_rate(0, mt_doc)


# ---------------------------------------------------------------------------
# 2. InvoiceManagement — dry-run API
# ---------------------------------------------------------------------------
class TestInvoiceManagement(EnhancedTestCase):
    """Tests for invoice_management module functions (bulk generation, summary)."""

    def _unwrap_result(self, result):
        """Unwrap OperationResult — security decorators may wrap it in a dict."""
        if isinstance(result, dict):
            # Wrapped by security decorator
            data = result.get("data", result)
            return data
        # Raw OperationResult
        if hasattr(result, "data"):
            return result.data
        return result

    def test_validate_invoice_generation_readiness_returns_result(self):
        """validate_invoice_generation_readiness returns a result with schedule info."""
        from verenigingen.services.billing.invoice_management import (
            validate_invoice_generation_readiness,
        )

        result = validate_invoice_generation_readiness()
        data = self._unwrap_result(result)
        self.assertIn("system_ready", data)
        self.assertIn("total_active_schedules", data)
        self.assertIn("issues", data)

    def test_get_dues_schedules_summary_returns_result(self):
        """get_dues_schedules_summary returns valid summary structure."""
        from verenigingen.services.billing.invoice_management import (
            get_dues_schedules_summary,
        )

        result = get_dues_schedules_summary(include_orphaned=False, days_ahead=7)
        data = self._unwrap_result(result)
        self.assertIn("total_active_schedules", data)
        self.assertIn("due_now", data)
        self.assertIn("auto_generate_enabled", data)

    def test_bulk_generate_dry_run_with_no_schedules(self):
        """Dry run with no matching schedules returns zero counts."""
        from verenigingen.services.billing.invoice_management import (
            bulk_generate_dues_invoices,
        )

        result = bulk_generate_dues_invoices(
            filter_criteria={"member": "NONEXISTENT-MEMBER-XYZ"},
            dry_run=True,
            max_invoices=5,
        )
        data = self._unwrap_result(result)
        self.assertEqual(data["invoices_generated"], 0)


# ---------------------------------------------------------------------------
# 3. DuesScheduleValidationService
# ---------------------------------------------------------------------------
class TestDuesScheduleValidationService(EnhancedTestCase):
    """Tests for DuesScheduleValidationService validation methods."""

    def setUp(self):
        super().setUp()
        from verenigingen.services.billing.dues_schedule_validation_service import (
            get_dues_schedule_validation_service,
        )

        self.svc = get_dues_schedule_validation_service()

    def _make_schedule_stub(self, **kwargs):
        """Create a minimal schedule-like object for validation testing."""
        defaults = {
            "name": "SCHED-TEST-001",
            "is_template": 0,
            "dues_rate": 25.0,
            "membership_type": None,
            "member": None,
            "last_invoice_date": None,
            "next_invoice_date": None,
            "last_invoice_coverage_end": None,
            "last_generated_invoice": None,
            "minimum_amount": None,
            "base_multiplier": 1.0,
            "contribution_mode": "Fixed",
            "_skip_minimum_validation": False,
        }
        defaults.update(kwargs)
        stub = SimpleNamespace(**defaults)
        stub.is_new = lambda: True
        return stub

    def test_validate_dues_rate_positive_passes(self):
        schedule = self._make_schedule_stub(dues_rate=50.0)
        result = self.svc.validate_dues_rate(schedule)
        self.assertTrue(result["valid"])

    def test_validate_dues_rate_zero_passes(self):
        """Zero is valid for free memberships."""
        schedule = self._make_schedule_stub(dues_rate=0)
        result = self.svc.validate_dues_rate(schedule)
        self.assertTrue(result["valid"])

    def test_validate_dues_rate_negative_fails(self):
        schedule = self._make_schedule_stub(dues_rate=-5.0)
        result = self.svc.validate_dues_rate(schedule)
        self.assertFalse(result["valid"])
        self.assertIn("negative", result["reason"].lower())

    def test_validate_dues_rate_none_fails(self):
        schedule = self._make_schedule_stub(dues_rate=None)
        result = self.svc.validate_dues_rate(schedule)
        self.assertFalse(result["valid"])

    def test_validate_dues_rate_extremely_high_fails(self):
        schedule = self._make_schedule_stub(dues_rate=99999.0)
        result = self.svc.validate_dues_rate(schedule)
        self.assertFalse(result["valid"])
        self.assertIn("exceeds", result["reason"].lower())

    def test_validate_rate_boundaries_template_skipped(self):
        """Templates skip boundary validation."""
        schedule = self._make_schedule_stub(is_template=1, dues_rate=-10.0)
        # Should not raise
        self.svc.validate_rate_boundaries(schedule)

    def test_validate_rate_boundaries_none_rate_skipped(self):
        """None dues_rate skips boundary validation."""
        schedule = self._make_schedule_stub(dues_rate=None)
        self.svc.validate_rate_boundaries(schedule)

    def test_validate_rate_boundaries_negative_raises(self):
        from verenigingen.utils.exceptions import InvalidDuesRateError

        schedule = self._make_schedule_stub(dues_rate=-5.0)
        with self.assertRaises(InvalidDuesRateError):
            self.svc.validate_rate_boundaries(schedule)

    def test_validate_dates_future_last_invoice_autocorrects(self):
        """Future last_invoice_date gets auto-corrected to today."""
        future = add_days(today(), 30)
        schedule = self._make_schedule_stub(
            last_invoice_date=future,
            next_invoice_date=add_days(today(), 60),
        )
        self.svc.validate_dates(schedule)
        self.assertEqual(getdate(schedule.last_invoice_date), getdate(today()))

    def test_validate_dates_next_before_last_throws(self):
        """next_invoice_date before last_invoice_date is invalid."""
        schedule = self._make_schedule_stub(
            last_invoice_date="2025-06-01",
            next_invoice_date="2025-01-01",
        )
        with self.assertRaises(frappe.ValidationError):
            self.svc.validate_dates(schedule)

    def test_validate_membership_type_consistency_no_member(self):
        """No member returns valid (will be caught elsewhere)."""
        schedule = self._make_schedule_stub(member=None, membership_type=None)
        result = self.svc.validate_membership_type_consistency(schedule)
        self.assertTrue(result["valid"])

    def test_validate_financial_constraints_template_skipped(self):
        """Templates skip financial constraints."""
        schedule = self._make_schedule_stub(is_template=1, dues_rate=99999.0)
        self.svc.validate_financial_constraints(schedule)

    def test_validate_financial_constraints_none_rate_skipped(self):
        schedule = self._make_schedule_stub(dues_rate=None)
        self.svc.validate_financial_constraints(schedule)

    def test_validate_dues_rate_configuration_template_skipped(self):
        """Templates skip rate configuration."""
        schedule = self._make_schedule_stub(is_template=1, dues_rate=None)
        self.svc.validate_dues_rate_configuration(schedule)

    def test_validate_dues_rate_configuration_no_membership_type_skipped(self):
        schedule = self._make_schedule_stub(dues_rate=None, membership_type=None)
        self.svc.validate_dues_rate_configuration(schedule)

    def test_validate_dues_rate_change_no_membership_type_returns_false(self):
        schedule = self._make_schedule_stub(membership_type=None)
        result = self.svc.validate_dues_rate_change(schedule)
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# 4. DuesScheduleCreationService
# ---------------------------------------------------------------------------
class TestDuesScheduleCreationService(EnhancedTestCase):
    """Tests for DuesScheduleCreationService retry logic and error categorization."""

    def setUp(self):
        super().setUp()
        from verenigingen.services.billing.dues_schedule_creation_service import (
            DuesScheduleCreationService,
        )

        self.svc = DuesScheduleCreationService()

    def test_input_validation_empty_member_name(self):
        result = self.svc.create_schedule_with_retry(
            member_name="",
            membership_name="MEM-001",
            membership_type="Standard",
        )
        self.assertFalse(result.success)
        self.assertIn("empty", result.error_message.lower())

    def test_input_validation_empty_membership_name(self):
        result = self.svc.create_schedule_with_retry(
            member_name="MBR-001",
            membership_name="",
            membership_type="Standard",
        )
        self.assertFalse(result.success)

    def test_input_validation_empty_membership_type(self):
        result = self.svc.create_schedule_with_retry(
            member_name="MBR-001",
            membership_name="MEM-001",
            membership_type="  ",
        )
        self.assertFalse(result.success)

    def test_input_validation_negative_custom_amount(self):
        result = self.svc.create_schedule_with_retry(
            member_name="MBR-001",
            membership_name="MEM-001",
            membership_type="Standard",
            custom_amount=-10.0,
        )
        self.assertFalse(result.success)
        self.assertIn("non-negative", result.error_message.lower())

    def test_categorize_error_duplicate(self):
        self.assertEqual(self.svc._categorize_error("already has a dues schedule"), "duplicate")
        self.assertEqual(self.svc._categorize_error("Schedule already exists"), "duplicate")

    def test_categorize_error_config(self):
        self.assertEqual(self.svc._categorize_error("template not found"), "config")
        self.assertEqual(self.svc._categorize_error("suggested_amount is missing"), "config")

    def test_categorize_error_validation(self):
        self.assertEqual(self.svc._categorize_error("validation failed"), "validation")
        self.assertEqual(self.svc._categorize_error("Invalid amount"), "validation")

    def test_categorize_error_system(self):
        self.assertEqual(self.svc._categorize_error("database connection lost"), "system")

    def test_is_retryable_error_config(self):
        self.assertTrue(self.svc._is_retryable_error("config"))

    def test_is_retryable_error_system(self):
        self.assertTrue(self.svc._is_retryable_error("system"))

    def test_is_retryable_error_validation_not_retryable(self):
        self.assertFalse(self.svc._is_retryable_error("validation"))

    def test_is_retryable_error_duplicate_not_retryable(self):
        self.assertFalse(self.svc._is_retryable_error("duplicate"))

    def test_circuit_breaker_default_closed(self):
        """Circuit breaker should be closed (allow retries) by default."""
        # Clear any existing circuit breaker state
        self.svc._record_success()
        self.assertFalse(self.svc._should_circuit_break())

    def test_record_failure_writes_to_cache(self):
        """_record_failure writes a failure count to cache."""
        key = self.svc.CIRCUIT_BREAKER_CACHE_KEY
        self.svc._record_success()  # Reset
        self.svc._record_failure()
        count = frappe.cache().get_value(key)
        # _record_failure writes a positive integer to cache
        self.assertIsNotNone(count)
        self.assertGreaterEqual(count, 1)
        # Cleanup
        self.svc._record_success()

    def test_record_success_clears_cache(self):
        """_record_success clears the failure count."""
        key = self.svc.CIRCUIT_BREAKER_CACHE_KEY
        self.svc._record_failure()
        self.svc._record_success()
        count = frappe.cache().get_value(key)
        self.assertIsNone(count)

    def test_circuit_breaker_opens_after_threshold_failures(self):
        """Circuit breaker opens (blocks retries) once failures reach the threshold.

        Regression (audit T1.3, 2026-05-17): _record_failure and _should_circuit_break
        read the counter with raw frappe.cache().get(), which does not apply Frappe's
        key prefix, while _record_failure writes with set_value() (prefixed). The reads
        always missed — the counter never incremented past 1 and the breaker never
        opened. Both reads must use get_value().
        """
        self.svc._record_success()  # reset to a known-closed state
        try:
            for _ in range(self.svc.CIRCUIT_BREAKER_THRESHOLD):
                self.svc._record_failure()
            self.assertTrue(self.svc._should_circuit_break())
        finally:
            self.svc._record_success()  # cleanup

    def test_retry_count_clamping(self):
        """Invalid retry_count values are clamped to valid range."""
        result = self.svc.create_schedule_with_retry(
            member_name="MBR-CLAMP",
            membership_name="MEM-CLAMP",
            membership_type="Standard",
            retry_count=-5,
        )
        # Should not crash; the retry_count is clamped
        self.assertIsNotNone(result)

    def test_max_retries_constant(self):
        self.assertEqual(self.svc.MAX_RETRIES, 3)

    # test_retry_delays_exponential removed with RETRY_DELAYS. The constant described
    # a 60s/300s/1800s backoff that never applied: it was fed to frappe.enqueue as
    # `at_time`, which is not an enqueue parameter, so every retry fired immediately.
    # The ladder cannot be reinstated -- frappe runs its workers with
    # with_scheduler=False, so there is no delayed-enqueue facility at all. Retries
    # still happen, just without delay, so there is no ordering left to assert.
    # See dues_schedule_creation_service._enqueue_retry.


# ---------------------------------------------------------------------------
# 5. InvoiceMatcher
# ---------------------------------------------------------------------------
class TestInvoiceMatcher(EnhancedTestCase):
    """Tests for invoice_matcher module: InvoiceMatchResult and matching logic."""

    def test_invoice_match_result_not_found(self):
        from verenigingen.services.billing.invoice_matcher import InvoiceMatchResult

        result = InvoiceMatchResult(invoice_name=None, match_type=None)
        self.assertFalse(result.found)
        d = result.to_dict()
        self.assertFalse(d["found"])
        self.assertIsNone(d["invoice_name"])

    def test_invoice_match_result_found(self):
        from verenigingen.services.billing.invoice_matcher import InvoiceMatchResult

        result = InvoiceMatchResult(
            invoice_name="SINV-001",
            match_type="exact_coverage",
            invoice_amount=25.0,
            outstanding_amount=25.0,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 12, 31),
        )
        self.assertTrue(result.found)
        d = result.to_dict()
        self.assertEqual(d["invoice_name"], "SINV-001")
        self.assertEqual(d["match_type"], "exact_coverage")
        self.assertEqual(d["coverage_start"], "2025-01-01")

    def test_find_matching_invoice_no_customer_returns_empty(self):
        """Member without customer returns no match."""
        from verenigingen.services.billing.invoice_matcher import find_matching_invoice

        result = find_matching_invoice(
            member_name="NONEXISTENT-MEMBER-XYZ",
            payment_date=date(2025, 6, 1),
            payment_amount=25.0,
        )
        self.assertFalse(result.found)

    def test_find_matching_invoice_invalid_date_type_raises(self):
        from verenigingen.services.billing.invoice_matcher import find_matching_invoice

        with self.assertRaises(ValueError):
            find_matching_invoice(
                member_name="MBR-001",
                payment_date="2025-06-01",  # string, not date/datetime
                payment_amount=25.0,
            )

    def test_find_matching_invoice_accepts_datetime(self):
        """datetime objects should be accepted and converted."""
        from verenigingen.services.billing.invoice_matcher import find_matching_invoice

        result = find_matching_invoice(
            member_name="NONEXISTENT-MEMBER-XYZ",
            payment_date=datetime(2025, 6, 1, 12, 0, 0),
            payment_amount=25.0,
        )
        self.assertFalse(result.found)

    def test_find_matching_invoice_accepts_decimal_amount(self):
        """Decimal amounts should be accepted."""
        from verenigingen.services.billing.invoice_matcher import find_matching_invoice

        result = find_matching_invoice(
            member_name="NONEXISTENT-MEMBER-XYZ",
            payment_date=date(2025, 6, 1),
            payment_amount=Decimal("25.00"),
        )
        self.assertFalse(result.found)

    def test_invoice_matcher_service_class(self):
        from verenigingen.services.billing.invoice_matcher import get_invoice_matcher

        svc = get_invoice_matcher()
        self.assertTrue(hasattr(svc, "find_matching_invoice"))
        self.assertTrue(hasattr(svc, "find_matching_invoice_for_payment"))

    def test_find_matching_invoice_for_payment_no_amount(self):
        """SDK payment without amount returns no match."""
        from verenigingen.services.billing.invoice_matcher import (
            find_matching_invoice_for_payment,
        )

        # Use dict to simulate SDK payment object (supports .get())
        sdk_payment = {"amount": None, "paidAt": None, "createdAt": None}
        result = find_matching_invoice_for_payment(sdk_payment, member_name="MBR-001")
        self.assertFalse(result.found)
        self.assertIn("no amount", result.overlap_warning.lower())

    def test_find_matching_invoice_for_payment_no_date(self):
        """SDK payment without date returns no match."""
        from verenigingen.services.billing.invoice_matcher import (
            find_matching_invoice_for_payment,
        )

        # Use dict to simulate SDK payment object (supports .get())
        sdk_payment = {"amount": {"value": "25.00"}, "paidAt": None, "createdAt": None}
        result = find_matching_invoice_for_payment(sdk_payment, member_name="MBR-001")
        self.assertFalse(result.found)
        self.assertIn("no date", result.overlap_warning.lower())


# ---------------------------------------------------------------------------
# 6. InvoiceErrorHandlerService
# ---------------------------------------------------------------------------
class TestInvoiceErrorHandlerService(EnhancedTestCase):
    """Tests for InvoiceErrorHandlerService error analysis and recovery logic."""

    def setUp(self):
        super().setUp()
        from verenigingen.services.billing.invoice_error_handler_service import (
            get_invoice_error_handler_service,
        )

        self.svc = get_invoice_error_handler_service()

    def test_deduplicate_error_message_single(self):
        msg = "Invoice generation failed: Amount too low"
        self.assertEqual(self.svc._deduplicate_error_message(msg), msg)

    def test_deduplicate_error_message_doubled(self):
        msg = "Invoice generation failed: Invoice generation failed: Amount too low"
        result = self.svc._deduplicate_error_message(msg)
        self.assertEqual(result, "Invoice generation failed: Amount too low")

    def test_deduplicate_error_message_triple(self):
        msg = "Invoice gen failed: Invoice gen failed: Invoice gen failed: Error"
        result = self.svc._deduplicate_error_message(msg)
        self.assertEqual(result, "Invoice generation failed: Error")

    def test_deduplicate_empty_string(self):
        self.assertEqual(self.svc._deduplicate_error_message(""), "")

    def test_deduplicate_none(self):
        self.assertIsNone(self.svc._deduplicate_error_message(None))

    def test_is_deadlock_error_true_1213(self):
        self.assertTrue(self.svc._is_deadlock_error("Error 1213: Deadlock found"))

    def test_is_deadlock_error_true_1205(self):
        self.assertTrue(self.svc._is_deadlock_error("Error 1205: Lock wait timeout"))

    def test_is_deadlock_error_true_generic(self):
        self.assertTrue(self.svc._is_deadlock_error("database deadlock detected"))

    def test_is_deadlock_error_false(self):
        self.assertFalse(self.svc._is_deadlock_error("Validation failed: Amount below minimum"))

    def test_is_deadlock_error_empty(self):
        self.assertFalse(self.svc._is_deadlock_error(""))

    def test_is_deadlock_error_none(self):
        self.assertFalse(self.svc._is_deadlock_error(None))

    def test_should_auto_advance_deadlock_returns_false(self):
        """Deadlocks should NOT auto-advance (they are transient)."""
        schedule = SimpleNamespace(name="SCHED-001")
        result = self.svc.should_auto_advance_schedule(
            schedule, "Error 1213: Deadlock found when trying to get lock"
        )
        self.assertFalse(result)

    def test_should_auto_advance_permission_denied_returns_false(self):
        schedule = SimpleNamespace(name="SCHED-002")
        result = self.svc.should_auto_advance_schedule(schedule, "permission denied")
        self.assertFalse(result)

    def test_should_auto_advance_customer_record_returns_false(self):
        """Errors mentioning 'customer record' trigger manual review."""
        schedule = SimpleNamespace(name="SCHED-003")
        result = self.svc.should_auto_advance_schedule(schedule, "customer record not found")
        self.assertFalse(result)

    def test_should_auto_advance_account_not_found_returns_false(self):
        schedule = SimpleNamespace(name="SCHED-004")
        result = self.svc.should_auto_advance_schedule(schedule, "account not found")
        self.assertFalse(result)

    def test_should_auto_advance_generic_validation_returns_true(self):
        """Generic validation errors should auto-advance."""
        schedule = SimpleNamespace(name="SCHED-005")
        result = self.svc.should_auto_advance_schedule(schedule, "Some unexpected error occurred")
        self.assertTrue(result)

    def test_should_auto_advance_membership_type_triggers_reconstruction(self):
        """Missing membership_type triggers health reconstruction and auto-advances."""
        schedule = SimpleNamespace(
            name="SCHED-006",
            _trigger_health_reconstruction=lambda msg: None,
        )
        result = self.svc.should_auto_advance_schedule(schedule, "membership_type is missing")
        self.assertTrue(result)


# ---------------------------------------------------------------------------
# 7. TemplateCreationService
# ---------------------------------------------------------------------------
class TestTemplateCreationService(EnhancedTestCase):
    """Tests for TemplateCreationService template creation and schedule creation."""

    def setUp(self):
        super().setUp()
        self.membership_type = self.ensure_membership_type("Test Template Svc Type")

    def test_create_default_template(self):
        """create_default_template creates a template and links it to membership type."""
        from verenigingen.services.billing.template_creation_service import (
            get_template_creation_service,
        )

        svc = get_template_creation_service()
        template = svc.create_default_template(self.membership_type.name)

        self.assertTrue(template.is_template)
        self.assertEqual(template.membership_type, self.membership_type.name)
        self.assertEqual(template.billing_frequency, "Annual")
        self.assertEqual(template.contribution_mode, "Income-Based")
        self.assertEqual(template.status, "Active")
        self.assertEqual(float(template.suggested_amount), 15.0)

        # Verify link back to membership type
        mt_doc = frappe.get_doc("Membership Type", self.membership_type.name)
        self.assertEqual(mt_doc.dues_schedule_template, template.name)

    def test_create_from_template_no_membership_type_template_throws(self):
        """Using a membership type without a template throws ValidationError."""
        from verenigingen.services.billing.template_creation_service import (
            get_template_creation_service,
        )

        svc = get_template_creation_service()

        # Create a membership type without a template
        mt_no_tpl = self.ensure_membership_type("Test No Template Type")
        # Clear the template assignment if any
        frappe.db.set_value(
            "Membership Type", mt_no_tpl.name, "dues_schedule_template", None
        )

        with self.assertRaises(frappe.ValidationError):
            svc.create_from_template(
                member_name="NONEXISTENT-MEMBER",
                membership_type=mt_no_tpl.name,
            )

    def test_create_from_template_non_template_schedule_throws(self):
        """Passing a non-template schedule name should throw ValidationError."""
        from verenigingen.services.billing.template_creation_service import (
            get_template_creation_service,
        )

        svc = get_template_creation_service()

        # Find any non-template schedule in the system
        non_template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 0},
            "name",
        )
        if not non_template:
            self.skipTest("No non-template schedule available for testing")

        with self.assertRaises(frappe.ValidationError):
            svc.create_from_template(
                member_name="NONEXISTENT-MEMBER",
                template_name=non_template,
            )


# ---------------------------------------------------------------------------
# 8. CoverageOverlapDetector
# ---------------------------------------------------------------------------
class TestCoverageOverlapDetector(EnhancedTestCase):
    """Tests for coverage_overlap_detector functions and OverlapCheckResult dataclass."""

    def test_overlap_check_result_no_overlap(self):
        from verenigingen.services.billing.coverage_overlap_detector import (
            OverlapCheckResult,
        )

        result = OverlapCheckResult(
            has_overlap=False,
            overlapping_invoices=[],
            exact_match=None,
            reason="No overlapping invoices found",
        )
        self.assertTrue(result.can_create_invoice)
        d = result.to_dict()
        self.assertFalse(d["has_overlap"])
        self.assertTrue(d["can_create_invoice"])

    def test_overlap_check_result_with_overlap(self):
        from verenigingen.services.billing.coverage_overlap_detector import (
            OverlapCheckResult,
        )

        result = OverlapCheckResult(
            has_overlap=True,
            overlapping_invoices=[{"name": "SINV-001"}],
            exact_match="SINV-001",
            reason="Exact duplicate found",
        )
        self.assertFalse(result.can_create_invoice)

    def test_check_coverage_overlap_no_invoices(self):
        """With a non-existent customer, no overlaps should be found."""
        from verenigingen.services.billing.coverage_overlap_detector import (
            check_coverage_overlap,
        )

        result = check_coverage_overlap(
            customer="NONEXISTENT-CUSTOMER-XYZ",
            proposed_start=date(2025, 1, 1),
            proposed_end=date(2025, 12, 31),
        )
        self.assertFalse(result.has_overlap)
        self.assertTrue(result.can_create_invoice)

    def test_find_overlapping_invoices_empty(self):
        from verenigingen.services.billing.coverage_overlap_detector import (
            find_overlapping_invoices,
        )

        result = find_overlapping_invoices(
            customer="NONEXISTENT-CUSTOMER-XYZ",
            proposed_start=date(2025, 1, 1),
            proposed_end=date(2025, 12, 31),
        )
        self.assertEqual(result, [])

    def test_find_exact_coverage_invoice_none(self):
        from verenigingen.services.billing.coverage_overlap_detector import (
            find_exact_coverage_invoice,
        )

        result = find_exact_coverage_invoice(
            customer="NONEXISTENT-CUSTOMER-XYZ",
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 12, 31),
        )
        self.assertIsNone(result)

    def test_get_member_coverage_gaps_no_invoices(self):
        """With no invoices, the entire period is a gap."""
        from verenigingen.services.billing.coverage_overlap_detector import (
            get_member_coverage_gaps,
        )

        gaps = get_member_coverage_gaps(
            customer="NONEXISTENT-CUSTOMER-XYZ",
            from_date=date(2025, 1, 1),
            to_date=date(2025, 12, 31),
        )
        self.assertEqual(len(gaps), 1)
        self.assertEqual(getdate(gaps[0]["start"]), date(2025, 1, 1))
        self.assertEqual(getdate(gaps[0]["end"]), date(2025, 12, 31))

    def test_coverage_overlap_with_existing_invoices(self):
        """Test overlap detection against existing invoices in the database."""
        from verenigingen.services.billing.coverage_overlap_detector import (
            check_coverage_overlap,
            find_overlapping_invoices,
        )

        # Find an existing submitted invoice with coverage dates
        existing_inv = frappe.db.get_value(
            "Sales Invoice",
            {
                "docstatus": 1,
                "custom_coverage_start_date": ["is", "set"],
                "custom_coverage_end_date": ["is", "set"],
            },
            ["name", "customer", "custom_coverage_start_date", "custom_coverage_end_date"],
            as_dict=True,
        )
        if not existing_inv:
            self.skipTest("No submitted invoice with coverage dates available")

        cov_start = getdate(existing_inv.custom_coverage_start_date)
        cov_end = getdate(existing_inv.custom_coverage_end_date)

        # A period that overlaps should be detected
        overlapping = find_overlapping_invoices(
            customer=existing_inv.customer,
            proposed_start=cov_start,
            proposed_end=cov_end,
        )
        self.assertGreaterEqual(len(overlapping), 1)

        result = check_coverage_overlap(
            customer=existing_inv.customer,
            proposed_start=cov_start,
            proposed_end=cov_end,
        )
        self.assertTrue(result.has_overlap)
        # Exact match should be detected
        self.assertIsNotNone(result.exact_match)


# ---------------------------------------------------------------------------
# 9. FeeChangeTrackingService
# ---------------------------------------------------------------------------
class TestFeeChangeTrackingService(EnhancedTestCase):
    """Tests for FeeChangeTrackingService fee change detection and member sync."""

    def setUp(self):
        super().setUp()
        from verenigingen.services.billing.fee_change_tracking_service import (
            get_fee_change_tracking_service,
        )

        self.svc = get_fee_change_tracking_service()

    def test_update_member_dues_rate_no_member_skips(self):
        """Schedule without member skips the update."""
        schedule = SimpleNamespace(member=None, dues_rate=25.0)
        # Should not raise
        self.svc.update_member_dues_rate(schedule)

    def test_update_member_dues_rate_propagates_for_non_elevated_user(self):
        """The schedule->member dues_rate mirror runs even when the triggering
        user holds no elevated-operation privileges.

        update_member_dues_rate is a system denormalization triggered by an
        already-authorized dues schedule change — it must not depend on the
        caller being trusted internal staff. Regression guard for the
        secure_document_operation elevation gate that silently dropped the
        propagation for member self-service edits and background syncs.
        """
        member = self.factory.create_member(
            first_name="DuesMirror", last_name="Test",
            email="dues-mirror@example.org",
        )
        schedule = SimpleNamespace(member=member.name, dues_rate=42.00, name="DS-TEST-001")

        # Verenigingen Volunteer cannot request elevated system operations.
        with self.as_role("Verenigingen Volunteer"):
            self.svc.update_member_dues_rate(schedule)

        self.assertEqual(
            float(frappe.db.get_value("Member", member.name, "dues_rate")),
            42.00,
        )

    def test_handle_schedule_update_template_skips(self):
        """Template schedules skip fee tracking."""
        schedule = SimpleNamespace(is_template=1, member="MBR-001")
        # Should not raise
        self.svc.handle_schedule_update(schedule)

    def test_handle_schedule_update_no_member_skips(self):
        schedule = SimpleNamespace(is_template=0, member=None)
        self.svc.handle_schedule_update(schedule)

    def test_handle_schedule_update_no_doc_before_save_skips(self):
        """Without _doc_before_save, change detection is impossible — skip."""
        schedule = SimpleNamespace(is_template=0, member="MBR-001")
        # No _doc_before_save attribute
        self.svc.handle_schedule_update(schedule)

    def test_handle_new_schedule_template_skips(self):
        schedule = SimpleNamespace(is_template=1, member="MBR-001")
        self.svc.handle_new_schedule(schedule)

    def test_handle_new_schedule_no_member_skips(self):
        schedule = SimpleNamespace(is_template=0, member=None)
        self.svc.handle_new_schedule(schedule)


# ---------------------------------------------------------------------------
# 10. SalesInvoiceAccountHandler
# ---------------------------------------------------------------------------
class TestSalesInvoiceAccountHandler(EnhancedTestCase):
    """Tests for sales_invoice_account_handler hook function."""

    def test_set_membership_receivable_account_no_debit_to_skips(self):
        """If debit_to is not set, handler returns early."""
        from verenigingen.services.billing.sales_invoice_account_handler import (
            set_membership_receivable_account,
        )

        doc = SimpleNamespace(debit_to=None, company="Test Co", items=[], remarks=None, customer=None)
        # Should not raise
        set_membership_receivable_account(doc)

    def test_set_membership_receivable_account_no_settings_skips(self):
        """If settings are missing, handler returns early."""
        from verenigingen.services.billing.sales_invoice_account_handler import (
            set_membership_receivable_account,
        )

        doc = SimpleNamespace(
            debit_to="Some Account",
            company="NONEXISTENT-COMPANY-XYZ",
            items=[],
            remarks=None,
            customer=None,
        )
        # Should not raise even with non-existent company
        set_membership_receivable_account(doc)

    def test_membership_item_detection_by_group(self):
        """Invoices with membership item groups are detected."""
        from verenigingen.services.billing.sales_invoice_account_handler import (
            set_membership_receivable_account,
        )

        item = SimpleNamespace(item_group="Membership", item_name="Annual Membership")
        doc = SimpleNamespace(
            debit_to="Debtors",
            company="Test",
            items=[item],
            remarks=None,
            customer=None,
        )
        # Even though settings are missing, the detection logic runs first
        # This just tests that the function doesn't crash
        set_membership_receivable_account(doc)

    def test_membership_item_detection_by_name(self):
        """Items with membership-related names are detected."""
        from verenigingen.services.billing.sales_invoice_account_handler import (
            set_membership_receivable_account,
        )

        item = SimpleNamespace(item_group="Services", item_name="Membership Dues Q1 2025")
        doc = SimpleNamespace(
            debit_to="Debtors",
            company="Test",
            items=[item],
            remarks=None,
            customer=None,
        )
        set_membership_receivable_account(doc)

    def test_membership_detection_by_remarks(self):
        """Remarks containing membership keywords trigger detection."""
        from verenigingen.services.billing.sales_invoice_account_handler import (
            set_membership_receivable_account,
        )

        doc = SimpleNamespace(
            debit_to="Debtors",
            company="Test",
            items=[],
            remarks="Payment for membership dues",
            customer=None,
        )
        set_membership_receivable_account(doc)


# ---------------------------------------------------------------------------
# Billing Constants
# ---------------------------------------------------------------------------
class TestBillingConstants(EnhancedTestCase):
    """Tests for billing_constants shared module."""

    def test_deadlock_patterns_contains_expected(self):
        from verenigingen.services.billing.billing_constants import DEADLOCK_PATTERNS

        self.assertIn("deadlock", DEADLOCK_PATTERNS)
        self.assertIn("1213", DEADLOCK_PATTERNS)
        self.assertIn("1205", DEADLOCK_PATTERNS)

    def test_error_dedup_pattern_compiles(self):
        from verenigingen.services.billing.billing_constants import ERROR_DEDUP_PATTERN

        self.assertIsNotNone(ERROR_DEDUP_PATTERN.pattern)

    def test_recovery_action_values(self):
        from verenigingen.services.billing.billing_constants import RecoveryAction

        self.assertEqual(RecoveryAction.RETRY_TRACKED.value, "retry_tracked")
        self.assertEqual(RecoveryAction.DATE_ADVANCED.value, "date_advanced")
        self.assertEqual(RecoveryAction.SKIPPED.value, "skipped")

    def test_max_length_constants(self):
        from verenigingen.services.billing.billing_constants import (
            MAX_DB_ERROR_LENGTH,
            MAX_LOG_ERROR_LENGTH,
            MAX_USER_ERROR_LENGTH,
        )

        self.assertEqual(MAX_DB_ERROR_LENGTH, 255)
        self.assertEqual(MAX_LOG_ERROR_LENGTH, 100)
        self.assertEqual(MAX_USER_ERROR_LENGTH, 200)
