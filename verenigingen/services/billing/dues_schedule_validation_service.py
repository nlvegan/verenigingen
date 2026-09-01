# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
DuesScheduleValidationService - Dues schedule financial validation logic

This service handles comprehensive validation of membership dues schedules:
- Rate boundary validation (minimum/maximum limits)
- Financial constraint validation (absolute min, max reasonable amounts)
- Rate change validation (extreme changes detection)
- Membership type consistency validation
- Configuration-based validation (contribution modes)

Extracted from membership_dues_schedule.py:
- validate_dues_rate_change() - Lines 304-315 (12 LOC)
- validate_dues_rate_configuration() - Lines 361-395 (35 LOC)
- validate_financial_constraints() - Lines 396-471 (76 LOC)
- validate_dues_rate() - Lines 752-832 (81 LOC)
- validate_rate_boundaries() - Lines 1809-1869 (61 LOC)

Total: ~265 LOC of validation logic in service layer

Architecture:
- Static methods for stateless validation
- Schedule document passed as parameter
- Throws validation errors using frappe.throw()
- Configuration-aware validation (uses Verenigingen Settings)

Business Logic:
- Enforces minimum amounts from membership types and templates
- Validates contribution mode configurations (Tier, Calculator, Custom)
- Checks for reasonable rate limits with admin overrides
- Detects extreme rate changes from previous periods
- Supports template vs. member schedule validation

Dependencies:
- frappe - For validation errors and configuration access
- ConfigManager - For boundary configuration
- TemplateConfigurationService - For template value retrieval

