# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, today

from verenigingen.services.billing import DuplicateInvoiceDetector
from verenigingen.services.billing.billing_period_calculator import (
    calculate_billing_period,
    calculate_next_invoice_date,
)
from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.validation_utilities import DocumentExistenceValidator


class MembershipDuesSchedule(Document):
    def get_template_values(self):
        """
        Get billing and contribution values from template if available.

        EXTRACTED: Moved to TemplateConfigurationService for service layer separation.

        Returns:
            dict: Template configuration values (minimum_amount, suggested_amount, etc.)
        """
        from verenigingen.services.billing.template_configuration_service import TemplateConfigurationService

        return TemplateConfigurationService().get_template_values(
            schedule_doc=self,
            membership_type=self.membership_type,
            is_template=self.is_template,
            skip_validation=getattr(self, "_skip_template_validation", False),
        )

    def before_save(self):
        """Store document state before save for comparison"""
        if not self.is_new():
            self._doc_before_save = frappe.get_doc("Membership Dues Schedule", self.name)

    def validate(self):
        self.validate_permissions()
        self.validate_template_or_instance()
        self.validate_member_membership()
        self.validate_dates()
        self.validate_custom_frequency()
        self.validate_progressive_configuration()
        self.sync_from_template()
        self.set_dues_rate_from_membership_type()
        self.validate_dues_rate_configuration()
        self.validate_financial_constraints()
        self.validate_status_transitions()
        self.validate_billing_frequency_consistency()
        self.validate_rate_boundaries()
        self.set_billing_day()
        self._initialize_next_invoice_date()

        # Note: Old values tracking moved to before_save() to capture actual previous values

    def validate_template_or_instance(self):
        """Validate template vs instance fields"""
        if self.is_template:
            # Templates must have membership type but no member
            if not self.membership_type:
                frappe.throw("Templates must specify a Membership Type")
            if self.member:
                frappe.throw("Templates cannot have a specific member")
            if self.template_reference:
                frappe.throw("Templates cannot reference other templates")
        else:
            # Instances must have member
            if not self.member:
                frappe.throw("Individual schedules must specify a member")
            # Validate uniqueness - one active schedule per member
            # Skip check if this is from an amendment (amendment handles cancellation)
            if not self.flags.get("from_amendment"):
                existing = frappe.db.get_value(
                    "Membership Dues Schedule",
                    {
                        "member": self.member,
                        "is_template": 0,
                        "status": "Active",
                        "name": ["!=", self.name or ""],
                    },
                    "name",
                )
                if existing:
                    frappe.throw(
                        f"Member {self.member} already has an active dues schedule: <a href='/app/membership-dues-schedule/{existing}' target='_blank'>{existing}</a>. "
                        f"Please edit the existing schedule or deactivate it before creating a new one.",
                        title="Duplicate Dues Schedule",
                    )

    def validate_member_membership(self):
        """Ensure the member has an active membership"""
        if self.is_template:
            return

        if self.member:
            # Skip active membership validation if we're pausing the schedule
            # This allows membership cancellation to pause dues schedules properly
            if getattr(self, "_skip_membership_validation", False):
                return

            # Skip validation when cancelling or pausing the schedule
            # This allows cleanup after membership cancellation
            if self.status in ["Cancelled", "Paused"]:
                return

            # Check if member has any active membership
            active_membership = DocumentExistenceValidator.check_document_exists(
                "Membership", {"member": self.member, "status": "Active", "docstatus": 1}
            )
            if not active_membership:
                frappe.throw(f"Member {self.member} does not have an active membership")

            # Auto-link to membership type from active membership if not set
            if not self.membership_type:
                membership_type = frappe.db.get_value("Membership", active_membership, "membership_type")
                if membership_type:
                    self.membership_type = membership_type

    def validate_dates(self):
        """
        Validate schedule dates.
        DELEGATES to: DuesScheduleValidationService.validate_dates()
        """
        if self.is_template:
            return

        from verenigingen.services.billing.dues_schedule_validation_service import (
            get_dues_schedule_validation_service,
        )

        return get_dues_schedule_validation_service().validate_dates(self)

    def validate_custom_frequency(self):
        """Validate custom frequency settings"""
        if self.is_template:
            return

        if self.billing_frequency == "Custom":
            # Check if fields exist (might not exist during migration)
            frequency_number = getattr(self, "custom_frequency_number", None)
            frequency_unit = getattr(self, "custom_frequency_unit", None)

            if not frequency_number or frequency_number <= 0:
                frappe.throw("Custom frequency number must be a positive integer")
            if not frequency_unit:
                frappe.throw("Custom frequency unit must be specified when using custom billing")

    def validate_progressive_configuration(self):
        """
        Validate progressive contribution mode settings.

        DELEGATES TO: ProgressiveDuesService.validate_progressive_configuration()
        """
        if self.is_template:
            return

        from verenigingen.services.billing.progressive_dues_service import (
            get_progressive_dues_service,
        )

        get_progressive_dues_service().validate_progressive_configuration(self)

    def calculate_progressive_dues(self, monthly_income, base_dues=None):
        """
        Calculate suggested dues based on progressive sliding scale formula.

        DELEGATES TO: ProgressiveDuesService.calculate_progressive_dues()

        Args:
            monthly_income: Applicant's monthly net income
            base_dues: The standard dues rate (100% reference). If None, uses suggested_amount.

        Returns:
            dict with keys:
                - multiplier: The calculated multiplier (0.0 to unbounded)
                - percentage: Multiplier as percentage (0 to unbounded)
                - suggested_dues: Calculated dues amount
                - base_dues: The base dues used for calculation
        """
        from verenigingen.services.billing.progressive_dues_service import (
            get_progressive_dues_service,
        )

        result = get_progressive_dues_service().calculate_progressive_dues(self, monthly_income, base_dues)
        return {
            "multiplier": result.multiplier,
            "percentage": result.percentage,
            "suggested_dues": result.suggested_dues,
            "base_dues": result.base_dues,
        }

    def validate_permissions(self):
        """
        Validate user permissions for editing this document.

        DELEGATES TO: DuesSchedulePermissionService.validate_permissions()
        """
        if self.is_template:
            return

        from verenigingen.services.billing.dues_schedule_permission_service import (
            get_dues_schedule_permission_service,
        )

        result = get_dues_schedule_permission_service().validate_permissions(self)
        if not result.allowed:
            frappe.throw(result.reason)

    def can_user_edit_schedule(self, user):
        """
        Check if user can edit this individual (non-template) schedule.

        DELEGATES TO: DuesSchedulePermissionService.can_user_edit_schedule()
        """
        from verenigingen.services.billing.dues_schedule_permission_service import (
            get_dues_schedule_permission_service,
        )

        result = get_dues_schedule_permission_service().can_user_edit_schedule(self, user)
        return result.allowed

    def validate_member_edit(self):
        """
        Validate what fields a member can edit on their own schedule.

        DELEGATES TO: DuesSchedulePermissionService.validate_member_edit()
        """
        from verenigingen.services.billing.dues_schedule_permission_service import (
            get_dues_schedule_permission_service,
        )

        result = get_dues_schedule_permission_service().validate_member_edit(self)
        if not result.allowed:
            frappe.throw(result.reason)
        return True

    def validate_dues_rate_change(self):
        """
        Validate if dues rate change meets requirements.

        DELEGATES to: DuesScheduleValidationService.validate_dues_rate_change()
        """
        from verenigingen.services.billing.dues_schedule_validation_service import (
            get_dues_schedule_validation_service,
        )

        return get_dues_schedule_validation_service().validate_dues_rate_change(self)

    def is_chapter_board_with_finance(self, user):
        """
        Check if user is a chapter board member with financial permissions.

        DELEGATES TO: DuesSchedulePermissionService.is_chapter_board_with_finance()
        """
        from verenigingen.services.billing.dues_schedule_permission_service import (
            get_dues_schedule_permission_service,
        )

        return get_dues_schedule_permission_service().is_chapter_board_with_finance(self.member, user)

    def validate_dues_rate_configuration(self):
        """
        Validate dues rate based on contribution mode.

        DELEGATES to: DuesScheduleValidationService.validate_dues_rate_configuration()
        """
        from verenigingen.services.billing.dues_schedule_validation_service import (
            get_dues_schedule_validation_service,
        )

        get_dues_schedule_validation_service().validate_dues_rate_configuration(self)

    def validate_financial_constraints(self):
        """
        Validate financial constraints and limits.

        DELEGATES to: DuesScheduleValidationService.validate_financial_constraints()
        """
        from verenigingen.services.billing.dues_schedule_validation_service import (
            get_dues_schedule_validation_service,
        )

        get_dues_schedule_validation_service().validate_financial_constraints(self)

    def sync_from_template(self):
        """Sync minimum_amount and other read-only fields from template and membership type"""
        if not self.membership_type:
            return

        membership_type = frappe.get_doc("Membership Type", self.membership_type)

        # For templates themselves, sync directly from membership type (not from another template)
        # This avoids circular logic where template calls get_template_values() which loads itself
        if self.is_template:
            # Templates get minimum_amount directly from membership type
            self.minimum_amount = (
                membership_type.minimum_amount if membership_type.minimum_amount is not None else 0
            )
            # Keep suggested_amount as manually set (don't override)
            return

        # For member-specific schedules, sync from the template
        template_values = self.get_template_values()

        # Always update minimum_amount from template (it's read-only so must be calculated)
        self.minimum_amount = template_values.get("minimum_amount", 0)

        # Update suggested_amount if not explicitly overridden
        if not self.suggested_amount:
            self.suggested_amount = template_values.get("suggested_amount", 0)

    def set_dues_rate_from_membership_type(self):
        """Set dues rate based on membership type template if not already set"""
        if self.is_template:
            return

        # Use 'is None' check to allow 0 as a valid dues rate (e.g., for free memberships)
        if self.dues_rate is None and self.membership_type:
            # Get the fee from template values (explicit configuration)
            template_values = self.get_template_values()
            if self.contribution_mode in ("Income-Based", "Flexible"):
                # suggested_amount is optional; fall back to minimum_amount
                self.dues_rate = (
                    template_values.get("suggested_amount") or template_values.get("minimum_amount") or 0
                )

    def set_billing_day(self):
        """
        Set billing day based on member's anniversary date.

        DELEGATES TO: BillingDateService.set_billing_day()
        """
        if self.is_template:
            return

        from verenigingen.services.billing.billing_date_service import (
            get_billing_date_service,
        )

        get_billing_date_service().set_billing_day(self)

    def _initialize_next_invoice_date(self):
        """Initialize next invoice date for new non-template schedules."""
        if self.is_new() and not self.is_template and not self.next_invoice_date:
            self.next_invoice_date = today()

    def can_generate_invoice(self):
        """
        Check if invoice can be generated with comprehensive validation.

        ✅ SERVICE EXTRACTION: Delegates to EligibilityChecker service for all validation logic.
        This method maintains backward compatibility by returning tuple format.

        Returns:
            tuple: (can_generate: bool, reason: str) for backward compatibility
        """
        from verenigingen.services.billing.eligibility_checker import EligibilityChecker

        # Delegate to service for comprehensive eligibility check
        checker = EligibilityChecker(self)
        result = checker.check_eligibility()

        # Return tuple for backward compatibility with existing code
        return result.can_generate, result.reason

    def check_for_duplicate_invoices(self):
        """
        Coverage-based duplicate invoice prevention using efficient SQL overlap detection.

        Delegates to DuplicateInvoiceDetector service for all duplicate detection logic.
        """
        # Calculate the period to check - use billing period for Monthly, sequential for others
        if self.billing_frequency == "Monthly":
            # For monthly schedules, check if the current month is already covered
            proposed_coverage_start, proposed_coverage_end = self.calculate_current_billing_period()
        else:
            # For other frequencies, use the existing sequential logic
            proposed_coverage_start, proposed_coverage_end = self.calculate_next_coverage_period()

        # Delegate to service
        detector = DuplicateInvoiceDetector(self)
        result = detector.check_for_duplicates(proposed_coverage_start, proposed_coverage_end)

        return result.to_dict()

    def calculate_current_billing_period(self):
        """
        Calculate the current billing period that should be covered by an invoice.
        This is different from calculate_next_coverage_period which uses sequential logic.

        Returns:
            tuple: (billing_start, billing_end) dates for the current period
        """
        return self.calculate_billing_period(frappe.utils.today())

    def get_latest_coverage_end_date(self):
        """
        Get the latest coverage end date from existing invoices for this schedule.

        ✅ SERVICE EXTRACTION: Use CoverageCalculator service for coverage queries.
        """
        from verenigingen.services.billing.coverage_calculator import CoverageCalculator

        if not self.member:
            return None

        member_doc = frappe.get_doc("Member", self.member)
        calculator = CoverageCalculator(self)

        return calculator.get_latest_coverage_end_date(member_doc)

    def calculate_next_coverage_period(self, force_date=None):
        """
        Calculate next coverage period using sequential logic for gap-free coverage.

        ✅ SERVICE EXTRACTION: Use CoverageCalculator service for period calculations.

        Args:
            force_date: Override date for coverage calculation (for testing/manual generation)

        Returns:
            tuple: (coverage_start, coverage_end) dates
        """
        from verenigingen.services.billing.coverage_calculator import CoverageCalculator

        member_doc = frappe.get_doc("Member", self.member)
        calculator = CoverageCalculator(self)

        result = calculator.calculate_next_coverage_period(member_doc=member_doc, force_date=force_date)

        # Validate result (now uses OperationResult pattern)
        if not result.success:
            error_msg = result.error_message or "Unknown coverage calculation error"
            frappe.throw(error_msg)

        return result.data.start_date, result.data.end_date

    def should_generate_for_cutoff_period(self, cutoff_date):
        """
        Determine if this schedule needs invoice generation to cover through cutoff_date.

        ✅ SERVICE EXTRACTION: Use CoverageCalculator service for cutoff logic.

        Args:
            cutoff_date: Target date that should be covered by invoices

        Returns:
            bool: True if invoice generation is needed
        """
        from verenigingen.services.billing.coverage_calculator import CoverageCalculator

        calculator = CoverageCalculator(self)
        return calculator.should_generate_invoice_for_cutoff(cutoff_date)

    def calculate_billing_period(self, invoice_date):
        """Calculate the billing period start and end dates for a given invoice date"""
        return calculate_billing_period(
            billing_frequency=self.billing_frequency,
            invoice_date=invoice_date,
            custom_frequency_number=getattr(self, "custom_frequency_number", None),
            custom_frequency_unit=getattr(self, "custom_frequency_unit", None),
        )

    def validate_member_eligibility_for_invoice(self):
        """
        Check if member is eligible for invoice generation.

        DELEGATES: Uses existing EligibilityChecker service for member status
        and membership validation.

        This prevents billing terminated members and those without active memberships.
        Payment method validation is done at DD batch creation time, not invoice generation.

        Returns:
            bool: True if member is eligible, False otherwise
        """
        from verenigingen.services.billing.eligibility_checker import EligibilityChecker

        if not self.member:
            return False

        try:
            checker = EligibilityChecker(self)
            member_doc = frappe.get_doc("Member", self.member)

            # Check member status
            status_result = checker.check_member_status(member_doc)
            if not status_result.can_generate:
                return False

            # Check active membership
            membership_result = checker.check_active_membership(member_doc)
            if not membership_result.can_generate:
                return False

            return True

        except frappe.DoesNotExistError:
            # Handle orphaned schedules (member deleted)
            frappe.log_error(
                f"Orphaned schedule '{self.name}' refs deleted member '{self.member}'",
                "Orphaned Dues Schedule",
            )
            try:
                self.add_comment("Comment", f"⚠️ ORPHANED: Member '{self.member}' not found.")
            except Exception:
                pass
            return False
        except Exception as e:
            frappe.log_error(
                f"Member validation error {self.member}: {str(e)[:50]}",
                "Member Eligibility Error",
            )
            return False

    def is_orphaned(self):
        """
        Check if this dues schedule references a non-existent member
        Returns True if the member doesn't exist, False otherwise
        """
        if not self.member:
            return False  # Templates and schedules without members are not orphaned
        return not DocumentExistenceValidator.check_document_exists("Member", self.member)

    @staticmethod
    def find_orphaned_schedules(limit=50):
        """
        Find dues schedules that reference non-existent members
        Returns list of schedule names and member IDs that need cleanup
        """
        orphaned = frappe.db.sql(
            """
            SELECT mds.name, mds.member, mds.status, mds.is_template
            FROM `tabMembership Dues Schedule` mds
            LEFT JOIN `tabMember` m ON m.name = mds.member
            WHERE m.name IS NULL
            AND mds.member IS NOT NULL
            AND mds.is_template = 0
            LIMIT %s
        """,
            (limit,),
            as_dict=True,
        )
        return orphaned

    def validate_dues_rate(self):
        """
        Validate dues rate for reasonableness and business logic.

        DELEGATES to: DuesScheduleValidationService.validate_dues_rate()
        """
        from verenigingen.services.billing.dues_schedule_validation_service import (
            get_dues_schedule_validation_service,
        )

        return get_dues_schedule_validation_service().validate_dues_rate(self)

    def validate_membership_type_consistency(self):
        """
        Verify member's current membership type matches schedule.
        DELEGATES to: DuesScheduleValidationService.validate_membership_type_consistency()
        """
        from verenigingen.services.billing.dues_schedule_validation_service import (
            get_dues_schedule_validation_service,
        )

        return get_dues_schedule_validation_service().validate_membership_type_consistency(self)

    @staticmethod
    def _deduplicate_error_message(error_msg):
        """
        Remove repetitive error prefixes.
        DELEGATES to: InvoiceErrorHandlerService._deduplicate_error_message()
        """
        from verenigingen.services.billing.invoice_error_handler_service import (
            get_invoice_error_handler_service,
        )

        return get_invoice_error_handler_service()._deduplicate_error_message(error_msg)

    @staticmethod
    def _is_deadlock_error(error_msg):
        """
        Check if error is a database deadlock.
        DELEGATES to: InvoiceErrorHandlerService._is_deadlock_error()
        """
        from verenigingen.services.billing.invoice_error_handler_service import (
            get_invoice_error_handler_service,
        )

        return get_invoice_error_handler_service()._is_deadlock_error(error_msg)

    def generate_invoice(self, force=False):
        """
        Generate invoice for the current period.

        Delegates to InvoiceGenerationOrchestrator for the full pipeline:
        eligibility check -> Redis lock -> coverage calc -> invoice generation -> tracking.

        Preserves existing contract: returns invoice doc or None, raises ValidationError on failure.
        """
        from verenigingen.services.billing.invoice_generation_orchestrator import (
            InvoiceGenerationOrchestrator,
        )

        orchestrator = InvoiceGenerationOrchestrator(self)
        result = orchestrator.generate(force=force)

        if not result.success:
            if result.error_message:
                raise frappe.ValidationError(result.error_message)
            return None

        return result.data

    def _handle_invoice_generation_failure(self, error_message):
        """
        Handle invoice generation failures with smart recovery logic.
        DELEGATES to: InvoiceErrorHandlerService.handle_invoice_generation_failure()
        """
        from verenigingen.services.billing.invoice_error_handler_service import (
            get_invoice_error_handler_service,
        )

        return get_invoice_error_handler_service().handle_invoice_generation_failure(self, error_message)

    def _clear_retry_tracking(self):
        """Clear retry tracking fields after successful invoice generation."""
        try:
            # Import secure operations
            from verenigingen.utils.secure_operations import secure_document_operation

            # Reset error tracking using secure operations
            self.custom_invoice_retry_count = 0
            self.custom_deadlock_count = 0
            self.custom_last_invoice_failure_date = None
            self.custom_last_invoice_error = None
            self.custom_requires_manual_review = 0
            secure_document_operation(
                operation="save",
                doc=self,
                justification=f"Successful invoice generation for {self.name} - resetting error tracking",
                required_permissions=["Membership Dues Schedule:write"],
                validate_business_rules=False,
            )
        except Exception as e:
            # Don't let retry tracking cleanup break invoice generation success
            frappe.log_error(
                f"Failed to clear retry tracking for {self.name}: {str(e)}", "Retry Tracking Cleanup Error"
            )

    def _should_auto_advance_schedule(self, error_message):
        """
        Determine if a schedule should be auto-advanced based on error patterns.
        DELEGATES to: InvoiceErrorHandlerService.should_auto_advance_schedule()
        """
        from verenigingen.services.billing.invoice_error_handler_service import (
            get_invoice_error_handler_service,
        )

        return get_invoice_error_handler_service().should_auto_advance_schedule(self, error_message)

    def _trigger_health_reconstruction(self, error_message):
        """
        Trigger health system reconstruction for this member
        """
        try:
            # Log the trigger for monitoring
            frappe.log_error(
                f"Triggered health reconstruction for member {self.member} due to error: {error_message}",
                "Health Reconstruction Trigger",
            )

            # If the error suggests missing membership data, try immediate reconstruction
            error_lower = error_message.lower()
            if "membership_type" in error_lower or "missing membership" in error_lower:
                try:
                    from verenigingen.services.billing.dues_schedule_health_manager import (
                        DuesScheduleHealthManager,
                    )

                    manager = DuesScheduleHealthManager()
                    manager.reconstruct_missing_membership(self.member)
                    manager.sync_member_fields(self.member)
                except Exception as reconstruction_error:
                    frappe.log_error(
                        f"Immediate reconstruction failed for {self.member}: {str(reconstruction_error)}",
                        "Immediate Reconstruction Error",
                    )

        except Exception as e:
            frappe.log_error(
                f"Failed to trigger health reconstruction for {self.member}: {str(e)}", "Health Trigger Error"
            )

    def _advance_schedule_dates(self):
        """Advance schedule dates to the next billing period."""
        try:
            # Calculate next invoice date based on billing frequency
            if self.next_invoice_date:
                new_next_date = self.calculate_next_invoice_date(self.next_invoice_date)

                # Update dates using db_set to avoid validation loops
                frappe.db.set_value(self.doctype, self.name, "last_invoice_date", self.next_invoice_date)
                frappe.db.set_value(self.doctype, self.name, "next_invoice_date", new_next_date)

                # Update local object for immediate consistency
                self.last_invoice_date = self.next_invoice_date
                self.next_invoice_date = new_next_date

                frappe.log_error(
                    f"Advanced schedule {self.name}: last_invoice_date={self.last_invoice_date}, next_invoice_date={self.next_invoice_date}",
                    "Schedule Date Advancement",
                )
        except Exception as e:
            frappe.log_error(
                f"Failed to advance dates for schedule {self.name}: {str(e)}", "Date Advancement Error"
            )

    def get_membership_dues_item(self):
        """Get the membership dues item name (assumes it exists)"""
        if self.billing_frequency == "Custom":
            # Get custom frequency settings with validation
            frequency_number = getattr(self, "custom_frequency_number", None)
            if not frequency_number or frequency_number < 1:
                frequency_number = 1  # Safe default

            frequency_unit = getattr(self, "custom_frequency_unit", None)
            if not frequency_unit:
                frequency_unit = "Months"  # Safe default
            frequency_desc = f"Every {frequency_number} {frequency_unit}"
            item_name = f"Membership Dues - Custom ({frequency_desc})"
        else:
            item_name = f"Membership Dues - {self.billing_frequency}"

        return item_name

    def ensure_membership_dues_item_exists(self):
        """Ensure the membership dues item exists - called before transaction starts"""
        item_name = self.get_membership_dues_item()

        if not DocumentExistenceValidator.check_document_exists("Item", item_name):
            # Get correct company settings
            settings = frappe.get_single("Verenigingen Settings")
            if not settings.company:
                frappe.throw("Company not configured in Verenigingen Settings")

            # Create item outside of the main transaction to avoid implicit commits
            item = frappe.new_doc("Item")
            item.item_code = item_name
            item.item_name = item_name
            item.item_group = "Services"
            item.is_sales_item = 1

            # Set correct default accounts from configuration
            # Income account from Verenigingen Payments Settings - use the proper P&L income account
            from verenigingen.utils.settings_utils import get_payments_settings

            payments_settings = get_payments_settings()
            # dues_income_account is a field on Verenigingen Payments Settings, not this DocType
            income_acct = (
                getattr(payments_settings, "dues_income_account", None) if payments_settings else None
            )
            if income_acct:
                item.income_account = income_acct

            # Expense account from Company's default cost of goods sold account
            try:
                company_doc = frappe.get_cached_doc("Company", settings.company)
                if company_doc.default_cost_of_goods_sold:
                    item.expense_account = company_doc.default_cost_of_goods_sold
            except Exception:
                pass  # Use defaults if not available

            item.insert()
            # Let Frappe handle transaction management automatically

        return item_name

    def update_schedule_dates(self, actual_invoice_date=None):
        """
        Update schedule dates after invoice generation.

        DELEGATES TO: BillingDateService.update_schedule_dates()

        CRITICAL FIX: For daily/sequential billing, base next_invoice_date on coverage end
        rather than posting date to prevent date drift when generating ahead of time.
        """
        from verenigingen.services.billing.billing_date_service import (
            get_billing_date_service,
        )

        get_billing_date_service().update_schedule_dates(self, actual_invoice_date)

    def get_member_payment_method(self):
        """Get member's preferred payment method"""
        if not self.member:
            return "Bank Transfer"  # Default

        active_mandate = frappe.db.exists(
            "SEPA Mandate",
            {"member": self.member, "status": "Active", "is_active": 1, "used_for_memberships": 1},
        )

        if active_mandate:
            return "SEPA Direct Debit"
        else:
            return "Bank Transfer"

    def get_member_active_mandate(self):
        """Get member's active SEPA mandate if exists"""
        if not self.member:
            return None

        return frappe.db.get_value(
            "SEPA Mandate",
            {"member": self.member, "status": "Active", "is_active": 1, "used_for_memberships": 1},
            "name",
        )

    def calculate_next_invoice_date(self, from_date=None):
        """Calculate next billing date based on frequency"""
        if not from_date:
            from_date = self.next_invoice_date or today()

        return calculate_next_invoice_date(
            billing_frequency=self.billing_frequency,
            from_date=from_date,
            custom_frequency_number=getattr(self, "custom_frequency_number", None),
            custom_frequency_unit=getattr(self, "custom_frequency_unit", None),
        )

    def pause_schedule(self, reason=None):
        """
        Pause the dues schedule.

        DELEGATES TO: DuesScheduleLifecycleService.pause_schedule()
        """
        from verenigingen.services.billing.dues_schedule_lifecycle_service import (
            get_dues_schedule_lifecycle_service,
        )

        get_dues_schedule_lifecycle_service().pause_schedule(self, reason)

    def resume_schedule(self, new_next_date=None):
        """
        Resume the dues schedule.

        DELEGATES TO: DuesScheduleLifecycleService.resume_schedule()
        """
        from verenigingen.services.billing.dues_schedule_lifecycle_service import (
            get_dues_schedule_lifecycle_service,
        )

        get_dues_schedule_lifecycle_service().resume_schedule(self, new_next_date)

    @staticmethod
    def create_default_template(membership_type):
        """
        Create a default template for a membership type.

        EXTRACTED: Moved to TemplateCreationService for service layer separation.
        """
        from verenigingen.services.billing.template_creation_service import TemplateCreationService

        return TemplateCreationService().create_default_template(membership_type)

    @staticmethod
    def create_from_template(
        member_name,
        template_name=None,
        membership_type=None,
        membership_name=None,
        custom_amount=None,
        custom_amount_reason=None,
        custom_amount_approved=0,
    ):
        """
        Create an individual dues schedule from a template.

        EXTRACTED: Moved to TemplateCreationService for service layer separation.
        """
        from verenigingen.services.billing.template_creation_service import TemplateCreationService

        return TemplateCreationService().create_from_template(
            member_name=member_name,
            template_name=template_name,
            membership_type=membership_type,
            membership_name=membership_name,
            custom_amount=custom_amount,
            custom_amount_reason=custom_amount_reason,
            custom_amount_approved=custom_amount_approved,
        )

    def after_insert(self):
        """Handle new schedule creation.

        DELEGATES TO: FeeChangeTrackingService.handle_new_schedule()
        """
        if self.is_template or not self.member:
            return

        from verenigingen.services.billing.fee_change_tracking_service import (
            get_fee_change_tracking_service,
        )

        # Record fee change and update member dues_rate via centralized service
        get_fee_change_tracking_service().handle_new_schedule(self)

        # Update member's current_dues_schedule if this should be the current one
        from .membership_dues_schedule_hooks import update_member_current_dues_schedule

        update_member_current_dues_schedule(self)

    def on_update(self):
        """
        Track billing history changes when schedule is updated.

        DELEGATES TO: FeeChangeTrackingService.handle_schedule_update()
        """
        if self.is_template or not self.member:
            return

        from verenigingen.services.billing.fee_change_tracking_service import (
            get_fee_change_tracking_service,
        )

        get_fee_change_tracking_service().handle_schedule_update(self)

        # Update member's current_dues_schedule when status changes
        if (
            hasattr(self, "_doc_before_save")
            and self._doc_before_save
            and self._doc_before_save.status != self.status
        ):
            from .membership_dues_schedule_hooks import update_member_current_dues_schedule

            update_member_current_dues_schedule(self)

    def update_member_dues_rate(self):
        """
        Update the member's dues_rate field to match the schedule.

        DELEGATES TO: FeeChangeTrackingService.update_member_dues_rate()
        """
        from verenigingen.services.billing.fee_change_tracking_service import (
            get_fee_change_tracking_service,
        )

        get_fee_change_tracking_service().update_member_dues_rate(self)

    def _record_schedule_fee_change(self, change_type, old_rate, new_rate):
        """
        Record fee change using the centralized recording service with smart deduplication.

        DELEGATES TO: FeeChangeRecordingService.record()

        Note: Prefer using FeeChangeTrackingService.handle_new_schedule() or
        handle_schedule_update() for hook-based recording. This method is kept
        for backwards compatibility.
        """
        if not self.member:
            return

        from verenigingen.services.member.financial.fee_change_recording_service import (
            get_fee_change_recording_service,
        )

        reason = (
            self.custom_amount_reason
            if self.uses_custom_amount
            else f"Schedule {change_type.lower()} - {self.schedule_name or self.name}"
        )

        get_fee_change_recording_service().record(
            member=self.member,
            old_amount=old_rate or 0,
            new_amount=new_rate,
            change_type=change_type,
            reason=reason,
            dues_schedule=self.name,
            billing_frequency=self.billing_frequency,
        )

    # ✅ ERPNext-Inspired Validation Enhancements

    def validate_status_transitions(self):
        """
        Validate allowed status transitions.

        DELEGATES TO: DuesScheduleLifecycleService.validate_status_transition()
        """
        from verenigingen.services.billing.dues_schedule_lifecycle_service import (
            get_dues_schedule_lifecycle_service,
        )

        get_dues_schedule_lifecycle_service().validate_status_transition(self)

    def validate_billing_frequency_consistency(self):
        """
        Ensure member's schedules maintain consistent billing frequencies
        Based on ERPNext's billing cycle consistency validation
        """
        if self.is_template or not self.member:
            return

        # Skip check if this is from an amendment (amendment handles old schedule cancellation)
        if self.flags.get("from_amendment"):
            return

        existing_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member, "status": "Active", "name": ["!=", self.name]},
            fields=["billing_frequency", "name"],
        )

        conflicting_schedules = [
            s for s in existing_schedules if s.billing_frequency != self.billing_frequency
        ]

        if conflicting_schedules:
            from verenigingen.utils.exceptions import BillingFrequencyConflictError

            conflicting_frequencies = list(set([s.billing_frequency for s in conflicting_schedules]))
            raise BillingFrequencyConflictError(
                f"Member {self.member} has existing schedules with different billing frequencies: "
                f"{', '.join(conflicting_frequencies)}. Current schedule uses {self.billing_frequency}. "
                f"All schedules for a member must use the same billing frequency."
            )

    def validate_rate_boundaries(self):
        """
        Enhanced rate validation with comprehensive boundary checks.

        DELEGATES to: DuesScheduleValidationService.validate_rate_boundaries()
        """
        from verenigingen.services.billing.dues_schedule_validation_service import (
            get_dues_schedule_validation_service,
        )

        get_dues_schedule_validation_service().validate_rate_boundaries(self)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def calculate_cutoff_date_for_period():
    """
    Calculate the cutoff date for invoice generation based on Verenigingen Settings.

    DELEGATES TO: BulkInvoiceGenerationService.calculate_cutoff_date()

    Returns:
        date: The cutoff date through which invoices should provide coverage
    """
    from verenigingen.services.billing.bulk_invoice_generation_service import (
        get_bulk_invoice_generation_service,
    )

    return get_bulk_invoice_generation_service().calculate_cutoff_date()


