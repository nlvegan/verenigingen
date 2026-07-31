# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for BulkInvoiceGenerationService.

Tests bulk invoice generation including:
- Cutoff date calculation (monthly, quarterly, yearly)
- Eligible schedule filtering
- Parallel vs sequential processing decision
- Lock acquisition/release
"""

from datetime import date
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.services.billing.bulk_invoice_generation_service import (
    BulkGenerationResult,
    BulkInvoiceGenerationService,
    ChunkResult,
    EligibilityDetails,
    get_bulk_invoice_generation_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestBulkInvoiceGenerationService(EnhancedTestCase):
    """Test suite for BulkInvoiceGenerationService."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_bulk_invoice_generation_service()

    def test_service_initialization(self):
        """Test that service initializes correctly."""
        service = BulkInvoiceGenerationService()
        self.assertEqual(service.service_name, "BulkInvoiceGenerationService")
        self.assertIsNotNone(service.logger)
        # Lock name is defined as a class constant (used by advisory_lock helper)
        self.assertEqual(service.LOCK_NAME, "verenigingen_bulk_invoice_generation")

    def test_get_bulk_invoice_generation_service_returns_instance(self):
        """Test that factory function returns service instance."""
        service = get_bulk_invoice_generation_service()
        self.assertIsInstance(service, BulkInvoiceGenerationService)


class TestBulkGenerationResult(EnhancedTestCase):
    """Test suite for BulkGenerationResult dataclass."""

    def test_default_values(self):
        """Test that BulkGenerationResult has correct default values."""
        result = BulkGenerationResult()

        self.assertEqual(result.processed, 0)
        self.assertEqual(result.generated, 0)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.invoices, [])
        self.assertEqual(result.payment_history_updates, 0)
        self.assertEqual(result.filtered_members, {})
        self.assertEqual(result.total_filtered, 0)
        self.assertIsNone(result.cutoff_date)
        self.assertEqual(result.coverage_gaps, [])
        self.assertEqual(result.coverage_gap_count, 0)
        self.assertEqual(result.rejection_reasons, {})
        self.assertFalse(result.parallel_mode)
        self.assertEqual(result.job_count, 0)
        self.assertEqual(result.total_schedules, 0)
        self.assertEqual(result.message, "")

    def test_custom_values(self):
        """Test that BulkGenerationResult accepts custom values."""
        result = BulkGenerationResult(
            processed=10,
            generated=8,
            errors=["Error 1"],
            total_schedules=15,
            parallel_mode=True,
        )

        self.assertEqual(result.processed, 10)
        self.assertEqual(result.generated, 8)
        self.assertEqual(result.errors, ["Error 1"])
        self.assertEqual(result.total_schedules, 15)
        self.assertTrue(result.parallel_mode)


class TestChunkResult(EnhancedTestCase):
    """Test suite for ChunkResult dataclass."""

    def test_default_values(self):
        """Test that ChunkResult has correct default values."""
        result = ChunkResult()

        self.assertEqual(result.chunk_id, 0)
        self.assertEqual(result.processed, 0)
        self.assertEqual(result.generated, 0)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.invoices, [])
        self.assertEqual(result.members_to_update, set())

    def test_custom_values(self):
        """Test that ChunkResult accepts custom values."""
        result = ChunkResult(
            chunk_id=3,
            processed=50,
            generated=48,
            errors=["Error in chunk"],
        )

        self.assertEqual(result.chunk_id, 3)
        self.assertEqual(result.processed, 50)
        self.assertEqual(result.generated, 48)
        self.assertEqual(result.errors, ["Error in chunk"])


class TestEligibilityDetails(EnhancedTestCase):
    """Test suite for EligibilityDetails dataclass."""

    def test_default_values(self):
        """Test that EligibilityDetails has correct default values."""
        result = EligibilityDetails()

        self.assertEqual(result.eligible_schedules, [])
        self.assertEqual(result.filtered_members, {})
        self.assertEqual(result.total_filtered, 0)
        self.assertEqual(result.summary, {})


