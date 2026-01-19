# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
BulkInvoiceGenerationService - Bulk invoice generation for membership dues.

This service handles bulk invoice generation including:
- Calculating cutoff dates based on billing period configuration
- Finding eligible schedules for invoice generation
- Parallel processing for large batches
- Chunk processing for background jobs
- Payment history updates
- Coverage gap detection and reporting

Extracted from membership_dues_schedule.py to reduce controller size
and improve testability.

Architecture:
- StatefulService base class for transaction management
- Redis-based concurrency protection
- Parallel processing for large batches (>50 schedules)
"""

import re
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.services.infrastructure.base_service import StatefulService
from verenigingen.utils.billing_constants import MAX_LOG_ERROR_LENGTH
from verenigingen.utils.validation_utilities import DocumentExistenceValidator

if TYPE_CHECKING:
    from frappe.model.document import Document


@dataclass
class BulkGenerationResult:
    """Result of bulk invoice generation operation."""

    processed: int = 0
    generated: int = 0
    errors: List[str] = field(default_factory=list)
    invoices: List[Dict] = field(default_factory=list)
    payment_history_updates: int = 0
    filtered_members: Dict[str, List[Dict]] = field(default_factory=dict)
    total_filtered: int = 0
    cutoff_date: Optional[date] = None
    coverage_gaps: List[Dict] = field(default_factory=list)
    coverage_gap_count: int = 0
    rejection_reasons: Dict = field(default_factory=dict)
    parallel_mode: bool = False
    job_count: int = 0
    total_schedules: int = 0
    message: str = ""


@dataclass
class ChunkResult:
    """Result of processing a single chunk of invoices."""

    chunk_id: int = 0
    processed: int = 0
    generated: int = 0
    errors: List[str] = field(default_factory=list)
    invoices: List[Dict] = field(default_factory=list)
    members_to_update: Set[str] = field(default_factory=set)


@dataclass
class EligibilityDetails:
    """Detailed eligibility information for invoice generation."""

    eligible_schedules: List[str] = field(default_factory=list)
    filtered_members: Dict[str, List[Dict]] = field(default_factory=dict)
    total_filtered: int = 0
    summary: Dict[str, Any] = field(default_factory=dict)


class BulkInvoiceGenerationService(StatefulService):
    """
    Service for bulk generation of membership dues invoices.

    Handles:
    - Cutoff date calculation based on billing period settings
    - Eligible schedule identification with comprehensive filtering
    - Parallel processing for large batches
    - Chunk processing for background jobs
    - Payment history batch updates
    - Coverage gap detection and reporting

    Concurrency Protection:
    - Uses centralized advisory_lock helper (verenigingen.utils.db_advisory_lock)
    - Redis backend for distributed locking across workers (uses redis.lock.Lock)
    - Falls back to database advisory lock if Redis unavailable
    - Aborts with error if lock acquisition fails (prevents duplicate generation)

    Example:
        service = get_bulk_invoice_generation_service()
        result = service.generate_invoices(test_mode=False)
        print(f"Generated {result.generated} invoices")
    """

    # Lock name for bulk invoice generation (used by advisory_lock helper)
    LOCK_NAME = "verenigingen_bulk_invoice_generation"

    def __init__(self):
        super().__init__(service_name="BulkInvoiceGenerationService")

    def calculate_cutoff_date(self) -> date:
        """
        Calculate the cutoff date for invoice generation based on Verenigingen Settings.

        The cutoff date determines through which date invoices should provide coverage.
        Based on billing_cutoff_frequency setting: Monthly, Quarterly, or Yearly.

        Returns:
            date: The cutoff date through which invoices should provide coverage
        """
        settings = frappe.get_single("Verenigingen Settings")
        cutoff_frequency = getattr(settings, "billing_cutoff_frequency", "Monthly")

        today_date = getdate(today())

        if cutoff_frequency == "Monthly":
            return self._calculate_monthly_cutoff(today_date)
        elif cutoff_frequency == "Quarterly":
            return self._calculate_quarterly_cutoff(today_date, settings)
        elif cutoff_frequency == "Yearly":
            return self._calculate_yearly_cutoff(today_date, settings)

        # Fallback to end of current month
        return self._calculate_monthly_cutoff(today_date)

    def _calculate_monthly_cutoff(self, today_date: date) -> date:
        """Calculate end of current month."""
        if today_date.month == 12:
            next_month = today_date.replace(year=today_date.year + 1, month=1, day=1)
        else:
            next_month = today_date.replace(month=today_date.month + 1, day=1)
        return add_days(next_month, -1)

    def _calculate_quarterly_cutoff(self, today_date: date, settings) -> date:
        """Calculate end of current quarter based on book year."""
        book_year_start_month = getattr(settings, "book_year_start_month", 1)

        # Calculate which quarter we're in based on book year
        months_since_book_start = (today_date.month - book_year_start_month) % 12
        current_quarter = (months_since_book_start // 3) + 1

        # Calculate end of current quarter
        quarter_end_month = ((current_quarter * 3 - 1) + book_year_start_month - 1) % 12 + 1

        if quarter_end_month >= today_date.month:
            quarter_end_year = today_date.year
        else:
            quarter_end_year = today_date.year + 1

        # Get last day of quarter end month
        if quarter_end_month == 12:
            next_month = quarter_end_year + 1, 1
        else:
            next_month = quarter_end_year, quarter_end_month + 1

        quarter_end = today_date.replace(year=next_month[0], month=next_month[1], day=1)
        return add_days(quarter_end, -1)

    def _calculate_yearly_cutoff(self, today_date: date, settings) -> date:
        """Calculate end of current book year."""
        book_year_end_month = getattr(settings, "book_year_end_month", 12)
        book_year_end_day = getattr(settings, "book_year_end_day", 31)
        book_year_start_month = getattr(settings, "book_year_start_month", 1)

        if today_date.month >= book_year_start_month:
            book_year = today_date.year
        else:
            book_year = today_date.year - 1

        # Calculate book year end date
        # For fiscal years that span two calendar years (e.g., April-March),
        # the end year is the year after the book year started.
        # For standard calendar years (Jan-Dec), the end year is the same as book_year.
        if book_year_end_month < book_year_start_month:
            # Fiscal year spans two calendar years (e.g., April 2025 - March 2026)
            end_year = book_year + 1
        else:
            # Standard calendar year or fiscal year within same calendar year
            end_year = book_year

        try:
            return today_date.replace(year=end_year, month=book_year_end_month, day=book_year_end_day)
        except ValueError:
            # Invalid day (e.g., Feb 31) - use last day of month
            if book_year_end_month == 12:
                next_month = end_year + 1, 1
            else:
                next_month = end_year, book_year_end_month + 1
            last_day_of_month = today_date.replace(year=next_month[0], month=next_month[1], day=1)
            return add_days(last_day_of_month, -1)

    def get_eligible_schedules(
        self,
        cutoff_date: Optional[date] = None,
        test_mode: bool = False,
        include_details: bool = False,
    ) -> EligibilityDetails:
        """
        Find schedules eligible for invoice generation.

        Applies comprehensive filtering:
        - Active status
        - Auto-generate enabled
        - Valid member status
        - Test mode matching
        - Coverage gap analysis
        - Business logic validation

        Args:
            cutoff_date: Target date for coverage (defaults to calculated cutoff)
            test_mode: Whether to filter for test mode schedules only
            include_details: Whether to return detailed filtering information

        Returns:
            EligibilityDetails with eligible schedules and filtering breakdown
        """
        if not cutoff_date:
            cutoff_date = self.calculate_cutoff_date()

        # Initialize tracking structures
        eligible_schedules = []
        filtered_members = {
            "ineligible_status": [],
            "test_mode_mismatch": [],
            "gap_reset": [],
            "business_logic": [],
            "no_customer": [],
            "duplicate_coverage": [],
            "too_early": [],
            "already_covered": [],
        }

        # Get all active schedules with member status filtering at SQL level
        all_schedules = frappe.db.sql(
            """
            SELECT
                mds.name,
                mds.next_invoice_date,
                mds.test_mode,
                m.name as member_id,
                m.first_name,
                m.last_name,
                m.status as member_status,
                m.customer
            FROM `tabMembership Dues Schedule` mds
            INNER JOIN `tabMember` m ON m.name = mds.member
            WHERE mds.status = 'Active'
            AND mds.auto_generate = 1
            AND mds.is_template = 0
            AND mds.member IS NOT NULL
            AND m.name IS NOT NULL
            ORDER BY m.last_name, m.first_name
            """,
            as_dict=True,
        )

        # Filter by member status
        ineligible_statuses = ["Terminated", "Expelled", "Deceased", "Quit"]
        eligible_for_processing = []

        for schedule_data in all_schedules:
            member_name = f"{schedule_data.first_name} {schedule_data.last_name}"

            if schedule_data.member_status in ineligible_statuses:
                filtered_members["ineligible_status"].append(
                    {
                        "member_id": schedule_data.member_id,
                        "member_name": member_name,
                        "reason": f"Member status: {schedule_data.member_status}",
                        "schedule": schedule_data.name,
                    }
                )
            else:
                eligible_for_processing.append(schedule_data)

        # Filter by test mode
        test_mode_eligible = []
        for schedule_data in eligible_for_processing:
            if test_mode and not schedule_data.test_mode:
                filtered_members["test_mode_mismatch"].append(
                    {
                        "member_id": schedule_data.member_id,
                        "member_name": f"{schedule_data.first_name} {schedule_data.last_name}",
                        "reason": "Test mode requested but schedule is not in test mode",
                        "schedule": schedule_data.name,
                    }
                )
            elif not test_mode and schedule_data.test_mode:
                filtered_members["test_mode_mismatch"].append(
                    {
                        "member_id": schedule_data.member_id,
                        "member_name": f"{schedule_data.first_name} {schedule_data.last_name}",
                        "reason": "Production mode requested but schedule is in test mode",
                        "schedule": schedule_data.name,
                    }
                )
            else:
                test_mode_eligible.append(schedule_data)

        # Business logic validation for each schedule
        for schedule_data in test_mode_eligible:
            try:
                schedule = frappe.get_doc("Membership Dues Schedule", schedule_data.name)
                member_name = f"{schedule_data.first_name} {schedule_data.last_name}"

                # Check if schedule needs invoice for cutoff period
                if not schedule.should_generate_for_cutoff_period(cutoff_date):
                    filtered_members["already_covered"].append(
                        {
                            "member_id": schedule_data.member_id,
                            "member_name": member_name,
                            "reason": f"Already has coverage through {cutoff_date}",
                            "schedule": schedule_data.name,
                        }
                    )
                    continue

                # Run comprehensive eligibility checks
                can_generate_result = schedule.can_generate_invoice()

                if isinstance(can_generate_result, tuple):
                    can_generate, reason = can_generate_result
                    gap_reset = False
                else:
                    can_generate = can_generate_result.get("can_generate", False)
                    reason = can_generate_result.get("reason", "Unknown")
                    gap_reset = can_generate_result.get("gap_reset", False)

                if can_generate:
                    eligible_schedules.append(schedule_data.name)
                else:
                    member_info = {
                        "member_id": schedule_data.member_id,
                        "member_name": member_name,
                        "reason": reason,
                        "schedule": schedule_data.name,
                    }

                    # Smart categorization based on reason text
                    if gap_reset or "gap reset" in reason.lower():
                        filtered_members["gap_reset"].append(member_info)
                    elif "customer" in reason.lower():
                        filtered_members["no_customer"].append(member_info)
                    elif "overlap" in reason.lower() or "duplicate" in reason.lower():
                        filtered_members["duplicate_coverage"].append(member_info)
                    elif "too early" in reason.lower():
                        filtered_members["too_early"].append(member_info)
                    else:
                        filtered_members["business_logic"].append(member_info)

            except Exception as e:
                filtered_members["business_logic"].append(
                    {
                        "member_id": schedule_data.member_id,
                        "member_name": f"{schedule_data.first_name} {schedule_data.last_name}",
                        "reason": f"Error during validation: {str(e)}",
                        "schedule": schedule_data.name,
                    }
                )
                frappe.log_error(
                    f"Error validating schedule {schedule_data.name}: {str(e)}",
                    "Schedule Eligibility Check Error",
                )

        total_filtered = sum(len(filtered_members[cat]) for cat in filtered_members)

        return EligibilityDetails(
            eligible_schedules=eligible_schedules,
            filtered_members=filtered_members,
            total_filtered=total_filtered,
            summary={
                "total_schedules_checked": len(all_schedules),
                "eligible_count": len(eligible_schedules),
                "filtered_count": total_filtered,
                "filter_breakdown": {
                    category: len(members) for category, members in filtered_members.items()
                },
            },
        )

    def generate_invoices(self, test_mode: bool = False) -> BulkGenerationResult:
        """
        Generate membership dues invoices in bulk.

        Main entry point for bulk invoice generation. Handles:
        - Concurrency protection via advisory locks (Redis preferred, database fallback)
        - Accounting configuration validation
        - Parallel vs sequential processing decision
        - Payment history updates
        - Coverage gap detection

        Args:
            test_mode: Whether to run in test mode

        Returns:
            BulkGenerationResult with generation statistics and details
        """
        from verenigingen.utils.db_advisory_lock import (
            AdvisoryLockError,
            _is_redis_available,
            advisory_lock_with_backend,
        )

        result = BulkGenerationResult()

        # Get lock timeout from settings
        lock_timeout = frappe.db.get_single_value("Verenigingen Settings", "bulk_generation_timeout") or 3600

        # Determine backend: prefer Redis for distributed locking, fallback to database
        backend = "redis" if _is_redis_available() else "database"
        if backend == "database":
            self.logger.info("Redis unavailable, using database advisory lock")

        try:
            # Try to acquire lock with graceful handling
            with advisory_lock_with_backend(
                self.LOCK_NAME,
                timeout=0,  # Non-blocking: return immediately if lock unavailable
                backend=backend,
                ttl=lock_timeout,
                raise_on_timeout=False,
            ) as lock_acquired:
                if not lock_acquired:
                    result.errors.append("Another invoice generation process is already running")
                    return result

                return self._execute_invoice_generation(test_mode, result)

        except AdvisoryLockError as e:
            # Lock system error - do NOT proceed without protection to prevent duplicates
            self.logger.error(f"Lock system error: {str(e)}. Aborting to prevent duplicate generation.")
            result.errors.append(f"Lock system error: {str(e)}. Please retry or contact support.")
            return result

    def _execute_invoice_generation(
        self, test_mode: bool, result: BulkGenerationResult
    ) -> BulkGenerationResult:
        """
        Execute the actual invoice generation logic.

        Extracted to support both locked and unlocked execution paths.

        Args:
            test_mode: Whether to run in test mode
            result: BulkGenerationResult to populate

        Returns:
            BulkGenerationResult with generation statistics and details
        """
        try:
            # Validate accounting configuration
            self._validate_accounting_configuration()

            # Set bulk processing flag
            frappe.flags.bulk_invoice_generation = True

            # Calculate cutoff date
            cutoff_date = self.calculate_cutoff_date()
            result.cutoff_date = cutoff_date

            # Get eligible schedules
            eligibility_result = self.get_eligible_schedules(
                cutoff_date=cutoff_date,
                test_mode=test_mode,
                include_details=True,
            )

            schedules = eligibility_result.eligible_schedules
            result.filtered_members = eligibility_result.filtered_members
            result.total_filtered = eligibility_result.total_filtered
            result.total_schedules = len(schedules)

            # Log filtering summary
            self.logger.info(
                f"Dues invoice generation: Checked {eligibility_result.summary['total_schedules_checked']} schedules, "
                f"found {len(schedules)} eligible, filtered {eligibility_result.total_filtered}"
            )

            # Decide between parallel and sequential processing
            total_schedules = len(schedules)
            use_parallel = total_schedules > 50 and not test_mode

            if use_parallel:
                return self._process_parallel(schedules, cutoff_date, test_mode, result)
            else:
                return self._process_sequential(schedules, cutoff_date, test_mode, result)

        finally:
            # Clear bulk processing flag
            if getattr(frappe.flags, "bulk_invoice_generation", None):
                delattr(frappe.flags, "bulk_invoice_generation")

    def _validate_accounting_configuration(self):
        """Validate that accounting is properly configured before generating invoices."""
        from verenigingen.utils.settings_utils import get_default_company

        company = get_default_company()
        if not company:
            frappe.throw("No default company configured in Verenigingen Settings")

        missing_configs = []
        company_doc = frappe.get_cached_doc("Company", company)

        if not company_doc.round_off_account:
            missing_configs.append(f"{company}: Missing Round Off Account")
        if not company_doc.default_receivable_account:
            missing_configs.append(f"{company}: Missing Default Receivable Account")
        if not company_doc.default_income_account:
            missing_configs.append(f"{company}: Missing Default Income Account")

        if missing_configs:
            error_msg = (
                "Cannot generate invoices: Accounting configuration incomplete.\n\n"
                + "Missing configurations:\n"
                + "\n".join(f"  - {config}" for config in missing_configs)
            )
            frappe.throw(error_msg, title="Accounting Configuration Required")

    def _process_parallel(
        self,
        schedules: List[str],
        cutoff_date: date,
        test_mode: bool,
        result: BulkGenerationResult,
    ) -> BulkGenerationResult:
        """Process schedules in parallel using background jobs."""
        total_schedules = len(schedules)
        num_workers = min(8, max(4, total_schedules // 100))
        chunk_size = (total_schedules + num_workers - 1) // num_workers

        self.logger.info(
            f"Using parallel processing: {total_schedules} schedules split into {num_workers} chunks"
        )

        # Split schedules into chunks
        chunks = []
        for i in range(0, total_schedules, chunk_size):
            chunks.append(schedules[i : i + chunk_size])

        # Enqueue background jobs
        job_ids = []
        for idx, chunk in enumerate(chunks, 1):
            job = frappe.enqueue(
                "verenigingen.services.billing.bulk_invoice_generation_service.process_invoice_chunk",
                queue="long",
                timeout=1800,
                now=False,
                schedule_names=chunk,
                chunk_id=idx,
                total_chunks=len(chunks),
                cutoff_date=cutoff_date,
                test_mode=test_mode,
            )
            job_ids.append(job)

        result.parallel_mode = True
        result.job_count = len(job_ids)
        result.message = f"Processing {total_schedules} invoices in {len(chunks)} parallel jobs."
        return result

    def _process_sequential(
        self,
        schedules: List[str],
        cutoff_date: date,
        test_mode: bool,
        result: BulkGenerationResult,
    ) -> BulkGenerationResult:
        """Process schedules sequentially."""
        self.logger.info(f"Using sequential processing for {len(schedules)} schedules")

        members_to_update = set()
        successful_invoices = []

        for schedule_name in schedules:
            try:
                schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
                result.processed += 1

                try:
                    invoice = schedule.generate_invoice()
                    if invoice:
                        result.generated += 1
                        invoice_data = {
                            "schedule": schedule_name,
                            "member": schedule.member_name,
                            "member_id": schedule.member,
                            "invoice": invoice,
                        }
                        result.invoices.append(invoice_data)
                        successful_invoices.append(invoice_data)

                        if schedule.member:
                            members_to_update.add(schedule.member)

                        schedule._clear_retry_tracking()
                    else:
                        error_msg = f"Schedule {schedule_name} returned None from generate_invoice()"
                        frappe.log_error(error_msg, "Invoice Generation Failed")
                        result.errors.append(error_msg)

                except frappe.ValidationError as ve:
                    recovery_result = schedule._handle_invoice_generation_failure(str(ve))
                    error_msg = self._format_validation_error(schedule_name, ve, recovery_result)
                    result.errors.append(error_msg)

                except Exception as ge:
                    recovery_result = schedule._handle_invoice_generation_failure(str(ge))
                    error_msg = (
                        f"Schedule {schedule_name} unexpected error "
                        f"(retry {recovery_result['retry_count']}/3): {str(ge)[:100]}"
                    )
                    frappe.log_error(error_msg, "Invoice Generation Unexpected Error")
                    result.errors.append(f"ERROR: {error_msg}")

            except Exception as e:
                clean_error = self._clean_error_message(str(e))
                error_msg = f"Error processing {schedule_name}: {clean_error}"
                frappe.log_error(error_msg, "Membership Dues Generation")
                result.errors.append(error_msg)

        # Commit changes
        frappe.db.commit()

        # Bulk update payment history
        if members_to_update:
            try:
                result.payment_history_updates = self.bulk_update_payment_history(
                    members_to_update, successful_invoices
                )
            except Exception as e:
                error_msg = f"Error in bulk payment history update: {str(e)[:100]}"
                frappe.log_error(error_msg, "Bulk Payment History Update Error")
                result.errors.append(error_msg)

        # Detect coverage gaps
        result.coverage_gaps, result.coverage_gap_count = self._detect_coverage_gaps(
            successful_invoices, cutoff_date
        )

        # Log blocked members summary
        self._log_blocked_members_summary()

        # Add rejection reasons
        if hasattr(frappe.local, "generation_rejections"):
            result.rejection_reasons = frappe.local.generation_rejections

        return result

    def _format_validation_error(self, schedule_name: str, error: Exception, recovery_result: Dict) -> str:
        """Format validation error message based on recovery action."""
        if recovery_result["action_taken"] == "date_advanced":
            return (
                f"ADVANCED: Schedule {schedule_name} validation failed, dates advanced: "
                f"{str(error)[:100]}. Retry count: {recovery_result['retry_count']}"
            )
        elif recovery_result["action_taken"] == "retry_tracked":
            return (
                f"RETRY {recovery_result['retry_count']}: Schedule {schedule_name} "
                f"validation failed (retry {recovery_result['retry_count']}/3): {str(error)[:100]}"
            )
        elif recovery_result["action_taken"] == "skipped":
            return (
                f"MANUAL REVIEW: Schedule {schedule_name} flagged for manual review "
                f"after {recovery_result['retry_count']} failures: {str(error)[:100]}"
            )
        return f"ERROR: {schedule_name}: {str(error)[:100]}"

    def _clean_error_message(self, error: str) -> str:
        """Clean error message to prevent HTML formatting cascade."""
        clean_error = re.sub(r"<[^<]+?>", "", error)  # Remove HTML tags
        clean_error = re.sub(r"Error Log [a-zA-Z0-9]+:", "", clean_error)
        return clean_error.strip()[:80]

    def _detect_coverage_gaps(self, successful_invoices: List[Dict], cutoff_date: date) -> tuple:
        """Detect members with coverage gaps after generation."""
        coverage_gaps = []

        for invoice_data in successful_invoices:
            try:
                invoice = invoice_data["invoice"]
                if hasattr(invoice, "custom_coverage_end_date") and invoice.custom_coverage_end_date:
                    if invoice.custom_coverage_end_date < cutoff_date:
                        gap_days = (cutoff_date - invoice.custom_coverage_end_date).days
                        coverage_gaps.append(
                            {
                                "member": invoice_data["member_id"],
                                "schedule": invoice_data["schedule"],
                                "invoice": invoice.name,
                                "coverage_end": invoice.custom_coverage_end_date,
                                "cutoff_date": cutoff_date,
                                "gap_days": gap_days,
                            }
                        )
            except Exception as e:
                frappe.log_error(f"Error checking coverage gap: {str(e)}", "Coverage Gap Detection")

        if coverage_gaps:
            gap_count = len(coverage_gaps)
            max_gap_days = max(gap["gap_days"] for gap in coverage_gaps)
            frappe.log_error(
                f"Coverage Gap Alert: {gap_count} members still have coverage gaps.\n"
                f"Maximum gap: {max_gap_days} days",
                "Coverage Gaps After Bulk Generation",
            )

        return coverage_gaps, len(coverage_gaps)

    def _log_blocked_members_summary(self):
        """Generate aggregated report for members blocked from invoice generation."""
        if not hasattr(frappe.local, "blocked_members") or not frappe.local.blocked_members:
            return

        total_blocked = sum(len(members) for members in frappe.local.blocked_members.values())

        summary_lines = [
            f"Daily Invoice Generation - Blocked Members Summary ({total_blocked} members blocked)",
            "=" * 80,
        ]

        for status, members in frappe.local.blocked_members.items():
            summary_lines.append(f"\n{status.upper()} STATUS: {len(members)} members")
            for member_info in members[:10]:
                member_name = member_info.get("member_name", member_info["member"])
                summary_lines.append(f"  - {member_info['member']} ({member_name})")

            if len(members) > 10:
                summary_lines.append(f"  ... and {len(members) - 10} more {status} members")

        frappe.log_error("\n".join(summary_lines), "Daily Blocked Members Summary")
        frappe.local.blocked_members = {}

    def bulk_update_payment_history(self, member_names: Set[str], successful_invoices: List[Dict]) -> int:
        """
        Efficiently update payment history for multiple members after bulk invoice generation.

        Args:
            member_names: Set of member names that need payment history updates
            successful_invoices: List of invoice data dictionaries

        Returns:
            Number of members successfully updated
        """
        updated_count = 0

        for member_name in member_names:
            try:
                if not DocumentExistenceValidator.check_document_exists("Member", member_name):
                    frappe.log_error(
                        f"Member {member_name} not found during bulk payment history update",
                        "Bulk Payment History Update",
                    )
                    continue

                member_invoices = [inv for inv in successful_invoices if inv.get("member_id") == member_name]

                if member_invoices:
                    member_doc = frappe.get_doc("Member", member_name)

                    for inv_data in member_invoices:
                        try:
                            from verenigingen.utils.member_financial_history_manager import (
                                get_payment_history_manager,
                            )

                            manager = get_payment_history_manager(member_doc)

                            def build_invoice_entry():
                                invoice = member_doc._get_invoice_with_retry(inv_data["invoice"])
                                if invoice and invoice.customer == member_doc.customer:
                                    return member_doc._build_payment_history_entry(invoice)
                                return None

                            manager.add_or_update_entry(inv_data["invoice"], build_invoice_entry, "invoice")
                        except Exception as inv_error:
                            frappe.log_error(
                                f"Failed to add invoice {inv_data['invoice']} to payment history: {str(inv_error)}",
                                "Individual Invoice Payment History Update",
                            )

                    updated_count += 1

            except Exception as e:
                frappe.log_error(
                    f"Error updating payment history for member {member_name}: {str(e)}",
                    "Bulk Payment History Member Update",
                )

        return updated_count

    def get_parallel_status(self) -> Dict:
        """
        Check the status of parallel invoice generation background jobs.

        Returns:
            Status information about queued and running jobs
        """
        from frappe.utils.background_jobs import get_jobs

        jobs = get_jobs(site=frappe.local.site, queue="long")

        invoice_jobs = []
        for job_id, job_info in jobs.items():
            if "process_invoice_chunk" in str(job_info.get("method", "")):
                invoice_jobs.append(
                    {
                        "job_id": job_id,
                        "status": job_info.get("status"),
                        "method": job_info.get("method"),
                        "created": job_info.get("creation"),
                    }
                )

        return {
            "total_jobs": len(invoice_jobs),
            "jobs": invoice_jobs,
            "message": f"Found {len(invoice_jobs)} invoice generation jobs in queue",
        }


def get_bulk_invoice_generation_service() -> BulkInvoiceGenerationService:
    """Get singleton instance of BulkInvoiceGenerationService."""
    return BulkInvoiceGenerationService()


# Module-level function for background job processing
def process_invoice_chunk(
    schedule_names: List[str],
    chunk_id: int,
    total_chunks: int,
    cutoff_date: date,
    test_mode: bool = False,
) -> ChunkResult:
    """
    Worker function to process a chunk of invoices in parallel.

    This function is called by background jobs for parallel processing.

    Args:
        schedule_names: List of schedule names to process in this chunk
        chunk_id: Identifier for this chunk (for logging)
        total_chunks: Total number of chunks being processed
        cutoff_date: Cutoff date for invoice generation
        test_mode: Whether to run in test mode

    Returns:
        ChunkResult with processed invoices, errors, and members to update
    """
    frappe.set_user("Administrator")

    result = ChunkResult(chunk_id=chunk_id)
    result.members_to_update = set()

    frappe.logger().info(f"Chunk {chunk_id}/{total_chunks}: Processing {len(schedule_names)} schedules")

    for schedule_name in schedule_names:
        try:
            schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
            result.processed += 1

            try:
                invoice = schedule.generate_invoice()
                if invoice:
                    result.generated += 1
                    invoice_data = {
                        "schedule": schedule_name,
                        "member": schedule.member_name,
                        "member_id": schedule.member,
                        "invoice": invoice,
                    }
                    result.invoices.append(invoice_data)

                    if schedule.member:
                        result.members_to_update.add(schedule.member)

                    schedule._clear_retry_tracking()
                else:
                    error_msg = f"Schedule {schedule_name} returned None from generate_invoice()"
                    frappe.log_error(title=f"Chunk {chunk_id} Invoice Gen Failed", message=error_msg)
                    result.errors.append(error_msg)

            except frappe.ValidationError as ve:
                recovery_result = schedule._handle_invoice_generation_failure(str(ve))
                error_msg = (
                    f"Schedule {schedule_name} validation failed "
                    f"(retry {recovery_result['retry_count']}/3): {str(ve)[:MAX_LOG_ERROR_LENGTH]}"
                )
                _safe_log_error(f"Chunk {chunk_id} Validation", schedule_name, ve)
                result.errors.append(error_msg)

            except Exception as e:
                error_msg = f"Unexpected error for {schedule_name}: {str(e)[:MAX_LOG_ERROR_LENGTH]}"
                _safe_log_error(f"Chunk {chunk_id} Error", schedule_name, e)
                result.errors.append(error_msg)

        except Exception as outer_e:
            error_msg = f"Error loading schedule {schedule_name}: {str(outer_e)[:MAX_LOG_ERROR_LENGTH]}"
            _safe_log_error(f"Chunk {chunk_id} Load Error", schedule_name, outer_e)
            result.errors.append(error_msg)

    frappe.db.commit()

    frappe.logger().info(
        f"Chunk {chunk_id}/{total_chunks} complete: {result.generated}/{result.processed} invoices generated"
    )

    return result


def _safe_log_error(title: str, schedule_name: str, error: Exception):
    """Safely log an error with fallbacks."""
    try:
        frappe.log_error(
            title=title,
            message=f"Schedule: {schedule_name}\n\n{str(error)}\n\n{frappe.get_traceback()}",
        )
    except Exception:
        try:
            frappe.logger().error(f"{title} for {schedule_name}: {str(error)}")
        except Exception:
            print(f"CRITICAL: All logging failed for {schedule_name}", file=sys.stderr)
