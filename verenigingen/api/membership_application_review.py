"""
API endpoints for reviewing and managing membership applications
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, today

# Import email service
from verenigingen.services.communication.email_service import get_email_service

# Import extracted services
from verenigingen.services.member.approval.member_approval_service import (
    create_member_iban_history,
    finalize_member_approval,
    process_member_approval,
    resolve_membership_type,
    validate_approval_prerequisites,
)
from verenigingen.services.member.validation.member_duplicate_detection_service import (
    check_duplicate_for_approval,
)
from verenigingen.utils.member_utils import get_volunteer_for_member
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.secure_operations import secure_document_operation

# Import security decorators
from verenigingen.utils.security.api_security_framework import critical_api, high_security_api, standard_api


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


def create_membership_and_invoice(member, membership_type):
    """Create membership record and invoice - extracted from approval workflow"""
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
            template = frappe.get_doc("Membership Dues Schedule", membership_type_doc.dues_schedule_template)
            billing_amount = template.dues_rate or template.suggested_amount or 0
        except Exception:
            pass

    # Fallback to minimum_amount if no template amount available
    if not billing_amount:
        billing_amount = membership_type_doc.minimum_amount

    # Submit membership first to trigger dues schedule creation
    try:
        membership.submit()
        frappe.logger().info(f"Successfully submitted membership {membership.name} for member {member.name}")
    except Exception as e:
        frappe.logger().error(f"Failed to submit membership for member {member.name}: {str(e)}")
        frappe.throw(_("Failed to submit membership. Please try again."))

    return membership, membership_type_doc, billing_amount


@frappe.whitelist()
@high_security_api()  # Member application approval workflow
def approve_membership_application(
    member_name,
    membership_type=None,
    chapter=None,
    notes=None,
    create_invoice=True,
    activate_as_volunteer=False,
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
    # Input sanitization and validation
    from verenigingen.utils.security.audit_logging import log_security_event
    from verenigingen.utils.validation.api_validators import APIValidator

    try:
        # Validate and sanitize all inputs
        member_name = APIValidator.sanitize_text(str(member_name), max_length=255)
        if membership_type:
            membership_type = APIValidator.sanitize_text(str(membership_type), max_length=255)
        if chapter:
            chapter = APIValidator.sanitize_text(str(chapter), max_length=255)
        if notes:
            notes = APIValidator.sanitize_text(str(notes), max_length=2000, allow_html=False)

        # Validate member exists before proceeding
        if not frappe.db.exists("Member", member_name):
            log_security_event(
                "invalid_member_access",
                {"message": f"Attempted approval of non-existent member: {member_name}"},
                severity="error",
            )
            frappe.throw(_("Invalid member reference"))

        # Idempotency check - if already approved, return success
        member_status = frappe.db.get_value(
            "Member", member_name, ["application_status", "status"], as_dict=True
        )
        if member_status and member_status.application_status == "Approved":
            frappe.logger().info(
                f"Member {member_name} already approved (application_status=Approved), returning existing approval"
            )
            # Get existing membership for response
            existing_membership = frappe.db.get_value(
                "Membership", {"member": member_name, "status": "Active", "docstatus": 1}, "name"
            )

            # Get most recent invoice for this member if exists
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
                "idempotent": True,  # Flag to indicate this was already done
            }

    except Exception as e:
        log_security_event(
            "input_validation_failure",
            {"message": f"Input validation failed for approval: {str(e)}"},
            severity="warning",
        )
        frappe.throw(_("Invalid input data provided"))

    member = frappe.get_doc("Member", member_name)

    # Validate application can be approved
    if member.application_status not in ["Pending"]:
        frappe.throw(_("This application cannot be approved in its current state"))

    # Check chapter-based permissions
    from verenigingen.utils.chapter_security import validate_chapter_permission_or_throw

    validate_chapter_permission_or_throw(member_name, "approve")

    # Resolve membership type using helper function
    membership_type = resolve_membership_type(member, membership_type)

    # Pre-check: Validate membership type has a valid dues schedule template
    validate_membership_type_for_approval(membership_type, member, is_application_approval=True)

    # Note: Frappe automatically manages transactions for @frappe.whitelist() functions

    # Assign member to chapter using helper function
    assign_member_to_chapter(member, chapter)

    # Explicitly update chapter display after assignment to ensure it's set
    if chapter:
        member.reload()
        member.update_current_chapter_display()
        member.save()

    # Set the selected membership type in memory (will be saved during membership creation)
    try:
        member.selected_membership_type = membership_type
    except AttributeError:
        # Field might not exist in the database yet, log but continue
        frappe.logger().warning(f"Could not set selected_membership_type field on member {member.name}")

    # Employee creation for volunteers is handled by AccountCreationManager
    # This ensures proper security compliance and avoids duplicate processing
    if hasattr(member, "interested_in_volunteering") and member.interested_in_volunteering:
        volunteer_record = get_volunteer_for_member(member.name)
        if volunteer_record:
            frappe.logger().info(
                f"Volunteer record {volunteer_record} exists - AccountCreationManager will handle employee creation"
            )

    # Create initial IBAN history using helper function
    create_member_iban_history(member)

    # Prepare approval fields to pass to create_membership_on_approval()
    # These will be set after reload and saved in one consolidated operation
    approval_fields = {
        "application_status": "Approved",
        "status": "Active",
        "member_since": today(),
        "reviewed_by": frappe.session.user,
        "review_date": now_datetime(),
        "selected_membership_type": membership_type,  # Include to prevent duplicate save
    }
    if notes:
        approval_fields["review_notes"] = notes

    # If member has custom dues rate, set fee_override_reason to satisfy validation
    if hasattr(member, "dues_rate") and member.dues_rate:
        if not hasattr(member, "fee_override_reason") or not member.fee_override_reason:
            approval_fields["fee_override_reason"] = "Application approval"

    # Create membership using member's built-in method which handles:
    # - Context manager coordination to prevent duplicate saves
    # - Invoice creation (sets application_invoice field)
    # - Dues schedule creation
    # - Approval fields setting after reload
    # - Consolidated member save with all fields updated once
    membership = member.create_membership_on_approval(create_invoice=True, approval_fields=approval_fields)

    # Note: Customer creation happens in member.after_insert() hook, not during approval

    # Get invoice and membership type for email notification
    invoice = None
    if hasattr(member, "application_invoice") and member.application_invoice:
        invoice = frappe.get_doc("Sales Invoice", member.application_invoice)

    membership_type_doc = frappe.get_doc("Membership Type", membership.membership_type)

    # Calculate billing amount for response
    # Prefer invoice amount, fallback to member rate, then membership type minimum
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

    # Activate volunteer record only when explicitly requested via checkbox
    # The volunteer record was created during application submission if interested_in_volunteering
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
            should_activate_volunteer = True  # Set flag for user account creation with Volunteer role
            frappe.logger().info(
                f"Activated volunteer record for {member.name} during approval (full activation)"
            )
        except Exception as e:
            safe_log_error(f"Non-critical: Failed to activate volunteer record for {member.name}: {str(e)}")
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

    # Create user account for portal access using secure AccountCreationManager
    # Pass should_activate_volunteer to ensure correct role profile assignment
    user_creation_result = {"success": False, "error": "Not attempted"}
    try:
        user_creation_result = create_secure_user_account_for_member(
            member, activate_as_volunteer=should_activate_volunteer
        )
    except Exception as e:
        safe_log_error(f"Non-critical: User account creation failed for {member.name}: {str(e)}")
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

    # Send approval email with payment link
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

    # Note: finalize_member_approval() call removed - approval fields are already set
    # and saved by member.create_membership_on_approval() in one consolidated save

    # Log status change for auditing
    # Queue background job to update payment history with initial invoice
    # This runs after a short delay to allow invoice to be fully committed
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
        "membership_approved",
        {"message": f"Member {member_name} approved with status change: Pending -> Approved/Active"},
        severity="info",
    )

    # Note: Frappe automatically commits successful transactions

    # Prepare response message with enhanced user feedback
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
                " User account creation queued for secure background processing - member will receive portal access within 2-3 minutes."
            )
            user_account_status = "queued"
            # Add specific timing expectations
            frappe.msgprint(
                _(
                    "User account creation is being processed securely in the background. The member will receive login credentials via email within 2-3 minutes."
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


def create_user_account_for_member(member):
    """DEPRECATED: Create user account for approved member

    This function is deprecated in favor of create_secure_user_account_for_member
    which uses the secure AccountCreationManager system.
    """
    try:
        from verenigingen.verenigingen.doctype.member.member import create_member_user_account

        return create_member_user_account(member.name, send_welcome_email=True)
    except Exception as e:
        safe_log_error(f"Error creating user account for member {member.name}: {str(e)}")
        return {"success": False, "error": str(e)}


def safe_log_error(message, title=None):
    """Helper to log errors with length protection"""
    # Truncate message to prevent log title validation errors
    safe_message = message[:100] + "..." if len(message) > 100 else message
    frappe.log_error(safe_message, title)


def create_secure_user_account_for_member(member, activate_as_volunteer=False):
    """
    Create user account for approved member using secure AccountCreationManager with proper role profiles.

    Args:
        member: Member document
        activate_as_volunteer: If True, assign Volunteer role profile; otherwise Member role profile

    Returns:
        dict: Result dictionary with keys: success, message, user, action, error, account_request
              (Compatible with existing callers that use .get() access)

    Note:
        Internally uses OperationResult pattern but returns dict for backward compatibility.
        Callers can use result.get("success"), result.get("action"), etc.
    """
    try:
        from verenigingen.utils.account_creation_manager import queue_account_creation_for_member

        # Determine role profile from membership type, with fallback to default
        # The membership type's role_profile field defines what permissions members get
        role_profile = None
        if member.selected_membership_type:
            # Validate membership type exists
            if not frappe.db.exists("Membership Type", member.selected_membership_type):
                frappe.logger().error(
                    f"Membership Type '{member.selected_membership_type}' no longer exists for member {member.name}"
                )
            else:
                role_profile = frappe.db.get_value(
                    "Membership Type", member.selected_membership_type, "role_profile"
                )
                # Validate retrieved role_profile exists
                if role_profile and not frappe.db.exists("Role Profile", role_profile):
                    frappe.logger().warning(
                        f"Role Profile '{role_profile}' configured for Membership Type "
                        f"'{member.selected_membership_type}' does not exist - using default"
                    )
                    role_profile = None

        if not role_profile:
            role_profile = "Verenigingen Member"  # Fallback default
            frappe.logger().info(
                f"Using default role profile 'Verenigingen Member' for member {member.name} "
                f"(membership_type: {member.selected_membership_type or 'not set'})"
            )
        additional_roles = []  # Only for roles not covered by role profiles

        # Override with Volunteer profile if explicitly requested via activate_as_volunteer parameter
        if activate_as_volunteer:
            # Verify volunteer record exists before assigning volunteer profile
            volunteer_name = get_volunteer_for_member(member.name)
            if volunteer_name:
                volunteer_status = frappe.db.get_value("Volunteer", volunteer_name, "status")
                if volunteer_status in ["Active", "Pending"]:
                    role_profile = "Verenigingen Volunteer"  # Volunteer role profile
                    frappe.logger().info(
                        f"Member {member.name} activated as volunteer, using Verenigingen Volunteer profile"
                    )

                    # Check if volunteer is a board member - this requires additional role assignment
                    board_member_chapters = frappe.get_all(
                        "Chapter Board Member",
                        filters={"volunteer": volunteer_name, "is_active": 1},
                        fields=["parent"],
                    )
                    if board_member_chapters:
                        additional_roles.append("Verenigingen Chapter Board Member")
                        frappe.logger().info(
                            f"Member {member.name} is board member of {len(board_member_chapters)} chapters - adding board member role"
                        )
                else:
                    frappe.logger().warning(
                        f"Cannot assign Volunteer profile to {member.name} - volunteer status is {volunteer_status}"
                    )
            else:
                frappe.logger().warning(
                    f"Cannot assign Volunteer profile to {member.name} - no volunteer record found"
                )

        frappe.logger().info(
            f"Creating secure user account for member {member.name} with role_profile: {role_profile}, additional_roles: {additional_roles}"
        )

        # Check if user already exists (quick check)
        if frappe.db.exists("User", member.email):
            frappe.logger().info(f"User already exists for {member.email}, linking to member")
            # Security: Simple reference link to existing User.
            # Uses db.set_value to link Member to User without triggering
            # Member validation hooks. The user already exists and is valid.
            # Explicit commit ensures link persists before verification check.
            frappe.db.set_value("Member", member.name, "user", member.email)
            frappe.db.commit()

            # Verify linkage persisted correctly
            linked_user = frappe.db.get_value("Member", member.name, "user")
            if linked_user != member.email:
                frappe.log_error(
                    f"User linkage verification failed: expected {member.email}, got {linked_user}",
                    "Account Linking Verification",
                )
                return OperationResult.fail(
                    _("Failed to link user account"),
                    errors=["Linkage verification failed"],
                    user=None,
                    action="link_failed",
                ).to_dict()

            return OperationResult.ok(
                member.email,
                message=_("Linked to existing user account"),
                user=member.email,
                action="linked_existing",
            ).to_dict()

        # Check for existing account creation request
        existing_request = frappe.db.get_value(
            "Account Creation Request",
            {"source_record": member.name, "status": ["in", ["Pending", "In Progress", "Completed"]]},
            "name",
        )

        if existing_request:
            frappe.logger().info(
                f"Account creation request already exists for {member.name}: {existing_request}"
            )
            return OperationResult.ok(
                existing_request,
                message=_("Account creation already in progress or completed"),
                user=None,
                action="existing_request",
                account_request=existing_request,
            ).to_dict()

        # Create new account creation request - this returns OperationResult
        account_result = queue_account_creation_for_member(
            member_name=member.name,
            roles=additional_roles if additional_roles else None,
            role_profile=role_profile,
            priority="High",  # Member approval is high priority
        )

        # Handle OperationResult from queue_account_creation_for_member
        if account_result and account_result.success:
            request_name = (
                account_result.data.get("request")
                if isinstance(account_result.data, dict)
                else str(account_result.data)
                if account_result.data
                else None
            )
            return OperationResult.ok(
                request_name,
                message=_("User account creation queued successfully via secure system"),
                user=None,  # Will be set when background job completes
                action="queued_secure",
                account_request=request_name,
            ).to_dict()
        else:
            error_msg = account_result.error_message if account_result else "Unknown error"
            return OperationResult.fail(
                _("Failed to queue account creation request"),
                errors=[error_msg],
                user=None,
                action="queue_failed",
            ).to_dict()

    except Exception as e:
        # Create shortened error message to avoid log title length issues
        error_msg = str(e)[:100] + "..." if len(str(e)) > 100 else str(e)
        frappe.log_error(f"Account creation error for {member.name}: {error_msg}")
        return OperationResult.fail(
            _("Account creation failed"),
            errors=[error_msg],
            user=None,
            action="exception",
        ).to_dict()


def activate_volunteer_record(member):
    """Activate volunteer record when membership application is approved"""
    # Permission check - ensure user can write to Volunteer records
    if not frappe.has_permission("Volunteer", "write"):
        frappe.throw(_("You don't have permission to activate volunteers"))

    try:
        # Find existing volunteer record for this member
        volunteer_name = get_volunteer_for_member(member.name)

        # Also check by email in case member record was recreated
        if not volunteer_name:
            volunteer_name = frappe.db.get_value("Volunteer", {"email": member.email}, "name")
            if volunteer_name:
                frappe.logger().info(
                    f"Found orphaned volunteer {volunteer_name} by email, relinking to member {member.name}"
                )
                # Relink the volunteer to this member
                volunteer = frappe.get_doc("Volunteer", volunteer_name)
                volunteer.member = member.name
                volunteer.volunteer_name = (
                    member.full_name or f"{member.first_name} {member.last_name}".strip()
                )
                volunteer.save()

                # Also update member's volunteer_record field if it exists
                if hasattr(member, "volunteer_record"):
                    member.volunteer_record = volunteer_name
                    member.save()

        if volunteer_name:
            # Update existing volunteer record
            volunteer = frappe.get_doc("Volunteer", volunteer_name)
            volunteer.status = "Active"
            volunteer.save()
            frappe.logger().info(f"Activated volunteer record {volunteer_name} for member {member.name}")

            # Link volunteer to member record if not already linked
            if hasattr(member, "volunteer_record") and member.volunteer_record != volunteer_name:
                member.reload()  # Ensure we have latest data
                member.volunteer_record = volunteer_name
                member.save()
                frappe.logger().info(f"Linked volunteer {volunteer_name} to member {member.name}")

            # Upgrade user account from Website User to System User for volunteer access
            if member.user:
                try:
                    from verenigingen.utils.account_creation_manager import upgrade_member_to_volunteer_user

                    upgrade_result = upgrade_member_to_volunteer_user(member.name)
                    if upgrade_result.success:
                        frappe.logger().info(f"User account upgrade for volunteer: {upgrade_result.message}")
                    else:
                        frappe.logger().warning(
                            f"Could not upgrade user account for volunteer: {'; '.join(upgrade_result.errors or [])}"
                        )
                except Exception as e:
                    frappe.logger().error(f"Error upgrading user account to System User: {str(e)}")
                    # Non-critical - continue with volunteer activation

            # Employee creation is now handled by AccountCreationManager
            # The account creation request will handle employee creation properly
            # with full security compliance and audit trail
            frappe.logger().info(
                f"Employee creation for volunteer {volunteer_name} will be handled by AccountCreationManager"
            )
        else:
            # Create volunteer record if it doesn't exist (fallback)
            from verenigingen.utils.application_helpers import create_volunteer_record

            volunteer = create_volunteer_record(member)
            if volunteer:
                volunteer.status = "Active"
                volunteer.save()
                frappe.logger().info(
                    f"Created and activated volunteer record {volunteer.name} for member {member.name}"
                )

                # Upgrade user account from Website User to System User for volunteer access
                if member.user:
                    try:
                        from verenigingen.utils.account_creation_manager import (
                            upgrade_member_to_volunteer_user,
                        )

                        upgrade_result = upgrade_member_to_volunteer_user(member.name)
                        if upgrade_result.success:
                            frappe.logger().info(
                                f"User account upgrade for new volunteer: {upgrade_result.message}"
                            )
                        else:
                            frappe.logger().warning(
                                f"Could not upgrade user account for new volunteer: {'; '.join(upgrade_result.errors or [])}"
                            )
                    except Exception as e:
                        frappe.logger().error(f"Error upgrading user account to System User: {str(e)}")
                        # Non-critical - continue with volunteer activation
    except Exception as e:
        safe_log_error(f"Error activating volunteer record for member {member.name}: {str(e)}")


@frappe.whitelist()
@high_security_api()  # Member application rejection workflow
def reject_membership_application(
    member_name,
    reason,
    email_template=None,
    rejection_category=None,
    internal_notes=None,
    process_refund=False,
):
    """Reject a membership application with enhanced template support and input validation"""
    # Input sanitization and validation
    from verenigingen.utils.security.audit_logging import log_security_event
    from verenigingen.utils.validation.api_validators import APIValidator

    try:
        # Validate and sanitize all inputs
        member_name = APIValidator.sanitize_text(str(member_name), max_length=255)
        reason = APIValidator.sanitize_text(str(reason), max_length=1000, allow_html=False)

        if email_template:
            email_template = APIValidator.sanitize_text(str(email_template), max_length=255)
        if rejection_category:
            rejection_category = APIValidator.sanitize_text(str(rejection_category), max_length=255)
        if internal_notes:
            internal_notes = APIValidator.sanitize_text(
                str(internal_notes), max_length=2000, allow_html=False
            )

        # Validate member exists
        if not frappe.db.exists("Member", member_name):
            log_security_event(
                "invalid_member_access",
                {"message": f"Attempted rejection of non-existent member: {member_name}"},
                severity="error",
            )
            frappe.throw(_("Invalid member reference"))

        # Validate email template if provided
        if email_template and not frappe.db.exists("Email Template", email_template):
            frappe.throw(_("Invalid email template specified"))

    except Exception as e:
        log_security_event(
            "input_validation_failure",
            {"message": f"Input validation failed for rejection: {str(e)}"},
            severity="warning",
        )
        frappe.throw(_("Invalid input data provided"))

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
    admin_roles = ["System Manager", "Verenigingen Administrator", "Verenigingen Staff"]
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
    user_chapters = []
    volunteer_records = frappe.get_all("Volunteer", filters={"member": user_member}, fields=["name"])

    for volunteer_record in volunteer_records:
        board_positions = frappe.get_all(
            "Chapter Board Member",
            filters={"volunteer": volunteer_record.name, "is_active": 1},
            fields=["parent", "chapter_role"],
        )

        for position in board_positions:
            # Check if the role has membership permissions
            try:
                role_doc = frappe.get_doc("Chapter Role", position.chapter_role)
                if role_doc.permissions_level in ["Admin", "Membership"]:
                    if position.parent not in user_chapters:
                        user_chapters.append(position.parent)
            except Exception:
                continue

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


def has_approval_permission(member):
    """
    Enhanced server-side permission validation for membership approval operations
    Implements comprehensive security checks with rate limiting and audit logging
    """
    user = frappe.session.user

    # Basic user validation
    if not user or user == "Guest":
        safe_log_error(f"Approval attempted by guest user for member {member.name}")
        return False

    # Note: Rate limiting is handled by COR (Critical Operation Rules) via @high_security_api decorator
    # on the API endpoints that call this function. No internal rate limit check needed.

    # Audit log the permission check
    safe_log_error(
        f"Permission check: User {user} attempting approval for member {member.name}",
        "Membership Approval Audit",
    )

    # System managers always have permission
    user_roles = frappe.get_roles(user)
    if "System Manager" in user_roles:
        return True

    # Association/Membership managers have permission
    if any(role in user_roles for role in ["Verenigingen Administrator", "Verenigingen Staff"]):
        return True

    # Enhanced chapter-based permission check
    try:
        # Get chapter from Chapter Member table instead of HTML field
        member_chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": member.name, "enabled": 1},
            fields=["parent"],
            order_by="chapter_join_date desc",
            limit=1,  # Only need the most recent
        )

        if not member_chapters:
            # Check for suggested chapter if no formal chapter membership
            suggested_chapter = getattr(member, "suggested_chapter", None)
            if suggested_chapter:
                member_chapters = [{"parent": suggested_chapter}]

        if member_chapters:
            chapter = member_chapters[0]["parent"]

            # Get user's member record with validation
            user_member = frappe.db.get_value("Member", {"user": user}, "name")
            if not user_member:
                safe_log_error(f"User {user} has no associated member record for approval permission check")
                return False

            # Validate chapter exists and user has board access
            if not frappe.db.exists("Chapter", chapter):
                safe_log_error(f"Chapter {chapter} does not exist for member {member.name}")
                return False

            # Use the corrected method from permissions.py fix
            from verenigingen.permissions import can_terminate_member

            # Check if user has termination permission (similar permission level required for approval)
            if can_terminate_member(member.name, user):
                return True

            # Additional direct check for board membership with proper validation
            chapter_doc = frappe.get_doc("Chapter", chapter)
            if hasattr(chapter_doc, "board_members") and chapter_doc.board_members:
                for board_member in chapter_doc.board_members:
                    if (
                        board_member.is_active
                        and board_member.volunteer == user_member
                        and board_member.chapter_role
                    ):
                        # Validate role exists and has proper permissions
                        if frappe.db.exists("Chapter Role", board_member.chapter_role):
                            role = frappe.get_doc("Chapter Role", board_member.chapter_role)
                            if hasattr(role, "permissions_level") and role.permissions_level in [
                                "Admin",
                                "Membership",
                            ]:
                                return True

    except Exception as e:
        safe_log_error(f"Error checking approval permissions for user {user}, member {member.name}: {str(e)}")
        return False

    # Log denied permission attempt for security monitoring
    safe_log_error(
        f"Permission denied: User {user} does not have approval permission for member {member.name}",
        "Security Alert: Unauthorized Approval Attempt",
    )
    return False


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

    if not result.get("success"):
        frappe.logger("membership_review").warning(
            f"Failed to send rejection notification to {member.email}: {'; '.join(result.get('errors', []))}"
        )


@frappe.whitelist()
@standard_api()  # Application listing - read-only
def get_pending_applications(chapter=None, days_overdue=None):
    """Get list of pending membership applications"""
    filters = {"application_status": "Pending", "status": "Pending"}

    # Chapter filtering will be done post-query since we need to check Chapter Member table
    # if chapter:
    #     filters["current_chapter_display"] = chapter

    # Filter by overdue if specified
    if days_overdue:
        cutoff_date = add_days(today(), -days_overdue)
        filters["application_date"] = ["<", cutoff_date]

    # Check user permissions
    user = frappe.session.user
    if not any(
        role in frappe.get_roles(user)
        for role in ["System Manager", "Verenigingen Administrator", "Verenigingen Staff"]
    ):
        # Regular users can only see applications for their chapter
        user_member = frappe.db.get_value("Member", {"user": user}, "name")
        if user_member:
            # Get chapters where user is a board member
            board_chapters = frappe.db.sql(
                """
                SELECT DISTINCT c.name
                FROM `tabChapter` c
                JOIN `tabChapter Board Member` cbm ON cbm.parent = c.name
                JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                WHERE v.member = %s AND cbm.is_active = 1
            """,
                user_member,
                as_dict=True,
            )

            if board_chapters:
                # Chapter filtering will be done post-query using Chapter Member relationships
                # chapter_list = [ch.name for ch in board_chapters]  # Not currently used
                # if "current_chapter_display" in filters:
                #     # Ensure requested chapter is in allowed list
                #     if filters["current_chapter_display"] not in chapter_list:
                #         return []
                # else:
                #     filters["current_chapter_display"] = ["in", chapter_list]
                pass
            else:
                return []  # No board memberships

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
def get_pending_reviews_for_member(member_name):
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
        safe_log_error(f"Error getting pending reviews for member {member_name}: {str(e)}")
        return []


@frappe.whitelist()
@standard_api()  # Debugging and diagnostic tool
def debug_and_fix_member_approval(member_name):
    """Debug and fix member approval issues"""
    try:
        member = frappe.get_doc("Member", member_name)

        # Check field access
        result = {
            "member": member.name,
            "full_name": member.full_name,
            "application_status": member.application_status,
            "has_selected_type": hasattr(member, "selected_membership_type"),
            "selected_membership_type": getattr(member, "selected_membership_type", None),
            "has_current_type": hasattr(member, "current_membership_type"),
            "current_membership_type": getattr(member, "current_membership_type", None),
        }

        # Get available membership types
        membership_types = frappe.get_all(
            "Membership Type", fields=["name", "membership_type_name", "minimum_amount"]
        )
        result["available_membership_types"] = len(membership_types)
        result["membership_types"] = membership_types[:3]  # Show first 3

        # Try to fix if no membership type is set
        if (
            not result["selected_membership_type"]
            and not result["current_membership_type"]
            and membership_types
        ):
            default_type = membership_types[0].name
            try:
                member.selected_membership_type = default_type
                member.save()
                result["fix_applied"] = True
                result["default_type_set"] = default_type
                result["selected_membership_type"] = default_type
            except AttributeError:
                # Field doesn't exist yet, but we can still use it for approval
                result["fix_applied"] = "field_missing_but_will_work"
                result["default_type_set"] = default_type
                result["note"] = "Field not in database yet, but approval logic will handle this"
        else:
            result["fix_applied"] = False

        return result

    except Exception as e:
        return {"error": str(e), "member": member_name}


@frappe.whitelist()
@standard_api()  # Testing and diagnostic tool
def test_member_approval(member_name):
    """Test member approval without actually approving"""
    try:
        member = frappe.get_doc("Member", member_name)

        # Test the same logic as in approve_membership_application
        membership_type = None

        # Use the same fallback logic
        if not membership_type:
            membership_type = getattr(member, "selected_membership_type", None)

        if not membership_type:
            membership_type = getattr(member, "current_membership_type", None)

        if not membership_type:
            membership_types = frappe.get_all("Membership Type", fields=["name"], limit=1)
            if membership_types:
                membership_type = membership_types[0].name

        result = {
            "member": member.name,
            "application_status": member.application_status,
            "resolved_membership_type": membership_type,
            "can_approve": bool(membership_type and member.application_status == "Pending"),
            "status": "Ready for approval" if membership_type else "No membership type available",
        }

        return result

    except Exception as e:
        return {"error": str(e), "member": member_name}


@frappe.whitelist()
@critical_api()  # Administrative member status synchronization
def sync_member_statuses():
    """Sync member application and status fields to ensure consistency"""
    try:
        # Get all members to check for inconsistencies
        members = frappe.get_all("Member", fields=["name", "status", "application_status", "application_id"])

        updated_count = 0

        for member_data in members:
            member = frappe.get_doc("Member", member_data.name)
            is_application_member = bool(getattr(member, "application_id", None))

            updated = False

            if is_application_member:
                # Handle application-created members
                if member.application_status == "Approved" and member.status != "Active":
                    member.status = "Active"
                    updated = True
                elif member.application_status == "Rejected" and member.status != "Rejected":
                    member.status = "Rejected"
                    updated = True
            else:
                # Handle backend-created members (no application process)
                if not member.application_status:
                    member.application_status = "Approved"
                    updated = True

                # Ensure backend-created members are Active by default unless explicitly set
                if not member.status or member.status == "Pending":
                    member.status = "Active"
                    updated = True

            if updated:
                member.save()
                updated_count += 1

        return {
            "success": True,
            "message": f"Synchronized {updated_count} member records",
            "updated_count": updated_count,
        }

    except Exception as e:
        safe_log_error(f"Error syncing member statuses: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api()  # Administrative member status correction
def fix_backend_member_statuses():
    """One-time fix for backend-created members showing as Pending"""
    try:
        # Get all members that have Pending application_status but no application_id
        members = frappe.get_all(
            "Member",
            fields=["name", "application_status", "application_id"],
            filters={"application_status": "Pending"},
        )

        fixed_count = 0

        for member_data in members:
            # If no application_id, this is a backend-created member
            if not member_data.application_id:
                member = frappe.get_doc("Member", member_data.name)
                member.application_status = "Approved"
                member.status = "Active"
                member.save()
                fixed_count += 1

        return {
            "success": True,
            "message": f"Fixed {fixed_count} backend-created members",
            "fixed_count": fixed_count,
        }

    except Exception as e:
        safe_log_error(f"Error fixing backend member statuses: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api()  # Application statistics - read-only
def get_application_stats():
    """Get statistics for membership applications"""
    # Check permissions
    if not any(
        role in frappe.get_roles()
        for role in ["System Manager", "Verenigingen Administrator", "Verenigingen Staff"]
    ):
        frappe.throw(_("Insufficient permissions"))

    stats = {}

    # Total applications by status
    status_counts = frappe.db.sql(
        """
        SELECT application_status, COUNT(*) as count
        FROM `tabMember`
        WHERE application_status IS NOT NULL
        GROUP BY application_status
    """,
        as_dict=True,
    )

    stats["by_status"] = {s.application_status: s.count for s in status_counts}

    # Applications in last 30 days
    stats["last_30_days"] = frappe.db.count("Member", {"application_date": [">=", add_days(today(), -30)]})

    # Average processing time (for approved applications)
    avg_time = frappe.db.sql(
        """
        SELECT AVG(TIMESTAMPDIFF(DAY, application_date, review_date)) as avg_days
        FROM `tabMember`
        WHERE application_status = 'Approved'
        AND review_date IS NOT NULL
        AND application_date IS NOT NULL
    """,
        as_dict=True,
    )

    stats["avg_processing_days"] = round(avg_time[0].avg_days or 0, 1)

    # Overdue applications (> 14 days)
    stats["overdue_count"] = frappe.db.count(
        "Member", {"application_status": "Pending", "application_date": ["<", add_days(today(), -14)]}
    )

    # Applications by chapter - using Chapter Member table
    chapter_counts = frappe.db.sql(
        """
        SELECT cm.parent as current_chapter_display, COUNT(*) as count
        FROM `tabMember` m
        LEFT JOIN `tabChapter Member` cm ON cm.member = m.name AND cm.enabled = 1
        WHERE m.application_status = 'Pending'
        GROUP BY cm.parent
        ORDER BY count DESC
        LIMIT 10
    """,
        as_dict=True,
    )

    stats["by_chapter"] = chapter_counts

    # Volunteer interest rate
    total_apps = frappe.db.count("Member", {"application_status": ["!=", None]})
    volunteer_interested = frappe.db.count(
        "Member", {"application_status": ["!=", None], "interested_in_volunteering": 1}
    )

    stats["volunteer_interest_rate"] = round(
        (volunteer_interested / total_apps * 100) if total_apps > 0 else 0, 1
    )

    return stats


@frappe.whitelist()
@critical_api()  # Administrative data migration
def migrate_active_application_status():
    """Migrate members with 'Active' application_status to 'Approved'"""
    try:
        # Check if user has permission
        if not any(role in frappe.get_roles() for role in ["System Manager", "Verenigingen Administrator"]):
            frappe.throw(_("Only System Managers and Verenigingen Administrators can run this migration"))

        # Find all members with 'Active' application_status
        members_to_migrate = frappe.get_all(
            "Member", filters={"application_status": "Active"}, fields=["name", "full_name", "application_id"]
        )

        migrated_count = 0

        for member_data in members_to_migrate:
            try:
                member = frappe.get_doc("Member", member_data.name)
                member.application_status = "Approved"
                # Use proper save without bypassing permissions
                # Migration operations should run with proper user context
                member.save()
                migrated_count += 1
                frappe.logger().info(
                    f"Migrated member {member.name} from Active to Approved application status"
                )

            except Exception as e:
                safe_log_error(f"Error migrating member {member_data.name}: {str(e)}")
                continue

        return {
            "success": True,
            "message": f"Successfully migrated {migrated_count} members from 'Active' to 'Approved' application status",
            "migrated_count": migrated_count,
            "total_found": len(members_to_migrate),
        }

    except Exception as e:
        safe_log_error(f"Error in migrate_active_application_status: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api()  # Member IBAN data validation
def check_member_iban_data(member_name):
    """Check the current IBAN data for a member"""
    try:
        member = frappe.get_doc("Member", member_name)

        result = {
            "member_name": member.name,
            "full_name": member.full_name,
            "payment_method": getattr(member, "payment_method", "Not set"),
            "iban": getattr(member, "iban", "Not set"),
            "bic": getattr(member, "bic", "Not set"),
            "bank_account_name": getattr(member, "bank_account_name", "Not set"),
            "application_id": getattr(member, "application_id", "Not set"),
            "application_status": getattr(member, "application_status", "Not set"),
        }

        return result

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
@standard_api()  # Financial debugging tool
def debug_custom_amount_flow(member_name):
    """Debug the custom amount flow for a specific member"""
    try:
        member = frappe.get_doc("Member", member_name)

        result = {
            "member_name": member_name,
            "full_name": member.full_name,
            "has_notes": bool(getattr(member, "notes", None)),
            "notes": getattr(member, "notes", ""),
            "custom_amount_data": None,
            "error": None,
        }

        # Legacy JSON parsing removed - check direct fee override field
        result["dues_rate"] = getattr(member, "dues_rate", None)
        result["uses_custom_amount"] = bool(getattr(member, "dues_rate", None))
        result["membership_amount"] = getattr(member, "dues_rate", None)

        # Check existing memberships
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member_name},
            fields=["name", "membership_type", "status"],
        )

        result["memberships"] = memberships

        # Check dues schedules if any
        for membership in memberships:
            dues_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member_name},
                fields=["name", "payment_terms_template", "dues_rate", "billing_frequency", "status"],
            )
            membership["dues_schedules"] = dues_schedules

        return result

    except Exception as e:
        return {"error": str(e), "member_name": member_name}


# Updated to use debug_membership_dues_schedule


# Updated to use debug_membership_dues_schedule


# Updated to use dues schedules


# Updated to use check_dues_schedule_invoice_relationship


@frappe.whitelist()
@standard_api()  # Notification sending utility
def send_overdue_notifications(**kwargs):
    """Send notifications for overdue applications (> 2 weeks)"""
    # This would be called by a scheduled job

    two_weeks_ago = add_days(today(), -14)

    # Get overdue applications
    overdue = frappe.get_all(
        "Member",
        filters={"application_status": "Pending", "application_date": ["<", two_weeks_ago]},
        fields=["name", "full_name", "application_date"],
    )

    if not overdue:
        return

    # Group by chapter


# NEW FUNCTIONS - MODERNIZED FOR DUES SCHEDULE SYSTEM


@frappe.whitelist()
@standard_api()  # Membership debugging tool
def debug_membership_dues_schedule(membership_name):
    """Debug a specific membership and its dues schedule"""
    try:
        membership = frappe.get_doc("Membership", membership_name)

        result = {
            "membership_name": membership_name,
            # Custom amount fields removed - these don't exist in Membership DocType
            # Custom amount handling is via Membership Dues Schedule
            "billing_amount": membership.get_billing_amount(),
            "dues_schedules": [],
        }

        # Get all dues schedules for this member
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": membership.member},
            fields=[
                "name",
                "contribution_mode",
                "dues_rate",
                "billing_frequency",
                "status",
                "next_invoice_date",
                "last_invoice_date",
            ],
        )

        for schedule in dues_schedules:
            schedule_data = {
                "name": schedule.name,
                "contribution_mode": schedule.contribution_mode,
                "dues_rate": schedule.dues_rate,
                "billing_frequency": schedule.billing_frequency,
                "status": schedule.status,
                "next_invoice_date": schedule.next_invoice_date,
                "last_invoice_date": schedule.last_invoice_date,
            }
            result["dues_schedules"].append(schedule_data)

        return result

    except Exception as e:
        return {"error": str(e), "membership_name": membership_name}


@frappe.whitelist()
@standard_api()  # Configuration debugging tool
def debug_membership_type_settings(membership_type_name):
    """Debug a membership type and its settings"""
    try:
        membership_type = frappe.get_doc("Membership Type", membership_type_name)

        # Get amount from template
        if not membership_type.dues_schedule_template:
            frappe.throw(f"Membership Type '{membership_type.name}' must have a dues schedule template")
        template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)

        result = {
            "membership_type_name": membership_type_name,
            "membership_type_details": {
                "membership_type_name": membership_type.membership_type_name,
                "amount": template.suggested_amount or 0,
                "description": membership_type.description,
            },
        }

        return result

    except Exception as e:
        return {"error": str(e), "membership_type_name": membership_type_name}


@frappe.whitelist()
@standard_api()  # Invoice relationship validation
def check_dues_schedule_invoice_relationship(invoice_name):
    """Check dues schedule invoice relationships"""
    try:
        invoice = frappe.get_doc("Sales Invoice", invoice_name)

        result = {
            "invoice_name": invoice_name,
            "customer": invoice.customer,
            "grand_total": invoice.grand_total,
            "docstatus": invoice.docstatus,
            "status": invoice.status,
            "dues_schedule": None,
        }

        # Find related dues schedule
        if invoice.customer:
            member = frappe.db.get_value("Member", {"customer": invoice.customer}, "name")
            if member:
                dues_schedule = frappe.get_all(
                    "Membership Dues Schedule",
                    filters={"member": member, "status": "Active"},
                    fields=["name", "contribution_mode", "dues_rate"],
                    limit=1,
                )
                if dues_schedule:
                    result["dues_schedule"] = dues_schedule[0]

        return result

    except Exception as e:
        return {"error": str(e), "invoice_name": invoice_name}


def notify_chapter_of_overdue_applications(chapter_name, applications):
    """Notify chapter board of overdue applications"""
    chapter = frappe.get_doc("Chapter", chapter_name)

    # Get board members with membership permissions
    recipients = []
    for board_member in chapter.board_members:
        if board_member.is_active and board_member.email:
            role = frappe.get_doc("Chapter Role", board_member.chapter_role)
            if role.permissions_level in ["Admin", "Membership"]:
                recipients.append(board_member.email)

    if recipients:
        # Create application list HTML
        # app_list = "\n".join(
        #     [
        #         f"<li>{app.full_name} - Applied {frappe.format_date(app.application_date)} "
        #         f"({(getdate(today()) - getdate(app.application_date)).days} days ago)</li>"
        #         for app in applications
        #     ]
        # )

        email_service = get_email_service()
        email_service.send_simple_email(
            recipients=recipients,
            subject=f"Action Required: {len(applications)} Overdue Membership Applications",
            message="""
            <h3>Overdue Membership Applications for {chapter_name}</h3>

            <p>The following membership applications have been pending for more than 2 weeks:</p>

            <ul>
            {app_list}
            </ul>

            <p>Please review these applications as soon as possible.</p>

            <p><a href="{frappe.utils.get_url()}/app/report/pending-membership-applications?chapter={chapter_name}">
            View All Pending Applications</a></p>
            """,
            now=True,
            notification_key="member_application_overdue",
        )


def notify_managers_of_overdue_applications(applications):
    """Notify association managers of overdue applications without chapters"""
    # Get all association managers
    managers = frappe.get_all("Has Role", filters={"role": "Verenigingen Administrator"}, pluck="parent")

    if managers:
        recipients = [
            frappe.get_value("User", m, "email") for m in managers if frappe.get_value("User", m, "enabled")
        ]

        if recipients:
            # app_list = "\n".join(
            #     [
            #         f"<li>{app.full_name} - Applied {frappe.format_date(app.application_date)} "
            #         f"({(getdate(today()) - getdate(app.application_date)).days} days ago)</li>"
            #         for app in applications
            #     ]
            # )

            email_service = get_email_service()
            email_service.send_simple_email(
                recipients=recipients,
                subject=f"Action Required: {len(applications)} Unassigned Overdue Applications",
                message="""
                <h3>Overdue Membership Applications Without Chapter Assignment</h3>

                <p>The following membership applications have been pending for more than 2 weeks
                and have no chapter assignment:</p>

                <ul>
                {app_list}
                </ul>

                <p>Please review and assign these applications to appropriate chapters.</p>

                <p><a href="{frappe.utils.get_url()}/app/report/pending-membership-applications?chapter=Unassigned">
                View Unassigned Applications</a></p>
                """,
                now=True,
                notification_key="member_application_overdue",
            )


@frappe.whitelist()
@critical_api()  # System configuration management
def create_default_email_templates():
    """Create default email templates for membership application management"""
    if not frappe.has_permission("Email Template", "create"):
        frappe.throw(_("You don't have permission to create email templates"))

    templates = []

    # 1. General rejection template
    if not frappe.db.exists("Email Template", "membership_application_rejected"):
        rejection_template = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "membership_application_rejected",
                "subject": "Membership Application Update - {{ member_name }}",
                "enabled": 1,
                "response": """