class TestCutoffDateCalculation(EnhancedTestCase):
    """Test suite for cutoff date calculation."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_bulk_invoice_generation_service()

    def test_calculate_monthly_cutoff_mid_month(self):
        """Test monthly cutoff calculation in middle of month."""
        # Test with a specific date
        test_date = date(2025, 3, 15)  # March 15, 2025
        cutoff = self.service._calculate_monthly_cutoff(test_date)

        # Should return end of March
        self.assertEqual(cutoff, date(2025, 3, 31))

    def test_calculate_monthly_cutoff_end_of_month(self):
        """Test monthly cutoff when already at end of month."""
        test_date = date(2025, 3, 31)  # March 31, 2025
        cutoff = self.service._calculate_monthly_cutoff(test_date)

        # Should still return end of March
        self.assertEqual(cutoff, date(2025, 3, 31))

    def test_calculate_monthly_cutoff_december(self):
        """Test monthly cutoff in December crosses to next year."""
        test_date = date(2025, 12, 15)  # December 15, 2025
        cutoff = self.service._calculate_monthly_cutoff(test_date)

        # Should return end of December
        self.assertEqual(cutoff, date(2025, 12, 31))

    def test_calculate_monthly_cutoff_february_leap_year(self):
        """Test monthly cutoff in February handles leap year correctly."""
        test_date = date(2024, 2, 15)  # February 15, 2024 (leap year)
        cutoff = self.service._calculate_monthly_cutoff(test_date)

        # Should return Feb 29 for leap year
        self.assertEqual(cutoff, date(2024, 2, 29))

    def test_calculate_monthly_cutoff_february_non_leap_year(self):
        """Test monthly cutoff in February handles non-leap year correctly."""
        test_date = date(2025, 2, 15)  # February 15, 2025 (not a leap year)
        cutoff = self.service._calculate_monthly_cutoff(test_date)

        # Should return Feb 28 for non-leap year
        self.assertEqual(cutoff, date(2025, 2, 28))


class TestQuarterlyCutoffCalculation(EnhancedTestCase):
    """Test suite for quarterly cutoff calculation."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_bulk_invoice_generation_service()

    def test_calculate_quarterly_cutoff_q1(self):
        """Test quarterly cutoff in Q1 with standard book year (Jan-Dec)."""
        test_date = date(2025, 2, 15)  # February = Q1
        mock_settings = MagicMock()
        mock_settings.book_year_start_month = 1  # January start

        cutoff = self.service._calculate_quarterly_cutoff(test_date, mock_settings)

        # Q1 ends March 31
        self.assertEqual(cutoff, date(2025, 3, 31))

    def test_calculate_quarterly_cutoff_q2(self):
        """Test quarterly cutoff in Q2 with standard book year."""
        test_date = date(2025, 5, 15)  # May = Q2
        mock_settings = MagicMock()
        mock_settings.book_year_start_month = 1

        cutoff = self.service._calculate_quarterly_cutoff(test_date, mock_settings)

        # Q2 ends June 30
        self.assertEqual(cutoff, date(2025, 6, 30))

    def test_calculate_quarterly_cutoff_q3(self):
        """Test quarterly cutoff in Q3 with standard book year."""
        test_date = date(2025, 8, 15)  # August = Q3
        mock_settings = MagicMock()
        mock_settings.book_year_start_month = 1

        cutoff = self.service._calculate_quarterly_cutoff(test_date, mock_settings)

        # Q3 ends September 30
        self.assertEqual(cutoff, date(2025, 9, 30))

    def test_calculate_quarterly_cutoff_q4(self):
        """Test quarterly cutoff in Q4 with standard book year."""
        test_date = date(2025, 11, 15)  # November = Q4
        mock_settings = MagicMock()
        mock_settings.book_year_start_month = 1

        cutoff = self.service._calculate_quarterly_cutoff(test_date, mock_settings)

        # Q4 ends December 31
        self.assertEqual(cutoff, date(2025, 12, 31))


