"""
Membership Application Service - Business logic for membership applications.

Handles contribution options resolution, dues schedule formatting,
contribution validation, and income-based contribution calculation.

Extracted from templates/pages/membership_application.py to keep
the controller thin and the business logic reusable/testable.
"""

from typing import Optional

import frappe
from frappe import _
from frappe.utils import flt

from verenigingen.services.infrastructure.base_service import StatelessService


class MembershipApplicationService(StatelessService):
    """Service for membership application business logic.

    Provides methods for:
    - Retrieving membership types with contribution options
    - Resolving billing/contribution values from dues schedule templates
    - Formatting dues schedules for frontend display
    - Validating contribution amounts against constraints
    - Calculating income-based contribution suggestions
    """

    def __init__(self):
        super().__init__("MembershipApplicationService")

    def get_template_contribution_values(self, membership_type_name: str) -> dict:
        """Get billing and contribution values from dues schedule template.

        Delegates core fee resolution to the canonical get_membership_type_fee_info()
        and supplements with template-specific fields (invoice_days, custom amounts).

        Args:
            membership_type_name: Name of the Membership Type document

        Returns:
            Dictionary with billing_frequency, minimum_contribution,
            suggested_contribution, maximum_contribution, fee_slider_max_multiplier,
            allow_custom_amounts, custom_amount_requires_approval, and
            invoice_days_before. Returns empty dict on error.
        """
        from verenigingen.utils.application_helpers import get_membership_type_fee_info

        try:
            info = get_membership_type_fee_info(membership_type_name)
            if not info.get("success"):
                frappe.throw(
                    f"Membership Type '{membership_type_name}' must have either a dues schedule template "
                    f"with suggested_amount/dues_rate or minimum_amount configured"
                )

            # Base values from canonical source
            values = {
                "billing_frequency": info["billing_frequency"],
                "minimum_contribution": 0,
                "suggested_contribution": info["amount"],
                "maximum_contribution": 0,
                "fee_slider_max_multiplier": 10.0,
                "allow_custom_amounts": True,
                "custom_amount_requires_approval": False,
                "invoice_days_before": 30,
            }

            # Supplement with template-specific fields the canonical function doesn't provide
            if info.get("has_template"):
                try:
                    mt_doc = frappe.get_doc("Membership Type", membership_type_name)
                    template = frappe.get_doc("Membership Dues Schedule", mt_doc.dues_schedule_template)
                    values["minimum_contribution"] = template.minimum_amount if template.minimum_amount else 0
                    values["invoice_days_before"] = (
                        template.invoice_days_before if template.invoice_days_before else 30
                    )
                    values["allow_custom_amounts"] = (
                        bool(template.uses_custom_amount) if hasattr(template, "uses_custom_amount") else True
                    )
                except Exception:
                    pass

            return values
        except Exception:
            return {}

    def get_membership_types_with_contributions(self) -> list:
        """Get all active membership types with their contribution options.

        Queries active membership types, resolves their contribution options
        from the Membership Type document, and supplements with billing values
        from the dues schedule template.

        Returns:
            List of dicts, each containing name, membership_type_name, description,
            amount, billing_frequency, and contribution_options for a membership type.
        """
        membership_types = frappe.get_all(
            "Membership Type",
            filters={"is_active": 1},
            fields=[
                "name",
                "membership_type_name",
                "description",
                "minimum_amount",
                "billing_period",
                "dues_schedule_template",
            ],
            order_by="membership_type_name",
        )

        enhanced_types = []
        for mt in membership_types:
            mt_doc = frappe.get_doc("Membership Type", mt.name)

            # Get contribution options with explicit validation
            try:
                contribution_options = mt_doc.get_contribution_options()
            except Exception as e:
                frappe.log_error(
                    f"Error getting contribution options for membership type '{mt.name}': {str(e)}",
                    "Membership Type Configuration Error",
                )

                # Check if minimum_amount is configured as fallback base
                if not mt.minimum_amount:
                    frappe.throw(
                        f"Membership Type '{mt.name}' must have either a properly configured "
                        f"dues schedule template or minimum_amount to generate contribution options"
                    )

                # Use minimum_amount as explicit base for fallback options
                base_amount = mt.minimum_amount
                contribution_options = {
                    "mode": "Calculator",
                    "minimum": base_amount,
                    "suggested": base_amount * 2,
                    "maximum": base_amount * 10,
                    "calculator": {
                        "enabled": True,
                        "percentage": 0.75,
                        "description": "Fallback contribution calculation based on minimum amount",
                    },
                    "quick_amounts": [],
                }

            # Get billing values from template
            template_values = self.get_template_contribution_values(mt.name)

            # Use suggested amount from contribution_options (which comes from dues schedule template)
            # Fall back to minimum_amount only if suggested is not available
            display_amount = contribution_options.get("suggested", mt.minimum_amount) or mt.minimum_amount

            enhanced_mt = {
                "name": mt.name,
                "membership_type_name": mt.membership_type_name,
                "description": mt.description,
                "amount": display_amount,
                "billing_frequency": template_values.get("billing_frequency", "Annual"),
                "contribution_options": contribution_options,
            }

            enhanced_types.append(enhanced_mt)

        return enhanced_types

    def get_dues_schedules(self, membership_type_name: str) -> dict:
        """Get all dues schedule templates for a membership type, formatted for the frontend.

        This is the core query + formatting logic. Input validation (empty check,
        sanitization, existence check) is handled by the calling controller endpoint.

        Args:
            membership_type_name: The validated name of the membership type

        Returns:
            Dict with success status, membership_type, and list of formatted schedules.
        """
        try:
            # Get all template dues schedules linked to this membership type
            schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={
                    "is_template": 1,
                    "membership_type": membership_type_name,
                    "status": ["in", ["Active", "Draft"]],
                },
                fields=[
                    "name",
                    "schedule_name",
                    "billing_frequency",
                    "dues_rate",
                    "currency",
                    "notes",
                    "contribution_mode",
                    "income_calculation_type",
                    "income_percentage",
                    "suggestion_multipliers",
                    "default_multiplier",
                    "allow_custom_amount",
                    "minimum_amount",
                    "suggested_amount",
                    "progressive_reference_income",
                    "progressive_lower_threshold",
                    "progressive_formula_description",
                ],
                order_by="dues_rate asc",
            )

            # Format the schedules for the frontend
            formatted_schedules = []
            for schedule in schedules:
                billing_display = self._get_billing_display(schedule.billing_frequency)

                schedule_data = {
                    "contribution_mode": schedule.contribution_mode,
                    "minimum_amount": schedule.minimum_amount,
                    "suggested_amount": schedule.suggested_amount,
                    "dues_rate": schedule.dues_rate,
                    "income_calculation_type": schedule.income_calculation_type,
                    "income_percentage": schedule.income_percentage,
                    "progressive_formula_description": schedule.progressive_formula_description,
                    "progressive_reference_income": schedule.progressive_reference_income,
                    "progressive_lower_threshold": schedule.progressive_lower_threshold,
                    "suggestion_multipliers": schedule.suggestion_multipliers,
                    "default_multiplier": schedule.default_multiplier,
                    "allow_custom_amount": schedule.allow_custom_amount,
                }
                contribution_settings = self._build_contribution_settings(
                    schedule_data.get("contribution_mode") or "Fixed",
                    schedule_data,
                )

                formatted_schedules.append(
                    {
                        "name": schedule.name,
                        "schedule_name": schedule.schedule_name or schedule.name,
                        "billing_frequency": schedule.billing_frequency,
                        "billing_display": billing_display,
                        "amount": schedule.dues_rate or 0,
                        "currency": schedule.currency or "EUR",
                        "notes": schedule.notes or "",
                        "contribution_settings": contribution_settings,
                    }
                )

            # If no templates found, check if the membership type has a default template
            if not formatted_schedules:
                formatted_schedules = self._get_fallback_schedule(membership_type_name)

            return {
                "success": True,
                "membership_type": membership_type_name,
                "schedules": formatted_schedules,
            }

        except frappe.DoesNotExistError:
            return {"success": False, "error": f"Membership type '{membership_type_name}' not found"}
        except Exception as e:
            frappe.log_error(f"Error getting dues schedules: {str(e)}")
            return {"success": False, "error": "An error occurred while retrieving dues schedules"}

    def validate_contribution(
        self,
        membership_type_name: str,
        amount,
        contribution_mode=None,
        selected_tier=None,
        base_multiplier=None,
    ) -> dict:
        """Validate a contribution amount against membership type constraints.

        Args:
            membership_type_name: Name of the Membership Type document
            amount: The contribution amount to validate (will be converted to float)
            contribution_mode: Optional contribution mode override
            selected_tier: Optional selected tier name
            base_multiplier: Optional base multiplier value

        Returns:
            Dict with valid (bool), amount, min_amount, max_amount, needs_approval,
            message, and optionally error.
        """
        try:
            amount = flt(amount)
            mt_doc = frappe.get_doc("Membership Type", membership_type_name)

            # Get minimum and maximum constraints from template with explicit fallback logic
            template_values = self.get_template_contribution_values(membership_type_name)

            # Calculate minimum amount with proper fallback hierarchy
            min_amount = template_values.get("minimum_contribution", 0)
            if min_amount <= 0:
                if mt_doc.minimum_amount:
                    min_amount = mt_doc.minimum_amount * 0.3
                else:
                    min_amount = 5.0  # Final fallback

            # Calculate maximum amount with proper fallback hierarchy
            max_amount = template_values.get("maximum_contribution", 0)
            if max_amount <= 0:
                suggested_amount = template_values.get("suggested_contribution", 15.0)
                max_multiplier = template_values.get("fee_slider_max_multiplier", 10.0)
                max_amount = suggested_amount * max_multiplier

            # Validate against constraints
            if amount < min_amount:
                return {
                    "valid": False,
                    "error": f"Amount cannot be less than minimum: \u20ac{min_amount:.2f}",
                    "min_amount": min_amount,
                    "max_amount": max_amount,
                }

            if max_amount and amount > max_amount:
                return {
                    "valid": False,
                    "error": f"Amount cannot be more than maximum: \u20ac{max_amount:.2f}",
                    "min_amount": min_amount,
                    "max_amount": max_amount,
                }

            # Determine if approval is needed for custom amounts
            needs_approval = False
            if amount != template_values.get("suggested_contribution", 0) and template_values.get(
                "custom_amount_requires_approval", False
            ):
                needs_approval = True

            return {
                "valid": True,
                "amount": amount,
                "min_amount": min_amount,
                "max_amount": max_amount,
                "needs_approval": needs_approval,
                "message": "Amount is valid",
            }

        except frappe.DoesNotExistError:
            return {"valid": False, "error": f"Membership type '{membership_type_name}' not found"}
        except Exception as e:
            frappe.log_error(f"Error validating contribution amount: {str(e)}")
            return {"valid": False, "error": "An error occurred while validating the amount"}

    def calculate_income_contribution(
        self, membership_type_name: str, monthly_income, interval: str = "monthly"
    ) -> dict:
        """Calculate suggested contribution based on income.

        Args:
            membership_type_name: Name of the Membership Type document
            monthly_income: Monthly net income (will be converted to float)
            interval: Payment interval - "monthly", "quarterly", or "annually"

        Returns:
            Dict with success, calculated_amount, base_monthly_amount,
            payment_interval, percentage_rate, minimum_amount, and monthly_income.
            On error, returns dict with error key.
        """
        try:
            monthly_income = flt(monthly_income)
            mt_doc = frappe.get_doc("Membership Type", membership_type_name)

            # Get percentage rate from membership type or fall back to global setting
            percentage_rate = (
                mt_doc.income_percentage_rate
                if hasattr(mt_doc, "income_percentage_rate") and mt_doc.income_percentage_rate
                else 0.5
            )

            # Calculate base amount (monthly)
            base_amount = monthly_income * (percentage_rate / 100)

            # Adjust for payment interval
            interval_multipliers = {"monthly": 1, "quarterly": 3, "annually": 12}
            multiplier = interval_multipliers.get(interval, 1)
            calculated_amount = base_amount * multiplier

            # Ensure minimum amount from template with explicit validation
            template_values = self.get_template_contribution_values(membership_type_name)
            min_contribution = template_values.get("minimum_contribution", 0)
            if min_contribution > 0:
                min_amount = min_contribution
            else:
                # Use explicit default instead of fuzzy fallback
                min_amount = 5.0
                frappe.log_error(
                    f"No minimum contribution configured for membership type "
                    f"'{membership_type_name}', using default \u20ac5.00",
                    "Membership Application Minimum Amount",
                )
            if interval == "quarterly":
                min_amount = min_amount * 3
            elif interval == "annually":
                min_amount = min_amount * 12

            final_amount = max(calculated_amount, min_amount)

            return {
                "success": True,
                "calculated_amount": final_amount,
                "base_monthly_amount": base_amount,
                "payment_interval": interval,
                "percentage_rate": percentage_rate,
                "minimum_amount": min_amount,
                "monthly_income": monthly_income,
            }

        except Exception as e:
            frappe.log_error(f"Error calculating suggested contribution: {str(e)}")
            return {"error": "An error occurred while calculating the suggested contribution"}

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _build_contribution_settings(self, mode: str, schedule_data: dict) -> dict:
        """Build contribution settings dict from schedule data.

        This is the shared method that eliminates the duplicated contribution_settings
        building logic. Both query-result schedules and fallback template objects
        prepare a uniform schedule_data dict before calling this method.

        Args:
            mode: Contribution mode - "Fixed", "Income-Based", or "Flexible"
            schedule_data: Dict containing the schedule fields:
                - dues_rate: Base dues rate amount
                - minimum_amount: Minimum contribution amount
                - suggested_amount: Suggested contribution amount
                - income_calculation_type: "Percentage" or "Progressive" (Income-Based)
                - income_percentage: Percentage for income-based calc
                - progressive_formula_description: Description for progressive formula
                - progressive_reference_income: Reference income for progressive calc
                - progressive_lower_threshold: Lower threshold for progressive calc
                - suggestion_multipliers: Comma-separated multiplier values (Flexible)
                - default_multiplier: Default multiplier value (Flexible)
                - allow_custom_amount: Whether custom amounts are allowed (Flexible)

        Returns:
            Dict with mode, minimum, suggested, and mode-specific fields.
        """
        dues_rate = schedule_data.get("dues_rate") or 0

        contribution_settings = {
            "mode": mode,
            "minimum": schedule_data.get("minimum_amount") or dues_rate or 0,
            "suggested": schedule_data.get("suggested_amount") or dues_rate or 0,
        }

        if mode == "Income-Based":
            calc_type = schedule_data.get("income_calculation_type") or "Percentage"
            contribution_settings["calculation_type"] = calc_type
            contribution_settings["description"] = schedule_data.get("progressive_formula_description") or ""

            if calc_type == "Percentage":
                contribution_settings["percentage"] = schedule_data.get("income_percentage") or 0.75
            elif calc_type == "Progressive":
                contribution_settings["progressive"] = {
                    "reference_income": schedule_data.get("progressive_reference_income") or 3500,
                    "lower_threshold": schedule_data.get("progressive_lower_threshold") or 2200,
                }

        elif mode == "Flexible":
            multipliers_str = schedule_data.get("suggestion_multipliers") or "1,1.25,1.5,2"
            try:
                multipliers = [float(m.strip()) for m in multipliers_str.split(",") if m.strip()]
            except ValueError:
                multipliers = [1, 1.25, 1.5, 2]

            base_amount = dues_rate
            default_mult = schedule_data.get("default_multiplier") or 1
            contribution_settings["suggestions"] = [
                {
                    "multiplier": m,
                    "amount": base_amount * m,
                    "label": f"{int(m * 100)}%" if m != 1 else "Minimum",
                    "is_default": m == default_mult,
                }
                for m in multipliers
            ]
            contribution_settings["allow_custom"] = bool(schedule_data.get("allow_custom_amount", True))
            contribution_settings["default_multiplier"] = default_mult

        return contribution_settings

    def _get_billing_display(self, billing_frequency: str) -> str:
        """Convert billing frequency to a display-friendly string.

        Args:
            billing_frequency: One of "Monthly", "Quarterly", "Semi-Annual", "Annual"

        Returns:
            Human-readable billing period string.
        """
        billing_period_map = {
            "Monthly": "per month",
            "Quarterly": "per quarter",
            "Semi-Annual": "every 6 months",
            "Annual": "per year",
        }
        return billing_period_map.get(billing_frequency, billing_frequency)

    def _get_fallback_schedule(self, membership_type_name: str) -> list:
        """Get fallback schedule from the membership type's default template.

        Called when no direct template dues schedules are found for the membership type.

        Args:
            membership_type_name: Name of the Membership Type document

        Returns:
            List containing at most one formatted schedule dict, or empty list.
        """
        mt_doc = frappe.get_doc("Membership Type", membership_type_name)
        if not mt_doc.dues_schedule_template:
            return []

        try:
            template = frappe.get_doc("Membership Dues Schedule", mt_doc.dues_schedule_template)

            # Prepare uniform schedule_data dict from template attributes
            schedule_data = {
                "contribution_mode": getattr(template, "contribution_mode", None),
                "minimum_amount": getattr(template, "minimum_amount", None),
                "suggested_amount": getattr(template, "suggested_amount", None),
                "dues_rate": template.dues_rate,
                "income_calculation_type": getattr(template, "income_calculation_type", None),
                "income_percentage": getattr(template, "income_percentage", 0.75),
                "progressive_formula_description": getattr(template, "progressive_formula_description", ""),
                "progressive_reference_income": getattr(template, "progressive_reference_income", 3500),
                "progressive_lower_threshold": getattr(template, "progressive_lower_threshold", 2200),
                "suggestion_multipliers": getattr(template, "suggestion_multipliers", "1,1.25,1.5,2"),
                "default_multiplier": getattr(template, "default_multiplier", 1),
                "allow_custom_amount": getattr(template, "allow_custom_amount", 1),
            }

            mode = schedule_data["contribution_mode"] or "Fixed"
            contribution_settings = self._build_contribution_settings(mode, schedule_data)

            return [
                {
                    "name": template.name,
                    "schedule_name": template.schedule_name or template.name,
                    "billing_frequency": template.billing_frequency,
                    "billing_display": self._get_billing_display(template.billing_frequency),
                    "amount": template.dues_rate or 0,
                    "currency": template.currency or "EUR",
                    "notes": template.notes or "",
                    "contribution_settings": contribution_settings,
                }
            ]
        except frappe.DoesNotExistError:
            return []


# Module-level singleton accessor
_service_instance: Optional[MembershipApplicationService] = None


def get_membership_application_service() -> MembershipApplicationService:
    """Get or create the MembershipApplicationService singleton.

    Returns:
        MembershipApplicationService: The service instance
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = MembershipApplicationService()
    return _service_instance