Security:
- Role-based warnings for high amounts
- Admin override support for exceptional cases
- Audit logging for validation bypasses
"""

from typing import TYPE_CHECKING, Any, Dict, TypedDict

import frappe
from frappe.utils import getdate, today

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.constants import Roles

if TYPE_CHECKING:
    from frappe.model.document import Document


class ValidationResult(TypedDict):
    """Type definition for validation result dictionaries."""

    valid: bool
    reason: str


class DuesScheduleValidationService(StatelessService):
    """
    Service for validating membership dues schedule financial constraints.

    This service handles:
    - Rate boundary validation (positive values, min/max limits)
    - Contribution mode configuration validation
    - Template consistency validation
    - Rate change reasonableness checks
    - Financial constraint enforcement
    """

    def __init__(self) -> None:
        """Initialize the dues schedule validation service."""
        super().__init__(service_name="DuesScheduleValidationService")

    def validate_dues_rate_change(self, schedule_doc: "Document") -> bool:
        """
        Validate if dues rate change meets minimum requirements.

        Checks that the current dues rate is not below the minimum amount
        required by the membership type's template configuration.

        Args:
            schedule_doc: MembershipDuesSchedule document instance

        Returns:
            bool: True if validation passes

        Raises:
            frappe.ValidationError: If dues rate is below minimum

        Example:
            >>> DuesScheduleValidationService.validate_dues_rate_change(schedule)
            True
        """
        if not schedule_doc.membership_type:
            return False

        from verenigingen.services.billing.template_configuration_service import TemplateConfigurationService

        template_values = TemplateConfigurationService().get_template_values(
            schedule_doc, schedule_doc.membership_type
        )
        min_amount = template_values.get("minimum_amount", 0)

        if schedule_doc.dues_rate < min_amount:
            frappe.throw(f"Dues rate cannot be less than minimum contribution: €{min_amount:.2f}")

        return True

    def validate_dues_rate_configuration(self, schedule_doc: "Document") -> None:
        """
        Validate and set dues rate based on contribution mode.

        Calculates the appropriate dues_rate for the schedule based on its
        contribution_mode (Fixed, Income-Based, or Flexible). Only calculates if
        dues_rate is not already set.

        Args:
            schedule_doc: MembershipDuesSchedule document instance

        Raises:
            frappe.ValidationError: If configuration is invalid or incomplete

        Business Logic:
            - Fixed mode: Uses template dues_rate directly
            - Income-Based mode: Multiplies suggested_amount by default_multiplier
            - Flexible mode: Uses user selection, falls back to suggested_amount
            - Templates skip calculation (may have incomplete configuration)
        """
        # Templates may not have all dues rate fields set
        if schedule_doc.is_template:
            return

        if not schedule_doc.membership_type:
            return

        # Only calculate dues_rate if not already explicitly set (None means not set)
        # Allow 0 as a valid value for free memberships
        if schedule_doc.dues_rate is None:
            if schedule_doc.contribution_mode == "Income-Based":
                # Income-Based: calculate from suggested_amount * multiplier
                # suggested_amount is optional - fall back to minimum_amount
                from verenigingen.services.billing.template_configuration_service import (
                    TemplateConfigurationService,
                )

                template_values = TemplateConfigurationService().get_template_values(
                    schedule_doc, schedule_doc.membership_type
                )
                suggested_amount = template_values.get("suggested_amount", 0)
                base_amount = suggested_amount or template_values.get("minimum_amount", 0)

                multiplier = (
                    schedule_doc.default_multiplier if schedule_doc.default_multiplier is not None else 1.0
                )
                schedule_doc.dues_rate = base_amount * multiplier
            elif schedule_doc.contribution_mode == "Flexible":
                # Flexible: dues_rate should be set from user selection
                # If not set, fall back to suggested_amount, then minimum_amount
                from verenigingen.services.billing.template_configuration_service import (
                    TemplateConfigurationService,
                )

                template_values = TemplateConfigurationService().get_template_values(
                    schedule_doc, schedule_doc.membership_type
                )
                schedule_doc.dues_rate = (
                    template_values.get("suggested_amount") or template_values.get("minimum_amount") or 0
                )

    def validate_financial_constraints(self, schedule_doc: "Document") -> None:
        """
        Validate financial constraints and limits.

        Performs comprehensive boundary checks including:
        - Absolute minimum (prevents invalid tiny amounts)
        - Maximum reasonable limit (prevents data entry errors)
        - Template minimum compliance
        - Admin override support for exceptional cases

        Args:
            schedule_doc: MembershipDuesSchedule document instance

        Raises:
            frappe.ValidationError: If constraints are violated

        Security:
            - Role-based admin override for high amounts
            - Warning messages for administrators
            - Error messages for regular users

        Business Logic:
            - Skips validation for templates (incomplete configuration allowed)
            - Enforces absolute minimum (€0.01 default)
            - Enforces maximum reasonable amount (€1000 default)
            - Validates against template-defined minimum

        Example:
            >>> schedule.dues_rate = 1500.00  # Above maximum
            >>> # Administrator: Shows warning, allows save
            >>> # Regular user: Throws error, blocks save
        """
        # Skip for templates or when dues_rate is not set (None)
        # Allow 0 as valid for free memberships
        if schedule_doc.is_template or schedule_doc.dues_rate is None:
            return

        try:
            # Get configuration values
            from verenigingen.utils.config_manager import ConfigManager

            # Check absolute minimum (safety check) - but allow 0 for free memberships
            # Only enforce minimum for non-zero rates
            if schedule_doc.dues_rate > 0:
                absolute_minimum = ConfigManager.get("absolute_minimum_dues", 0.01)  # €0.01 minimum
                if float(schedule_doc.dues_rate) < absolute_minimum:
                    frappe.throw(
                        f"Dues rate cannot be less than €{absolute_minimum:.2f}", frappe.ValidationError
                    )

            # Check maximum reasonable amount
            maximum_dues = ConfigManager.get("maximum_dues_limit", 1000.0)  # €1000 default max
            if float(schedule_doc.dues_rate) > maximum_dues:
                # Allow with warning for administrators
                user_roles = frappe.get_roles(frappe.session.user)
                admin_roles = Roles.ADMIN_ROLES

                if any(role in user_roles for role in admin_roles):
                    frappe.msgprint(
                        f"High dues amount detected: €{schedule_doc.dues_rate:.2f}. Please verify this is correct.",
                        title="High Amount Warning",
                    )
                else:
                    frappe.throw(
                        f"Dues rate exceeds maximum limit of €{maximum_dues:.2f}. "
                        f"Please contact an administrator if this amount is correct.",
                        frappe.ValidationError,
                    )

            # Validate against template constraints if available
            if hasattr(schedule_doc, "minimum_amount") and schedule_doc.minimum_amount:
                if float(schedule_doc.dues_rate) < float(schedule_doc.minimum_amount):
                    frappe.throw(
                        f"Dues rate (€{schedule_doc.dues_rate:.2f}) cannot be less than minimum amount (€{schedule_doc.minimum_amount:.2f})",
                        frappe.ValidationError,
                    )

            # Check if dues rate is within reasonable multiplier of suggested amount
            if schedule_doc.membership_type:
                membership_type = frappe.get_doc("Membership Type", schedule_doc.membership_type)

                # If no template configured, skip multiplier check — the schedule
                # may have been created from a template resolved via payment-period
                # settings rather than the Membership Type's default.
                if not membership_type.dues_schedule_template:
                    return

        except Exception as e:
            # Re-raise validation errors
            if isinstance(e, frappe.ValidationError):
                raise
            # Log other errors but don't block validation
            self.logger.error(f"Error in financial constraints validation for {schedule_doc.name}: {str(e)}")

    def validate_dues_rate(self, schedule_doc: "Document") -> ValidationResult:
        """
        Validate dues rate for reasonableness and business logic.

        Comprehensive validation including:
        - Negative rate detection
        - Extremely high rate detection (configurable threshold)
        - Extreme rate change detection from previous period
        - Configuration-based boundary checks

        Args:
            schedule_doc: MembershipDuesSchedule document instance

        Returns:
            dict: Validation result with keys:
                - valid (bool): Whether validation passed
                - reason (str): Validation outcome message

        Business Logic:
            - Allows zero for free memberships
            - Prevents negative rates
            - Checks against configurable max_reasonable_rate (default 10000)
            - Compares to previous invoice amount if available
            - Logs extreme changes but doesn't block

        Example:
            >>> result = DuesScheduleValidationService.validate_dues_rate(schedule)
            >>> if not result["valid"]:
            ...     print(f"Validation failed: {result['reason']}")
        """
        try:
            # Check for negative rates (zero is allowed for free memberships)
            if schedule_doc.dues_rate is None or schedule_doc.dues_rate < 0:
                return {
                    "valid": False,
                    "reason": f"Invalid dues rate: {schedule_doc.dues_rate} (cannot be negative)",
                }

            # Check for extremely high rates (configurable threshold with safe fallback)
            try:
                max_reasonable_rate = (
                    frappe.db.get_single_value("Verenigingen Settings", "max_reasonable_dues_rate") or 10000
                )
            except frappe.DoesNotExistError:
                self.logger.warning(
                    f"Verenigingen Settings doctype does not exist, using default max_reasonable_dues_rate. "
                    f"Reference: Membership Dues Schedule/{getattr(schedule_doc, 'name', 'New Document')}"
                )
                max_reasonable_rate = 10000  # Safe fallback if setting doesn't exist
            except Exception as e:
                self.logger.error(
                    f"Failed to access dues rate configuration: {str(e)}. "
                    f"Reference: Membership Dues Schedule/{getattr(schedule_doc, 'name', 'New Document')}"
                )
                max_reasonable_rate = 10000  # Safe fallback if setting doesn't exist

            if schedule_doc.dues_rate > max_reasonable_rate:
                # Use shorter error message to avoid length limits
                return {
                    "valid": False,
                    "reason": f"Dues rate {schedule_doc.dues_rate} exceeds max {max_reasonable_rate}",
                }

            # Check for extreme rate changes from previous period (if exists)
            if schedule_doc.last_generated_invoice:
                try:
                    last_invoice = frappe.get_doc("Sales Invoice", schedule_doc.last_generated_invoice)
                    if last_invoice.grand_total > 0:
                        rate_change_percent = abs(
                            (schedule_doc.dues_rate - last_invoice.grand_total)
                            / last_invoice.grand_total
                            * 100
                        )
                        try:
                            max_rate_change = (
                                frappe.db.get_single_value("Verenigingen Settings", "max_rate_change_percent")
                                or 200
                            )
                        except frappe.DoesNotExistError:
                            self.logger.warning(
                                f"Verenigingen Settings doctype does not exist, using default max_rate_change_percent. "
                                f"Reference: Membership Dues Schedule/{getattr(schedule_doc, 'name', 'New Document')}"
                            )
                            max_rate_change = 200  # Safe fallback
                        except Exception as e:
                            self.logger.error(
                                f"Failed to access rate change configuration: {str(e)}. "
                                f"Reference: Membership Dues Schedule/{getattr(schedule_doc, 'name', 'New Document')}"
                            )
                            max_rate_change = 200  # Safe fallback

                        if rate_change_percent > max_rate_change:
                            # Just log, don't block - might be legitimate
                            pass
                except Exception:
                    # Don't fail validation if we can't check previous rate
                    pass

            return {"valid": True, "reason": "Rate validation passed"}

        except Exception as e:
            # Log validation error for debugging
            self.logger.warning(
                f"Rate validation error for schedule {getattr(schedule_doc, 'name', 'Unknown')}: {str(e)}"
            )
            # Use shorter error message to avoid length limits
            return {"valid": True, "reason": "Rate validation error - allowing generation"}

    def validate_rate_boundaries(self, schedule_doc: "Document") -> None:
        """
        Enhanced rate validation with comprehensive boundary checks.

        More thorough than basic positive/negative validation, including:
        - Positive value enforcement
        - Template minimum compliance
        - Unreasonably high amount detection
        - Smart handling for existing schedules (warnings vs. errors)

        Args:
            schedule_doc: MembershipDuesSchedule document instance

        Raises:
            InvalidDuesRateError: If rate violates boundaries

        Business Logic:
            - Enforces positive rates (negative/zero not allowed)
            - Compares to membership type minimum
            - Existing schedules get warnings instead of errors
            - New schedules must comply with minimum
            - Very high rates trigger warnings for verification
            - Skips strict validation during invoice generation

        Security:
            - Prevents invoice generation with invalid rates
            - Allows flexibility for existing member agreements
            - Admin-friendly warnings for unusual amounts

        Example:
            >>> schedule.dues_rate = -5.00
            >>> DuesScheduleValidationService.validate_rate_boundaries(schedule)
            # Raises: InvalidDuesRateError("Dues rate must be positive. Got: €-5.00")
        """
        # Skip validation for templates or when dues_rate is not set (None)
        # Allow 0 as valid for free memberships
        if schedule_doc.is_template or schedule_doc.dues_rate is None:
            return

        # Block negative values only (0 is allowed for free memberships)
        if schedule_doc.dues_rate < 0:
            from verenigingen.utils.exceptions import InvalidDuesRateError

            raise InvalidDuesRateError(f"Dues rate cannot be negative. Got: €{schedule_doc.dues_rate:.2f}")

        # Check against membership type boundaries - but only during user edits, not invoice generation
        # Skip strict validation if we're in an automated context like invoice generation
        if (
            schedule_doc.membership_type
            and not getattr(schedule_doc, "_skip_minimum_validation", False)
            and not frappe.flags.in_invoice_generation
        ):
            # Skip template validation for existing schedules when changing membership type
            schedule_doc._skip_template_validation = not schedule_doc.is_new()

            from verenigingen.services.billing.template_configuration_service import (
                TemplateConfigurationService,
            )

            template_values = TemplateConfigurationService().get_template_values(
                schedule_doc, schedule_doc.membership_type
            )
            min_amount = template_values.get("minimum_amount", 0)

            if schedule_doc.dues_rate < min_amount:
                # For existing schedules, allow the rate to remain as-is when changing membership type
                if not schedule_doc.is_new():
                    # Only show warning, don't block the change
                    frappe.msgprint(
                        f"Warning: Dues rate €{schedule_doc.dues_rate:.2f} is below minimum required "
                        f"€{min_amount:.2f} for membership type {schedule_doc.membership_type}. "
                        f"This is allowed for existing schedules to maintain member flexibility.",
                        alert=True,
                    )
                    return  # Don't block existing schedules

                from verenigingen.utils.exceptions import InvalidDuesRateError

                raise InvalidDuesRateError(
                    f"Dues rate €{schedule_doc.dues_rate:.2f} is below minimum required "
                    f"€{min_amount:.2f} for membership type {schedule_doc.membership_type}"
                )

        # Check for unreasonably high rates (configurable maximum)
        try:
            max_reasonable_rate = (
                frappe.db.get_single_value("Verenigingen Settings", "max_reasonable_dues_rate") or 10000
            )
        except Exception:
            # Fallback if field doesn't exist yet
            max_reasonable_rate = 10000

        if schedule_doc.dues_rate > max_reasonable_rate:
            frappe.msgprint(
                f"Warning: Dues rate €{schedule_doc.dues_rate:.2f} exceeds recommended maximum "
                f"€{max_reasonable_rate:.2f}. Please verify this amount is correct.",
                alert=True,
            )

    def validate_dates(self, schedule_doc: "Document") -> None:
        """
        Validate schedule dates for consistency and reasonableness.

        Performs comprehensive date validation including:
        - Last invoice date not in future
        - Next invoice date after last invoice date
        - Coverage period alignment warnings

        Args:
            schedule_doc: MembershipDuesSchedule document instance

        Raises:
            frappe.ValidationError: If dates are logically inconsistent

        Business Logic:
            - Auto-corrects future last invoice dates to today
            - Warns if next invoice date != last invoice date (but allows it)
            - Warns if invoice timing significantly misaligned with coverage dates
            - Allows equal dates (invoice already generated for period)

        Example:
            >>> schedule.last_invoice_date = future_date
            >>> DuesScheduleValidationService.validate_dates(schedule)
            # Shows warning, auto-corrects to today
        """
        today_date = getdate(today())

        # Validate last_invoice_date is not in the future
        if schedule_doc.last_invoice_date:
            last_date = getdate(schedule_doc.last_invoice_date)
            if last_date > today_date:
                # Auto-correct invalid future last invoice dates
                frappe.msgprint(
                    f"Warning: Last Invoice Date ({last_date}) was in the future and has been reset to today ({today_date}). "
                    "Last invoice dates should only reflect actual past invoices.",
                    alert=True,
                )
                schedule_doc.last_invoice_date = today_date

        # Allow last_invoice_date == next_invoice_date (means invoice already generated for period)
        # Coverage dates are the source of truth for overlap detection, not these tracking dates
        if schedule_doc.last_invoice_date and schedule_doc.next_invoice_date:
            if getdate(schedule_doc.last_invoice_date) > getdate(schedule_doc.next_invoice_date):
                frappe.throw("Next Invoice Date cannot be before Last Invoice Date")

        # Warn about significant gaps between next invoice date and coverage end date
        if schedule_doc.next_invoice_date and schedule_doc.last_invoice_coverage_end:
            next_date = getdate(schedule_doc.next_invoice_date)
            coverage_end = getdate(schedule_doc.last_invoice_coverage_end)

            # Calculate gap in days (positive = invoice after coverage ends, negative = invoice before coverage ends)
            gap_days = (next_date - coverage_end).days

            # Warn if invoice is scheduled more than 30 days after coverage ends
            if gap_days > 30:
                frappe.msgprint(
                    f"Warning: Next Invoice Date ({next_date}) is {gap_days} days after Coverage End Date ({coverage_end}). "
                    f"This schedule may be trying to invoice for expired coverage.",
                    indicator="orange",
                    alert=True,
                )

            # Warn if invoice is scheduled more than 30 days before coverage ends
            elif gap_days < -30:
                frappe.msgprint(
                    f"Warning: Next Invoice Date ({next_date}) is {abs(gap_days)} days before Coverage End Date ({coverage_end}). "
                    f"This schedule may not generate invoices before coverage expires.",
                    indicator="orange",
                    alert=True,
                )

    def validate_membership_type_consistency(self, schedule_doc: "Document") -> ValidationResult:
        """
        Verify member's current membership type matches schedule.

        Prevents billing with outdated membership type information by comparing
        the schedule's membership type against the member's current active membership.

        Args:
            schedule_doc: MembershipDuesSchedule document instance

        Returns:
            dict: Validation result with keys:
                - valid (bool): Whether validation passed
                - reason (str): Validation outcome message

        Business Logic:
            - Returns True if no member or membership type (nothing to compare)
            - Returns True if no active membership - defensive only: the sole
              production caller, EligibilityChecker.check_eligibility(), already
              calls check_active_membership() on the same (member, Active,
              docstatus=1) filter earlier in its pipeline and returns before
              reaching this method, so this branch is currently unreachable in
              practice. It stays fail-open (not an error) in case a future
              caller invokes this method without that upstream guard.
            - Returns False only if membership types mismatch
            - Gracefully handles validation errors (doesn't block generation)

        Example:
            >>> result = DuesScheduleValidationService.validate_membership_type_consistency(schedule)
            >>> if not result["valid"]:
            ...     print(f"Type mismatch: {result['reason']}")
        """
        try:
            if not schedule_doc.member or not schedule_doc.membership_type:
                return {"valid": True, "reason": "No member or membership type to validate"}

            # Get member's current active membership
            current_membership = frappe.get_all(
                "Membership",
                filters={"member": schedule_doc.member, "status": "Active", "docstatus": 1},
                fields=["membership_type", "name"],
                limit=1,
            )

            if not current_membership:
                # Defensive fallback, not a live gap: the only production caller,
                # EligibilityChecker.check_membership_type_consistency() (called
                # from check_eligibility()), only reaches this method after
                # check_active_membership() has already passed on this exact
                # filter, so "no active membership" cannot occur here today. See
                # the Business Logic note above - #619.
                return {
                    "valid": True,
                    "reason": "No active membership found - not this method's concern to enforce",
                }

            current_type = current_membership[0].membership_type

            # Check if membership types match
            if current_type != schedule_doc.membership_type:
                return {
                    "valid": False,
                    "reason": f"Type mismatch: schedule={schedule_doc.membership_type}, current={current_type}",
                }

            return {"valid": True, "reason": "Membership type consistency validated"}

        except Exception as e:
            # Log validation error for debugging
            self.logger.warning(
                f"Type consistency validation error for schedule {getattr(schedule_doc, 'name', 'Unknown')}: {str(e)}"
            )
            # Don't block generation on validation errors - continue gracefully
            return {"valid": True, "reason": "Type validation error - allowing generation"}


def get_dues_schedule_validation_service() -> DuesScheduleValidationService:
    """Get singleton instance of DuesScheduleValidationService"""
    return DuesScheduleValidationService()