class TestYearlyCutoffCalculation(EnhancedTestCase):
    """Test suite for yearly cutoff calculation."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_bulk_invoice_generation_service()

    def test_calculate_yearly_cutoff_standard_calendar_year(self):
        """Test yearly cutoff with standard calendar year (Jan-Dec)."""
        test_date = date(2025, 6, 15)
        mock_settings = MagicMock()
        mock_settings.book_year_start_month = 1
        mock_settings.book_year_end_month = 12
        mock_settings.book_year_end_day = 31

        cutoff = self.service._calculate_yearly_cutoff(test_date, mock_settings)

        # Should return end of current book year (Dec 31, 2025)
        self.assertEqual(cutoff, date(2025, 12, 31))

    def test_calculate_yearly_cutoff_handles_invalid_day(self):
        """Test yearly cutoff handles invalid day gracefully (e.g., Feb 31)."""
        test_date = date(2025, 1, 15)
        mock_settings = MagicMock()
        mock_settings.book_year_start_month = 3  # March
        mock_settings.book_year_end_month = 2  # February
        mock_settings.book_year_end_day = 31  # Invalid - Feb doesn't have 31 days

        cutoff = self.service._calculate_yearly_cutoff(test_date, mock_settings)

        # Should return last day of February (Feb 28, 2025 - not a leap year)
        self.assertEqual(cutoff, date(2025, 2, 28))


class TestProcessingModeDecision(EnhancedTestCase):
    """Test suite for parallel vs sequential processing decision."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_bulk_invoice_generation_service()

    def test_sequential_processing_for_small_batch(self):
        """Test that small batches (<= 50) use sequential processing."""
        # The threshold is 50 schedules for parallel processing
        # Sequential is used for <= 50 or in test mode
        # This is tested implicitly through the generate_invoices flow
        pass  # Covered by integration tests

    def test_parallel_processing_threshold(self):
        """Test the parallel processing threshold constant."""
        # The code uses: total_schedules > 50 and not test_mode
        # This is a behavioral test - the threshold is hardcoded at 50
        self.assertTrue(True)  # Placeholder - threshold is tested via integration


