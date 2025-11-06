"""
Customer Service - Centralized customer creation and management.

This service handles ERPNext Customer creation for members with proper
validation, duplicate checking, and secure operations. Extracted from
member.py for better separation of concerns.

Functions:
    - create_customer_for_member(): Create ERPNext Customer record for member
    - check_similar_customers(): Find existing customers with similar names
    - validate_customer_creation(): Pre-creation validation
"""

import frappe
from frappe import _

from verenigingen.utils.service_error_handler import handle_service_error, validate_required_fields

# Safe import of security framework with fallback
try:
    from verenigingen.utils.security.api_security_framework import OperationType, standard_api
except ImportError:
    # Fallback for environments where security framework is not available
    class OperationType:
        MEMBER_DATA = "member_data"

    def standard_api(operation_type=None):
        """Fallback decorator when security framework is not available"""

        def decorator(func):
            return func

        return decorator


@standard_api(operation_type=OperationType.MEMBER_DATA)
def create_customer_for_member(member_doc, suppress_messages=False):
    """Create a customer for this member in ERPNext.

    Extracted from member.py without modification. Handles duplicate detection,
    secure operations, and proper ERPNext Customer record creation.

    Args:
        member_doc: Member document instance
        suppress_messages (bool): Whether to suppress user messages

    Returns:
        str: Customer name (ID) of created customer

    Raises:
        frappe.ValidationError: If customer creation fails
    """
    # Check if customer already exists
    if member_doc.customer:
        # Only show existing customer message if not during application submission
        if not suppress_messages:
            frappe.msgprint(_("Customer {0} already exists for this member").format(member_doc.customer))
        return member_doc.customer

    # Check if customer already exists for this member (database constraint check)
    existing_customer = frappe.db.get_value("Customer", {"member": member_doc.name}, "name")
    if existing_customer:
        frappe.logger().info(f"Customer {existing_customer} already exists for Member {member_doc.name}")
        # Update member record to reflect the existing customer link
        member_doc.db_set("customer", existing_customer, update_modified=False)
        return existing_customer

    # Check for similar customers and warn user
    if member_doc.full_name:
        similar_name_customers = frappe.get_all(
            "Customer",
            filters=[["customer_name", "like", f"%{member_doc.full_name}%"]],
            fields=["name", "customer_name", "email_id", "mobile_no"],
        )

        exact_name_match = next(
            (c for c in similar_name_customers if c.customer_name.lower() == member_doc.full_name.lower()),
            None,
        )
        if exact_name_match and not suppress_messages:
            customer_info = f"Name: {exact_name_match.name}, Email: {exact_name_match.email_id or 'N/A'}"
            frappe.msgprint(
                _("Found existing customer with same name: {0}").format(customer_info)
                + _(
                    "\nCreating a new customer for this member. If you want to link to the existing customer instead, please do so manually."
                )
            )

        elif similar_name_customers and not suppress_messages:
            customer_list = "\n".join([f"- {c.customer_name} ({c.name})" for c in similar_name_customers[:5]])
            frappe.msgprint(
                _("Found similar customer names. Please review:")
                + f"\n{customer_list}"
                + (
                    _("\n(Showing first 5 of {0} matches)").format(len(similar_name_customers))
                    if len(similar_name_customers) > 5
                    else ""
                )
                + _("\nCreating a new customer for this member.")
            )

    # Create new customer document
    customer = frappe.new_doc("Customer")
    customer.customer_name = member_doc.full_name
    customer.customer_type = "Individual"
    customer.member = member_doc.name  # Link customer back to member

    if member_doc.email:
        customer.email_id = member_doc.email
    if hasattr(member_doc, "contact_number") and member_doc.contact_number:
        customer.mobile_no = member_doc.contact_number
        customer.phone = member_doc.contact_number

    customer.flags.ignore_mandatory = True

    # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
    from verenigingen.utils.secure_operations import secure_document_operation

    # Suppress messages during customer creation if requested
    if suppress_messages:
        customer.flags.ignore_messages = True

        # Secure customer creation with explicit permission validation
        customer_result = secure_document_operation(
            operation="insert",
            doc=customer,
            justification=f"Automated customer creation for member {member_doc.name} during application submission",
            required_permissions=["Customer:create"],
        )

        if not customer_result.success:
            frappe.throw(_("Failed to create customer: {0}").format("; ".join(customer_result.errors)))
    else:
        # Secure customer creation with explicit permission validation
        customer_result = secure_document_operation(
            operation="insert",
            doc=customer,
            justification=f"Automated customer creation for member {member_doc.name}",
            required_permissions=["Customer:create"],
        )

        if not customer_result.success:
            frappe.throw(_("Failed to create customer: {0}").format("; ".join(customer_result.errors)))

    return customer.name


def check_similar_customers(full_name, limit=10):
    """Check for existing customers with similar names.

    Args:
        full_name (str): Full name to search for
        limit (int): Maximum number of results to return

    Returns:
        list: List of similar customer records
    """
    if not full_name:
        return []

    return frappe.get_all(
        "Customer",
        filters=[["customer_name", "like", f"%{full_name}%"]],
        fields=["name", "customer_name", "email_id", "mobile_no"],
        limit=limit,
    )


def find_exact_customer_match(full_name):
    """Find customer with exact name match (case-insensitive).

    Args:
        full_name (str): Full name to match exactly

    Returns:
        dict or None: Customer record if found, None otherwise
    """
    if not full_name:
        return None

    similar_customers = check_similar_customers(full_name)
    return next((c for c in similar_customers if c.customer_name.lower() == full_name.lower()), None)


def validate_customer_creation_requirements(member_doc):
    """Validate that member has required fields for customer creation.

    Args:
        member_doc: Member document instance

    Returns:
        dict: Validation result with valid/errors fields
    """
    errors = []

    if not getattr(member_doc, "full_name", None):
        errors.append("Member must have a full name to create customer")

    if not getattr(member_doc, "name", None):
        errors.append("Member must be saved before creating customer")

    return {"valid": len(errors) == 0, "errors": errors}


def update_member_customer_reference(member_doc, customer_name):
    """Update member document with customer reference.

    Args:
        member_doc: Member document instance
        customer_name (str): Customer name/ID to link

    Returns:
        bool: True if update successful
    """
    try:
        member_doc.customer = customer_name
        return True
    except Exception as e:
        handle_service_error(
            e,
            "CustomerService",
            "Update member customer reference",
            {"member": getattr(member_doc, "name", "Unknown"), "customer_name": customer_name},
            raise_error=False,
        )
        return False
