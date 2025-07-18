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


def get_membership_types_with_contributions():
    """Get all active membership types with their contribution options"""
    membership_types = frappe.get_all(
        "Membership Type",
        filters={"is_active": 1},
        fields=[
            "name",
            "membership_type_name",
            "description",
            "amount",
            "subscription_period",
            "contribution_mode",
            "minimum_contribution",
            "suggested_contribution",
            "maximum_contribution",
            "fee_slider_max_multiplier",
            "enable_income_calculator",
            "income_percentage_rate",
            "calculator_description",
            "allow_custom_amounts",
            "custom_amount_requires_approval",
        ],
        order_by="membership_type_name",
    )

    enhanced_types = []
    for mt in membership_types:
        # Get the membership type document to access contribution options
        mt_doc = frappe.get_doc("Membership Type", mt.name)

        # Get contribution options
        try:
            contribution_options = mt_doc.get_contribution_options()
        except:
            # Fallback for membership types without new fields
            contribution_options = {
                "mode": "Calculator",
                "minimum": mt.amount * 0.5 if mt.amount else 5.0,
                "suggested": mt.amount or 15.0,
                "maximum": (mt.amount or 15.0) * 10,
                "calculator": {
                    "enabled": True,
                    "percentage": 0.5,
                    "description": "Standard contribution calculation",
                },
                "quick_amounts": [],
            }

        enhanced_mt = {
            "name": mt.name,
            "membership_type_name": mt.membership_type_name,
            "description": mt.description,
            "amount": mt.amount,
            "subscription_period": mt.subscription_period,
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
        return {
            "success": True,
            "membership_type": {
                "name": mt_doc.name,
                "membership_type_name": mt_doc.membership_type_name,
                "description": mt_doc.description,
                "amount": mt_doc.amount,
                "subscription_period": mt_doc.subscription_period,
                "contribution_options": mt_doc.get_contribution_options(),
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

        # Get minimum and maximum constraints
        min_amount = mt_doc.minimum_contribution or (mt_doc.amount * 0.3 if mt_doc.amount else 5.0)
        max_amount = mt_doc.maximum_contribution or (
            mt_doc.suggested_contribution or mt_doc.amount or 15.0
        ) * (mt_doc.fee_slider_max_multiplier or 10.0)

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
            amount != mt_doc.suggested_contribution and mt_doc.custom_amount_requires_approval
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

        # Ensure minimum amount
        min_amount = mt_doc.minimum_contribution or 5.0
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