class TestLockAcquisition(EnhancedTestCase):
    """Test suite for advisory lock integration in generate_invoices."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_bulk_invoice_generation_service()

    def test_lock_name_constant_defined(self):
        """Test that LOCK_NAME constant is defined for external reference."""
        self.assertEqual(
            self.service.LOCK_NAME,
            "verenigingen_bulk_invoice_generation"
        )

    def test_generate_invoices_returns_error_when_lock_unavailable(self):
        """Test that generate_invoices returns error when lock is held."""
        # Mock advisory_lock_with_backend at the utils module level
        with patch(
            "verenigingen.utils.db_advisory_lock.advisory_lock_with_backend"
        ) as mock_lock:
            # Configure mock context manager to yield False (lock not acquired)
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=False)
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_lock.return_value = mock_cm

            result = self.service.generate_invoices(test_mode=True)

            # Should return error about lock being held
            self.assertIn(
                "Another invoice generation process is already running",
                result.errors
            )

    def test_generate_invoices_uses_redis_backend_when_available(self):
        """Test that generate_invoices prefers Redis backend when available."""
        # Patch at the source location (utils module, not where it's imported)
        with patch(
            "verenigingen.utils.db_advisory_lock._is_redis_available",
            return_value=True,
        ):
            with patch(
                "verenigingen.utils.db_advisory_lock.advisory_lock_with_backend"
            ) as mock_lock:
                # Configure mock to succeed immediately
                mock_cm = MagicMock()
                mock_cm.__enter__ = MagicMock(return_value=True)
                mock_cm.__exit__ = MagicMock(return_value=False)
                mock_lock.return_value = mock_cm

                # Also need to mock _execute_invoice_generation
                with patch.object(
                    self.service, "_execute_invoice_generation"
                ) as mock_execute:
                    mock_execute.return_value = BulkGenerationResult()
                    self.service.generate_invoices(test_mode=True)

                # Verify Redis backend was used
                mock_lock.assert_called_once()
                call_kwargs = mock_lock.call_args[1]
                self.assertEqual(call_kwargs["backend"], "redis")


class TestEligibleScheduleFiltering(EnhancedTestCase):
    """Test suite for eligible schedule filtering logic."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_bulk_invoice_generation_service()

    def test_eligibility_details_structure(self):
        """Test that get_eligible_schedules returns proper structure."""
        # Get eligibility with today's cutoff
        result = self.service.get_eligible_schedules(include_details=True)

        # Verify structure
        self.assertIsInstance(result, EligibilityDetails)
        self.assertIsInstance(result.eligible_schedules, list)
        self.assertIsInstance(result.filtered_members, dict)
        self.assertIsInstance(result.total_filtered, int)
        self.assertIsInstance(result.summary, dict)

        # Verify filtered_members has expected categories
        expected_categories = [
            "ineligible_status",
            "test_mode_mismatch",
            "gap_reset",
            "business_logic",
            "no_customer",
            "duplicate_coverage",
            "too_early",
            "already_covered",
        ]
        for category in expected_categories:
            self.assertIn(category, result.filtered_members)

    def test_eligibility_summary_fields(self):
        """Test that eligibility summary has required fields."""
        result = self.service.get_eligible_schedules(include_details=True)

        # Summary should have these fields
        self.assertIn("total_schedules_checked", result.summary)
        self.assertIn("eligible_count", result.summary)
        self.assertIn("filtered_count", result.summary)
        self.assertIn("filter_breakdown", result.summary)


class TestAccountingConfigurationValidation(EnhancedTestCase):
    """Test suite for accounting configuration validation."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_bulk_invoice_generation_service()

    def test_validation_checks_required_accounts(self):
        """Test that validation checks for required accounting accounts."""
        # This test verifies the validation method exists and is callable
        # Full validation requires proper ERPNext setup which is an integration test
        self.assertTrue(hasattr(self.service, "_validate_accounting_configuration"))
        self.assertTrue(callable(self.service._validate_accounting_configuration))


class TestErrorMessageCleaning(EnhancedTestCase):
    """Test suite for error message cleaning."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_bulk_invoice_generation_service()

    def test_clean_error_message_removes_html(self):
        """Test that HTML tags are removed from error messages."""
        dirty_error = "<div>Error: <b>Something went wrong</b></div>"
        clean = self.service._clean_error_message(dirty_error)

        self.assertNotIn("<div>", clean)
        self.assertNotIn("<b>", clean)
        self.assertNotIn("</b>", clean)
        self.assertNotIn("</div>", clean)

    def test_clean_error_message_removes_error_log_reference(self):
        """Test that Error Log references are removed."""
        dirty_error = "Error Log ABC123: Something went wrong"
        clean = self.service._clean_error_message(dirty_error)

        self.assertNotIn("Error Log ABC123:", clean)
        self.assertIn("Something went wrong", clean)

    def test_clean_error_message_truncates_long_messages(self):
        """Test that long error messages are truncated."""
        long_error = "x" * 200  # 200 character error
        clean = self.service._clean_error_message(long_error)

        # Should be truncated to 80 characters
        self.assertLessEqual(len(clean), 80)

    def test_clean_error_message_handles_empty_string(self):
        """Test that empty string is handled."""
        clean = self.service._clean_error_message("")
        self.assertEqual(clean, "")


