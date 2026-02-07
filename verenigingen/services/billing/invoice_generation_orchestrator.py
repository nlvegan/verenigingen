# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
InvoiceGenerationOrchestrator - Orchestrates the full single-schedule invoice generation pipeline.

Extracted from MembershipDuesSchedule.generate_invoice() (lines 608-780) which was a 174-line
god method mixing five concerns:
1. Eligibility checking
2. Redis concurrency locking
3. Coverage calculation
4. Invoice generation delegation
5. Error handling with coverage tracking

This orchestrator uses OperationResult internally and is called by the controller's
thin generate_invoice() delegator, which translates back to the legacy contract
(returns invoice/None, raises ValidationError).

Architecture:
    - Inherits from StatelessService for consistent logging, metrics, error handling
    - Returns OperationResult[SalesInvoice] for all outcomes
    - Delegates to existing services: EligibilityChecker, CoverageCalculator, InvoiceGenerator
"""

from typing import Any, Tuple

import frappe

from verenigingen.services.billing.invoice_error_handler_service import (
    get_invoice_error_handler_service,
)
from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.billing_constants import MAX_USER_ERROR_LENGTH
from verenigingen.utils.operation_result import OperationResult


class InvoiceGenerationOrchestrator(StatelessService):
    """
    Orchestrates single-schedule invoice generation.

    Owns the full pipeline: eligibility -> lock -> coverage calc -> generate -> track.
    All outcomes are returned as OperationResult[SalesInvoice].

    Example:
        orchestrator = InvoiceGenerationOrchestrator(schedule_doc)
        result = orchestrator.generate(force=False)
        if result.success:
            invoice = result.data
    """

    def __init__(self, schedule_doc):
        super().__init__(service_name="InvoiceGenerationOrchestrator")
        self.schedule = schedule_doc

    def generate(self, force: bool = False) -> OperationResult:
        """
        Main entry point - orchestrates the full invoice generation pipeline.

        Args:
            force: If True, skip eligibility checks

        Returns:
            OperationResult with SalesInvoice doc on success, None on skip/test-mode
        """
        # 1. Eligibility check
        eligibility = self._check_eligibility(force)
        if eligibility.metadata.get("skipped"):
            return eligibility

        # 2. Test mode early return
        if self.schedule.test_mode:
            return self._handle_test_mode()

        # 3. Acquire Redis lock
        lock_acquired, redis_conn, lock_key = self._acquire_lock()

        try:
            # If lock was not acquired (another process is generating), skip
            if redis_conn and not lock_acquired:
                frappe.log_error(
                    f"Schedule {self.schedule.name} invoice generation blocked by concurrent process",
                    "Invoice Generation Concurrency",
                )
                return OperationResult.ok(None, skipped=True, reason="concurrent_lock")

            # 4. Execute generation pipeline
            frappe.flags.in_invoice_generation = True
            return self._execute_generation()

        except Exception as e:
            self._handle_error(e)

        finally:
            frappe.flags.in_invoice_generation = False
            self._release_lock(lock_acquired, redis_conn, lock_key)

    def _check_eligibility(self, force: bool) -> OperationResult:
        """
        Delegate eligibility check to EligibilityChecker.

        Classifies skip-reasons as info (expected business logic) vs error.
        """
        can_generate, reason = self.schedule.can_generate_invoice()

        if not can_generate and not force:
            reason_lower = reason.lower()
            if "not eligible for billing" in reason_lower or "coverage overlap" in reason_lower:
                frappe.logger().info(f"Invoice generation skipped for {self.schedule.name}: {reason}")
            else:
                frappe.log_error(
                    f"Cannot generate invoice: {reason}",
                    f"Membership Dues Schedule {self.schedule.name}",
                )
            return OperationResult.ok(None, skipped=True, reason=reason)

        return OperationResult.ok(None)

    def _handle_test_mode(self) -> OperationResult:
        """Handle test mode: log and update dates without creating an invoice."""
        frappe.logger().info(
            f"TEST MODE: Would generate invoice for {self.schedule.member} "
            f"- Dues Rate: {self.schedule.dues_rate}"
        )
        self.schedule.update_schedule_dates()
        return OperationResult.ok(None, test_mode=True)

    def _acquire_lock(self) -> Tuple[bool, Any, str]:
        """
        Acquire Redis lock for concurrency protection.

        Returns:
            (lock_acquired, redis_connection, lock_key) tuple.
            If Redis is unavailable, returns (False, None, key) and generation proceeds
            without concurrency protection.
        """
        from frappe.utils.redis_wrapper import RedisWrapper

        lock_key = f"verenigingen_invoice_generation_{self.schedule.name}"
        lock_timeout = (
            frappe.db.get_single_value("Verenigingen Settings", "invoice_generation_timeout") or 300
        )

        # Attempt Redis connection
        try:
            redis_conn = RedisWrapper.from_url(frappe.conf.redis_cache)
            redis_conn.ping()
        except Exception as redis_error:
            frappe.log_error(
                f"Redis unavailable for invoice generation concurrency protection: {str(redis_error)}",
                "Redis Connectivity Warning",
            )
            frappe.logger().warning(
                f"Invoice generation for {self.schedule.name} proceeding without "
                f"concurrency protection due to Redis unavailability"
            )
            return False, None, lock_key

        # Attempt lock acquisition
        try:
            lock_acquired = redis_conn.set(lock_key, "generating", nx=True, ex=lock_timeout)
            return lock_acquired, redis_conn, lock_key
        except Exception as lock_error:
            frappe.log_error(
                f"Failed to acquire Redis lock for {self.schedule.name}: {str(lock_error)}. "
                f"Proceeding without lock.",
                "Redis Lock Warning",
            )
            return False, None, lock_key

    def _release_lock(self, lock_acquired: bool, redis_conn: Any, lock_key: str):
        """Release Redis lock. Safe to call even if lock wasn't acquired."""
        if lock_acquired and redis_conn:
            try:
                redis_conn.delete(lock_key)
            except Exception as e:
                frappe.log_error(
                    f"Error releasing schedule lock for {self.schedule.name}: {str(e)}",
                    "Schedule Lock Cleanup",
                )

    def _execute_generation(self) -> OperationResult:
        """
        Core pipeline: coverage calc -> InvoiceGenerator -> coverage tracking -> date update.
        """
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        # Calculate coverage period
        coverage_start, coverage_end = self.schedule.calculate_next_coverage_period()

        # Get member document
        member_doc = frappe.get_doc("Member", self.schedule.member)

        # Generate invoice via service
        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(coverage_start, coverage_end, member_doc)

        if not result.success:
            frappe.throw(f"Invoice generation failed: {result.error_message}")

        invoice = result.data

        # Safety check: ensure we're not editing a cancelled invoice
        if invoice.docstatus == 2:
            frappe.throw(
                f"Cannot edit cancelled invoice {invoice.name}. "
                f"This may indicate a naming collision or data issue."
            )

        # Validate coverage dates were set
        if not invoice.custom_coverage_start_date or not invoice.custom_coverage_end_date:
            frappe.throw(f"Coverage dates were not set during invoice creation for {invoice.name}")

        # Update coverage tracking on schedule
        self._update_coverage_tracking(invoice, coverage_start, coverage_end)

        frappe.logger().info(
            f"Generated invoice {invoice.name} for {self.schedule.member} "
            f"covering period {coverage_start} to {coverage_end}"
        )

        return OperationResult.ok(invoice)

    def _update_coverage_tracking(self, invoice, coverage_start, coverage_end):
        """Set last_generated_invoice, coverage dates, and update schedule dates."""
        self.schedule.last_generated_invoice = invoice.name
        self.schedule.last_invoice_coverage_start = coverage_start
        self.schedule.last_invoice_coverage_end = coverage_end
        self.schedule.update_schedule_dates(actual_invoice_date=invoice.posting_date)

    def _handle_error(self, exc: Exception):
        """
        Handle invoice generation exceptions.

        Logs the error and re-raises as ValidationError to preserve existing contract.
        Always raises -- never returns.
        """
        error_handler = get_invoice_error_handler_service()
        error_msg = error_handler._deduplicate_error_message(str(exc))

        full_error_details = (
            f"Schedule: {self.schedule.name}\n"
            f"Error: {error_msg}\n\n"
            f"Traceback:\n{frappe.get_traceback()}"
        )

        try:
            frappe.log_error(
                title=f"Invoice Gen Fail - {self.schedule.name[:50]}",
                message=full_error_details,
            )
        except Exception:
            try:
                frappe.logger().error(
                    f"Failed to log invoice generation error for {self.schedule.name}. "
                    f"Original error: {error_msg}"
                )
            except Exception:
                pass

        user_error_msg = (
            f"Invoice gen failed for {self.schedule.name}: " f"{error_msg[:MAX_USER_ERROR_LENGTH]}"
        )
        raise frappe.ValidationError(user_error_msg)
