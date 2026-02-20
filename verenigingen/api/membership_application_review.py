"""
API endpoints for reviewing and managing membership applications
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, today

from verenigingen.services.communication.email_service import get_email_service
from verenigingen.services.member.account.member_user_account_service import (
    create_secure_user_account_for_member,
)
from verenigingen.services.member.approval.member_approval_service import (
    create_member_iban_history,
    resolve_membership_type,
    validate_membership_type_for_approval,
)
from verenigingen.services.volunteer.volunteer_activation_service import activate_volunteer_record
from verenigingen.utils.constants import Roles
from verenigingen.utils.member_utils import get_volunteer_for_member
from verenigingen.utils.safe_error_logging import safe_log_error
from verenigingen.utils.security.api_security_framework import high_security_api, standard_api
from verenigingen.utils.security.audit_logging import log_security_event
from verenigingen.utils.validation.api_validators import APIValidator


def _validate_member_for_review(member_name, operation_label):
    """Validate member exists for review operations (approve/reject).

    Sanitizes the member_name input, checks existence, and logs security events.

    Args:
        member_name: Raw member name from API call
        operation_label: Label for security logs (e.g. "approval", "rejection")

    Returns:
        Sanitized member_name string.

    Raises:
        frappe.ValidationError: On invalid member or sanitization failure.
    """
    try:
        member_name = APIValidator.sanitize_text(str(member_name), max_length=255)

        if not frappe.db.exists("Member", member_name):
            log_security_event(
                "invalid_member_access",
                {"message": f"Attempted {operation_label} of non-existent member: {member_name}"},
                severity="error",
            )
            frappe.throw(_("Invalid member reference"))

        return member_name

    except frappe.ValidationError:
        raise
    except Exception as e:
        log_security_event(
            "input_validation_failure",
            {"message": f"Input validation failed for {operation_label}: {str(e)}"},
            severity="warning",
        )
        frappe.throw(_("Invalid input data provided"))


def _sanitize_text_fields(text_fields):
    """Sanitize text input fields for API endpoints.

    Args:
        text_fields: Dict of {field_name: (value, max_length, allow_html)} to sanitize.
            If allow_html is omitted, defaults to True.

    Returns:
        Dict of {field_name: sanitized_value}.
    """
    sanitized = {}
    if not text_fields:
        return sanitized

    for field_name, spec in text_fields.items():
        value, max_length = spec[0], spec[1]
        allow_html = spec[2] if len(spec) > 2 else True
        if value:
            sanitized[field_name] = APIValidator.sanitize_text(
                str(value), max_length=max_length, allow_html=allow_html
            )
        else:
            sanitized[field_name] = value

    return sanitized


def assign_member_to_chapter(member, chapter, notify=None):
    """
    Assign member to chapter using centralized ChapterMembershipManager.

    This ensures proper history tracking and avoids race conditions.

    Args:
        member: Member document
        chapter: Chapter name
        notify: Override for notification sending (None = use global setting)
    """
    if not chapter:
        return

    try:
        from verenigingen.utils.chapter_membership_manager import ChapterMembershipManager

        result = ChapterMembershipManager.assign_member_to_chapter(
            member_id=member.name,
            chapter_name=chapter,
            reason="Membership application approval",
            assigned_by=frappe.session.user,
            notify=notify,  # Pass through notification override
        )

        if result.get("success"):
            frappe.logger().info(f"Assigned member {member.name} to chapter {chapter}")
        else:
            frappe.logger().warning(
                f"Chapter assignment returned non-success: {result.get('error', 'Unknown error')}"
            )

    except Exception as e:
        # Non-critical error - log but don't fail the approval
        frappe.logger().warning(f"Could not assign member to chapter: {str(e)}")


def _handle_idempotent_approval(member_name):
    """Check if member is already approved and return existing data if so.

    Returns dict with existing membership/invoice data if already approved, None otherwise.
    """
    member_status = frappe.db.get_value("Member", member_name, ["application_status", "status"], as_dict=True)
    if member_status and member_status.application_status == "Approved":
        frappe.logger().info(
            f"Member {member_name} already approved (application_status=Approved), returning existing approval"
        )
        existing_membership = frappe.db.get_value(
            "Membership", {"member": member_name, "status": "Active", "docstatus": 1}, "name"
        )
        existing_invoice = frappe.db.get_value(
            "Sales Invoice",
            {"customer": frappe.db.get_value("Member", member_name, "customer"), "docstatus": 1},
            "name",
            order_by="creation desc",
        )
        return {
            "success": True,
            "message": _("Member application already approved"),
            "membership": existing_membership,
            "invoice": existing_invoice,
            "idempotent": True,
        }
    return None


def _prepare_approval_fields(member, membership_type, notes):
    """Build approval fields dict for create_membership_on_approval().

    Includes conditional review_notes and fee_override_reason.
    """
    approval_fields = {
        "application_status": "Approved",
        "status": "Active",
        "member_since": today(),
        "reviewed_by": frappe.session.user,
        "review_date": now_datetime(),
        "selected_membership_type": membership_type,
    }
    if notes:
        approval_fields["review_notes"] = notes

    # If member has custom dues rate, set fee_override_reason to satisfy validation
    if hasattr(member, "dues_rate") and member.dues_rate:
        if not hasattr(member, "fee_override_reason") or not member.fee_override_reason:
            approval_fields["fee_override_reason"] = "Application approval"

    return approval_fields


def _calculate_billing_amount(member, invoice, membership_type_doc):
    """Calculate billing amount with 3-way fallback: invoice -> member rate -> membership type minimum."""
    billing_amount = 0
    if invoice and hasattr(invoice, "grand_total"):
        billing_amount = invoice.grand_total
    elif hasattr(member, "dues_rate") and member.dues_rate:
        billing_amount = member.dues_rate
    else:
        billing_amount = membership_type_doc.minimum_amount

    frappe.logger().info(
        f"Billing amount for approval response: {billing_amount} "
        f"(source: {'invoice' if invoice and hasattr(invoice, 'grand_total') else 'member_rate' if hasattr(member, 'dues_rate') and member.dues_rate else 'membership_type'})"
    )
    return billing_amount


def _activate_volunteer_if_requested(member, activate_as_volunteer):
    """Handle volunteer activation based on interest flag and activation checkbox.

    4-way branch: interest+activate, interest-only, activate-only, neither.
    Returns should_activate_volunteer flag for role profile selection.
    """
    should_activate_volunteer = False
    has_volunteer_interest = (
        hasattr(member, "interested_in_volunteering") and member.interested_in_volunteering
    )

    if has_volunteer_interest and activate_as_volunteer:
        # Full activation: checkbox was checked for member with volunteer interest
        # Validate age requirement (volunteers must be 16+)
        if member.birth_date:
            from verenigingen.utils.validation_utilities import AgeValidator

            age_result = AgeValidator.validate_age(
                member.birth_date, context="volunteer", throw_on_error=False
            )
            if not age_result.get("valid"):
                frappe.throw(
                    _("Cannot activate as volunteer: {0}").format(
                        age_result.get("message", "Age requirement not met")
                    )
                )

        try:
            activate_volunteer_record(member)
            should_activate_volunteer = True
            frappe.logger().info(
                f"Activated volunteer record for {member.name} during approval (full activation)"
            )
        except Exception as e:
            safe_log_error(
                "Volunteer activation failed",
                f"Failed to activate volunteer record for {member.name}: {str(e)}",
            )
            # Continue with approval - this is not critical
    elif has_volunteer_interest:
        # Interest-only: volunteer record exists but no full activation requested
        frappe.logger().info(
            f"Volunteer interest registered for {member.name} - full activation deferred (checkbox not checked)"
        )
    elif activate_as_volunteer:
        # Edge case: explicit activation requested but no volunteer interest flag
        frappe.logger().warning(
            f"Cannot activate as volunteer for {member.name} - no interested_in_volunteering flag set"
        )

    return should_activate_volunteer


def _create_user_account_safe(member, should_activate_volunteer):
    """Create user account with error handling. Non-critical - approval continues on failure."""
    user_creation_result = {"success": False, "error": "Not attempted"}
    try:
        user_creation_result = create_secure_user_account_for_member(
            member, activate_as_volunteer=should_activate_volunteer
        )
    except Exception as e:
        safe_log_error(
            "User account creation failed", f"User account creation failed for {member.name}: {str(e)}"
        )
        user_creation_result = {"success": False, "error": "Account creation failed"}
        # Continue with approval - user accounts can be created manually later

    # AccountCreationManager handles all user document management
    # including role assignment, refreshing, and linking - no manual intervention needed
    if user_creation_result.get("action") == "queued_secure":
        frappe.logger().info(
            f"User account creation queued for member {member.name} - AccountCreationManager will handle all user setup"
        )
    elif user_creation_result.get("success"):
        frappe.logger().info(
            f"User account {'linked' if user_creation_result.get('action') == 'linked_existing' else 'processed'} for member {member.name}"
        )

    return user_creation_result


def _send_approval_email_safe(member, invoice, membership_type_doc):
    """Send approval email with nested error handling. Fire-and-forget."""
    try:
        email_result = send_approval_notification(member, invoice, membership_type_doc)
        if not email_result or not email_result.success:
            frappe.log_error(
                f"Approval email failed for {member.name} ({member.email}): {'; '.join(email_result.errors or []) if email_result else 'No result returned'}",
                "Approval Email Failed",
            )
            frappe.msgprint(
                _(
                    "⚠️ Approval successful, but email notification failed. Please check error logs or send the approval email manually."
                ),
                title=_("Email Warning"),
                indicator="orange",
            )
    except Exception as e:
        frappe.log_error(
            f"Exception sending approval email for {member.name} ({member.email}): {str(e)}\n{frappe.get_traceback()}",
            "Approval Email Exception",
        )
        frappe.msgprint(
            _(
                "⚠️ Approval successful, but email notification encountered an error. Please check error logs."
            ),
            title=_("Email Error"),
            indicator="orange",
        )
        # Continue with approval - emails can be sent manually


def _build_approval_response(member, invoice, billing_amount, user_creation_result):
    """Build approval response dict with 5-way user account status branching."""
    message = _("Application approved. Invoice sent to applicant.")
    user_account_status = "pending"

    if user_creation_result.get("success"):
        if user_creation_result.get("action") in ["created_new", "created_new_immediate"]:
            message += _(" User account created for portal access.")
            user_account_status = "created"
            if user_creation_result.get("action") == "created_new_immediate":
                # Show success message for immediate processing
                frappe.msgprint(
                    _("✅ User account created successfully! The member can now log in to the portal."),
                    title=_("Account Created"),
                    indicator="green",
                )
        elif user_creation_result.get("action") == "linked_existing":
            message += _(" Linked to existing user account.")
            user_account_status = "linked"
        elif user_creation_result.get("action") == "queued_secure":
            message += _(
                " User account creation queued for secure background processing"
                " - member will receive portal access within 2-3 minutes."
            )
            user_account_status = "queued"
            # Add specific timing expectations
            frappe.msgprint(
                _(
                    "User account creation is being processed securely in the background."
                    " The member will receive login credentials via email within 2-3 minutes."
                ),
                title=_("Account Creation in Progress"),
                indicator="blue",
            )
    else:
        message += _(" Note: Could not create user account - member will need manual account creation.")
        user_account_status = "failed"

    return {
        "success": True,
        "message": message,
        "invoice": invoice.name if invoice else None,
        "amount": billing_amount,
        "user_account": user_creation_result,
        "user_account_status": user_account_status,
        # Enhanced progress tracking for better UX
        "progress_tracking": {
            "account_request_id": user_creation_result.get("account_request"),
            "estimated_completion": "2-3 minutes" if user_account_status == "queued" else None,
            "tracking_url": (
                f"/app/account-creation-request/{user_creation_result.get('account_request')}"
                if user_creation_result.get("account_request")
                else None
            ),
        },
    }


@frappe.whitelist()
@high_security_api()  # Member application approval workflow
def approve_membership_application(
    member_name: str,
    membership_type: str = None,
    chapter: str = None,
    notes: str = None,
    create_invoice: bool = True,
    activate_as_volunteer: bool = False,
):
    """
    Approve a membership application with focused responsibilities

    This function is the canonical approval pathway and handles:
    - Idempotency: Safe to call multiple times for the same member
    - Input validation and security checks
    - Member status updates and chapter assignments
    - Membership record and invoice creation
    - Notification sending

    Delegated to AccountCreationManager:
    - User account creation
    - Role assignment and management
    - Employee record creation

    Args:
        member_name (str): Member document name
        membership_type (str, optional): Membership type to assign (auto-resolved if not provided)
        chapter (str, optional): Chapter to assign member to
        notes (str, optional): Review notes
        create_invoice (bool, optional): Whether to create initial invoice (default True)
        activate_as_volunteer (bool, optional): Whether to activate as volunteer and assign Volunteer role profile (default False)

    Returns:
        dict: Approval result with structure:
            {
                "success": bool,
                "message": str,
                "invoice": str (invoice name),
                "amount": float,
                "user_account": dict,
                "membership": str (membership name),
                "idempotent": bool (optional, True if member was already approved)
            }

    Idempotency:
        If the member is already approved (application_status == "Approved"), the function
        returns success with existing membership/invoice data and sets idempotent=True.
        This prevents duplicate memberships, invoices, or status changes.

    Internal approval_fields dict structure:
        {
            "application_status": "Approved",
            "status": "Active",
            "member_since": date,
            "reviewed_by": str (user),
            "review_date": datetime,
            "selected_membership_type": str (membership type),
            "review_notes": str (optional),
            "fee_override_reason": str (optional, auto-set if custom dues_rate)
        }

    This separation ensures proper security compliance and maintainable code.
    """
    # Input validation and sanitization
    member_name = _validate_member_for_review(member_name, "approval")
    sanitized = _sanitize_text_fields(
        {
            "membership_type": (membership_type, 255),
            "chapter": (chapter, 255),
            "notes": (notes, 2000, False),
        }
    )
    membership_type = sanitized["membership_type"]
    chapter = sanitized["chapter"]
    notes = sanitized["notes"]

    # Idempotency check - if already approved, return success
    idempotent_result = _handle_idempotent_approval(member_name)
    if idempotent_result:
        return idempotent_result

    member = frappe.get_doc("Member", member_name)

    # Validate application can be approved
    if member.application_status not in ["Pending"]:
        frappe.throw(_("This application cannot be approved in its current state"))

    # Check chapter-based permissions
    from verenigingen.utils.chapter_security import validate_chapter_permission_or_throw

    validate_chapter_permission_or_throw(member_name, "approve")

    # Resolve and validate membership type
    membership_type = resolve_membership_type(member, membership_type)
    validate_membership_type_for_approval(membership_type, member, is_application_approval=True)

    # Assign member to chapter
    assign_member_to_chapter(member, chapter)
    if chapter:
        member.reload()
        member.update_current_chapter_display()
        member.save()

    # Set the selected membership type in memory (will be saved during membership creation)
    try:
        member.selected_membership_type = membership_type
    except AttributeError:
        frappe.logger().warning(f"Could not set selected_membership_type field on member {member.name}")

    # Log volunteer record info for AccountCreationManager
    if hasattr(member, "interested_in_volunteering") and member.interested_in_volunteering:
        volunteer_record = get_volunteer_for_member(member.name)
        if volunteer_record:
            frappe.logger().info(
                f"Volunteer record {volunteer_record} exists - AccountCreationManager will handle employee creation"
            )

    create_member_iban_history(member)

    approval_fields = _prepare_approval_fields(member, membership_type, notes)
    membership = member.create_membership_on_approval(create_invoice=True, approval_fields=approval_fields)

    # Get invoice and membership type docs for downstream steps
    invoice = None
    if hasattr(member, "application_invoice") and member.application_invoice:
        invoice = frappe.get_doc("Sales Invoice", member.application_invoice)
    membership_type_doc = frappe.get_doc("Membership Type", membership.membership_type)

    billing_amount = _calculate_billing_amount(member, invoice, membership_type_doc)
    should_activate_volunteer = _activate_volunteer_if_requested(member, activate_as_volunteer)
    user_creation_result = _create_user_account_safe(member, should_activate_volunteer)
    _send_approval_email_safe(member, invoice, membership_type_doc)

    # Queue background job to update payment history with initial invoice
    if invoice:
        frappe.enqueue(
            "verenigingen.api.membership_application_review.update_payment_history_for_invoice",
            queue="default",
            timeout=300,
            member_name=member.name,
            invoice_name=invoice.name,
            enqueue_after_commit=True,
        )

    log_security_event(
        "data_modification",
        {"message": f"Membership approved: {member_name} status change Pending -> Approved/Active"},
        severity="info",
    )

    return _build_approval_response(member, invoice, billing_amount, user_creation_result)


@frappe.whitelist()
@high_security_api()  # Member application rejection workflow
def reject_membership_application(
    member_name: str,
    reason: str,
    email_template: str = None,
    rejection_category: str = None,
    internal_notes: str = None,
    process_refund: bool = False,
):
    """Reject a membership application with enhanced template support and input validation"""
    # Input validation and sanitization
    member_name = _validate_member_for_review(member_name, "rejection")
    sanitized = _sanitize_text_fields(
        {
            "reason": (reason, 1000, False),
            "email_template": (email_template, 255),
            "rejection_category": (rejection_category, 255),
            "internal_notes": (internal_notes, 2000, False),
        }
    )
    reason = sanitized["reason"]
    email_template = sanitized["email_template"]
    rejection_category = sanitized["rejection_category"]
    internal_notes = sanitized["internal_notes"]

    # Validate email template if provided
    if email_template and not frappe.db.exists("Email Template", email_template):
        frappe.throw(_("Invalid email template specified"))

    member = frappe.get_doc("Member", member_name)

    # Validate application can be rejected
    if member.application_status not in ["Pending", "Payment Failed", "Payment Cancelled", "Approved"]:
        frappe.throw(_("This application cannot be rejected in its current state"))

    # Check chapter-based permissions
    from verenigingen.utils.chapter_security import validate_chapter_permission_or_throw

    validate_chapter_permission_or_throw(member_name, "reject")

    # Note: Frappe automatically manages transactions for @frappe.whitelist() functions

    # Build comprehensive review notes
    review_notes = f"Rejection Category: {rejection_category or 'Not specified'}\n"
    review_notes += f"Reason: {reason}\n"
    if internal_notes:
        review_notes += f"Internal Notes: {internal_notes}\n"
    review_notes += f"Email Template Used: {email_template or 'Default'}"

    # Update member status
    member.application_status = "Rejected"
    member.status = "Rejected"
    member.reviewed_by = frappe.session.user
    member.review_date = now_datetime()
    member.review_notes = review_notes
    member.save()

    # Process refund if payment was made
    refund_processed = False
    if (
        process_refund
        and hasattr(member, "application_invoice")
        and getattr(member, "application_invoice", None)
    ):
        from verenigingen.api.payment_processing import process_application_refund

        refund_result = process_application_refund(member_name, "Application Rejected: " + reason)
        refund_processed = refund_result.get("success", False)

    # Cancel any pending membership
    if frappe.db.exists(
        "Membership", {"member": member.name, "status": ["in", ["Draft", "Pending", "Active"]]}
    ):
        membership = frappe.get_doc("Membership", {"member": member.name})
        if membership.docstatus == 1:
            membership.cancel()
        else:
            frappe.delete_doc("Membership", membership.name)

    # Remove pending chapter memberships
    from verenigingen.utils.application_helpers import remove_all_pending_chapter_memberships

    remove_all_pending_chapter_memberships(member)

    # Update CRM Lead status if exists
    if frappe.db.exists("Lead", {"member": member.name}):
        lead = frappe.get_doc("Lead", {"member": member.name})
        lead.status = "Do Not Contact"
        lead.save()

    # Send rejection notification with specified template
    send_rejection_notification(member, reason, email_template, rejection_category)

    # Note: Frappe automatically commits successful transactions

    return {
        "success": True,
        "message": _("Application rejected. Notification sent to applicant."),
        "refund_processed": refund_processed,
    }


@frappe.whitelist()
@standard_api  # User chapter access - read-only
def get_user_chapter_access(**kwargs):
    """Get user's chapter access for filtering applications"""
    user = frappe.session.user

    # Admin roles see all chapters
    admin_roles = Roles.ADMIN_ROLES
    if any(role in frappe.get_roles(user) for role in admin_roles):
        return {"restrict_to_chapters": False, "chapters": [], "is_admin": True}

    # Get user's member record
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not user_member:
        return {
            "restrict_to_chapters": True,
            "chapters": [],
            "is_admin": False,
            "message": "User is not a member",
        }

    # Get chapters where user has board access with membership permissions
    # Single query replaces N+1 pattern (was: 1 + N volunteers + M board positions)
    user_chapters = []
    volunteer_names = frappe.get_all("Volunteer", filters={"member": user_member}, pluck="name")
    if volunteer_names:
        board_positions = frappe.get_all(
            "Chapter Board Member",
            filters={"volunteer": ["in", volunteer_names], "is_active": 1},
            fields=["parent", "chapter_role"],
        )
        if board_positions:
            role_names = list({p.chapter_role for p in board_positions})
            role_levels = {
                r.name: r.permissions_level
                for r in frappe.get_all(
                    "Chapter Role",
                    filters={"name": ["in", role_names]},
                    fields=["name", "permissions_level"],
                )
            }
            for position in board_positions:
                level = role_levels.get(position.chapter_role)
                if level in ("Admin", "Membership") and position.parent not in user_chapters:
                    user_chapters.append(position.parent)

    # Check national chapter access
    national_access = False
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if hasattr(settings, "national_chapter") and settings.national_chapter:
            if settings.national_chapter in user_chapters:
                national_access = True
    except Exception:
        pass

    return {
        "restrict_to_chapters": len(user_chapters) > 0 and not national_access,
        "chapters": user_chapters,
        "is_admin": False,
        "has_national_access": national_access,
    }