def get_eligible_schedules_for_period(cutoff_date=None, test_mode=False, include_details=False):
    """
    Unified eligibility logic for identifying schedules that need invoice generation.

    DELEGATES TO: BulkInvoiceGenerationService.get_eligible_schedules()

    Args:
        cutoff_date: Target date that invoices should cover through (defaults to calculated cutoff)
        test_mode: Whether to filter for test mode schedules only
        include_details: Whether to return detailed filtering information

    Returns:
        If include_details=False: List of eligible schedule names
        If include_details=True: Dict with details
    """
    from verenigingen.services.billing.bulk_invoice_generation_service import (
        get_bulk_invoice_generation_service,
    )

    result = get_bulk_invoice_generation_service().get_eligible_schedules(
        cutoff_date=cutoff_date, test_mode=test_mode, include_details=include_details
    )

    if include_details:
        return {
            "eligible_schedules": result.eligible_schedules,
            "filtered_members": result.filtered_members,
            "total_filtered": result.total_filtered,
            "summary": result.summary,
        }
    else:
        return result.eligible_schedules


def generate_dues_invoices(test_mode=False):
    """
    Enhanced scheduled job to generate membership dues invoices with coverage-aware logic.

    DELEGATES TO: BulkInvoiceGenerationService.generate_invoices()

    Features:
    - Coverage-aware selection
    - Sequential coverage with gap-free billing
    - Coverage gap detection
    - Configurable cutoff periods
    - Concurrency protection
    - Parallel processing for large batches
    """
    from verenigingen.services.billing.bulk_invoice_generation_service import (
        get_bulk_invoice_generation_service,
    )

    result = get_bulk_invoice_generation_service().generate_invoices(test_mode)

    # Convert dataclass to dict for backward compatibility
    return {
        "processed": result.processed,
        "generated": result.generated,
        "errors": result.errors,
        "invoices": result.invoices,
        "payment_history_updates": result.payment_history_updates,
        "filtered_members": result.filtered_members,
        "total_filtered": result.total_filtered,
        "cutoff_date": result.cutoff_date,
        "coverage_gaps": result.coverage_gaps,
        "coverage_gap_count": result.coverage_gap_count,
        "rejection_reasons": result.rejection_reasons,
        "parallel_mode": result.parallel_mode,
        "job_count": result.job_count,
        "total_schedules": result.total_schedules,
        "message": result.message,
    }