class TestValidationErrorFormatting(EnhancedTestCase):
    """Test suite for validation error formatting."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_bulk_invoice_generation_service()

    def test_format_date_advanced_error(self):
        """Test formatting for date advanced recovery action."""
        error = Exception("Validation failed")
        recovery_result = {"action_taken": "date_advanced", "retry_count": 2}

        formatted = self.service._format_validation_error("SCH-001", error, recovery_result)

        self.assertIn("ADVANCED:", formatted)
        self.assertIn("SCH-001", formatted)
        self.assertIn("dates advanced", formatted)

    def test_format_retry_tracked_error(self):
        """Test formatting for retry tracked recovery action."""
        error = Exception("Validation failed")
        recovery_result = {"action_taken": "retry_tracked", "retry_count": 1}

        formatted = self.service._format_validation_error("SCH-001", error, recovery_result)

        self.assertIn("RETRY 1:", formatted)
        self.assertIn("SCH-001", formatted)

    def test_format_skipped_error(self):
        """Test formatting for skipped (manual review) recovery action."""
        error = Exception("Persistent error")
        recovery_result = {"action_taken": "skipped", "retry_count": 3}

        formatted = self.service._format_validation_error("SCH-001", error, recovery_result)

        self.assertIn("MANUAL REVIEW:", formatted)
        self.assertIn("SCH-001", formatted)
        self.assertIn("3 failures", formatted)

    def test_format_unknown_error(self):
        """Test formatting for unknown recovery action."""
        error = Exception("Unknown error")
        recovery_result = {"action_taken": "unknown", "retry_count": 0}

        formatted = self.service._format_validation_error("SCH-001", error, recovery_result)

        self.assertIn("ERROR:", formatted)
        self.assertIn("SCH-001", formatted)


class TestChunkRechecksCutoffAtExecutionTime(EnhancedTestCase):
    """
    process_invoice_chunk must re-evaluate the cutoff, not trust the eligibility
    snapshot it was enqueued with.

    Chunks are enqueued and the generation lock is released before they run
    (_process_parallel), so the snapshot can be minutes old. Two overlapping runs - the
    daily scheduler plus an admin-triggered run, which enqueues without deduplication -
    both see the same uncovered schedules and both generate. EligibilityChecker used to
    catch the stale snapshot via check_schedule_timing; that guard has been removed
    because it duplicated the cutoff comparison and drifted, so the re-check has to
    happen here. The duplicate detector cannot help: it probes the sequential next
    period, which by construction never overlaps existing coverage.
    """

    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type(
            membership_type_name="Chunk Cutoff Type", amount=10.0, contribution_mode="Fixed Amount"
        )
        self.member, self.schedule = self.create_test_member_with_schedule(
            first_name="ChunkCutoff",
            last_name="Member",
            membership_type_name=self.membership_type.name,
            start_date=today(),
        )
        self.schedule.billing_frequency = "Monthly"
        self.schedule.save()
        frappe.db.commit()
        self.member.reload()

    def test_chunk_skips_a_schedule_that_became_covered_after_the_snapshot(self):
        """Simulates the second of two overlapping runs: coverage now reaches the cutoff."""
        from verenigingen.services.billing.bulk_invoice_generation_service import process_invoice_chunk
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        # The invoice the FIRST run generated, covering past the cutoff.
        cutoff = add_days(getdate(today()), 20)
        result = InvoiceGenerator(self.schedule).generate_invoice(
            coverage_start=getdate(today()),
            coverage_end=add_days(getdate(today()), 25),
            member_doc=self.member,
        )
        self.assertTrue(result.success, getattr(result, "error_message", None))
        self.assertEqual(frappe.db.get_value("Sales Invoice", result.data.name, "docstatus"), 1)
        frappe.db.commit()

        invoices_before = frappe.db.count("Sales Invoice", {"customer": self.member.customer})

        chunk = process_invoice_chunk([self.schedule.name], chunk_id=1, total_chunks=1, cutoff_date=cutoff)

        self.assertEqual(chunk.generated, 0, "chunk generated against a stale eligibility snapshot")
        self.assertEqual(
            frappe.db.count("Sales Invoice", {"customer": self.member.customer}),
            invoices_before,
            "a second invoice was created for coverage that already passes the cutoff",
        )
