# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import re
import sys
from datetime import datetime, timedelta

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, add_months, add_years, flt, getdate, today

from verenigingen.services.billing import DuplicateInvoiceDetector
from verenigingen.utils.billing_constants import (
    DEADLOCK_PATTERNS,
    MAX_DB_ERROR_LENGTH,
    MAX_LOG_ERROR_LENGTH,
    MAX_USER_ERROR_LENGTH,
)
from verenigingen.utils.billing_period_calculator import calculate_billing_period, calculate_next_invoice_date
from verenigingen.utils.member_utils import get_active_membership_for_member, get_member_chapters
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    development_only_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.validation_utilities import DateRangeValidator, DocumentExistenceValidator


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
        if not self.is_template:
            self.validate_member_membership()
            self.validate_dates()

        self.validate_custom_frequency()  # Validate custom frequency settings
        self.sync_from_template()  # Sync minimum_amount and other fields from template
        self.set_dues_rate_from_membership_type()  # Set default before validation
        self.validate_dues_rate_configuration()
        self.validate_financial_constraints()  # Add financial validation

        # ERPNext-inspired validation enhancements
        self.validate_status_transitions()
        self.validate_billing_frequency_consistency()
        self.validate_rate_boundaries()

        # Set billing day for member schedules
        if not self.is_template:
            self.set_billing_day()

        # Initialize next invoice date for new schedules
        if self.is_new() and not self.is_template and not self.next_invoice_date:
            self.next_invoice_date = today()

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
        from verenigingen.services.billing.dues_schedule_validation_service import (
            DuesScheduleValidationService,
        )

        return DuesScheduleValidationService.validate_dates(self)

    def validate_custom_frequency(self):
        """Validate custom frequency settings"""
        if self.billing_frequency == "Custom":
            # Check if fields exist (might not exist during migration)
            frequency_number = getattr(self, "custom_frequency_number", None)
            frequency_unit = getattr(self, "custom_frequency_unit", None)

            if not frequency_number or frequency_number <= 0:
                frappe.throw("Custom frequency number must be a positive integer")
            if not frequency_unit:
                frappe.throw("Custom frequency unit must be specified when using custom billing")

    def validate_permissions(self):
        """Validate user permissions for editing this document"""
        # Skip permission check if ignore_permissions flag is set
        if getattr(self, "_ignore_permissions", False) or frappe.flags.ignore_permissions:
            return

        if not self.is_new() and self.has_value_changed("is_template"):
            frappe.throw("Cannot change template status after creation")

        user = frappe.session.user

        # System Manager and configured creation user always have full access
        creation_user = None
        try:
            settings = frappe.get_single("Verenigingen Settings")
            creation_user = getattr(settings, "creation_user", None)
        except Exception:
            pass

        admin_users = ["System Manager"]
        if creation_user:
            admin_users.append(creation_user)
        else:
            admin_users.append("Administrator")  # Fallback

        if user in admin_users or "System Manager" in frappe.get_roles(user):
            return

        # Check if user has Verenigingen Administrator role
        if "Verenigingen Administrator" in frappe.get_roles(user):
            return  # Full access

        # Template editing is restricted to Verenigingen Administrator only
        if self.is_template:
            frappe.throw("Only Verenigingen Administrators can edit template schedules")

        # For individual schedules, check various permission levels
        if not self.can_user_edit_schedule(user):
            frappe.throw("You don't have permission to edit this dues schedule")

    def can_user_edit_schedule(self, user):
        """Check if user can edit this individual (non-template) schedule"""
        if not self.member:
            return False

        # Check if user is the member themselves
        member_user = frappe.db.get_value("Member", self.member, "user")
        if member_user == user:
            return self.validate_member_edit()

        # Check if user has Verenigingen Staff role
        if "Verenigingen Staff" in frappe.get_roles(user):
            return True

        # Check if user is a chapter board member with finance permissions
        if self.is_chapter_board_with_finance(user):
            return True

        return False

    def validate_member_edit(self):
        """Validate what fields a member can edit on their own schedule"""
        # Members can only edit certain fields
        allowed_fields = [
            "dues_rate",
            "base_multiplier",
            "contribution_mode",
            "selected_tier",
            "uses_custom_amount",
            "custom_amount_reason",
            "notes",
            "status",
        ]

        # Check if any restricted fields were changed
        if self.is_new():
            return True

        # Check each field for changes
        for field in self.meta.fields:
            if field.fieldname in allowed_fields:
                continue

            if self.has_value_changed(field.fieldname):
                # Special case: dues_rate can be changed if it meets minimum
                if field.fieldname == "dues_rate":
                    if self.validate_dues_rate_change():
                        continue

                frappe.throw(f"Members cannot modify the field: {field.label}")

        return True

    def validate_dues_rate_change(self):
        """
        Validate if dues rate change meets requirements.

        DELEGATES to: DuesScheduleValidationService.validate_dues_rate_change()
        """
        from verenigingen.services.billing.dues_schedule_validation_service import (
            DuesScheduleValidationService,
        )

        return DuesScheduleValidationService.validate_dues_rate_change(self)

    def is_chapter_board_with_finance(self, user):
        """Check if user is a chapter board member with financial permissions"""
        if not self.member:
            return False

        # Get member's chapter through standardized utility
        chapters = get_member_chapters(self.member, active_only=True)
        if not chapters:
            return False
        chapter = chapters[0]  # Use first active chapter

        # Get the user's member record
        member_name = frappe.db.get_value("Member", {"user": user}, "name")
        if not member_name:
            return False

        # Get the volunteer linked to the member
        volunteer_name = frappe.db.get_value("Volunteer", {"member": member_name}, "name")
        if not volunteer_name:
            return False

        # Check if user is a board member of this chapter with finance permissions
        # Note: Chapter Board Member is a child table, not a standalone DocType
        board_member = frappe.db.get_value(
            "Chapter Board Member",
            {
                "parent": chapter,
                "volunteer": volunteer_name,
                "is_active": 1,
            },
            ["name", "chapter_role"],
            as_dict=True,
        )

        if not board_member:
            return False

        # Check if the role has financial permissions
        if board_member.chapter_role:
            role_doc = frappe.get_doc("Chapter Role", board_member.chapter_role)
            return getattr(role_doc, "permissions_level", None) in ["Financial", "Admin"]

        return False

    def validate_dues_rate_configuration(self):
        """
        Validate dues rate based on contribution mode.

        DELEGATES to: DuesScheduleValidationService.validate_dues_rate_configuration()
        """
        from verenigingen.services.billing.dues_schedule_validation_service import (
            DuesScheduleValidationService,
        )

        DuesScheduleValidationService.validate_dues_rate_configuration(self)

    def validate_financial_constraints(self):
        """
        Validate financial constraints and limits.

        DELEGATES to: DuesScheduleValidationService.validate_financial_constraints()
        """
        from verenigingen.services.billing.dues_schedule_validation_service import (
            DuesScheduleValidationService,
        )

        DuesScheduleValidationService.validate_financial_constraints(self)

    def validate_template_fields(self):
        """Additional validation for template-specific fields"""
        if self.is_template:
            # Templates should not have member-specific data
            # (Most member-specific fields have been removed)
            pass
        else:
            # Instances should have required member data
            self.member_name = None
            if not self.member_name:
                if self.member:
                    member_doc = frappe.get_doc("Member", self.member)
                    self.member_name = member_doc.full_name

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
        if not self.dues_rate and self.membership_type:
            # Get the fee from template values (explicit configuration)
            template_values = self.get_template_values()
            # For Calculator mode, use suggested_amount as default
            # For Custom mode, suggested_amount is optional (can be 0)
            # For Tier mode, dues_rate will be set from tier selection
            if self.contribution_mode == "Calculator":
                self.dues_rate = template_values.get("suggested_amount", 0)
            elif self.contribution_mode == "Custom":
                # For Custom mode, use suggested_amount if available, otherwise 0
                self.dues_rate = template_values.get("suggested_amount", 0)

    def set_billing_day(self):
        """Set billing day based on member's anniversary date"""
        self.billing_day = None
        if not self.billing_day or self.billing_day == 0:
            if self.member:
                # Get the member_since value directly from database to avoid field object issues
                member_since = frappe.db.get_value("Member", self.member, "member_since")
                if member_since:
                    # Use day from member's anniversary date
                    member_since_date = getdate(member_since)
                    self.billing_day = member_since_date.day
                else:
                    # Default to 1st of month when no member_since date
                    self.billing_day = 1
            else:
                # Default for templates or schedules without member
                self.billing_day = 1

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
            DuesScheduleValidationService,
        )

        return DuesScheduleValidationService.validate_dues_rate(self)

    def validate_membership_type_consistency(self):
        """
        Verify member's current membership type matches schedule.
        DELEGATES to: DuesScheduleValidationService.validate_membership_type_consistency()
        """
        from verenigingen.services.billing.dues_schedule_validation_service import (
            DuesScheduleValidationService,
        )

        return DuesScheduleValidationService.validate_membership_type_consistency(self)

    @staticmethod
    def _deduplicate_error_message(error_msg):
        """
        Remove repetitive error prefixes.
        DELEGATES to: InvoiceErrorHandlerService._deduplicate_error_message()
        """
        from verenigingen.services.billing.invoice_error_handler_service import InvoiceErrorHandlerService

        return InvoiceErrorHandlerService._deduplicate_error_message(error_msg)

    @staticmethod
    def _is_deadlock_error(error_msg):
        """
        Check if error is a database deadlock.
        DELEGATES to: InvoiceErrorHandlerService._is_deadlock_error()
        """
        from verenigingen.services.billing.invoice_error_handler_service import InvoiceErrorHandlerService

        return InvoiceErrorHandlerService._is_deadlock_error(error_msg)

    def generate_invoice(self, force=False):
        """Generate invoice for the current period with enhanced coverage tracking and concurrency protection"""
        from frappe.utils.redis_wrapper import RedisWrapper

        can_generate, reason = self.can_generate_invoice()

        if not can_generate and not force:
            # Use appropriate logging level based on reason - don't create error logs for expected business logic
            if "not eligible for billing" in reason.lower() or "coverage overlap" in reason.lower():
                # These are expected business logic outcomes, not errors
                frappe.logger().info(f"Invoice generation skipped for {self.name}: {reason}")
            else:
                # Actual errors that need investigation
                frappe.log_error(
                    f"Cannot generate invoice: {reason}", f"Membership Dues Schedule {self.name}"
                )
            return None

        if self.test_mode:
            # In test mode, just log and update dates - but only if we can actually generate
            frappe.logger().info(
                f"TEST MODE: Would generate invoice for {self.member} - Dues Rate: {self.dues_rate}"
            )
            self.update_schedule_dates()  # Test mode uses fallback behavior
            return "TEST_INVOICE"

        # ✅ CONCURRENCY PROTECTION: Acquire lock for this specific schedule
        lock_acquired = False
        redis = None
        schedule_lock_key = f"verenigingen_invoice_generation_{self.name}"

        # Get configurable timeout
        lock_timeout = (
            frappe.db.get_single_value("Verenigingen Settings", "invoice_generation_timeout") or 300
        )

        try:
            # Attempt Redis connection with graceful fallback
            try:
                redis = RedisWrapper.from_url(frappe.conf.redis_cache)
                # Test Redis connectivity
                redis.ping()
            except Exception as redis_error:
                frappe.log_error(
                    f"Redis unavailable for invoice generation concurrency protection: {str(redis_error)}",
                    "Redis Connectivity Warning",
                )
                # Continue without concurrency protection but log the risk
                frappe.logger().warning(
                    f"Invoice generation for {self.name} proceeding without concurrency protection due to Redis unavailability"
                )

            if redis:
                try:
                    # Attempt to acquire lock
                    lock_acquired = redis.set(schedule_lock_key, "generating", nx=True, ex=lock_timeout)

                    if not lock_acquired:
                        frappe.log_error(
                            f"Schedule {self.name} invoice generation blocked by concurrent process",
                            "Invoice Generation Concurrency",
                        )
                        return None
                except Exception as lock_error:
                    frappe.log_error(
                        f"Failed to acquire Redis lock for {self.name}: {str(lock_error)}. Proceeding without lock.",
                        "Redis Lock Warning",
                    )
                    # Continue without lock rather than failing completely

            # ✅ FIX: Let Frappe handle transactions automatically - avoid micromanaging
            # Set flag to skip strict validation during invoice generation
            frappe.flags.in_invoice_generation = True

            # ✅ ENHANCED: Calculate coverage period using sequential logic
            coverage_start, coverage_end = self.calculate_next_coverage_period()

            # ✅ SERVICE EXTRACTION: Use InvoiceGenerator service for invoice creation
            from verenigingen.services.billing.invoice_generator import InvoiceGenerator

            # Get member document for service
            member_doc = frappe.get_doc("Member", self.member)

            # Generate invoice via service
            generator = InvoiceGenerator(self)
            result = generator.generate_invoice(coverage_start, coverage_end, member_doc)

            # Check service result
            if not result.success:
                frappe.throw(f"Invoice generation failed: {result.error}")

            invoice = result.invoice
            invoice_name = invoice.name

            # ✅ SAFETY CHECK: Ensure we're not trying to edit a cancelled invoice
            if invoice.docstatus == 2:  # 2 = Cancelled
                frappe.throw(
                    f"Cannot edit cancelled invoice {invoice_name}. This may indicate a naming collision or data issue."
                )

            # ✅ VALIDATION: Ensure coverage dates were set during invoice creation
            if not invoice.custom_coverage_start_date or not invoice.custom_coverage_end_date:
                frappe.throw(f"Coverage dates were not set during invoice creation for {invoice.name}")

            # No need to save again - invoice was already created and submitted by create_sales_invoice()

            # ✅ ENHANCED: Create direct link and track coverage (use normal fields instead of db_set)
            self.last_generated_invoice = invoice.name
            self.last_invoice_coverage_start = coverage_start
            self.last_invoice_coverage_end = coverage_end

            # ✅ CRITICAL FIX: Update schedule with actual invoice posting date
            # This also saves the coverage tracking fields above
            self.update_schedule_dates(actual_invoice_date=invoice.posting_date)

            # ✅ DEFENSIVE: Verify coverage tracking was actually saved
            saved_coverage_end = frappe.db.get_value(
                "Membership Dues Schedule", self.name, "last_invoice_coverage_end"
            )
            if saved_coverage_end != coverage_end:
                frappe.log_error(
                    f"Coverage tracking save verification failed for {self.name}. "
                    f"Expected end: {coverage_end}, Got: {saved_coverage_end}",
                    "Coverage Tracking Save Failure",
                )

        except Exception as e:
            # Extract and clean root cause error message
            error_msg = self._deduplicate_error_message(str(e))

            # Log full error details with safe error handling
            full_error_details = (
                f"Schedule: {self.name}\n" f"Error: {error_msg}\n\n" f"Traceback:\n{frappe.get_traceback()}"
            )

            try:
                frappe.log_error(title=f"Invoice Gen Fail - {self.name[:50]}", message=full_error_details)
            except Exception as log_error:
                # If logging fails, use logger as fallback
                try:
                    frappe.logger().error(
                        f"Failed to log invoice generation error for {self.name}: {str(log_error)}\n"
                        f"Original error: {error_msg}"
                    )
                except Exception:
                    # Absolute last resort - print to stderr
                    print(
                        f"CRITICAL: All logging failed for {self.name} - Error: {error_msg}", file=sys.stderr
                    )

            # Create user-friendly shortened message for display
            user_error_msg = f"Invoice gen failed for {self.name}: {error_msg[:MAX_USER_ERROR_LENGTH]}"

            # Re-raise exception to maintain existing error handling behavior
            raise frappe.ValidationError(user_error_msg)
        finally:
            # Always clear the flag
            frappe.flags.in_invoice_generation = False

            # Release schedule-specific lock if we acquired it
            if lock_acquired and redis:
                try:
                    redis.delete(schedule_lock_key)
                except Exception as e:
                    frappe.log_error(
                        f"Error releasing schedule lock for {self.name}: {str(e)}", "Schedule Lock Cleanup"
                    )

        frappe.logger().info(
            f"Generated invoice {invoice.name} for {self.member} covering period {coverage_start} to {coverage_end}"
        )

        return invoice

    def _handle_invoice_generation_failure(self, error_message):
        """
        Handle invoice generation failures with smart recovery logic.
        DELEGATES to: InvoiceErrorHandlerService.handle_invoice_generation_failure()
        """
        from verenigingen.services.billing.invoice_error_handler_service import InvoiceErrorHandlerService

        return InvoiceErrorHandlerService.handle_invoice_generation_failure(self, error_message)

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
        from verenigingen.services.billing.invoice_error_handler_service import InvoiceErrorHandlerService

        return InvoiceErrorHandlerService.should_auto_advance_schedule(self, error_message)

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
                    from vereiningen.utils.dues_schedule_health_manager import DuesScheduleHealthManager

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
            # Income account from Verenigingen Settings - use the proper P&L income account
            if settings.dues_income_account:
                item.income_account = settings.dues_income_account

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

    def get_invoice_description(self):
        """Generate invoice description with appropriate period formatting"""
        period_start = self.last_invoice_date or self.next_invoice_date
        period_end = self.calculate_next_invoice_date(self.next_invoice_date)

        # Format period description based on billing frequency
        if self.billing_frequency == "Daily":
            # For daily billing, show the specific date
            return f"Membership dues for {self.member_name} ({self.membership_type}) - Daily fee for {period_start}"
        elif self.billing_frequency in ["Monthly", "Quarterly", "Semi-Annual", "Annual"]:
            # For longer periods, show the range
            return f"Membership dues for {self.member_name} ({self.membership_type}) - {self.billing_frequency} period: {period_start} to {period_end}"
        else:
            # For custom or other frequencies, show the generic range
            return f"Membership dues for {self.member_name} ({self.membership_type}) - Period: {period_start} to {period_end}"

    def update_schedule_dates(self, actual_invoice_date=None):
        """
        Update schedule dates after invoice generation.

        CRITICAL FIX: For daily/sequential billing, base next_invoice_date on coverage end
        rather than posting date to prevent date drift when generating ahead of time.
        """
        if actual_invoice_date:
            # Use the actual posting date from the created invoice
            self.last_invoice_date = actual_invoice_date

            # For daily billing or when we have coverage tracking, calculate next date from coverage end
            # This prevents date drift when generating invoices ahead of the posting date
            if self.billing_frequency == "Daily" and self.last_invoice_coverage_end:
                # For daily: next invoice should be day after coverage ends
                self.next_invoice_date = self.calculate_next_invoice_date(self.last_invoice_coverage_end)
            else:
                # For other frequencies: use posting date as before
                self.next_invoice_date = self.calculate_next_invoice_date(actual_invoice_date)
        else:
            # Fallback to old behavior (for test mode)
            self.last_invoice_date = self.next_invoice_date
            self.next_invoice_date = self.calculate_next_invoice_date(self.next_invoice_date)

        self.save()

        # Also update the Member's next_invoice_date field
        if self.member:
            # Check member status before updating (don't update terminated members)
            member_status = frappe.db.get_value("Member", self.member, "status")

            if member_status not in ["Deceased", "Banned", "Terminated"]:
                # Use db.set_value to avoid triggering Member's validate/on_update hooks
                # This prevents cascading saves that can cause race conditions
                frappe.db.set_value(
                    "Member", self.member, "next_invoice_date", self.next_invoice_date, update_modified=False
                )

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
        """Pause the dues schedule"""
        self.status = "Paused"
        if reason:
            self.notes = (
                f"{self.notes}\n\nPaused on {today()}: {reason}"
                if self.notes
                else f"Paused on {today()}: {reason}"
            )
        # Skip membership validation when pausing (allows cancellation workflow)
        self._skip_membership_validation = True
        self.save()

    def resume_schedule(self, new_next_date=None):
        """Resume the dues schedule"""
        self.status = "Active"
        if new_next_date:
            self.next_invoice_date = new_next_date
        self.notes = f"{self.notes}\n\nResumed on {today()}" if self.notes else f"Resumed on {today()}"
        self.save()

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
        """Handle new schedule creation"""
        if not self.is_template and self.member:
            self._record_schedule_fee_change("New Schedule", 0, self.dues_rate)
            # Update member's dues_rate field
            self.update_member_dues_rate()
            # Update member's current_dues_schedule if this should be the current one
            from .membership_dues_schedule_hooks import update_member_current_dues_schedule

            update_member_current_dues_schedule(self)

    def on_update(self):
        """Track billing history changes when schedule is updated"""
        if self.is_template or not self.member:
            return

        # Only proceed if we have the old document for comparison
        if not hasattr(self, "_doc_before_save") or self._doc_before_save is None:
            return

        old_doc = self._doc_before_save

        # Check for dues rate change
        if old_doc.dues_rate != self.dues_rate:
            self._record_schedule_fee_change("Fee Adjustment", old_doc.dues_rate, self.dues_rate)
            # Update member's dues_rate field
            self.update_member_dues_rate()

        # Check for status change
        if old_doc.status != self.status:
            if self.status == "Cancelled":
                self._record_schedule_fee_change("Schedule Cancelled", self.dues_rate, self.dues_rate)
            elif old_doc.status == "Paused" and self.status == "Active":
                self._record_schedule_fee_change("Schedule Resumed", self.dues_rate, self.dues_rate)

            # Update member's current_dues_schedule when status changes
            from .membership_dues_schedule_hooks import update_member_current_dues_schedule

            update_member_current_dues_schedule(self)

        # Check for billing frequency change
        if old_doc.billing_frequency != self.billing_frequency:
            self._record_schedule_fee_change("Billing Frequency Change", self.dues_rate, self.dues_rate)

    def update_member_dues_rate(self):
        """Update the member's dues_rate field to match the schedule"""
        try:
            member_doc = frappe.get_doc("Member", self.member)
            if member_doc.dues_rate != self.dues_rate:
                member_doc.dues_rate = self.dues_rate
                # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                from verenigingen.utils.secure_operations import secure_document_operation

                member_rate_result = secure_document_operation(
                    operation="save",
                    doc=member_doc,
                    justification=f"Update member dues rate from schedule {self.name}",
                    required_permissions=["Member:write"],
                )

                if not member_rate_result.success:
                    frappe.logger().error(
                        f"Failed to update member dues rate: {'; '.join(member_rate_result.errors)}"
                    )
                    # Don't fail the main operation for member update failure
        except Exception as e:
            frappe.log_error(f"Error updating member dues rate: {str(e)}", "Member Dues Rate Update")

    def _record_schedule_fee_change(self, change_type, old_rate, new_rate):
        """Record fee change using the centralized record_fee_change method with deduplication"""
        try:
            member_doc = frappe.get_doc("Member", self.member)

            # Determine reason based on context
            reason = (
                self.custom_amount_reason
                if self.uses_custom_amount
                else f"{change_type} - {self.schedule_name or self.name}"
            )

            # Check if this change is from an amendment
            amendment_request = None
            if frappe.db.exists("Contribution Amendment Request", {"new_dues_schedule": self.name}):
                amendment_request = frappe.db.get_value(
                    "Contribution Amendment Request", {"new_dues_schedule": self.name}, "name"
                )

            # Build change data in the format expected by record_fee_change
            change_data = {
                "change_date": frappe.utils.now_datetime(),
                "old_amount": old_rate or 0,
                "new_amount": new_rate,
                "reason": reason,
                "changed_by": frappe.session.user or "Administrator",
                "dues_schedule_name": self.name,
                "dues_schedule_action": change_type.lower().replace(" ", "_"),
                "billing_frequency": self.billing_frequency,
                "change_type": change_type,
            }

            # Add amendment reference if available
            if amendment_request:
                change_data["amendment_request_name"] = amendment_request

            # Use the centralized method with automatic deduplication
            member_doc.record_fee_change(change_data)

        except Exception as e:
            # Shorten error message to avoid database field length limits
            error_msg = f"Fee change recording error for {self.name}: {str(e)[:80]}"
            frappe.log_error(error_msg, "Fee Change Recording")

    # ✅ ERPNext-Inspired Validation Enhancements

    def validate_status_transitions(self):
        """
        Validate allowed status transitions (inspired by ERPNext subscription patterns)
        Prevents invalid status changes that could break business logic
        """
        if self.is_new() or not hasattr(self, "_doc_before_save"):
            return

        old_status = self._doc_before_save.status
        new_status = self.status

        if old_status == new_status:
            return

        # Define allowed transitions based on business rules
        allowed_transitions = {
            "Active": ["Paused", "Cancelled"],
            "Paused": ["Active", "Cancelled"],
            "Cancelled": [],  # No transitions from cancelled
            "Test": ["Active", "Cancelled"],
        }

        if new_status not in allowed_transitions.get(old_status, []):
            from verenigingen.utils.exceptions import InvalidStatusTransitionError

            raise InvalidStatusTransitionError(
                f"Cannot transition dues schedule status from {old_status} to {new_status}. "
                f"Allowed transitions from {old_status}: {', '.join(allowed_transitions.get(old_status, []))}"
            )

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
            DuesScheduleValidationService,
        )

        DuesScheduleValidationService.validate_rate_boundaries(self)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def calculate_cutoff_date_for_period():
    """
    Calculate the cutoff date for invoice generation based on Verenigingen Settings

    Returns:
        date: The cutoff date through which invoices should provide coverage
    """
    settings = frappe.get_single("Verenigingen Settings")
    cutoff_frequency = getattr(settings, "billing_cutoff_frequency", "Monthly")

    today_date = getdate(today())

    if cutoff_frequency == "Monthly":
        # End of current month
        if today_date.month == 12:
            next_month = today_date.replace(year=today_date.year + 1, month=1, day=1)
        else:
            next_month = today_date.replace(month=today_date.month + 1, day=1)
        return add_days(next_month, -1)

    elif cutoff_frequency == "Quarterly":
        # End of current quarter based on book year
        book_year_start_month = getattr(settings, "book_year_start_month", 1)

        # Calculate which quarter we're in based on book year
        months_since_book_start = (today_date.month - book_year_start_month) % 12
        current_quarter = (months_since_book_start // 3) + 1

        # Calculate end of current quarter
        quarter_end_month = ((current_quarter * 3 - 1) + book_year_start_month - 1) % 12 + 1

        # If quarter end month is greater than current month, quarter ends later this year
        # If quarter end month is less than/equal to current month, we're past that quarter end
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

    elif cutoff_frequency == "Yearly":
        # End of current book year
        book_year_end_month = getattr(settings, "book_year_end_month", 12)
        book_year_end_day = getattr(settings, "book_year_end_day", 31)

        # Determine which book year we're in
        book_year_start_month = getattr(settings, "book_year_start_month", 1)

        if today_date.month >= book_year_start_month:
            book_year = today_date.year
        else:
            book_year = today_date.year - 1

        # Calculate book year end date
        if book_year_end_month == book_year_start_month - 1 or (
            book_year_start_month == 1 and book_year_end_month == 12
        ):
            end_year = book_year + 1
        else:
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

    # Fallback to end of current month
    if today_date.month == 12:
        next_month = today_date.replace(year=today_date.year + 1, month=1, day=1)
    else:
        next_month = today_date.replace(month=today_date.month + 1, day=1)
    return add_days(next_month, -1)


def get_eligible_schedules_for_period(cutoff_date=None, test_mode=False, include_details=False):
    """
    Unified eligibility logic for identifying schedules that need invoice generation.

    This function centralizes all business rules for determining which schedules should
    generate invoices, ensuring consistency between preview (check_member_status) and
    execution (generate_dues_invoices).

    Args:
        cutoff_date: Target date that invoices should cover through (defaults to calculated cutoff)
        test_mode: Whether to filter for test mode schedules only
        include_details: Whether to return detailed filtering information

    Returns:
        If include_details=False: List of eligible schedule names
        If include_details=True: Dict with:
            - eligible_schedules: List of eligible schedule names
            - filtered_members: Dict categorizing filtered members with reasons
            - total_filtered: Count of filtered schedules
            - summary: High-level statistics
    """
    # Calculate cutoff date if not provided
    if not cutoff_date:
        cutoff_date = calculate_cutoff_date_for_period()

    # Initialize tracking structures
    eligible_schedules = []
    filtered_members = {
        "ineligible_status": [],  # Terminated/Expelled/Deceased/Quit
        "test_mode_mismatch": [],  # Test mode doesn't match request
        "gap_reset": [],  # Large coverage gaps (>30 days)
        "business_logic": [],  # Coverage overlap, rate validation, etc.
        "no_customer": [],  # Missing customer record
        "duplicate_coverage": [],  # Overlapping coverage periods
        "too_early": [],  # Before invoice_days_before threshold
        "already_covered": [],  # Already has coverage through cutoff
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

    # First pass: Filter by member status (ineligible members)
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

    # Second pass: Test mode filtering
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

    # Third pass: Business logic validation for each schedule
    for schedule_data in test_mode_eligible:
        try:
            schedule = frappe.get_doc("Membership Dues Schedule", schedule_data.name)
            member_name = f"{schedule_data.first_name} {schedule_data.last_name}"

            # Check if schedule needs invoice for cutoff period
            if not schedule.should_generate_for_cutoff_period(cutoff_date):
                # This member already has coverage through cutoff
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

            # Handle both old tuple format and new dict format
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
                # Categorize the rejection reason
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
            # Handle unexpected errors gracefully
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

    # Calculate summary statistics
    total_filtered = sum(len(filtered_members[cat]) for cat in filtered_members)

    if include_details:
        return {
            "eligible_schedules": eligible_schedules,
            "filtered_members": filtered_members,
            "total_filtered": total_filtered,
            "summary": {
                "total_schedules_checked": len(all_schedules),
                "eligible_count": len(eligible_schedules),
                "filtered_count": total_filtered,
                "filter_breakdown": {
                    category: len(members) for category, members in filtered_members.items()
                },
            },
        }
    else:
        return eligible_schedules


def generate_dues_invoices(test_mode=False):
    """
    Enhanced scheduled job to generate membership dues invoices with coverage-aware logic.

    New features:
    - Coverage-aware selection: Schedules that need invoices to cover through cutoff period
    - Sequential coverage: Gap-free billing periods based on previous invoice coverage
    - Coverage gap detection: Identifies members who remain behind after remedial invoicing
    - Configurable cutoff periods: Monthly/Quarterly/Yearly based on organization settings
    - Concurrency protection: Prevents multiple simultaneous generation runs
    """
    import time

    from frappe.utils.redis_wrapper import RedisWrapper

    # Redis-based concurrency protection with graceful fallback
    redis = None
    lock_key = "verenigingen_bulk_invoice_generation"
    lock_acquired = False

    # Get configurable timeout
    lock_timeout = frappe.db.get_single_value("Verenigingen Settings", "bulk_generation_timeout") or 3600

    try:
        # Attempt Redis connection with graceful fallback
        try:
            redis = RedisWrapper.from_url(frappe.conf.redis_cache)
            # Test Redis connectivity
            redis.ping()
        except Exception as redis_error:
            frappe.log_error(
                f"Redis unavailable for bulk generation concurrency protection: {str(redis_error)}",
                "Redis Connectivity Warning",
            )
            # Continue without concurrency protection but log the risk
            frappe.logger().warning(
                "Bulk invoice generation proceeding without concurrency protection due to Redis unavailability"
            )

        if redis:
            try:
                # Attempt to acquire lock with timeout
                lock_acquired = redis.set(lock_key, "processing", nx=True, ex=lock_timeout)

                if not lock_acquired:
                    # Check if existing lock is stale
                    existing_lock_time = redis.get(f"{lock_key}_start_time")
                    if existing_lock_time:
                        try:
                            start_time = float(existing_lock_time)
                            if time.time() - start_time > lock_timeout:
                                # Force release stale lock
                                redis.delete(lock_key)
                                redis.delete(f"{lock_key}_start_time")
                                lock_acquired = redis.set(lock_key, "processing", nx=True, ex=lock_timeout)
                        except (ValueError, TypeError):
                            pass

                    if not lock_acquired:
                        frappe.log_error(
                            "Bulk invoice generation already in progress. Skipping this run to prevent conflicts.",
                            "Bulk Invoice Generation Concurrency",
                        )
                        return {
                            "processed": 0,
                            "generated": 0,
                            "errors": ["Another invoice generation process is already running"],
                            "invoices": [],
                            "payment_history_updates": 0,
                        }

                # Record start time for stale lock detection
                redis.set(f"{lock_key}_start_time", str(time.time()), ex=lock_timeout)
            except Exception as lock_error:
                frappe.log_error(
                    f"Failed to acquire Redis lock for bulk generation: {str(lock_error)}. Proceeding without lock.",
                    "Redis Lock Warning",
                )
                # Continue without lock rather than failing completely

        # ✅ CRITICAL: Validate accounting configuration before generating invoices
        # Check that the default company has required accounting fields configured
        from verenigingen.utils.settings_utils import get_default_company

        company = get_default_company()
        if not company:
            frappe.throw("No default company configured in Verenigingen Settings")

        missing_configs = []
        company_doc = frappe.get_cached_doc("Company", company)

        # Check critical accounting fields
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
                + "\n\nPlease configure these fields in Company settings before running bulk invoice generation.\n"
                + "This prevents creation of invoices without GL/Payment Ledger entries."
            )
            frappe.log_error(error_msg, "Bulk Invoice Generation - Accounting Config Missing")
            frappe.throw(error_msg, title="Accounting Configuration Required")

        # Set bulk processing flag to prevent duplicate event handling
        frappe.flags.bulk_invoice_generation = True

        # Calculate cutoff date for this generation run
        cutoff_date = calculate_cutoff_date_for_period()

        # Use unified eligibility logic to get eligible schedules and filtering details
        eligibility_result = get_eligible_schedules_for_period(
            cutoff_date=cutoff_date, test_mode=test_mode, include_details=True
        )

        schedules = eligibility_result["eligible_schedules"]

        # Initialize results dictionary with comprehensive filtering information
        results = {
            "processed": 0,
            "generated": 0,
            "errors": [],
            "invoices": [],
            "payment_history_updates": 0,
            "filtered_members": eligibility_result["filtered_members"],
            "total_filtered": eligibility_result["total_filtered"],
            "cutoff_date": cutoff_date,  # Include for downstream transparency
        }

        # Log filtering summary for transparency
        frappe.logger().info(
            f"Dues invoice generation: Checked {eligibility_result['summary']['total_schedules_checked']} schedules, "
            f"found {len(schedules)} eligible, filtered {eligibility_result['total_filtered']} "
            f"(breakdown: {eligibility_result['summary']['filter_breakdown']})"
        )

        # Track which members need payment history updates
        members_to_update = set()
        successful_invoices = []

        # ✅ PARALLEL PROCESSING: Split work into chunks for concurrent execution
        # Determine optimal chunk size based on total schedules
        total_schedules = len(schedules)

        # Use parallel processing for large batches (>50 schedules)
        use_parallel = total_schedules > 50 and not test_mode

        if use_parallel:
            # Calculate chunk size: aim for 4-8 concurrent workers
            # Each chunk should have 50-100 schedules for efficiency
            num_workers = min(8, max(4, total_schedules // 100))
            chunk_size = (total_schedules + num_workers - 1) // num_workers  # Ceiling division

            frappe.logger().info(
                f"Using parallel processing: {total_schedules} schedules split into {num_workers} chunks "
                f"of ~{chunk_size} schedules each"
            )

            # Split schedules into chunks
            chunks = []
            for i in range(0, total_schedules, chunk_size):
                chunks.append(schedules[i : i + chunk_size])

            # Enqueue background jobs for each chunk
            job_ids = []
            for idx, chunk in enumerate(chunks, 1):
                job = frappe.enqueue(
                    "verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule._process_invoice_chunk",
                    queue="long",
                    timeout=1800,  # 30 minutes per chunk
                    now=False,  # Queue for background processing
                    schedule_names=chunk,
                    chunk_id=idx,
                    total_chunks=len(chunks),
                    cutoff_date=cutoff_date,
                    test_mode=test_mode,
                )
                job_ids.append(job)

            frappe.logger().info(f"Queued {len(chunks)} background jobs for parallel invoice generation")

            # Return early with job tracking info
            return {
                "processed": 0,
                "generated": 0,
                "errors": [],
                "invoices": [],
                "payment_history_updates": 0,
                "parallel_mode": True,
                "job_count": len(job_ids),
                "total_schedules": total_schedules,
                "message": f"Processing {total_schedules} invoices in {len(chunks)} parallel jobs. Check background jobs for progress.",
            }

        # SEQUENTIAL PROCESSING (for small batches or test mode)
        frappe.logger().info(f"Using sequential processing for {total_schedules} schedules")

        for idx, schedule_name in enumerate(schedules, 1):
            try:
                schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

                # Schedules returned by get_eligible_schedules_for_period() are already validated
                # No need for redundant can_generate checks
                results["processed"] += 1

                # ✅ ENHANCED: Try invoice generation with comprehensive error recovery
                try:
                    invoice = schedule.generate_invoice()
                    if invoice:
                        results["generated"] += 1
                        invoice_data = {
                            "schedule": schedule_name,
                            "member": schedule.member_name,
                            "member_id": schedule.member,
                            "invoice": invoice,
                        }
                        results["invoices"].append(invoice_data)
                        successful_invoices.append(invoice_data)

                        # Track member for payment history update
                        if schedule.member:
                            members_to_update.add(schedule.member)

                        # ✅ NEW: Clear any retry tracking on success
                        schedule._clear_retry_tracking()
                    else:
                        # Invoice generation returned None - log for investigation
                        error_msg = f"Schedule {schedule_name} returned None from generate_invoice()"
                        frappe.log_error(error_msg, "Invoice Generation Failed")
                        results["errors"].append(error_msg)

                except frappe.ValidationError as ve:
                    # ✅ NEW: Handle validation errors with smart recovery
                    recovery_result = schedule._handle_invoice_generation_failure(str(ve))

                    if recovery_result["action_taken"] == "date_advanced":
                        # Schedule was advanced to prevent infinite loops
                        error_msg = (
                            f"Schedule {schedule_name} validation failed, dates advanced: {str(ve)[:100]}. "
                            f"Retry count: {recovery_result['retry_count']}"
                        )
                        frappe.log_error(error_msg, "Schedule Auto-Advanced Due to Validation Failure")
                        results["errors"].append(f"ADVANCED: {error_msg}")

                    elif recovery_result["action_taken"] == "retry_tracked":
                        # Failure logged, will retry next time
                        error_msg = (
                            f"Schedule {schedule_name} validation failed (retry {recovery_result['retry_count']}/3): "
                            f"{str(ve)[:100]}"
                        )
                        frappe.log_error(error_msg, "Invoice Generation Validation Error")
                        results["errors"].append(f"RETRY {recovery_result['retry_count']}: {error_msg}")

                    elif recovery_result["action_taken"] == "skipped":
                        # Schedule flagged for manual review
                        error_msg = (
                            f"Schedule {schedule_name} flagged for manual review after {recovery_result['retry_count']} failures: "
                            f"{str(ve)[:100]}"
                        )
                        frappe.log_error(error_msg, "Schedule Requires Manual Review")
                        results["errors"].append(f"MANUAL REVIEW: {error_msg}")

                except Exception as ge:
                    # ✅ ENHANCED: Handle unexpected errors with recovery tracking
                    recovery_result = schedule._handle_invoice_generation_failure(str(ge))
                    error_msg = (
                        f"Schedule {schedule_name} unexpected error (retry {recovery_result['retry_count']}/3): "
                        f"{str(ge)[:100]}"
                    )
                    frappe.log_error(error_msg, "Invoice Generation Unexpected Error")
                    results["errors"].append(f"ERROR: {error_msg}")

            except Exception as e:
                # Clean error message to prevent HTML formatting cascade and shorten to avoid database limits
                clean_error = str(e)
                # Remove HTML tags and Error Log references to prevent cascade logging
                clean_error = re.sub(r"<[^<]+?>", "", clean_error)  # Remove HTML tags
                clean_error = re.sub(
                    r"Error Log [a-zA-Z0-9]+:", "", clean_error
                )  # Remove Error Log references
                clean_error = clean_error.strip()[:80]  # Clean whitespace and limit length

                error_msg = f"Error processing {schedule_name}: {clean_error}"
                try:
                    frappe.log_error(error_msg, "Membership Dues Generation")
                except Exception as log_error:
                    # If logging fails, attempt to log the logging failure
                    # Use print as absolute fallback to avoid infinite loops
                    print(f"Critical: Failed to log membership dues generation error: {str(log_error)}")
                    print(f"Original error was: {error_msg}")
                results["errors"].append(error_msg)

        # Commit all sequential changes at end
        frappe.db.commit()
        frappe.logger().info(f"Sequential processing complete: {len(schedules)} schedules processed")

        # HYBRID ARCHITECTURE: Bulk update payment history for all affected members
        if members_to_update:
            try:
                results["payment_history_updates"] = _bulk_update_payment_history(
                    members_to_update, successful_invoices
                )
                frappe.logger().info(
                    f"Bulk payment history update completed for {len(members_to_update)} members"
                )
            except Exception as e:
                error_msg = f"Error in bulk payment history update: {str(e)[:100]}"
                frappe.log_error(error_msg, "Bulk Payment History Update Error")
                results["errors"].append(error_msg)

        # Log results
        frappe.logger().info(
            f"Membership dues generation completed: {results['generated']} invoices from {results['processed']} schedules, "
            f"{results['payment_history_updates']} payment history updates"
        )

        # Generate aggregated blocked member report
        _log_blocked_members_summary()

        # ✅ NEW: Coverage gap detection - identify members still behind after generation
        coverage_gaps = []
        for invoice_data in successful_invoices:
            try:
                invoice = frappe.get_doc("Sales Invoice", invoice_data["invoice"])
                if hasattr(invoice, "custom_coverage_end_date") and invoice.custom_coverage_end_date:
                    if invoice.custom_coverage_end_date < cutoff_date:
                        # Get member name from schedule
                        schedule = frappe.get_doc(
                            "Membership Dues Schedule", invoice.membership_dues_schedule_display
                        )
                        gap_days = (cutoff_date - invoice.custom_coverage_end_date).days

                        coverage_gaps.append(
                            {
                                "member": schedule.member,
                                "schedule": schedule.name,
                                "invoice": invoice.name,
                                "coverage_end": invoice.custom_coverage_end_date,
                                "cutoff_date": cutoff_date,
                                "gap_days": gap_days,
                            }
                        )
            except Exception as e:
                frappe.log_error(
                    f"Error checking coverage gap for invoice {getattr(invoice, 'name', 'Unknown')}: {str(e)}",
                    "Coverage Gap Detection",
                )

        # Log coverage gaps if any found
        if coverage_gaps:
            gap_count = len(coverage_gaps)
            max_gap_days = max(gap["gap_days"] for gap in coverage_gaps)

            frappe.log_error(
                f"Coverage Gap Alert: {gap_count} members still have coverage gaps after invoice generation.\n"
                f"Cutoff date: {cutoff_date}\n"
                f"Maximum gap: {max_gap_days} days\n"
                f"Members with gaps: {', '.join([gap['member'] for gap in coverage_gaps[:10]])}"
                + ("..." if gap_count > 10 else ""),
                "Coverage Gaps After Bulk Generation",
            )

            # Add coverage gap info to results
            results["coverage_gaps"] = coverage_gaps
            results["coverage_gap_count"] = gap_count
        else:
            results["coverage_gaps"] = []
            results["coverage_gap_count"] = 0

        # ✅ DEBUG: Add rejection reasons to results
        if hasattr(frappe.local, "generation_rejections"):
            results["rejection_reasons"] = frappe.local.generation_rejections
        else:
            results["rejection_reasons"] = {}

        return results

    finally:
        # Always clear the bulk processing flag
        if getattr(frappe.flags, "bulk_invoice_generation", None):
            delattr(frappe.flags, "bulk_invoice_generation")

        # Release Redis lock if we acquired it
        if lock_acquired and redis:
            try:
                redis.delete(lock_key)
                redis.delete(f"{lock_key}_start_time")
            except Exception as e:
                frappe.log_error(
                    f"Error releasing bulk invoice generation lock: {str(e)}",
                    "Bulk Invoice Generation Lock Cleanup",
                )


@frappe.whitelist()
def get_parallel_invoice_generation_status():
    """
    Check the status of parallel invoice generation background jobs.

    Returns:
        dict: Status information about queued and running jobs
    """
    from frappe.utils.background_jobs import get_jobs

    # Get all jobs in the long queue
    jobs = get_jobs(site=frappe.local.site, queue="long")

    invoice_jobs = []
    for job_id, job_info in jobs.items():
        if "_process_invoice_chunk" in str(job_info.get("method", "")):
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


def _process_invoice_chunk(schedule_names, chunk_id, total_chunks, cutoff_date, test_mode=False):
    """
    Worker function to process a chunk of invoices in parallel.

    Args:
        schedule_names: List of schedule names to process in this chunk
        chunk_id: Identifier for this chunk (for logging)
        total_chunks: Total number of chunks being processed
        cutoff_date: Cutoff date for invoice generation
        test_mode: Whether to run in test mode

    Returns:
        dict: Results containing generated invoices, errors, and members to update
    """
    frappe.set_user("Administrator")

    results = {
        "chunk_id": chunk_id,
        "processed": 0,
        "generated": 0,
        "errors": [],
        "invoices": [],
        "members_to_update": set(),
    }

    frappe.logger().info(f"Chunk {chunk_id}/{total_chunks}: Processing {len(schedule_names)} schedules")

    # Process each schedule in this chunk
    for schedule_name in schedule_names:
        try:
            schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
            results["processed"] += 1

            try:
                invoice = schedule.generate_invoice()
                if invoice:
                    results["generated"] += 1
                    invoice_data = {
                        "schedule": schedule_name,
                        "member": schedule.member_name,
                        "member_id": schedule.member,
                        "invoice": invoice,
                    }
                    results["invoices"].append(invoice_data)

                    if schedule.member:
                        results["members_to_update"].add(schedule.member)

                    schedule._clear_retry_tracking()
                else:
                    error_msg = f"Schedule {schedule_name} returned None from generate_invoice()"
                    frappe.log_error(title=f"Chunk {chunk_id} Invoice Gen Failed", message=error_msg)
                    results["errors"].append(error_msg)

            except frappe.ValidationError as ve:
                recovery_result = schedule._handle_invoice_generation_failure(str(ve))
                error_msg = (
                    f"Schedule {schedule_name} validation failed (retry {recovery_result['retry_count']}/3): "
                    f"{str(ve)[:MAX_LOG_ERROR_LENGTH]}"
                )
                try:
                    frappe.log_error(
                        title=f"Chunk {chunk_id} Validation",
                        message=f"Schedule: {schedule_name}\nRetry: {recovery_result['retry_count']}/3\n\n{str(ve)}\n\n{frappe.get_traceback()}",
                    )
                except Exception:
                    try:
                        frappe.logger().error(f"Validation error for {schedule_name}: {str(ve)}")
                    except Exception:
                        print(
                            f"CRITICAL: Failed to log validation error for {schedule_name}", file=sys.stderr
                        )
                results["errors"].append(error_msg)

            except Exception as e:
                error_msg = f"Unexpected error for {schedule_name}: {str(e)[:MAX_LOG_ERROR_LENGTH]}"
                try:
                    frappe.log_error(
                        title=f"Chunk {chunk_id} Error",
                        message=f"Schedule: {schedule_name}\n\n{str(e)}\n\n{frappe.get_traceback()}",
                    )
                except Exception:
                    try:
                        frappe.logger().error(f"Unexpected error for {schedule_name}: {str(e)}")
                    except Exception:
                        print(f"CRITICAL: Failed to log error for {schedule_name}", file=sys.stderr)
                results["errors"].append(error_msg)

        except Exception as outer_e:
            error_msg = f"Error loading schedule {schedule_name}: {str(outer_e)[:MAX_LOG_ERROR_LENGTH]}"
            # Safe error logging that prevents cascading failures
            try:
                frappe.log_error(
                    title=f"Chunk {chunk_id} Load Error",
                    message=f"Schedule: {schedule_name}\nError: {str(outer_e)}\n\n{frappe.get_traceback()}",
                )
            except Exception as log_error:
                # If error logging fails, use logger instead
                try:
                    frappe.logger().error(
                        f"Failed to log error for {schedule_name}: {str(log_error)}\n"
                        f"Original error: {str(outer_e)}"
                    )
                except Exception:
                    # Absolute last resort - print to stderr
                    print(
                        f"CRITICAL: All logging failed for chunk {chunk_id}, schedule {schedule_name}",
                        file=sys.stderr,
                    )
            results["errors"].append(error_msg)

    # Commit this chunk's work
    frappe.db.commit()

    frappe.logger().info(
        f"Chunk {chunk_id}/{total_chunks} complete: {results['generated']}/{results['processed']} invoices generated"
    )

    return results


def _bulk_update_payment_history(member_names, successful_invoices):
    """
    Efficiently update payment history for multiple members after bulk invoice generation.

    Args:
        member_names: Set of member names that need payment history updates
        successful_invoices: List of invoice data dictionaries for tracking

    Returns:
        int: Number of members successfully updated
    """
    updated_count = 0

    for member_name in member_names:
        try:
            # Get member document with error handling
            if not DocumentExistenceValidator.check_document_exists("Member", member_name):
                frappe.log_error(
                    f"Member {member_name} not found during bulk payment history update",
                    "Bulk Payment History Update",
                )
                continue

            # Use atomic add method for each new invoice for this member
            member_invoices = [inv for inv in successful_invoices if inv.get("member_id") == member_name]

            if member_invoices:
                member_doc = frappe.get_doc("Member", member_name)

                # Add each invoice to payment history using direct processing for bulk operations
                for inv_data in member_invoices:
                    try:
                        # FIXED: Use direct manager during bulk processing to avoid queueing conflicts
                        from verenigingen.utils.member_financial_history_manager import (
                            get_payment_history_manager,
                        )

                        manager = get_payment_history_manager(member_doc)

                        def build_invoice_entry():
                            invoice = member_doc._get_invoice_with_retry(inv_data["invoice"])
                            if invoice and invoice.customer == member_doc.customer:
                                return member_doc._build_payment_history_entry(invoice)
                            return None

                        # Direct processing during bulk operations (no 10s delay needed)
                        manager.add_or_update_entry(inv_data["invoice"], build_invoice_entry, "invoice")
                    except Exception as inv_error:
                        frappe.log_error(
                            f"Failed to add invoice {inv_data['invoice']} to payment history for member {member_name}: {str(inv_error)}",
                            "Individual Invoice Payment History Update",
                        )

                updated_count += 1

        except Exception as e:
            frappe.log_error(
                f"Error updating payment history for member {member_name}: {str(e)}",
                "Bulk Payment History Member Update",
            )

    return updated_count


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def create_schedule_from_template(member_name, template_name=None):
    """API endpoint to create schedule from template"""
    return MembershipDuesSchedule.create_from_template(member_name, template_name)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def create_template_for_membership_type(membership_type, template_name=None):
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
    template.contribution_mode = getattr(membership_type_doc, "contribution_mode", "Calculator")
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
def get_member_dues_schedule(member=None):
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
        if not any(
            role in roles for role in ["Verenigingen Staff", "Verenigingen Administrator", "System Manager"]
        ):
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
def update_member_contribution(schedule_name, updates):
    """Update member's contribution settings with permission checks"""
    if isinstance(updates, str):
        updates = frappe.parse_json(updates)

    schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

    # Permission check happens in validate()

    # Only allow updating specific fields
    allowed_updates = {
        "contribution_mode": updates.get("contribution_mode"),
        "selected_tier": updates.get("selected_tier"),
        "base_multiplier": updates.get("base_multiplier"),
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


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_billing_day_field():
    """Test billing_day field implementation"""
    try:
        # Test 1: Create a member with member_since date
        test_member = frappe.new_doc("Member")
        test_member.first_name = "Billing"
        test_member.last_name = "Test"
        test_member.email = f"billing.test.{frappe.generate_hash(length=6)}@example.com"
        test_member.member_since = "2023-03-15"  # 15th of the month
        test_member.save()

        # Test 2: Create a dues schedule for this member
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"Test-Billing-Day-{frappe.generate_hash(length=4)}"
        schedule.is_template = 0
        schedule.member = test_member.name
        schedule.membership_type = "Test Membership"  # Use existing membership type
        schedule.dues_rate = 10.0
        schedule.save()

        # Test 3: Create a member without member_since date
        no_date_member = frappe.new_doc("Member")
        no_date_member.first_name = "NoDate"
        no_date_member.last_name = "Test"
        no_date_member.email = f"nodate.test.{frappe.generate_hash(length=6)}@example.com"
        no_date_member.member_since = None
        no_date_member.save()

        # Test 4: Create a dues schedule for member without date
        no_date_schedule = frappe.new_doc("Membership Dues Schedule")
        no_date_schedule.schedule_name = f"Test-No-Date-{frappe.generate_hash(length=4)}"
        no_date_schedule.is_template = 0
        no_date_schedule.member = no_date_member.name
        no_date_schedule.membership_type = "Test Membership"
        no_date_schedule.dues_rate = 10.0
        no_date_schedule.save()

        results = {
            "test_1_member_with_date": {
                "member_since": test_member.member_since,
                "expected_billing_day": 15,
                "actual_billing_day": schedule.billing_day,
                "correct": schedule.billing_day == 15,
            },
            "test_2_member_without_date": {
                "member_since": no_date_member.member_since,
                "expected_billing_day": 1,
                "actual_billing_day": no_date_schedule.billing_day,
                "correct": no_date_schedule.billing_day == 1,
            },
            "field_exists": hasattr(schedule, "billing_day"),
            "overall_success": schedule.billing_day == 15 and no_date_schedule.billing_day == 1,
        }

        # Cleanup
        schedule.delete()
        no_date_schedule.delete()
        test_member.delete()
        no_date_member.delete()

        return results

    except Exception as e:
        return {"error": str(e), "success": False}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def create_test_schedule(member_name, membership_name=None):
    """Create a test dues schedule for development"""
    try:
        return MembershipDuesSchedule.create_from_template(member_name)
    except Exception:
        # Fallback to manual creation if no template exists
        # Get membership if not provided
        if not membership_name:
            membership_info = get_active_membership_for_member(member_name, ["name"])
            membership_name = membership_info["name"] if membership_info else None

        if not membership_name:
            frappe.throw(f"No membership found for member {member_name}")

        # Create test schedule
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.is_template = 0
        schedule.member = member_name
        schedule.schedule_name = f"Test-Schedule-{member_name}"
        schedule.billing_frequency = "Monthly"
        schedule.dues_rate = 10.00  # Test dues rate
        schedule.next_invoice_date = today()
        schedule.invoice_days_before = 0  # Generate immediately
        schedule.test_mode = 1
        schedule.auto_generate = 1
        schedule.status = "Test"
        schedule.insert()

        return schedule.name


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def debug_template_daglid_issue():
    """Debug Template-Daglid billing frequency override issue"""
    result = {
        "timestamp": frappe.utils.now(),
        "template_status": {},
        "membership_type_status": {},
        "inheritance_tests": {},
        "recent_schedules": [],
    }

    # Check Template-Daglid current state
    try:
        template = frappe.get_doc("Membership Dues Schedule", "Template-Daglid")
        result["template_status"] = {
            "billing_frequency": template.billing_frequency,
            "is_template": template.is_template,
            "modified": str(template.modified),
            "modified_by": template.modified_by,
        }
    except Exception as e:
        result["template_status"]["error"] = str(e)

    # Check Daglid membership type
    try:
        membership_type = frappe.get_doc("Membership Type", "Daglid")
        result["membership_type_status"] = {
            "dues_schedule_template": membership_type.dues_schedule_template,
            "amount": getattr(membership_type, "amount", 0),
        }
    except Exception as e:
        result["membership_type_status"]["error"] = str(e)

    # Test the auto-creator inheritance logic
    try:
        billing_frequency = "Annual"  # Default from auto_creator
        if membership_type.dues_schedule_template:
            template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)
            # Use explicit validation instead of fallback
            if template.billing_frequency:
                billing_frequency = template.billing_frequency
            else:
                billing_frequency = "Annual"
                frappe.log_error(
                    f"Template '{membership_type.dues_schedule_template}' has no billing_frequency configured, using default 'Annual'",
                    "Membership Dues Schedule Template Configuration",
                )

        result["inheritance_tests"]["auto_creator_logic"] = {
            "would_set": billing_frequency,
            "template_value": template.billing_frequency,
            "template_truthy": bool(template.billing_frequency),
        }
    except Exception as e:
        result["inheritance_tests"]["auto_creator_error"] = str(e)

    # Test the get_template_values() method
    try:
        test_schedule = frappe.new_doc("Membership Dues Schedule")
        test_schedule.membership_type = "Daglid"
        template_values = test_schedule.get_template_values()
        result["inheritance_tests"]["get_template_values"] = {
            "billing_frequency": template_values.get("billing_frequency"),
            "all_values": template_values,
        }
    except Exception as e:
        result["inheritance_tests"]["get_template_values_error"] = str(e)

    # Check recent dues schedules
    try:
        recent_schedules = frappe.db.sql(
            """
            SELECT name, billing_frequency, modified, membership_type
            FROM `tabMembership Dues Schedule`
            WHERE membership_type = 'Daglid'
            ORDER BY modified DESC
            LIMIT 5
        """,
            as_dict=True,
        )
        result["recent_schedules"] = recent_schedules
    except Exception as e:
        result["recent_schedules_error"] = str(e)

    return result


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_template_daglid_fix():
    """Test that Template-Daglid billing frequency is preserved during template recreation"""

    # Step 1: Check current Template-Daglid status
    before = frappe.get_doc("Membership Dues Schedule", "Template-Daglid")
    before_frequency = before.billing_frequency
    before_modified = str(before.modified)

    # Step 2: Simulate template recreation (this was the source of the bug)
    daglid_membership_type = frappe.get_doc("Membership Type", "Daglid")
    template_name = daglid_membership_type.create_dues_schedule_template()

    # Step 3: Check Template-Daglid status after recreation
    after = frappe.get_doc("Membership Dues Schedule", "Template-Daglid")
    after_frequency = after.billing_frequency
    after_modified = str(after.modified)

    return {
        "template_name": template_name,
        "before": {"billing_frequency": before_frequency, "modified": before_modified},
        "after": {"billing_frequency": after_frequency, "modified": after_modified},
        "preserved": before_frequency == after_frequency,
        "test_result": "PASS" if before_frequency == after_frequency else "FAIL",
    }


def has_permission(doc, user=None, permission_type="read"):
    """Custom permission handler for Membership Dues Schedule"""
    if not user:
        user = frappe.session.user

    # Debug logging
    frappe.logger().info(
        f"PERMISSION CHECK: User {user}, Doc {doc.name if hasattr(doc, 'name') else 'Unknown'}, Type {permission_type}"
    )

    # System Manager always has access
    if "System Manager" in frappe.get_roles(user):
        frappe.logger().info(f"PERMISSION GRANTED: System Manager access for {user}")
        return True

    # Verenigingen Administrator and Manager have full access
    user_roles = frappe.get_roles(user)
    if any(role in user_roles for role in ["Verenigingen Administrator", "Verenigingen Staff"]):
        frappe.logger().info(f"PERMISSION GRANTED: Admin role access for {user}")
        return True

    # Templates are visible to all authenticated users (for viewing available options)
    if hasattr(doc, "is_template") and doc.is_template:
        frappe.logger().info(f"PERMISSION GRANTED: Template access for {user}")
        return True

    # For non-templates, only allow access if user is the member
    if hasattr(doc, "member") and doc.member:
        # Check if current user is linked to this member
        member_user = frappe.db.get_value("Member", doc.member, "user")
        frappe.logger().info(
            f"PERMISSION CHECK: Doc member {doc.member}, Member user {member_user}, Current user {user}"
        )
        if member_user == user:
            frappe.logger().info(f"PERMISSION GRANTED: User matches member for {user}")
            return True

    # Check if user is chapter board member (any active board position grants access)
    if hasattr(doc, "member") and doc.member and "Verenigingen Chapter Board Member" in user_roles:
        try:
            # Get member's chapters
            member_chapters = frappe.db.get_all(
                "Chapter Member",
                filters={"member": doc.member, "status": "Active"},
                fields=["parent"],
                pluck="parent",
            )

            if member_chapters:
                # Get user's member and volunteer records
                user_member = frappe.db.get_value("Member", {"user": user}, "name")
                if user_member:
                    user_volunteer = frappe.db.get_value("Volunteer", {"member": user_member}, "name")
                    if user_volunteer:
                        # Check if user is board member in any of the member's chapters
                        board_position = frappe.db.exists(
                            "Chapter Board Member",
                            {
                                "parent": ["in", member_chapters],
                                "volunteer": user_volunteer,
                                "is_active": 1,
                            },
                        )

                        if board_position:
                            frappe.logger().info(
                                f"PERMISSION GRANTED: Chapter board member access for {user}"
                            )
                            return True
        except Exception as e:
            frappe.logger().error(f"Error checking chapter board permission: {str(e)}")
            pass  # If any chapter permission check fails, continue to deny access

    frappe.logger().info(
        f"PERMISSION DENIED: No access granted for {user} to doc {doc.name if hasattr(doc, 'name') else 'Unknown'}"
    )
    return False


def get_permission_query_conditions(user=None):
    """Permission query conditions for Membership Dues Schedule list views"""
    if not user:
        user = frappe.session.user

    # Debug logging
    frappe.logger().info(f"QUERY PERMISSION CHECK: User {user}")

    # System Manager and admin roles get full access
    user_roles = frappe.get_roles(user)
    if "System Manager" in user_roles:
        frappe.logger().info(f"QUERY PERMISSION: System Manager full access for {user}")
        return ""  # No restrictions

    if any(role in user_roles for role in ["Verenigingen Administrator", "Verenigingen Staff"]):
        frappe.logger().info(f"QUERY PERMISSION: Admin role full access for {user}")
        return ""  # No restrictions

    # Chapter Board Members can access dues schedules for members in their chapters
    if "Verenigingen Chapter Board Member" in user_roles:
        # Get chapters where user is a board member
        user_member = frappe.db.get_value("Member", {"user": user}, "name")
        if user_member:
            # Get the volunteer record for this member
            volunteer = frappe.db.get_value("Volunteer", {"member": user_member}, "name")
            if volunteer:
                chapters = frappe.db.sql(
                    """
                    SELECT DISTINCT cbm.parent
                    FROM `tabChapter Board Member` cbm
                    WHERE cbm.volunteer = %s AND cbm.is_active = 1
                    """,
                    volunteer,
                    as_dict=False,
                )

                if chapters:
                    chapter_names = [f"'{c[0]}'" for c in chapters]
                    frappe.logger().info(
                        f"QUERY PERMISSION: Chapter Board Member access for chapters {chapter_names}"
                    )
                    # Allow templates OR records for members in their chapters OR their own
                    return f"""(
                        `tabMembership Dues Schedule`.is_template = 1
                        OR `tabMembership Dues Schedule`.member IN (
                            SELECT DISTINCT cm.member
                            FROM `tabChapter Member` cm
                            WHERE cm.parent IN ({','.join(chapter_names)})
                              AND cm.status = 'Active'
                        )
                        OR `tabMembership Dues Schedule`.member = '{user_member}'
                    )"""

    # For regular members, restrict to templates OR their own records
    # Get the user's member record
    user_member = frappe.db.get_value("Member", {"user": user}, "name")

    if user_member:
        frappe.logger().info(f"QUERY PERMISSION: Member {user_member} access for {user}")
        # Allow templates OR records where the member field matches their member record
        return f"(`tabMembership Dues Schedule`.is_template = 1 OR `tabMembership Dues Schedule`.member = '{user_member}')"
    else:
        frappe.logger().info(f"QUERY PERMISSION: Template-only access for {user}")
        # Only allow templates if user is not linked to a member
        return "`tabMembership Dues Schedule`.is_template = 1"


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def validate_and_fix_schedule_dates():
    """
    Validate and fix all dues schedule dates to prevent issues like Assoc-Member-2025-07-0030
    Returns a report of issues found and fixed
    """
    # using add_days, getdate, today from top-level import

    today_date = getdate(today())
    results = {"total_schedules": 0, "issues_found": 0, "fixes_applied": 0, "issues": [], "success": True}

    try:
        # Get all active schedules
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"status": "Active", "is_template": 0},
            fields=[
                "name",
                "member",
                "billing_frequency",
                "next_invoice_date",
                "last_invoice_date",
                "modified",
            ],
        )

        results["total_schedules"] = len(schedules)

        for schedule_data in schedules:
            issues = []
            fixes = []

            try:
                schedule = frappe.get_doc("Membership Dues Schedule", schedule_data.name)

                if schedule.next_invoice_date:
                    next_date = getdate(schedule.next_invoice_date)

                    # Check for unreasonably far future dates
                    if schedule.billing_frequency == "Daily":
                        max_future_days = 7
                    elif schedule.billing_frequency == "Weekly":
                        max_future_days = 14
                    elif schedule.billing_frequency == "Monthly":
                        max_future_days = 62
                    elif schedule.billing_frequency == "Quarterly":
                        max_future_days = 100
                    elif schedule.billing_frequency == "Annual":
                        max_future_days = 400
                    else:
                        max_future_days = 30

                    max_future_date = add_days(today_date, max_future_days)

                    if next_date > max_future_date:
                        issues.append(f"Next invoice date too far in future: {next_date}")
                        schedule.next_invoice_date = today_date
                        fixes.append(f"Corrected next_invoice_date from {next_date} to {today_date}")

                    # Check for very old dates
                    min_past_date = add_days(today_date, -180)  # 6 months ago
                    if next_date < min_past_date:
                        issues.append(f"Next invoice date too far in past: {next_date}")
                        schedule.next_invoice_date = today_date
                        fixes.append(f"Corrected next_invoice_date from {next_date} to {today_date}")

                # If we made fixes, save the schedule
                if fixes:
                    schedule.save()
                    results["fixes_applied"] += 1

                    results["issues"].append(
                        {
                            "schedule": schedule_data.name,
                            "member": schedule_data.member,
                            "billing_frequency": schedule_data.billing_frequency,
                            "issues": issues,
                            "fixes": fixes,
                        }
                    )

            except Exception as e:
                results["issues"].append(
                    {
                        "schedule": schedule_data.name,
                        "member": schedule_data.member,
                        "error": f"Failed to process: {str(e)}",
                    }
                )

        results["issues_found"] = len([i for i in results["issues"] if "fixes" in i])

    except Exception as e:
        results["success"] = False
        results["error"] = str(e)

    return results


def _log_blocked_members_summary():
    """
    Generate aggregated report for members blocked from invoice generation.
    Reduces log spam by consolidating multiple blocked member reports into one.
    """
    if not hasattr(frappe.local, "blocked_members") or not frappe.local.blocked_members:
        return

    # Build summary report
    total_blocked = sum(len(members) for members in frappe.local.blocked_members.values())

    summary_lines = [
        f"Daily Invoice Generation - Blocked Members Summary ({total_blocked} members blocked)",
        "=" * 80,
    ]

    for status, members in frappe.local.blocked_members.items():
        summary_lines.append(f"\n{status.upper()} STATUS: {len(members)} members")
        for member_info in members[:10]:  # Show first 10, truncate if more
            member_name = member_info.get("member_name", member_info["member"])
            summary_lines.append(f"  - {member_info['member']} ({member_name})")

        if len(members) > 10:
            summary_lines.append(f"  ... and {len(members) - 10} more {status} members")

    # Log as single consolidated report
    frappe.log_error("\n".join(summary_lines), "Daily Blocked Members Summary")

    # Clear the aggregated data
    frappe.local.blocked_members = {}
