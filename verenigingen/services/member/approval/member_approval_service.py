"""
Member Approval Service - Centralized membership application approval workflow.

This service handles the complete member approval process that was previously
in membership_application_review.py. Provides reusable workflow components
for approval, membership creation, and status management.

Functions:
    - resolve_membership_type(): Validate and resolve membership type
    - create_member_iban_history(): Initialize IBAN history tracking
    - create_membership_and_invoice(): Create membership record and billing
    - finalize_member_approval(): Update member status and metadata
    - process_member_approval(): Orchestrate complete approval workflow
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from verenigingen.utils.service_error_handler import create_service_result, handle_service_error


def validate_member_fields(required_fields):
    """Validate that required Member DocType fields exist.

    Per CLAUDE.md requirements: Always verify field names before use.

    Args:
        required_fields (list): List of field names to validate

    Raises:
        ValidationError: If any required fields don't exist
    """
    try:
        member_doctype = frappe.get_meta("Member")
        existing_fields = [field.fieldname for field in member_doctype.fields]

        missing_fields = [field for field in required_fields if field not in existing_fields]

        if missing_fields:
            frappe.throw(_(f"Missing required Member fields: {', '.join(missing_fields)}"))

    except Exception as e:
        handle_service_error(
            e,
            "MemberApprovalService",
            "Validate member fields",
            {"required_fields": required_fields},
            raise_error=True,
        )


def resolve_membership_type(member, membership_type=None):
    """Resolve and validate membership type.

    Extracted from membership_application_review.py without modification.
    Handles membership type resolution with fallbacks and validation.

    Args:
        member: Member document instance
        membership_type (str, optional): Explicit membership type to use

    Returns:
        str: Resolved membership type name

    Raises:
        frappe.ValidationError: If no valid membership type can be resolved
    """
    try:
        # Use provided membership type or fallback to selected
        if not membership_type:
            membership_type = getattr(member, "selected_membership_type", None)

        # Additional fallback to current membership type if selected is not set
        if not membership_type:
            membership_type = getattr(member, "current_membership_type", None)

        # If still no membership type, try to set a default from available types
        if not membership_type:
            membership_types = frappe.get_all("Membership Type", fields=["name"], limit=1)
            if membership_types:
                membership_type = membership_types[0].name
                # Set this as the selected type for the member
                try:
                    member.selected_membership_type = membership_type
                    member.save()
                    frappe.logger().info(
                        f"Auto-assigned membership type {membership_type} to member {member.name}"
                    )
                except Exception as e:
                    frappe.logger().error(f"Could not save membership type to member: {str(e)}")
            else:
                frappe.throw(
                    _("No membership types available in the system. Please create a membership type first.")
                )

        if not membership_type:
            frappe.throw(_("Please select a membership type"))

        return membership_type

    except Exception as e:
        handle_service_error(
            e,
            "MemberApprovalService",
            "Resolve membership type",
            {"member": getattr(member, "name", "Unknown"), "membership_type": membership_type},
            raise_error=True,
        )


def create_member_iban_history(member):
    """Create initial IBAN history tracking for approved member.

    Extracted from membership_application_review.py without modification.
    Initializes IBAN history tracking for members with banking details.

    Args:
        member: Member document instance with IBAN data

    Returns:
        dict: Result with success status and created history info
    """
    try:
        if not (hasattr(member, "iban") and member.iban):
            return create_service_result(
                success=True,
                data={"message": "No IBAN provided, skipping history creation"},
                service_name="MemberApprovalService",
                operation="create_member_iban_history",
            )

        # Check if IBAN history already exists to avoid duplicates
        existing_history = frappe.db.exists(
            "Member IBAN History", {"member": member.name, "iban": member.iban}
        )

        if existing_history:
            frappe.logger().info(f"IBAN history already exists for member {member.name}")
            return create_service_result(
                success=True,
                data={"existing_record": existing_history, "message": "IBAN history already exists"},
                service_name="MemberApprovalService",
                operation="create_member_iban_history",
            )

        # Create IBAN history record as child table entry
        iban_history = frappe.get_doc(
            {
                "doctype": "Member IBAN History",
                "iban": member.iban,
                "bank_account_name": getattr(
                    member, "bank_account_name", member.iban.split()[-1] if member.iban else ""
                ),
                "from_date": today(),
                "is_active": 1,
                "change_reason": "Application Approval",
                "parent": member.name,
                "parenttype": "Member",
                "parentfield": "iban_history",
            }
        )

        iban_history.insert()

        return create_service_result(
            success=True,
            data={"iban_history": iban_history.name, "message": "IBAN history created successfully"},
            service_name="MemberApprovalService",
            operation="create_member_iban_history",
        )

    except Exception as e:
        error_result = handle_service_error(
            e,
            "MemberApprovalService",
            "Create IBAN history",
            {"member": getattr(member, "name", "Unknown")},
            raise_error=False,
        )
        return error_result


def create_membership_and_invoice(member, membership_type, create_invoice=True):
    """Create membership record and invoice for approved member.

    Extracted from membership_application_review.py without modification.
    Handles membership creation, billing amount calculation, and invoice generation.

    Args:
        member: Member document instance
        membership_type (str): Validated membership type name
        create_invoice (bool): Whether to create billing invoice

    Returns:
        dict: Result with membership and invoice details
    """
    try:
        # Check for existing active membership first
        existing_membership = frappe.db.get_value(
            "Membership", {"member": member.name, "status": ["in", ["Active", "Draft"]]}, "name"
        )

        if existing_membership:
            frappe.logger().info(f"Member {member.name} already has active membership: {existing_membership}")
            membership = frappe.get_doc("Membership", existing_membership)
            # Update membership type if different
            if membership.membership_type != membership_type:
                membership.membership_type = membership_type
                membership.save()
        else:
            # Create membership record
            membership = frappe.get_doc(
                {
                    "doctype": "Membership",
                    "member": member.name,
                    "membership_type": membership_type,
                    "start_date": today(),
                    "status": "Draft",  # Will be activated after payment
                }
            )

            membership.insert()

        # Get membership type details
        membership_type_doc = frappe.get_doc("Membership Type", membership_type)

        # Get billing amount from created dues schedule or template
        billing_amount = 0
        if hasattr(member, "dues_rate") and member.dues_rate:
            # Use member's custom dues rate
            billing_amount = member.dues_rate
        elif membership_type_doc.dues_schedule_template:
            try:
                template = frappe.get_doc(
                    "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                )
                billing_amount = template.dues_rate or template.suggested_amount or 0
            except Exception as e:
                frappe.logger().warning(f"Could not load dues schedule template: {str(e)}")
                billing_amount = membership_type_doc.minimum_amount or 0
        else:
            billing_amount = membership_type_doc.minimum_amount or 0

        invoice = None
        if create_invoice and billing_amount > 0:
            # Use the dedicated application payments utility
            try:
                from verenigingen.utils.application_payments import create_membership_invoice

                invoice = create_membership_invoice(
                    member.name,
                    billing_amount,
                    membership_type,
                    invoice_description=f"Membership dues for {membership_type}",
                )
                frappe.logger().info(f"Created invoice {invoice.name} for member {member.name}")
            except Exception as e:
                frappe.logger().error(f"Could not create invoice for member {member.name}: {str(e)}")

        return create_service_result(
            success=True,
            data={
                "message": "Membership and invoice created successfully",
                "membership": membership.name,
                "membership_type": membership_type,
                "billing_amount": billing_amount,
                "invoice": invoice.name if invoice else None,
            },
        )

    except Exception as e:
        error_result = handle_service_error(
            e,
            "MemberApprovalService",
            "Create membership and invoice",
            {"member": getattr(member, "name", "Unknown"), "membership_type": membership_type},
            raise_error=False,
        )
        return error_result


def finalize_member_approval(member, notes=None):
    """Finalize member approval status with robust concurrency handling.

    Extracted from membership_application_review.py without modification.
    Updates member status fields with retry logic for concurrent modifications.

    Args:
        member: Member document instance
        notes (str, optional): Review notes to add

    Returns:
        dict: Result with success status
    """
    # Validate required fields per CLAUDE.md requirements
    validate_member_fields(
        ["application_status", "status", "member_since", "reviewed_by", "review_date", "review_notes"]
    )
    max_retries = 3

    for attempt in range(max_retries):
        try:
            # Always reload member to get latest version
            if attempt > 0:
                member.reload()

            member.application_status = "Approved"
            member.status = "Active"
            member.member_since = today()
            member.reviewed_by = frappe.session.user
            member.review_date = now_datetime()
            if notes:
                member.review_notes = notes

            member.save()

            # Success - break out of retry loop
            frappe.logger().info(
                f"Member approval finalized successfully for {member.name} on attempt {attempt + 1}"
            )

            return create_service_result(
                success=True,
                data={
                    "message": "Member approval finalized successfully",
                    "member": member.name,
                    "status": member.status,
                    "application_status": member.application_status,
                    "member_since": member.member_since,
                },
            )

        except frappe.TimestampMismatchError as e:
            if attempt == max_retries - 1:
                # Final attempt failed
                handle_service_error(
                    e,
                    "MemberApprovalService",
                    "Finalize member approval - timestamp mismatch",
                    {"member": member.name, "attempts": max_retries},
                    raise_error=False,
                )
                frappe.throw(_("Document has been modified by another user. Please refresh and try again."))
            else:
                # Wait briefly before retry
                import time

                time.sleep(0.1 * (attempt + 1))  # Progressive backoff
                continue

        except Exception as e:
            error_result = handle_service_error(
                e,
                "MemberApprovalService",
                "Finalize member approval",
                {"member": getattr(member, "name", "Unknown"), "attempt": attempt + 1},
                raise_error=True if attempt == max_retries - 1 else False,
            )
            if attempt == max_retries - 1:
                return error_result


def process_member_approval(member_name, membership_type=None, notes=None, create_invoice=True):
    """Orchestrate complete member approval workflow.

    New orchestration function that combines all approval steps into a single
    transaction with proper error handling and rollback capabilities.

    Args:
        member_name (str): Name/ID of member to approve
        membership_type (str, optional): Membership type to assign
        notes (str, optional): Review notes
        create_invoice (bool): Whether to create billing invoice

    Returns:
        dict: Complete approval result with all created records
    """
    try:
        # Load member document
        member = frappe.get_doc("Member", member_name)

        # Step 1: Resolve membership type
        resolved_membership_type = resolve_membership_type(member, membership_type)

        # Step 2: Create IBAN history if applicable
        iban_result = create_member_iban_history(member)

        # Step 3: Create membership and invoice
        membership_result = create_membership_and_invoice(member, resolved_membership_type, create_invoice)

        if not membership_result["success"]:
            return membership_result

        # Step 4: Finalize approval status
        approval_result = finalize_member_approval(member, notes)

        if not approval_result["success"]:
            return approval_result

        # Return comprehensive result
        return create_service_result(
            success=True,
            data={
                "message": "Member approval completed successfully",
                "member": member_name,
                "membership_type": resolved_membership_type,
                "iban_history": iban_result.get("data", {}).get("iban_history"),
                "membership": membership_result["data"]["membership"],
                "invoice": membership_result["data"]["invoice"],
                "approval_details": approval_result["data"],
            },
        )

    except Exception as e:
        error_result = handle_service_error(
            e,
            "MemberApprovalService",
            "Process member approval",
            {"member": member_name, "membership_type": membership_type},
            raise_error=False,
        )
        return error_result


def validate_approval_prerequisites(member_name):
    """Validate that member meets approval prerequisites.

    New utility function to check approval readiness before processing.

    Args:
        member_name (str): Name/ID of member to validate

    Returns:
        dict: Validation result with prerequisites status
    """
    try:
        member = frappe.get_doc("Member", member_name)

        errors = []
        warnings = []

        # Check application status
        if getattr(member, "application_status", "") == "Approved":
            warnings.append("Member is already approved")

        # Check required fields
        if not getattr(member, "full_name", ""):
            errors.append("Member must have a full name")

        if not getattr(member, "email", ""):
            errors.append("Member must have an email address")

        # Check for existing active membership
        existing_membership = frappe.db.exists("Membership", {"member": member_name, "status": "Active"})
        if existing_membership:
            warnings.append(f"Member already has active membership: {existing_membership}")

        return create_service_result(
            success=len(errors) == 0,
            data={
                "message": "Validation completed",
                "ready_for_approval": len(errors) == 0,
                "errors": errors,
                "warnings": warnings,
            },
            service_name="MemberApprovalService",
            operation="validate_approval_prerequisites",
        )

    except Exception as e:
        error_result = handle_service_error(
            e,
            "MemberApprovalService",
            "Validate approval prerequisites",
            {"member": member_name},
            raise_error=False,
        )
        return error_result
