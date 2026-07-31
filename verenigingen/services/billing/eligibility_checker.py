# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
EligibilityChecker Service - Consolidated eligibility determination for invoice generation.

Extracts eligibility validation logic from MembershipDuesSchedule god object.
Provides structured, testable validation with detailed failure reasons.

Architecture:
    - Inherits from StatelessService for consistent logging, metrics, error handling
    - Returns EligibilityResult with category-based routing for detailed diagnostics
"""

from typing import Any, Dict, Optional

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.services.infrastructure.base_service import StatelessService


class EligibilityResult:
    """
    Result object for eligibility checks.

    Provides detailed eligibility status with category-based reasons
    for better diagnostics and error reporting.

    Deprecated: Migrate to OperationResult[None] in future versions.

    This class maintains backward compatibility while providing OperationResult-compatible
    properties for gradual migration.

    Attributes:
        can_generate: Whether invoice generation is allowed (legacy - use .success)
        reason: Human-readable explanation (legacy - use .error_message for failures)
        category: Classification of result ("valid", "member_status", "membership",
                  "rate", "duplicate", "timing", "system")
        metadata: Additional context (gap_reset, lock_status, etc.)
        success: OperationResult-compatible alias for can_generate
        error_message: OperationResult-compatible alias for reason (when can_generate=False)
    """

    def __init__(self, can_generate: bool, reason: str, category: str, **metadata: Any):
        """
        Initialize eligibility result.

        Args:
            can_generate: Whether invoice generation is allowed
            reason: Human-readable explanation
            category: Classification of result
            **metadata: Additional context for debugging/reporting
        """
        self.can_generate = can_generate
        self.reason = reason
        self.category = category
        self.metadata = metadata

        # OperationResult-compatible properties
        self.success: bool = can_generate
        self.data = None  # No data payload for eligibility checks
        self.error_message: Optional[str] = reason if not can_generate else None

    def to_dict(self) -> Dict:
        """
        Convert to dict for backward compatibility.

        Returns:
            dict: Result as dictionary with can_generate, reason, category, and metadata
        """
        return {
            "can_generate": self.can_generate,
            "reason": self.reason,
            "category": self.category,
            **self.metadata,
        }

    def __repr__(self):
        return (
            f"EligibilityResult(can_generate={self.can_generate}, "
            f"reason='{self.reason}', category='{self.category}')"
        )


class EligibilityChecker(StatelessService):
    """
    Service for determining if a membership dues schedule is eligible for invoice generation.

    Consolidates all eligibility validation logic into a single, testable service.
    Orchestrates multiple validation checks and returns structured results.

    The service performs checks in order of cost (cheapest first) and uses fast-fail
    semantics - returns immediately on first failure to minimize overhead.

    Example:
        checker = EligibilityChecker(schedule_doc)
        result = checker.check_eligibility(member_doc)
        if result.can_generate:
            # Generate invoice
        else:
            # Log or display result.reason (categorized by result.category)
    """

    def __init__(self, schedule_doc: Any):
        """
        Initialize checker with schedule context.

        Args:
            schedule_doc: MembershipDuesSchedule document
        """
        super().__init__(service_name="EligibilityChecker")
        self.schedule_name = schedule_doc.name
        self.member_name = schedule_doc.member
        self.billing_frequency = schedule_doc.billing_frequency
        self.status = schedule_doc.status
        self.auto_generate = schedule_doc.auto_generate
        self.is_template = schedule_doc.is_template
        self.test_mode = schedule_doc.test_mode
        self.membership_type = schedule_doc.membership_type
        self.next_invoice_date = schedule_doc.next_invoice_date
        self.last_invoice_date = schedule_doc.last_invoice_date
        self.invoice_days_before = getattr(schedule_doc, "invoice_days_before", None)

        # Keep reference to full doc for methods that need it
        self._schedule_doc = schedule_doc

    # ========== Primary Public API ==========

    def check_eligibility(
        self, member_doc: Optional[Any] = None, skip_concurrency_check: bool = False
    ) -> EligibilityResult:
        """
        Comprehensive eligibility check for invoice generation.

        Runs all validation checks in order of cheapest to most expensive.
        Returns immediately on first failure to minimize overhead.

        Fast checks (no I/O):
        1. Template check
        2. Status check
        3. Auto-generate flag
        4. Test mode bypass

        Database checks:
        5. Member status
        6. Active membership
        7. Customer record
        8. Rate validation
        9. Membership type consistency

        Expensive checks (Redis/SQL):
        10. Concurrency lock (Redis)
        11. Duplicate detection (SQL)

        Deliberately NOT checked here: when to generate. That is decided by
        BulkInvoiceGenerationService.should_generate_for_cutoff_period(), which compares
        the member's latest coverage end against the cutoff date derived from
        billing_cutoff_frequency. This service used to re-decide the same question from
        next_invoice_date and invoice_days_before, and the two mechanisms disagreed:
        next_invoice_date is derived from the POSTING date (billing_date_service.py:104),
        so it drifts out of step with coverage - on the live site 431 schedules carry a
        next_invoice_date 83 days later than their coverage actually lapsed. Coverage end
        versus cutoff is the single source of truth.

        Args:
            member_doc: Member document (fetched if not provided)
            skip_concurrency_check: Skip Redis lock check (useful for batch operations)

        Returns:
            EligibilityResult with can_generate status and detailed reason
        """

        # ========== Fast Checks (No I/O) ==========

        if self.is_template:
            return EligibilityResult(False, "Templates cannot generate invoices", "system")

        if self.status != "Active":
            return EligibilityResult(False, "Schedule is not active", "system")

        if not self.auto_generate:
            return EligibilityResult(False, "Auto generation is disabled", "system")

        # Test mode bypass - allows generation regardless of other checks
        if self.test_mode:
            return EligibilityResult(True, "Test mode - can generate", "valid")

        # ========== Member Validation (Database Access) ==========

        if self.member_name:
            # Fetch member if not provided
            if member_doc is None:
                try:
                    member_doc = frappe.get_doc("Member", self.member_name)
                except frappe.DoesNotExistError:
                    return EligibilityResult(
                        False, f"Member {self.member_name} does not exist", "member_status", orphaned=True
                    )

            # Member status check
            member_status_result = self.check_member_status(member_doc)
            if not member_status_result.can_generate:
                return member_status_result

            # Active membership check
            membership_result = self.check_active_membership(member_doc)
            if not membership_result.can_generate:
                return membership_result

            # Customer record check
            customer_result = self.check_customer_record(member_doc)
            if not customer_result.can_generate:
                return customer_result

        # ========== Business Logic Validation ==========

        # Rate validation
        rate_result = self.check_rate_validity()
        if not rate_result.can_generate:
            return rate_result

        # Membership type consistency
        if self.member_name and member_doc:
            type_result = self.check_membership_type_consistency(member_doc)
            if not type_result.can_generate:
                return type_result

        # ========== Expensive Checks (Redis/SQL) ==========

        # Concurrency protection (Redis check - relatively expensive)
        if not skip_concurrency_check:
            concurrency_result = self.check_concurrency_lock()
            if not concurrency_result.can_generate:
                return concurrency_result

        # Duplicate detection (most expensive - SQL query)
        duplicate_result = self.check_for_duplicates()
        if not duplicate_result.can_generate:
            return duplicate_result

        # All checks passed. WHEN to generate is not decided here - see the docstring.
        return EligibilityResult(True, "Can generate invoice", "valid")

    # ========== Individual Validation Methods ==========

    def check_member_status(self, member_doc: Any) -> EligibilityResult:
        """
        Check if member status allows billing.

        Terminated/Banned/Deceased members cannot be billed.
        Suspended members CAN be billed (they're still members, just inactive).
        Rejected/Expired members don't have active memberships so fail later checks.

        Args:
            member_doc: Member document to check

        Returns:
            EligibilityResult indicating if member status allows billing
        """
        ineligible_statuses = ["Quit", "Banned", "Deceased"]

        if member_doc.status in ineligible_statuses:
            # Aggregate blocked members for batch reporting
            # This prevents log spam when checking many schedules
            if not hasattr(frappe.local, "blocked_members"):
                frappe.local.blocked_members = {}
            if member_doc.status not in frappe.local.blocked_members:
                frappe.local.blocked_members[member_doc.status] = []

            frappe.local.blocked_members[member_doc.status].append(
                {
                    "member": self.member_name,
                    "member_name": getattr(member_doc, "member_name", self.member_name),
                    "schedule": self.schedule_name,
                }
            )

            return EligibilityResult(
                False, f"Member status: {member_doc.status}", "member_status", member_status=member_doc.status
            )

        return EligibilityResult(True, "Member status valid", "valid")

    def check_active_membership(self, member_doc: Any) -> EligibilityResult:
        """
        Check if member has an active membership record.

        A schedule without an active membership is orphaned and should not generate invoices.

        Args:
            member_doc: Member document to check

        Returns:
            EligibilityResult indicating if active membership exists
        """
        from verenigingen.utils.validation_utilities import DocumentExistenceValidator

        active_membership = DocumentExistenceValidator.check_document_exists(
            "Membership", {"member": self.member_name, "status": "Active", "docstatus": 1}
        )

        if not active_membership:
            self.logger.error(f"Invoice blocked: member {self.member_name} no active membership")
            return EligibilityResult(
                False, f"Member {self.member_name} has no active membership", "membership"
            )

        return EligibilityResult(True, "Active membership exists", "valid")

    def check_customer_record(self, member_doc: Any) -> EligibilityResult:
        """
        Check if member has a customer record for invoice creation.

        ERPNext requires a Customer record to create Sales Invoices.

        Args:
            member_doc: Member document to check

        Returns:
            EligibilityResult indicating if customer record exists
        """
        if not member_doc.customer:
            return EligibilityResult(
                False,
                f"Member {self.member_name} does not have a customer record",
                "system",
                missing_customer=True,
            )

        return EligibilityResult(True, "Customer record exists", "valid")

    def check_rate_validity(self) -> EligibilityResult:
        """
        Validate dues rate for reasonableness.

        Delegates to schedule's validate_dues_rate() method which checks:
        - Zero or negative rates
        - Extremely high rates (>€10,000/month)
        - Unrealistic custom frequencies

        Returns:
            EligibilityResult indicating if rate is valid
        """
        try:
            rate_validation = self._schedule_doc.validate_dues_rate()

            if not rate_validation["valid"]:
                return EligibilityResult(False, rate_validation["reason"], "rate", rate_check_failed=True)

            return EligibilityResult(True, "Rate validation passed", "valid")

        except Exception as e:
            # Fail closed on rate validation errors - better to block than generate invalid invoices
            self.logger.error(f"Rate validation error for {self.schedule_name}: {str(e)}")
            return EligibilityResult(False, f"Rate validation system error: {str(e)}", "system")

    def check_membership_type_consistency(self, member_doc: Any) -> EligibilityResult:
        """
        Verify member's current membership type matches schedule.

        Delegates to schedule's validate_membership_type_consistency() method.
        This prevents billing at the wrong rate if member changed membership type.

        Args:
            member_doc: Member document to check

        Returns:
            EligibilityResult indicating if membership types match
        """
        try:
            type_validation = self._schedule_doc.validate_membership_type_consistency()

            if not type_validation["valid"]:
                return EligibilityResult(False, type_validation["reason"], "membership", type_mismatch=True)

            return EligibilityResult(True, "Membership type consistent", "valid")

        except Exception as e:
            # Fail closed on type validation errors - better to block than bill at wrong rate
            self.logger.error(f"Type validation error for {self.schedule_name}: {str(e)}")
            return EligibilityResult(False, f"Type validation system error: {str(e)}", "system")

    def check_concurrency_lock(self) -> EligibilityResult:
        """
        Check for concurrent invoice generation using Redis lock.

        Prevents race conditions where multiple processes try to generate
        invoices for the same schedule simultaneously.

        Returns:
            EligibilityResult indicating if concurrent generation is detected
        """
        import time

        from frappe.utils.redis_wrapper import RedisWrapper

        try:
            redis = RedisWrapper.from_url(frappe.conf.redis_cache)
            schedule_lock_key = f"verenigingen_invoice_generation_{self.schedule_name}"

            # Check if another process is already generating an invoice
            existing_lock = redis.get(schedule_lock_key)
            if existing_lock:
                # Allow a small grace period for quick operations to complete
                time.sleep(0.1)
                if redis.get(schedule_lock_key):
                    return EligibilityResult(
                        False,
                        "Another process is already generating an invoice for this schedule",
                        "system",
                        concurrent_generation=True,
                    )

            return EligibilityResult(True, "No concurrent generation detected", "valid")

        except Exception as e:
            # Fail closed on Redis errors - if Redis is down, instance has bigger problems
            # Pre-generation safety checks (missing invoice checks) provide additional safety
            self.logger.error(f"Redis lock check error for {self.schedule_name}: {str(e)}")
            return EligibilityResult(False, f"Concurrency check system error: {str(e)}", "system")

    def check_for_duplicates(self) -> EligibilityResult:
        """
        Check for duplicate invoice coverage using DuplicateInvoiceDetector.

        This is the primary duplicate prevention mechanism based on coverage periods.
        Prevents generating invoices that would overlap with existing coverage.

        Returns:
            EligibilityResult indicating if duplicate coverage exists
        """
        try:
            duplicate_check = self._schedule_doc.check_for_duplicate_invoices()

            if not duplicate_check["can_generate"]:
                return EligibilityResult(
                    False,
                    duplicate_check["reason"],
                    "duplicate",
                    gap_reset=duplicate_check.get("gap_reset", False),
                    overlap_detected=True,
                )

            return EligibilityResult(
                True,
                "No duplicate coverage detected",
                "valid",
                gap_reset=duplicate_check.get("gap_reset", False),
            )

        except Exception as e:
            # Fail closed on duplicate detection errors
            # Better to block generation than create duplicates
            self.logger.error(f"Duplicate check error for {self.schedule_name}: {str(e)}")
            return EligibilityResult(False, f"Duplicate detection error: {str(e)}", "system")

    # check_schedule_timing() was removed here. It decided WHEN to generate from
    # next_invoice_date - invoice_days_before, duplicating the cutoff comparison in
    # BulkInvoiceGenerationService.should_generate_for_cutoff_period() and disagreeing
    # with it: next_invoice_date is derived from the posting date, so it drifts a period
    # backwards on every early generation. With invoice_days_before defaulting to 30 -
    # a whole Monthly period - that drift re-opened the guard the day after each
    # generation, so a Monthly member accumulated one invoice per scheduler run until
    # coverage reached the cutoff. Coverage end versus cutoff is now the only rule.