def send_approval_notification(member, invoice, membership_type):
    """Send approval notification with payment link - MIGRATED to unified EmailService"""
    # Create payment link
    payment_url = frappe.utils.get_url(f"/payment/membership/{member.name}/{invoice.name}")

    # MIGRATED: Use unified EmailService instead of direct frappe.sendmail
    from verenigingen.services.communication.compatibility import send_member_notification

    # Prepare context with all necessary variables
    context = {
        "member": member,
        "invoice": invoice,
        "membership_type": membership_type,
        "payment_url": payment_url,
        "payment_amount": frappe.format_value(invoice.grand_total, {"fieldtype": "Currency"}),
        "application_id": getattr(member, "application_id", member.name),
        "company": frappe.defaults.get_global_default("company"),
        "support_email": frappe.db.get_single_value("Verenigingen Settings", "member_contact_email")
        or "info@verenigingen.nl",
        "base_url": frappe.utils.get_url(),
    }

    # Send using unified EmailService - it will automatically use the template we created
    result = send_member_notification(
        member_name=member.name,
        notification_type="approval",  # This will map to "member_approval" template
        context=context,
    )

    if not result.success:
        frappe.logger("membership_review").warning(
            f"Failed to send approval notification to {member.email}: {'; '.join(result.errors or [])}"
        )

    return result