<h3>Membership Application Update</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>After careful review, we regret to inform you that your membership application has not been approved at this time.</p>

<div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Reason:</strong> {{ reason }}</p>
</div>

<p>If you have any questions or would like to discuss this decision, please don't hesitate to contact us.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>
            """.strip(),
            }
        )
        rejection_template.insert()
        templates.append("membership_application_rejected")

    # 2. Incomplete information rejection
    if not frappe.db.exists("Email Template", "membership_rejection_incomplete"):
        incomplete_template = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "membership_rejection_incomplete",
                "subject": "Membership Application - Additional Information Required - {{ member_name }}",
                "enabled": 1,
                "response": """
<h3>Membership Application - Additional Information Required</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>We have reviewed your membership application, but unfortunately we need additional information to proceed with your application.</p>

<div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Missing Information:</strong> {{ reason }}</p>
</div>

<p>You are welcome to submit a new application with the complete information at any time. We encourage you to reapply once you have the required documentation or details.</p>

<p>If you have any questions about what information is needed, please don't hesitate to contact us.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>
            """.strip(),
            }
        )
        incomplete_template.insert()
        templates.append("membership_rejection_incomplete")

    # 3. Ineligible rejection
    if not frappe.db.exists("Email Template", "membership_rejection_ineligible"):
        ineligible_template = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "membership_rejection_ineligible",
                "subject": "Membership Application Update - {{ member_name }}",
                "response": """