@frappe.whitelist()
def get_parallel_invoice_generation_status():
    """
    Check the status of parallel invoice generation background jobs.

    DELEGATES TO: BulkInvoiceGenerationService.get_parallel_status()

    Returns:
        dict: Status information about queued and running jobs
    """
    from verenigingen.services.billing.bulk_invoice_generation_service import (
        get_bulk_invoice_generation_service,
    )

    return get_bulk_invoice_generation_service().get_parallel_status()


def _process_invoice_chunk(schedule_names, chunk_id, total_chunks, cutoff_date, test_mode=False):
    """
    Worker function to process a chunk of invoices in parallel.

    DELEGATES TO: bulk_invoice_generation_service.process_invoice_chunk()
    """
    from verenigingen.services.billing.bulk_invoice_generation_service import (
        process_invoice_chunk,
    )

    return process_invoice_chunk(schedule_names, chunk_id, total_chunks, cutoff_date, test_mode)


def _bulk_update_payment_history(member_names, successful_invoices):
    """
    Efficiently update payment history for multiple members after bulk invoice generation.

    DELEGATES TO: BulkInvoiceGenerationService.bulk_update_payment_history()
    """
    from verenigingen.services.billing.bulk_invoice_generation_service import (
        get_bulk_invoice_generation_service,
    )

    return get_bulk_invoice_generation_service().bulk_update_payment_history(
        member_names, successful_invoices
    )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def create_schedule_from_template(member_name: str, template_name: str = None):
    """API endpoint to create schedule from template"""
    return MembershipDuesSchedule.create_from_template(member_name, template_name)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def create_template_for_membership_type(membership_type: str, template_name: str = None):
    """Create a new template for a membership type"""
    if not template_name:
        # Use membership type name for more descriptive template naming
        membership_type_doc = frappe.get_doc("Membership Type", membership_type)
        template_name = f"Template-{membership_type_doc.membership_type_name}"

    # Check if template already exists
    existing = frappe.db.exists(
        "Membership Dues Schedule", {"membership_type": membership_type, "is_template": 1}
    )
    if existing:
        frappe.throw(f"Template already exists for {membership_type}: {existing}")

    # Get membership type details
    membership_type_doc = frappe.get_doc("Membership Type", membership_type)

    # Create template
    template = frappe.new_doc("Membership Dues Schedule")
    template.is_template = 1
    template.schedule_name = template_name
    template.membership_type = membership_type
    template.status = "Active"

    # Set defaults from membership type
    template.billing_frequency = "Annual"  # Default, since this is now owned by dues schedule
    template.contribution_mode = getattr(membership_type_doc, "contribution_mode", "Income-Based")
    template.minimum_amount = 0  # Will be set per schedule
    template.suggested_amount = 15.0  # Default template value - should be configured explicitly
    template.invoice_days_before = 30  # Default
    template.billing_day = 1  # Default template billing day
    template.auto_generate = 1

    template.insert()

    # Link template back to membership type
    membership_type_doc.dues_schedule_template = template.name
    membership_type_doc.save()

    return template.name


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_member_dues_schedule(member: str = None):
    """Get dues schedule for a member (with permission checks)"""
    user = frappe.session.user

    # If no member specified, try to get current user's member record
    if not member:
        member = frappe.db.get_value("Member", {"user": user}, "name")
        if not member:
            frappe.throw("No member record found for current user")

    # Check permissions
    member_user = frappe.db.get_value("Member", member, "user")
    if member_user != user:
        # Check if user has permission to view this member's schedule
        roles = frappe.get_roles(user)
        if not any(role in roles for role in Roles.ADMIN_ROLES):
            # Check if user is chapter board with finance permissions
            schedule_doc = frappe.new_doc("Membership Dues Schedule")
            schedule_doc.member = member
            if not schedule_doc.is_chapter_board_with_finance(user):
                frappe.throw("You don't have permission to view this member's dues schedule")

    # Get the schedule
    schedule_name = frappe.db.get_value(
        "Membership Dues Schedule", {"member": member, "is_template": 0}, "name"
    )

    if not schedule_name:
        return None

    return frappe.get_doc("Membership Dues Schedule", schedule_name)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def update_member_contribution(schedule_name: str, updates: str):
    """Update member's contribution settings with permission checks"""
    if isinstance(updates, str):
        updates = frappe.parse_json(updates)

    schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

    # Permission check happens in validate()

    # Only allow updating specific fields
    allowed_updates = {
        "contribution_mode": updates.get("contribution_mode"),
        "selected_tier": updates.get("selected_tier"),
        # The field is default_multiplier; accept the legacy "base_multiplier" payload
        # key too (the membership application form posts that name).
        "default_multiplier": updates.get("default_multiplier", updates.get("base_multiplier")),
        "uses_custom_amount": updates.get("uses_custom_amount"),
        "custom_amount_reason": updates.get("custom_amount_reason"),
        "dues_rate": updates.get("dues_rate"),
        "notes": updates.get("notes"),
    }

    # Remove None values
    allowed_updates = {k: v for k, v in allowed_updates.items() if v is not None}

    # Update the document
    for field, value in allowed_updates.items():
        setattr(schedule, field, value)

    schedule.save()

    return {"success": True, "schedule": schedule.as_dict()}


def has_permission(doc, user=None, permission_type="read"):
    """
    DELEGATES TO: DuesSchedulePermissionService.check_document_permission()

    Custom permission handler for Membership Dues Schedule.
    """
    from verenigingen.services.billing.dues_schedule_permission_service import (
        has_permission as _has_permission,
    )

    return _has_permission(doc, user, permission_type)


def get_permission_query_conditions(user=None):
    """
    DELEGATES TO: DuesSchedulePermissionService.get_permission_query_conditions()

    Permission query conditions for Membership Dues Schedule list views.
    """
    from verenigingen.services.billing.dues_schedule_permission_service import (
        get_permission_query_conditions as _get_permission_query_conditions,
    )

    return _get_permission_query_conditions(user)


def _log_blocked_members_summary():
    """
    DEPRECATED: Moved to BulkInvoiceGenerationService._log_blocked_members_summary()

    This function is now called internally by BulkInvoiceGenerationService.generate_invoices().
    This stub is kept for backward compatibility with any direct callers.
    """
    from verenigingen.services.billing.bulk_invoice_generation_service import (
        get_bulk_invoice_generation_service,
    )

    get_bulk_invoice_generation_service()._log_blocked_members_summary()
