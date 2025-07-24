"""
Enhanced context for membership application page with flexible contribution system
"""

import frappe
from frappe import _
from frappe.utils import flt


def get_context(context):
    """Get context for enhanced membership application page"""

    # Set page properties
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Apply for Membership")

    # Check if user is already a member
    if frappe.session.user != "Guest":
        existing_member = frappe.db.get_value("Member", {"email": frappe.session.user})
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
    """Get billing and contribution values from dues schedule template"""
    try:
        mt_doc = frappe.get_doc("Membership Type", membership_type_name)

        # Get template-based suggested amount, not minimum_amount
        suggested_contribution = 0
        if mt_doc.dues_schedule_template:
            try:
                template = frappe.get_doc("Membership Dues Schedule", mt_doc.dues_schedule_template)
                # Check dues_rate first, then suggested_amount
                if template.dues_rate:
                    suggested_contribution = template.dues_rate
                elif template.suggested_amount:
                    suggested_contribution = template.suggested_amount
                else:
                    frappe.log_error(
                        f"Dues schedule template '{mt_doc.dues_schedule_template}' has no dues_rate or suggested_amount configured",
                        "Membership Application Template Configuration",
                    )
            except Exception as e:
                frappe.log_error(
                    f"Error accessing dues schedule template '{mt_doc.dues_schedule_template}': {str(e)}",
                    "Membership Application Template Access",
                )

        # Fallback to minimum_amount only if no template available and explicit validation
        if not suggested_contribution:
            if mt_doc.minimum_amount:
                suggested_contribution = mt_doc.minimum_amount
            else:
                frappe.throw(
                    f"Membership Type '{membership_type_name}' must have either a dues schedule template with suggested_amount/dues_rate or minimum_amount configured"
                )

        # Default values
        values = {
            "billing_frequency": "Annual",
            "minimum_contribution": 0,
            "suggested_contribution": suggested_contribution,
            "maximum_contribution": 0,
            "fee_slider_max_multiplier": 10.0,
            "allow_custom_amounts": True,
            "custom_amount_requires_approval": False,
            "invoice_days_before": 30,
        }

        # Get values from template if available
        if mt_doc.dues_schedule_template:
            try:
                template = frappe.get_doc("Membership Dues Schedule", mt_doc.dues_schedule_template)
                # Validate template configuration
                billing_frequency = template.billing_frequency if template.billing_frequency else "Annual"
                minimum_contribution = template.minimum_amount if template.minimum_amount else 0

                # Check suggested contribution with explicit validation
                template_suggested = None
                if template.dues_rate:
                    template_suggested = template.dues_rate
                elif template.suggested_amount:
                    template_suggested = template.suggested_amount
                else:
                    template_suggested = suggested_contribution

                invoice_days = template.invoice_days_before if template.invoice_days_before else 30
                allow_custom = (
                    bool(template.uses_custom_amount) if hasattr(template, "uses_custom_amount") else True
                )

                values.update(
                    {
                        "billing_frequency": billing_frequency,
                        "minimum_contribution": minimum_contribution,
                        "suggested_contribution": template_suggested,
                        "invoice_days_before": invoice_days,
                        "allow_custom_amounts": allow_custom,
                    }
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

        enhanced_mt = {
            "name": mt.name,
            "membership_type_name": mt.membership_type_name,
            "description": mt.description,
            "amount": mt.minimum_amount,  # Use minimum_amount field that exists in query
            "billing_frequency": template_values.get("billing_frequency", "Annual"),
            "contribution_options": contribution_options,
        }

        enhanced_types.append(enhanced_mt)

    return enhanced_types


@frappe.whitelist()
def get_membership_type_details(membership_type_name):
    """Get detailed contribution options for a specific membership type"""
    if not membership_type_name:
        return {"error": "Membership type name is required"}

    try:
        mt_doc = frappe.get_doc("Membership Type", membership_type_name)
        template_values = get_dues_schedule_template_values(membership_type_name)

        # Get suggested contribution from template values or minimum amount
        amount = template_values.get("suggested_contribution", 0)
        if not amount:
            amount = mt_doc.minimum_amount if mt_doc.minimum_amount else 0

        return {
            "success": True,
            "membership_type": {
                "name": mt_doc.name,
                "membership_type_name": mt_doc.membership_type_name,
                "description": mt_doc.description,
                "amount": amount,  # Use template-based amount or minimum_amount
                "billing_frequency": template_values.get("billing_frequency", "Annual"),
                "contribution_options": mt_doc.get_contribution_options()
                if hasattr(mt_doc, "get_contribution_options")
                else {},
            },
        }
    except frappe.DoesNotExistError:
        return {"error": f"Membership type '{membership_type_name}' not found"}
    except Exception as e:
        frappe.log_error(f"Error getting membership type details: {str(e)}")
        return {"error": "An error occurred while retrieving membership type details"}


@frappe.whitelist()
def validate_contribution_amount(
    membership_type_name, amount, contribution_mode=None, selected_tier=None, base_multiplier=None
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
def calculate_suggested_contribution(membership_type_name, monthly_income, payment_interval="monthly"):
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