<h3>Membership Application Update</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>After careful review of your application, we regret to inform you that you do not currently meet the eligibility requirements for membership.</p>

<div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Details:</strong> {{ reason }}</p>
</div>

<p>We encourage you to review our membership requirements and consider reapplying in the future if your circumstances change.</p>

<p>If you have any questions about our membership criteria, please don't hesitate to contact us.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>
            """.strip(),
            }
        )
        ineligible_template.insert()
        templates.append("membership_rejection_ineligible")

    # 4. Duplicate application rejection
    if not frappe.db.exists("Email Template", "membership_rejection_duplicate"):
        duplicate_template = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "membership_rejection_duplicate",
                "subject": "Membership Application - Duplicate Detected - {{ member_name }}",
                "response": """
<h3>Membership Application - Duplicate Application</h3>

<p>Dear {{ first_name }},</p>

<p>Thank you for your interest in joining our association.</p>

<p>We have detected that you have already submitted a membership application or are already a member of our association.</p>

<div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <p><strong>Application ID:</strong> {{ application_id }}</p>
    <p><strong>Details:</strong> {{ reason }}</p>
</div>

<p>If you believe this is an error or if you need assistance with your existing membership, please contact us immediately.</p>

<p>If you have any questions, please don't hesitate to reach out.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>
            """.strip(),
            }
        )
        duplicate_template.insert()
        templates.append("membership_rejection_duplicate")

    # Also create approval template if it doesn't exist
    if not frappe.db.exists("Email Template", "membership_application_approved"):
        approval_template = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": "membership_application_approved",
                "subject": "Membership Application Approved - Payment Required - {{ member_name }}",
                "response": """