def send_rejection_notification(member, reason, email_template=None, rejection_category=None):
    """Send rejection notification to applicant using specified template - MIGRATED to unified EmailService"""
    # MIGRATED: Use unified EmailService instead of direct frappe.sendmail and template handling
    from verenigingen.services.communication.email_service import get_email_service

    # Prepare context with all necessary variables
    context = {
        "member": member,
        "reason": reason,
        "rejection_category": rejection_category or "Not specified",
        "company": frappe.defaults.get_global_default("company"),
        "member_name": member.full_name,
        "first_name": member.first_name,
        "application_id": getattr(member, "application_id", member.name),
        "support_email": frappe.db.get_single_value("Verenigingen Settings", "member_contact_email")
        or "info@verenigingen.nl",
        "base_url": frappe.utils.get_url(),
    }

    email_service = get_email_service()

    # Use specified template if provided, otherwise use default rejection template
    template_name = email_template if email_template else "membership_application_rejected"

    result = email_service.send_templated_email(
        template_name=template_name,
        recipients=[member.email],
        context=context,
        reference_doctype="Member",
        reference_name=member.name,
        notification_key="member_application_rejected",
    )

    if not result.success:
        frappe.logger("membership_review").warning(
            f"Failed to send rejection notification to {member.email}: {'; '.join(result.errors)}"
        )


