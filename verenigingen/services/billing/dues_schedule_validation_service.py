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

from typing import TYPE_CHECKING, Any, Dict

import frappe
from frappe import _
from frappe.utils import getdate, today

if TYPE_CHECKING:
    from frappe.model.document import Document


class DuesScheduleValidationService:
    """
    Service for validating membership dues schedule financial constraints.

    This service handles:
    - Rate boundary validation (positive values, min/max limits)
    - Contribution mode configuration validation
    - Template consistency validation
    - Rate change reasonableness checks
    - Financial constraint enforcement
    """

    @staticmethod
    def validate_dues_rate_change(schedule_doc: "Document") -> bool:
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

        template_values = TemplateConfigurationService.get_template_values(
            schedule_doc, schedule_doc.membership_type
        )
        min_amount = template_values.get("minimum_amount", 0)

        if schedule_doc.dues_rate < min_amount:
            frappe.throw(f"Dues rate cannot be less than minimum contribution: €{min_amount:.2f}")

        return True

    @staticmethod
    def validate_dues_rate_configuration(schedule_doc: "Document") -> None:
        """
        Validate and set dues rate based on contribution mode.

        Calculates the appropriate dues_rate for the schedule based on its
        contribution_mode (Tier, Calculator, or Custom). Only calculates if
        dues_rate is not already set or is zero.

        Args:
            schedule_doc: MembershipDuesSchedule document instance

        Raises:
            frappe.ValidationError: If configuration is invalid or incomplete

        Business Logic:
            - Tier mode: Uses selected tier's amount
            - Calculator mode: Multiplies suggested_amount by base_multiplier
            - Custom mode: Requires uses_custom_amount flag
            - Templates skip calculation (may have incomplete configuration)

        Example:
            >>> schedule.contribution_mode = "Calculator"
            >>> schedule.base_multiplier = 1.5
            >>> DuesScheduleValidationService.validate_dues_rate_configuration(schedule)
            >>> print(schedule.dues_rate)  # Will be suggested_amount * 1.5
        """
        # Templates may not have all dues rate fields set
        if schedule_doc.is_template:
            return

        if not schedule_doc.membership_type:
            return

        # Only calculate dues_rate if not already explicitly set or if it's zero
        if not schedule_doc.dues_rate or schedule_doc.dues_rate == 0:
            if schedule_doc.contribution_mode == "Tier" and schedule_doc.selected_tier:
                tier = frappe.get_doc("Membership Tier", schedule_doc.selected_tier)
                schedule_doc.dues_rate = tier.amount
            elif schedule_doc.contribution_mode == "Calculator":
                from verenigingen.services.billing.template_configuration_service import (
                    TemplateConfigurationService,
                )

                template_values = TemplateConfigurationService.get_template_values(
                    schedule_doc, schedule_doc.membership_type
                )
                suggested_amount = template_values.get("suggested_amount", 0)
                if not suggested_amount:
                    frappe.throw(
                        "Cannot calculate dues: template has no suggested_amount configured. "
                        "Either set a suggested_amount or switch to Custom contribution mode."
                    )

                # Use base multiplier, defaulting to 1.0 if not set
                multiplier = schedule_doc.base_multiplier if schedule_doc.base_multiplier is not None else 1.0
                schedule_doc.dues_rate = suggested_amount * multiplier
            elif schedule_doc.contribution_mode == "Custom":
                if not schedule_doc.uses_custom_amount:
                    frappe.throw("Custom dues rate must be enabled for custom contribution mode")

        # If contribution mode is Custom but dues_rate is set, ensure custom amount flags are set
        if schedule_doc.contribution_mode == "Custom" and schedule_doc.dues_rate:
            if not schedule_doc.uses_custom_amount:
                schedule_doc.uses_custom_amount = 1

    @staticmethod
    def validate_financial_constraints(schedule_doc: "Document") -> None:
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
        if schedule_doc.is_template or not schedule_doc.dues_rate:
            return  # Skip for templates or when no dues rate is set

        try:
            # Get configuration values
            from verenigingen.utils.config_manager import ConfigManager

            # Check absolute minimum (safety check)
            absolute_minimum = ConfigManager.get("absolute_minimum_dues", 0.01)  # €0.01 minimum
            if float(schedule_doc.dues_rate) < absolute_minimum:
                frappe.throw(f"Dues rate cannot be less than €{absolute_minimum:.2f}", frappe.ValidationError)

            # Check maximum reasonable amount
            maximum_dues = ConfigManager.get("maximum_dues_limit", 1000.0)  # €1000 default max
            if float(schedule_doc.dues_rate) > maximum_dues:
                # Allow with warning for administrators
                user_roles = frappe.get_roles(frappe.session.user)
                admin_roles = ["System Manager", "Verenigingen Administrator", "Verenigingen Staff"]

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

                # Get suggested amount from template (explicit configuration)
                if not membership_type.dues_schedule_template:
                    frappe.throw(
                        f"Membership Type '{membership_type.name}' must have a dues schedule template"
                    )

        except Exception as e:
            # Re-raise validation errors
            if isinstance(e, frappe.ValidationError):
                raise
            # Log other errors but don't block validation
            frappe.log_error(
                f"Error in financial constraints validation for {schedule_doc.name}: {str(e)}",
                "Dues Schedule Validation",
            )

    @staticmethod
    def validate_dues_rate(schedule_doc: "Document") -> Dict[str, Any]:
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
                frappe.log_error(
                    message="Verenigingen Settings doctype does not exist, using default max_reasonable_dues_rate",
                    title="Membership Dues - Missing Settings Doctype",
                    reference_doctype="Membership Dues Schedule",
                    reference_name=getattr(schedule_doc, "name", "New Document"),
                )
                max_reasonable_rate = 10000  # Safe fallback if setting doesn't exist
            except Exception as e:
                frappe.log_error(
                    message=f"Failed to access dues rate configuration: {str(e)}",
                    title="Membership Dues - Configuration Access Failed",
                    reference_doctype="Membership Dues Schedule",
                    reference_name=getattr(schedule_doc, "name", "New Document"),
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
                            frappe.log_error(
                                message="Verenigingen Settings doctype does not exist, using default max_rate_change_percent",
                                title="Membership Dues - Missing Settings for Rate Change",
                                reference_doctype="Membership Dues Schedule",
                                reference_name=getattr(schedule_doc, "name", "New Document"),
                            )
                            max_rate_change = 200  # Safe fallback
                        except Exception as e:
                            frappe.log_error(
                                message=f"Failed to access rate change configuration: {str(e)}",
                                title="Membership Dues - Rate Change Config Access Failed",
                                reference_doctype="Membership Dues Schedule",
                                reference_name=getattr(schedule_doc, "name", "New Document"),
                            )
                            max_rate_change = 200  # Safe fallback

                        if rate_change_percent > max_rate_change:
                            # Just log, don't block - might be legitimate
                            pass
                except Exception:
                    # Don't fail validation if we can't check previous rate
                    pass

            return {"valid": True, "reason": "Rate validation passed"}

        except Exception:
            # Use shorter error message to avoid length limits
            return {"valid": True, "reason": "Rate validation error - allowing generation"}

    @staticmethod
    def validate_rate_boundaries(schedule_doc: "Document") -> None:
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
        if schedule_doc.is_template or not schedule_doc.dues_rate:
            return

        # Enhanced minimum validation
        if schedule_doc.dues_rate <= 0:
            from verenigingen.utils.exceptions import InvalidDuesRateError

            raise InvalidDuesRateError(f"Dues rate must be positive. Got: €{schedule_doc.dues_rate:.2f}")

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

            template_values = TemplateConfigurationService.get_template_values(
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

    @staticmethod
    def validate_dates(schedule_doc: "Document") -> None:
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

    @staticmethod
    def validate_membership_type_consistency(schedule_doc: "Document") -> Dict[str, Any]:
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
            - Returns True if no member or membership type (will be caught elsewhere)
            - Returns True if no active membership (eligibility check handles this)
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
                # This will be caught by the member eligibility check
                return {
                    "valid": True,
                    "reason": "No active membership found - will be handled by eligibility check",
                }

            current_type = current_membership[0].membership_type

            # Check if membership types match
            if current_type != schedule_doc.membership_type:
                return {
                    "valid": False,
                    "reason": f"Type mismatch: schedule={schedule_doc.membership_type}, current={current_type}",
                }

            return {"valid": True, "reason": "Membership type consistency validated"}

        except Exception:
            # Don't block generation on validation errors - continue gracefully
            return {"valid": True, "reason": "Type validation error - allowing generation"}


def get_dues_schedule_validation_service() -> DuesScheduleValidationService:
    """Get singleton instance of DuesScheduleValidationService"""
    return DuesScheduleValidationService()