<h2>🎉 Membership Application Approved!</h2>

<p>Dear {{ first_name }},</p>

<p>Congratulations! Your membership application has been approved.</p>

<div style="background: #d4edda; border: 1px solid #c3e6cb; padding: 15px; border-radius: 5px; margin: 15px 0;">
    <h4>Application Details:</h4>
    <ul>
        <li><strong>Application ID:</strong> {{ application_id }}</li>
        <li><strong>Membership Type:</strong> {{ membership_type.membership_type_name }}</li>
        <li><strong>Fee Amount:</strong> {{ payment_amount }}</li>
    </ul>
</div>

<p>To complete your membership, please pay the membership fee using the link below:</p>

<div style="text-align: center; margin: 20px 0;">
    <a href="{{ payment_url }}" style="background-color: #4CAF50; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; display: inline-block;">
        Pay Membership Fee
    </a>
</div>

<p>Your membership will be activated immediately after payment confirmation.</p>

<p>If you have any questions, please don't hesitate to contact us.</p>

<p>Best regards,<br>The Membership Team<br>{{ company }}</p>
            """.strip(),
            }
        )
        approval_template.insert()
        templates.append("membership_application_approved")

    # Note: Frappe automatically commits template creation

    return {"success": True, "message": f"Created {len(templates)} email templates", "templates": templates}


def validate_membership_type_for_approval(membership_type, member, is_application_approval=False):
    """
    Validate that the membership type has a proper dues schedule template
    and all required fields are properly configured before approval

    Args:
        membership_type: The membership type to validate
        member: The member record
        is_application_approval: If True, skip existing membership validation
    """
    # Check if membership type exists and is active
    if not frappe.db.exists("Membership Type", membership_type):
        frappe.throw(_("Membership Type {0} does not exist").format(membership_type))

    membership_type_doc = frappe.get_doc("Membership Type", membership_type)

    # Check if membership type is active
    if hasattr(membership_type_doc, "is_active") and not membership_type_doc.is_active:
        frappe.throw(_("Membership Type {0} is not active").format(membership_type))

    # Check if dues schedule template exists
    template_exists = frappe.db.exists(
        "Membership Dues Schedule", {"membership_type": membership_type, "is_template": 1, "status": "Active"}
    )

    if not template_exists:
        frappe.throw(
            _(
                "Cannot approve application: Membership Type {0} does not have a valid dues schedule template. "
                "Please create a dues schedule template for this membership type first."
            ).format(membership_type)
        )

    # Get the template and validate it
    template = frappe.get_doc(
        "Membership Dues Schedule", {"membership_type": membership_type, "is_template": 1, "status": "Active"}
    )

    # Validate template has required fields
    validation_errors = []

    # Check required fields
    if not template.billing_frequency:
        validation_errors.append(_("Billing frequency is not set"))

    if not template.dues_rate or template.dues_rate <= 0:
        validation_errors.append(_("Amount must be greater than 0"))

    if not template.contribution_mode:
        validation_errors.append(_("Contribution mode is not set"))

    # Check if auto_generate is enabled (optional but recommended)
    if not template.auto_generate:
        frappe.msgprint(
            _(
                "Warning: Auto-generate is disabled for this membership type. "
                "Invoices will need to be created manually."
            ),
            alert=True,
        )

    # Validate member-specific requirements
    if member and not is_application_approval:
        # Check if member already has an active membership
        # Skip this check for application approvals as they may create the first membership
        existing_membership = frappe.db.exists(
            "Membership", {"member": member.name, "status": "Active", "docstatus": 1}
        )

        if existing_membership:
            frappe.throw(
                _(
                    "Member {0} already has an active membership. "
                    "Please cancel or terminate the existing membership first."
                ).format(member.name)
            )

        # Check if member already has an active dues schedule
        existing_schedule = frappe.db.exists(
            "Membership Dues Schedule",
            {"member": member.name, "is_template": 0, "status": ["in", ["Active", "Grace Period"]]},
        )

        if existing_schedule:
            frappe.throw(
                _(
                    "Member {0} already has an active dues schedule. "
                    "Please resolve the existing schedule first."
                ).format(member.name)
            )

        # Validate member has required fields for billing
        if hasattr(member, "email") and not member.email:
            validation_errors.append(_("Member email is required for billing notifications"))

        # Check if SEPA is required but member has no valid IBAN
        # Note: We don't block approval for missing IBAN as members can add it later
        if hasattr(member, "iban") and not member.iban:
            frappe.msgprint(
                _(
                    "Note: Member has no IBAN configured. "
                    "They will need to add payment details before SEPA collection can begin."
                ),
                alert=True,
            )

    if validation_errors:
        frappe.throw(
            _("Cannot approve application due to the following issues with the dues schedule template:<br>")
            + "<br>".join(f"• {error}" for error in validation_errors)
        )


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