@frappe.whitelist()
@standard_api()  # Application listing - read-only
def get_pending_applications(chapter: str | None = None, days_overdue: int | None = None):
    """Get list of pending membership applications"""
    filters = {"application_status": "Pending", "status": "Pending"}

    # Filter by overdue if specified
    if days_overdue:
        cutoff_date = add_days(today(), -days_overdue)
        filters["application_date"] = ["<", cutoff_date]

    # Chapter-based permission filtering is applied at the end of this function
    # via filter_applications_by_permission() from chapter_security.py, which
    # calls get_user_manageable_chapters() and can_user_manage_application()
    # for each result. No inline permission check is needed here.

    # Get applications
    applications = frappe.get_all(
        "Member",
        filters=filters,
        fields=[
            "name",
            "application_id",
            "full_name",
            "email",
            "contact_number",
            "application_date",
            # "current_chapter_display",  # HTML field - not in database
            "selected_membership_type",
            "interested_in_volunteering",
            "age",
        ],
        order_by="application_date desc",
    )

    # Optimize chapter lookup by fetching all chapter memberships at once
    member_names = [app.name for app in applications]

    # Get all chapter memberships for these members in a single query
    chapter_memberships = {}
    if member_names:
        all_memberships = frappe.db.sql(
            """
            SELECT member, parent as chapter_name
            FROM `tabChapter Member`
            WHERE member IN %(member_names)s AND enabled = 1
            ORDER BY chapter_join_date DESC
        """,
            {"member_names": member_names},
            as_dict=True,
        )

        # Group by member (taking the most recent chapter)
        for membership in all_memberships:
            if membership.member not in chapter_memberships:
                chapter_memberships[membership.member] = membership.chapter_name

    # Get all membership types in one query for amount lookup
    membership_types = {app.selected_membership_type for app in applications if app.selected_membership_type}
    membership_type_data = {}
    if membership_types:
        type_data = frappe.get_all(
            "Membership Type",
            filters={"name": ["in", list(membership_types)]},
            fields=["name", "minimum_amount", "dues_schedule_template"],
        )

        # Optimize template amount queries - batch fetch all templates
        template_names = [mt.dues_schedule_template for mt in type_data if mt.dues_schedule_template]
        template_data = {}

        if template_names:
            templates = frappe.get_all(
                "Membership Dues Schedule",
                filters={"name": ["in", template_names]},
                fields=["name", "dues_rate", "suggested_amount"],
            )
            template_data = {t.name: t for t in templates}

        # Get template amounts for each membership type using cached data
        for mt in type_data:
            billing_amount = 0
            if mt.dues_schedule_template and mt.dues_schedule_template in template_data:
                template = template_data[mt.dues_schedule_template]
                billing_amount = template.dues_rate or template.suggested_amount or 0

            # Fallback to minimum_amount if no template amount available
            if not billing_amount:
                billing_amount = mt.minimum_amount

            # Store the membership type data with calculated billing_amount
            membership_type_data[mt.name] = {
                "name": mt.name,
                "minimum_amount": mt.minimum_amount,
                "dues_schedule_template": mt.dues_schedule_template,
                "billing_amount": billing_amount,
            }

    # Add additional info and apply chapter filtering
    filtered_applications = []
    for app in applications:
        app["days_pending"] = (getdate(today()) - getdate(app.application_date)).days

        # Get membership type amount from cached data or application
        if app.selected_membership_type and app.selected_membership_type in membership_type_data:
            mt = membership_type_data[app.selected_membership_type]
            # Amount should come from the application itself
            app["membership_amount"] = (
                app.get("payment_amount") or app.get("membership_fee") or mt["billing_amount"]
            )
            # Currency should come from application or default to EUR
            app["membership_currency"] = app.get("currency") or "EUR"

        # Get chapter information from pre-loaded data
        app["current_chapter_display"] = chapter_memberships.get(app.name, "Unassigned")

        # Apply chapter filter if specified
        if chapter:
            member_chapter = chapter_memberships.get(app.name)
            if chapter == "Unassigned" and member_chapter:
                continue  # Skip if looking for unassigned but member has chapters
            elif chapter != "Unassigned" and member_chapter != chapter:
                continue  # Skip if doesn't match requested chapter

        filtered_applications.append(app)

    # Apply chapter-based security filtering
    from verenigingen.utils.chapter_security import filter_applications_by_permission

    return filter_applications_by_permission(filtered_applications)


