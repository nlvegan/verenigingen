"""
Volunteer Expense System Setup Utilities

This module contains setup and configuration functions for the volunteer expense system.
These were moved from the main expense page template to maintain proper separation of concerns.
"""

import frappe
from frappe import _
from frappe.utils import flt

from verenigingen.utils.secure_operations import secure_document_operation


def setup_expense_claim_types():
    """
    Set up expense claim types with proper account mappings.
    Moved from expense page template for better code organization.
    """
    print("   Setting up expense claim types with account mappings...")
    expense_type_name = "Volunteer Expenses"

    # Check if the expense type already exists
    if frappe.db.exists("Expense Claim Type", expense_type_name):
        print(f"   ✅ Expense type '{expense_type_name}' already exists")
        return expense_type_name

    try:
        # Create the expense claim type
        expense_claim_type = frappe.new_doc("Expense Claim Type")
        expense_claim_type.name = expense_type_name

        # Get default company
        default_company = frappe.db.get_single_value("Global Defaults", "default_company")

        # Try to find suitable expense account
        expense_account = frappe.db.get_value(
            "Account", {"company": default_company, "account_name": ["like", "%Volunteer%"]}, "name"
        )

        if not expense_account:
            expense_account = frappe.db.get_value(
                "Account", {"company": default_company, "root_type": "Expense", "is_group": 0}, "name"
            )

        if expense_account:
            # Add account configuration
            expense_claim_type.append(
                "accounts", {"company": default_company, "default_account": expense_account}
            )

            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            setup_result = secure_document_operation(
                operation="save",
                doc=expense_claim_type,
                justification=f"Configure expense type '{expense_type_name}' with account '{expense_account}' for volunteer expense processing",
                required_permissions=["Expense Claim Type:write"],
            )

            if not setup_result.success:
                frappe.logger().error(
                    f"Failed to configure expense claim type: {'; '.join(setup_result.errors)}"
                )
                raise frappe.ValidationError(
                    f"Expense type configuration failed: {setup_result.errors[0] if setup_result.errors else 'Unknown error'}"
                )

            print(f"   ✅ Configured expense type '{expense_type_name}' with account '{expense_account}'")
        else:
            # Fallback: Create the basic expense claim type without accounts
            basic_result = secure_document_operation(
                operation="save",
                doc=expense_claim_type,
                justification=f"Create basic expense type '{expense_type_name}' for volunteer expenses (no account configuration available)",
                required_permissions=["Expense Claim Type:write"],
            )

            if not basic_result.success:
                frappe.logger().error(
                    f"Failed to create basic expense claim type: {'; '.join(basic_result.errors)}"
                )
                raise frappe.ValidationError(
                    f"Basic expense type creation failed: {basic_result.errors[0] if basic_result.errors else 'Unknown error'}"
                )

            print(
                f"   ⚠️ Created basic expense type '{expense_type_name}' - accounts configuration not available"
            )

        return expense_type_name

    except Exception as e:
        frappe.logger().error("Error setting up expense claim types: %s", str(e))
        import traceback

        traceback.print_exc()
        return "Travel"  # Fallback to standard type


def create_default_cost_center(company):
    """
    Create default cost center for volunteer expenses if none exists.
    Moved from expense page template for better code organization.
    """
    try:
        cost_center_name = f"Volunteer Expenses - {company}"

        if frappe.db.exists("Cost Center", cost_center_name):
            return cost_center_name

        # Find parent cost center
        parent_cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 1}, "name")

        if not parent_cost_center:
            parent_cost_center = company  # Use company as parent

        cost_center_doc = frappe.get_doc(
            {
                "doctype": "Cost Center",
                "cost_center_name": "Volunteer Expenses",
                "parent_cost_center": parent_cost_center,
                "company": company,
                "is_group": 0,
            }
        )

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        center_result = secure_document_operation(
            operation="insert",
            doc=cost_center_doc,
            justification=f"Create default cost center for volunteer expenses in company {company}",
            required_permissions=["Cost Center:create"],
        )

        if not center_result.success:
            frappe.logger().error("Failed to create default cost center: %s", "; ".join(center_result.errors))
            return get_fallback_cost_center()

        frappe.logger().info("Created default cost center: %s", cost_center_name)
        return cost_center_name

    except Exception as e:
        frappe.log_error(
            message=f"Error creating default cost center: {str(e)}", title="Cost Center Creation Error"
        )
        return get_fallback_cost_center()


def get_organization_cost_center(company=None):
    """Get organization's main cost center for volunteer expenses"""
    if not company:
        company = frappe.db.get_single_value("Global Defaults", "default_company")

    # Try to find existing volunteer expense cost center
    cost_center_name = f"Volunteer Expenses - {company}"
    if frappe.db.exists("Cost Center", cost_center_name):
        return cost_center_name

    # If not found, create it
    return create_default_cost_center(company)


def get_fallback_cost_center():
    """Get any available cost center as fallback"""
    try:
        # Try to find any cost center
        cost_center = frappe.db.get_value("Cost Center", {"is_group": 0}, "name")
        if cost_center:
            return cost_center

        # Create minimal cost center if none exists
        company = frappe.db.get_single_value("Global Defaults", "default_company")
        if company:
            return f"Main - {company}"

    except Exception:
        pass

    return "Main"  # Ultimate fallback


def get_or_create_expense_type(category):
    """
    Get expense account from Expense Category.

    This function returns the category name for use as expense_type in Expense Claim.
    The actual expense account is retrieved separately from the Expense Category DocType.

    Note: Despite the name, this function no longer creates Expense Claim Types.
    It validates that the Expense Category exists and is properly configured.
    """
    try:
        # Check if our custom Expense Category exists
        if not frappe.db.exists("Expense Category", category):
            frappe.throw(
                frappe._(
                    "Expense Category '{0}' not found. Please contact your administrator to configure this category."
                ).format(category)
            )

        # Validate that the category has an expense account configured
        expense_account = frappe.db.get_value("Expense Category", category, "expense_account")
        if not expense_account:
            frappe.throw(
                frappe._(
                    "Expense Category '{0}' does not have an expense account configured. Please contact your administrator."
                ).format(category)
            )

        # Return the category name to be used as expense_type
        # The expense account will be set separately from the Expense Category
        return category

    except frappe.ValidationError:
        # The validations above raise specific, user-facing ValidationErrors
        # (category not found / no expense account). Re-raise them unchanged so
        # the caller sees the real reason instead of a generic message.
        raise
    except Exception as e:
        frappe.log_error(
            f"Error validating expense category {category}: {str(e)}", "Expense Category Validation"
        )
        frappe.throw(
            frappe._("Unable to process expense category '{0}'. Please contact your administrator.").format(
                category
            )
        )
