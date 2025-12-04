# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
TemplateConfigurationService - Template value loading and validation

This service handles retrieving configuration values from dues schedule templates
and membership types with comprehensive validation.

Extracted from membership_dues_schedule.py:
- get_template_values() - Lines 39-126 (87 LOC)

Architecture:
- StatelessService base class with unified logging and metrics
- Template value resolution with fallback logic
- Circular reference handling for self-referencing templates
- Minimum amount enforcement from membership types

Business Logic:
- Template value retrieval: minimum_amount, suggested_amount, billing_frequency, invoice_days_before
- Membership type minimum enforcement
- Calculator mode validation (requires suggested_amount)
- Template-to-membership-type consistency checks

Dependencies:
- frappe.model.document for template and membership type loading
- Configuration validation with clear error messages
"""

from typing import TYPE_CHECKING, Any, Dict

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class TemplateConfigurationService(StatelessService):
    """
    Service for managing dues schedule template configuration.

    This service handles:
    - Retrieving configuration values from templates
    - Validating template configuration
    - Enforcing membership type minimums
    - Handling self-referencing templates
    """

    def __init__(self):
        super().__init__(service_name="TemplateConfigurationService")

    def get_template_values(
        self,
        schedule_doc: "Document",
        membership_type: str,
        is_template: bool = False,
        skip_validation: bool = False,
    ) -> Dict[str, Any]:
        """
        Get billing and contribution values from template if available.

        Retrieves configuration from the dues schedule template assigned to the
        membership type, with comprehensive validation and fallback logic.

        Args:
            schedule_doc: The schedule document (for self-reference detection)
            membership_type: Name of the membership type
            is_template: Whether this schedule is itself a template
            skip_validation: Skip template validation (for updates)

        Returns:
            Dict with keys:
                - minimum_amount (float): Minimum contribution amount
                - suggested_amount (float): Suggested/default amount
                - billing_frequency (str): Billing frequency
                - invoice_days_before (int): Days before period to invoice

        Raises:
            frappe.ValidationError: If template not found, not configured, or invalid

        Example:
            >>> service = TemplateConfigurationService()
            >>> values = service.get_template_values(
            ...     schedule_doc=schedule,
            ...     membership_type="Standard",
            ...     is_template=False
            ... )
            >>> print(values["minimum_amount"])  # 15.0
        """
        if not membership_type:
            return {
                "minimum_amount": 0,
                "suggested_amount": 0,
                "billing_frequency": "Annual",
                "invoice_days_before": 30,
            }

        membership_type_doc = frappe.get_doc("Membership Type", membership_type)
        values = {
            "minimum_amount": 0,
            "suggested_amount": 0,
            "billing_frequency": "Annual",
            "invoice_days_before": 30,
        }

        # Get values from template (now required)
        if not membership_type_doc.dues_schedule_template:
            frappe.throw(
                f"Membership Type '{membership_type_doc.name}' must have a dues schedule template assigned"
            )

        # Calculate membership type minimum first to use as fallback
        membership_type_minimum = (
            membership_type_doc.minimum_amount if membership_type_doc.minimum_amount is not None else 0
        )

        try:
            # Special case: if this template is calling get_template_values() on itself during validation,
            # use the current unsaved values instead of loading from database
            if (
                is_template
                and hasattr(schedule_doc, "name")
                and schedule_doc.name == membership_type_doc.dues_schedule_template
            ):
                # Template is looking up its own values - use current state, not database state
                template = schedule_doc
            else:
                # Load the template from database (normal case for member schedules)
                template = frappe.get_doc(
                    "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                )

            # Validate template has required configuration based on contribution mode
            # Only require suggested_amount for Calculator mode (not Custom mode)
            if template.contribution_mode == "Calculator" and not template.suggested_amount:
                frappe.throw(
                    f"Dues schedule template '{membership_type_doc.dues_schedule_template}' with Calculator mode "
                    f"must have a suggested_amount configured"
                )

            values.update(
                {
                    "minimum_amount": (
                        template.minimum_amount
                        if template.minimum_amount is not None
                        else membership_type_minimum
                    ),
                    "suggested_amount": template.suggested_amount,
                    "billing_frequency": template.billing_frequency or "Annual",
                    "invoice_days_before": (
                        template.invoice_days_before if template.invoice_days_before is not None else 30
                    ),
                }
            )
        except Exception as e:
            frappe.throw(
                f"Failed to load dues schedule template '{membership_type_doc.dues_schedule_template}': {str(e)}"
            )

        # Validate template respects membership type minimum (both required)
        # Skip this validation when updating existing schedules to allow flexible dues rates
        template_minimum = values["minimum_amount"]
        template_suggested = values["suggested_amount"]

        # Use the maximum of template minimum and membership type minimum
        # This ensures compliance even if template is misconfigured
        if not skip_validation:
            if template_minimum < membership_type_minimum:
                self.logger.warning(
                    f"Template minimum amount (€{template_minimum:.2f}) is less than "
                    f"membership type minimum (€{membership_type_minimum:.2f}). "
                    f"Using membership type minimum instead."
                )
                values["minimum_amount"] = membership_type_minimum
                template_minimum = membership_type_minimum

            # Use the same logic as application helpers: dues_rate takes precedence over suggested_amount
            effective_amount = (
                template.dues_rate
                if hasattr(template, "dues_rate") and template.dues_rate
                else template_suggested
            )
            if effective_amount < membership_type_minimum:
                amount_type = (
                    "dues rate"
                    if hasattr(template, "dues_rate") and template.dues_rate
                    else "suggested amount"
                )
                frappe.throw(
                    f"Template {amount_type} (€{effective_amount:.2f}) cannot be less than "
                    f"membership type minimum (€{membership_type_minimum:.2f})"
                )

        return values


def get_template_configuration_service() -> TemplateConfigurationService:
    """Get singleton instance of TemplateConfigurationService"""
    return TemplateConfigurationService()
