"""
Enhanced context for membership application page with flexible contribution system
"""

import frappe
from frappe import _
from frappe.utils import flt

from verenigingen.utils.member_utils import get_current_user_member_name
from verenigingen.utils.security.api_security_framework import OperationType, public_api, standard_api


def get_context(context):
    """Get context for enhanced membership application page"""

    # Set page properties
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Apply for Membership")

    # Check if user is already a member
    if frappe.session.user != "Guest":
        existing_member = get_current_user_member_name()
        if existing_member:
            context.already_member = True
            context.member_name = existing_member
            return context

    # Get verenigingen settings
    settings = frappe.get_single("Verenigingen Settings")
    context.settings = {
        "enable_chapter_management": settings.enable_chapter_management,
        "company_name": frappe.get_value("Company", settings.company, "company_name"),
    }

    # Get organization logo from Brand Settings
    from verenigingen.verenigingen.doctype.brand_settings.brand_settings import get_organization_logo

    context.organization_logo = get_organization_logo()

    # Get all active membership types with contribution options
    membership_types = get_membership_types_with_contributions()
    context.membership_types = membership_types

    # Add income calculator settings (global defaults)
    context.enable_income_calculator = getattr(settings, "enable_income_calculator", 0)
    context.income_percentage_rate = getattr(settings, "income_percentage_rate", 0.5)
    context.calculator_description = getattr(
        settings,
        "calculator_description",
        "Our suggested contribution is 0.5% of your monthly net income. This helps ensure fair and equitable contributions based on your financial capacity.",
    )

    # Basic context setup
    context.already_member = False

    return context