@frappe.whitelist()
@standard_api()  # Member data query
def get_pending_reviews_for_member(member_name: str):
    """Get pending membership application reviews for a specific member"""
    try:
        # Check if there are any pending reviews for this member
        # Since this is for membership applications, we check if the member
        # has a pending application status that needs review
        member = frappe.get_doc("Member", member_name)

        reviews = []

        # If member has pending application status, they need review
        if member.application_status == "Pending":
            reviews.append(
                {
                    "name": member.name,
                    "member": member.name,
                    "member_name": member.full_name,
                    "application_status": member.application_status,
                    "application_date": getattr(member, "application_date", None),
                    "review_type": "Membership Application",
                }
            )

        return reviews

    except Exception as e:
        safe_log_error(
            "Pending reviews error", f"Error getting pending reviews for member {member_name}: {str(e)}"
        )
        return []


def update_payment_history_for_invoice(member_name: str, invoice_name: str):
    """
    Background job to update member payment history with initial invoice.

    This runs after approval to ensure the invoice is fully committed and
    the member payment history is updated with the new invoice entry.

    Args:
        member_name: Member document name
        invoice_name: Sales Invoice document name
    """
    try:
        # Get member document
        member = frappe.get_doc("Member", member_name)

        # Get invoice document
        invoice = frappe.get_doc("Sales Invoice", invoice_name)

        # Verify invoice belongs to this member
        if invoice.customer != member.customer:
            frappe.log_error(
                f"Invoice {invoice_name} customer ({invoice.customer}) does not match member {member_name} customer ({member.customer})",
                "Payment History Update Error",
            )
            return

        # Get payment history manager
        from verenigingen.utils.member_financial_history_manager import get_payment_history_manager

        manager = get_payment_history_manager(member)

        # Build entry using the member's method
        def build_invoice_entry():
            return member._build_payment_history_entry(invoice)

        # Add or update the entry
        success = manager.add_or_update_entry(invoice_name, build_invoice_entry, "invoice")

        if success:
            frappe.logger().info(
                f"Successfully updated payment history for member {member_name} with invoice {invoice_name}"
            )
        else:
            frappe.log_error(
                f"Failed to update payment history for member {member_name} with invoice {invoice_name}",
                "Payment History Update Error",
            )

    except Exception as e:
        frappe.log_error(
            f"Error updating payment history for member {member_name} with invoice {invoice_name}: {str(e)}",
            "Payment History Update Error",
        )