def get_dues_schedule_template_values(membership_type_name):
    """Get billing and contribution values from dues schedule template.

    Delegates core fee resolution to the canonical get_membership_type_fee_info()
    and supplements with template-specific fields (invoice_days, custom amounts).
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


def get_membership_types_with_contributions():
    """Get all active membership types with their contribution options"""
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
        # Get the membership type document to access contribution options
        mt_doc = frappe.get_doc("Membership Type", mt.name)

        # Get contribution options with explicit validation
        try:
            contribution_options = mt_doc.get_contribution_options()
        except Exception as e:
            # Explicit error handling instead of fuzzy fallback
            frappe.log_error(
                f"Error getting contribution options for membership type '{mt.name}': {str(e)}",
                "Membership Type Configuration Error",
            )

            # Check if minimum_amount is configured as fallback base
            if not mt.minimum_amount:
                frappe.throw(
                    f"Membership Type '{mt.name}' must have either a properly configured dues schedule template or minimum_amount to generate contribution options"
                )

            # Use minimum_amount as explicit base for fallback options
            base_amount = mt.minimum_amount
            contribution_options = {
                "mode": "Calculator",
                "minimum": base_amount,
                "suggested": base_amount * 2,  # Explicit multiplier instead of magic numbers
                "maximum": base_amount * 10,
                "calculator": {
                    "enabled": True,
                    "percentage": 0.75,  # Standard percentage
                    "description": "Fallback contribution calculation based on minimum amount",
                },
                "quick_amounts": [],
            }

        # Get billing values from template
        template_values = get_dues_schedule_template_values(mt.name)

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


@frappe.whitelist()
@public_api
def get_membership_type_details(membership_type_name: str):
    """Get detailed contribution options for a specific membership type."""
    if not membership_type_name:
        return {"error": "Membership type name is required"}

    try:
        from verenigingen.utils.application_helpers import get_membership_type_fee_info

        info = get_membership_type_fee_info(membership_type_name)
        if not info.get("success"):
            return {"error": info.get("error", "Unknown error")}

        mt_doc = frappe.get_doc("Membership Type", membership_type_name)
        return {
            "success": True,
            "membership_type": {
                "name": info["membership_type"],
                "membership_type_name": info["membership_type_name"],
                "description": info["description"],
                "amount": info["amount"],
                "billing_frequency": info["billing_frequency"],
                "contribution_options": (
                    mt_doc.get_contribution_options() if hasattr(mt_doc, "get_contribution_options") else {}
                ),
            },
        }
    except frappe.DoesNotExistError:
        return {"error": f"Membership type '{membership_type_name}' not found"}
    except Exception as e:
        frappe.log_error(f"Error getting membership type details: {str(e)}")
        return {"error": "An error occurred while retrieving membership type details"}


@frappe.whitelist(allow_guest=True)
def get_dues_schedules_for_membership_type(membership_type_name: str):
    """Get all dues schedule templates for a specific membership type.

    This is used in the two-phase membership selection where:
    1. User first selects a membership type
    2. Then sees available payment plans (dues schedules) for that type

    Args:
        membership_type_name: The name of the membership type

    Returns:
        dict with success status and list of dues schedules
    """
    # Input validation for guest-accessible endpoint
    if not membership_type_name:
        return {"success": False, "error": "Membership type name is required"}

    # Sanitize input - membership type names should be reasonable length and format
    membership_type_name = str(membership_type_name).strip()
    if len(membership_type_name) > 140:
        return {"success": False, "error": "Invalid membership type name"}

    # Verify the membership type actually exists before proceeding
    if not frappe.db.exists("Membership Type", membership_type_name):
        return {"success": False, "error": f"Membership type '{membership_type_name}' not found"}

    try:
        # Get all template dues schedules linked to this membership type
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={
                "is_template": 1,
                "membership_type": membership_type_name,
                "status": ["in", ["Active", "Draft"]],  # Include both for flexibility
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
            # Create a display-friendly billing period
            billing_period_map = {
                "Monthly": "per month",
                "Quarterly": "per quarter",
                "Semi-Annual": "every 6 months",
                "Annual": "per year",
            }
            billing_display = billing_period_map.get(schedule.billing_frequency, schedule.billing_frequency)

            # Build contribution settings based on the new mode structure
            mode = schedule.contribution_mode or "Fixed"
            contribution_settings = {
                "mode": mode,
                "minimum": schedule.minimum_amount or schedule.dues_rate or 0,
                "suggested": schedule.suggested_amount or schedule.dues_rate or 0,
            }

            if mode == "Income-Based":
                calc_type = schedule.income_calculation_type or "Percentage"
                contribution_settings["calculation_type"] = calc_type
                contribution_settings["description"] = schedule.progressive_formula_description or ""

                if calc_type == "Percentage":
                    contribution_settings["percentage"] = schedule.income_percentage or 0.75
                elif calc_type == "Progressive":
                    contribution_settings["progressive"] = {
                        "reference_income": schedule.progressive_reference_income or 3500,
                        "lower_threshold": schedule.progressive_lower_threshold or 2200,
                    }

            elif mode == "Flexible":
                # Parse suggestion multipliers
                multipliers_str = schedule.suggestion_multipliers or "1,1.25,1.5,2"
                try:
                    multipliers = [float(m.strip()) for m in multipliers_str.split(",") if m.strip()]
                except ValueError:
                    multipliers = [1, 1.25, 1.5, 2]

                base_amount = schedule.dues_rate or 0
                contribution_settings["suggestions"] = [
                    {
                        "multiplier": m,
                        "amount": base_amount * m,
                        "label": f"{int(m * 100)}%" if m != 1 else "Minimum",
                        "is_default": m == (schedule.default_multiplier or 1),
                    }
                    for m in multipliers
                ]
                contribution_settings["allow_custom"] = bool(schedule.allow_custom_amount)
                contribution_settings["default_multiplier"] = schedule.default_multiplier or 1

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
            mt_doc = frappe.get_doc("Membership Type", membership_type_name)
            if mt_doc.dues_schedule_template:
                try:
                    template = frappe.get_doc("Membership Dues Schedule", mt_doc.dues_schedule_template)
                    billing_period_map = {
                        "Monthly": "per month",
                        "Quarterly": "per quarter",
                        "Semi-Annual": "every 6 months",
                        "Annual": "per year",
                    }

                    # Include contribution settings for fallback template
                    mode = getattr(template, "contribution_mode", None) or "Fixed"
                    contribution_settings = {
                        "mode": mode,
                        "minimum": getattr(template, "minimum_amount", None) or template.dues_rate or 0,
                        "suggested": getattr(template, "suggested_amount", None) or template.dues_rate or 0,
                    }

                    if mode == "Income-Based":
                        calc_type = getattr(template, "income_calculation_type", None) or "Percentage"
                        contribution_settings["calculation_type"] = calc_type
                        contribution_settings["description"] = (
                            getattr(template, "progressive_formula_description", "") or ""
                        )

                        if calc_type == "Percentage":
                            contribution_settings["percentage"] = (
                                getattr(template, "income_percentage", 0.75) or 0.75
                            )
                        elif calc_type == "Progressive":
                            contribution_settings["progressive"] = {
                                "reference_income": getattr(template, "progressive_reference_income", 3500)
                                or 3500,
                                "lower_threshold": getattr(template, "progressive_lower_threshold", 2200)
                                or 2200,
                            }

                    elif mode == "Flexible":
                        multipliers_str = (
                            getattr(template, "suggestion_multipliers", "1,1.25,1.5,2") or "1,1.25,1.5,2"
                        )
                        try:
                            multipliers = [float(m.strip()) for m in multipliers_str.split(",") if m.strip()]
                        except ValueError:
                            multipliers = [1, 1.25, 1.5, 2]

                        base_amount = template.dues_rate or 0
                        default_mult = getattr(template, "default_multiplier", 1) or 1
                        contribution_settings["suggestions"] = [
                            {
                                "multiplier": m,
                                "amount": base_amount * m,
                                "label": f"{int(m * 100)}%" if m != 1 else "Minimum",
                                "is_default": m == default_mult,
                            }
                            for m in multipliers
                        ]
                        contribution_settings["allow_custom"] = bool(
                            getattr(template, "allow_custom_amount", 1)
                        )
                        contribution_settings["default_multiplier"] = default_mult

                    formatted_schedules.append(
                        {
                            "name": template.name,
                            "schedule_name": template.schedule_name or template.name,
                            "billing_frequency": template.billing_frequency,
                            "billing_display": billing_period_map.get(
                                template.billing_frequency, template.billing_frequency
                            ),
                            "amount": template.dues_rate or 0,
                            "currency": template.currency or "EUR",
                            "notes": template.notes or "",
                            "contribution_settings": contribution_settings,
                        }
                    )
                except frappe.DoesNotExistError:
                    pass

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


@frappe.whitelist()
@public_api
def validate_contribution_amount(
    membership_type_name: str, amount, contribution_mode=None, selected_tier=None, base_multiplier=None
):
    """Validate a contribution amount against membership type constraints"""
    if not membership_type_name or not amount:
        return {"valid": False, "error": "Membership type and amount are required"}

    try:
        amount = flt(amount)
        mt_doc = frappe.get_doc("Membership Type", membership_type_name)

        # Get minimum and maximum constraints from template with explicit fallback logic
        template_values = get_dues_schedule_template_values(membership_type_name)

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
                "error": f"Amount cannot be less than minimum: €{min_amount:.2f}",
                "min_amount": min_amount,
                "max_amount": max_amount,
            }

        if max_amount and amount > max_amount:
            return {
                "valid": False,
                "error": f"Amount cannot be more than maximum: €{max_amount:.2f}",
                "min_amount": min_amount,
                "max_amount": max_amount,
            }

        # Determine if approval is needed for custom amounts
        needs_approval = False
        if contribution_mode == "Custom" or (
            amount != template_values.get("suggested_contribution", 0)
            and template_values.get("custom_amount_requires_approval", False)
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


@frappe.whitelist()
@public_api
def calculate_suggested_contribution(
    membership_type_name: str, monthly_income, payment_interval: str = "monthly"
):
    """Calculate suggested contribution based on income"""
    if not membership_type_name or not monthly_income:
        return {"error": "Membership type and monthly income are required"}

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

        multiplier = interval_multipliers.get(payment_interval, 1)
        calculated_amount = base_amount * multiplier

        # Ensure minimum amount from template with explicit validation
        template_values = get_dues_schedule_template_values(membership_type_name)
        min_contribution = template_values.get("minimum_contribution", 0)
        if min_contribution > 0:
            min_amount = min_contribution
        else:
            # Use explicit default instead of fuzzy fallback
            min_amount = 5.0
            frappe.log_error(
                f"No minimum contribution configured for membership type '{membership_type_name}', using default €5.00",
                "Membership Application Minimum Amount",
            )
        if payment_interval == "quarterly":
            min_amount = min_amount * 3
        elif payment_interval == "annually":
            min_amount = min_amount * 12

        final_amount = max(calculated_amount, min_amount)

        return {
            "success": True,
            "calculated_amount": final_amount,
            "base_monthly_amount": base_amount,
            "payment_interval": payment_interval,
            "percentage_rate": percentage_rate,
            "minimum_amount": min_amount,
            "monthly_income": monthly_income,
        }

    except Exception as e:
        frappe.log_error(f"Error calculating suggested contribution: {str(e)}")
        return {"error": "An error occurred while calculating the suggested contribution"}


# Add route configuration
no_cache = 1
sitemap = 0  # Don't include in sitemap
