"""
API endpoints for reviewing and managing membership applications
"""

import json

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, today

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
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS, rollback_to_savepoint
from verenigingen.utils.validation.api_validators import APIValidator


def _sanitize_application_name(application_name, operation_label):
    """Sanitize the raw application_name before anything uses it (the permission check, the advisory lock
    name, the lookup): HTML-escaped, and refused as invalid input past 255 characters rather than reaching
    the database. Applied first, so it cannot tell an unknown name from a foreign one.

    Raises:
        frappe.ValidationError: On sanitization failure.
    """
    try:
        return APIValidator.sanitize_text(str(application_name), max_length=255)
    except frappe.ValidationError:
        raise
    except Exception as e:
        log_security_event(
            "validation_failed",
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


def _activate_pending_chapter_memberships(member):
    """Activate any Chapter Member rows that are 'Pending' for this member.

    The membership application form creates Chapter Member rows in status
    ``Pending`` at submit time (when the applicant picks a chapter). On
    approval, those rows must be flipped to ``Active`` so the member's
    chapter assignment is real. The deprecated ``MemberLifecycleService``
    had this step in ``_perform_post_approval_setup``; it now lives here
    so the canonical approval path is behaviourally complete.

    Note on Chapter Member SQL: it is a child table on Chapter, so the
    chapter name lives in ``parent`` (not in a ``chapter`` column).
    Filtering by ``member`` + ``status='Pending'`` finds every pending row
    for the member regardless of which chapter it belongs to - in practice
    a member usually has at most one, but multi-chapter applications exist.

    Errors are logged but do not fail the approval - the membership and
    invoice have already been created at the call site, and a follow-up
    chapter manual activation is recoverable.
    """
    try:
        from verenigingen.utils.application_helpers import activate_pending_chapter_membership

        pending = frappe.db.sql(
            """
            SELECT parent AS chapter
            FROM `tabChapter Member`
            WHERE member = %s AND status = 'Pending'
            """,
            (member.name,),
            as_dict=True,
        )
        for row in pending:
            try:
                activate_pending_chapter_membership(member, row.chapter)
            except Exception as e:  # noqa: BLE001
                frappe.logger().warning(
                    f"Failed to activate pending Chapter Member for member="
                    f"{member.name} chapter={row.chapter}: {e}"
                )
    except Exception as e:  # noqa: BLE001
        frappe.logger().warning(f"Pending chapter activation step failed for member={member.name}: {e}")


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
        from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager

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
    # for_update performs a locking "current read" that returns the latest
    # COMMITTED application_status rather than this transaction's REPEATABLE READ
    # snapshot. This is what lets a concurrent approval (running under the
    # per-member advisory lock acquired by the caller) observe a racing winner's
    # committed Approved status and short-circuit, without committing the caller's
    # own transaction. Harmless for the direct unit-test callers (brief row lock).
    member_status = frappe.db.get_value(
        "Member", member_name, ["application_status", "status"], as_dict=True, for_update=True
    )
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


def _refuse_if_terminated_after_application(member):
    """Refuse approval when the member's most recent Executed termination
    postdates this application's application_date -- see the call site for
    why a silent approval would be wrong here."""
    termination = frappe.db.get_value(
        "Membership Termination Request",
        {"member": member.name, "status": "Executed"},
        ["name", "termination_date", "execution_date"],
        order_by="execution_date desc",
        as_dict=True,
    )
    if not termination or not member.application_date:
        return

    effective_date = termination.termination_date or termination.execution_date
    if effective_date and getdate(effective_date) > getdate(member.application_date):
        frappe.throw(
            _(
                "This member was terminated on {0}, after this application was submitted on {1}. "
                "Please review this case manually before approving."
            ).format(
                frappe.utils.format_date(effective_date),
                frappe.utils.format_date(member.application_date),
            )
        )


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
            # AgeValidator.validate_age returns an AgeValidationResult object
            # (attributes is_valid/message), not a dict — use attribute access.
            if not age_result.is_valid:
                frappe.throw(
                    _("Cannot activate as volunteer: {0}").format(
                        age_result.message or "Age requirement not met"
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


def _account_meta(user_creation_result):
    """The account outcome's ``action`` / ``account_request`` live under ``meta``.

    ``create_secure_user_account_for_member`` returns ``OperationResult.to_dict()``, which
    nests them there; reading them at the top level never matched (#1739). The failure dicts
    built in ``_create_user_account_safe`` have no ``meta`` and yield ``{}``.
    """
    return user_creation_result.get("meta") or {}


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
    account_meta = _account_meta(user_creation_result)
    if account_meta.get("action") == "queued_secure":
        frappe.logger().info(
            f"User account creation queued for member {member.name} - AccountCreationManager will handle all user setup"
        )
    elif user_creation_result.get("success"):
        frappe.logger().info(
            f"User account {'linked' if account_meta.get('action') == 'linked_existing' else 'processed'} for member {member.name}"
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


def _build_approval_response(member, invoice, billing_amount, user_creation_result, invoice_requested=False):
    """Build approval response dict with 5-way user account status branching.

    invoice_requested: the caller asked for an invoice. With no invoice then, the response
    says so instead of claiming one was sent (#1774); the Error Log row is written where
    the failure happens (MembershipCreationService._create_membership_invoice).
    """
    invoice_failed = bool(invoice_requested and not invoice)
    if invoice_failed:
        message = _(
            "Application approved, but the membership invoice could NOT be created, so no invoice "
            "was sent to the applicant. See the Error Log, then create the invoice manually."
        )
    else:
        message = _("Application approved. Invoice sent to applicant.")
    user_account_status = "pending"
    user_account_error_code = None
    account_meta = _account_meta(user_creation_result)

    if user_creation_result.get("success"):
        if account_meta.get("action") in ["created_new", "created_new_immediate"]:
            message += _(" User account created for portal access.")
            user_account_status = "created"
            if account_meta.get("action") == "created_new_immediate":
                # Show success message for immediate processing
                frappe.msgprint(
                    _("✅ User account created successfully! The member can now log in to the portal."),
                    title=_("Account Created"),
                    indicator="green",
                )
        elif account_meta.get("action") == "linked_existing":
            message += _(" Linked to existing user account.")
            user_account_status = "linked"
        elif account_meta.get("action") == "queued_secure":
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
        user_account_error = user_creation_result.get("error")
        if isinstance(user_account_error, dict):
            # Fixed text only: the raw reason can carry exception text and is rendered by desk JS.
            # The detail is in the Error Log.
            user_account_error_code = user_account_error.get("code")
            if user_account_error_code:
                message += _(" Reason code: {0}. See the Error Log for details.").format(
                    user_account_error_code
                )

    response = {
        "success": True,
        "message": message,
        "invoice": invoice.name if invoice else None,
        "invoice_failed": invoice_failed,
        "amount": billing_amount,
        "user_account": user_creation_result,
        "user_account_status": user_account_status,
        # Enhanced progress tracking for better UX
        "progress_tracking": {
            "account_request_id": account_meta.get("account_request"),
            "estimated_completion": "2-3 minutes" if user_account_status == "queued" else None,
            "tracking_url": (
                f"/app/account-creation-request/{account_meta.get('account_request')}"
                if account_meta.get("account_request")
                else None
            ),
        },
    }
    if user_account_error_code:
        response["user_account_error_code"] = user_account_error_code
    return response


def _approve_membership_application_locked(
    member_name, membership_type, chapter, notes, create_invoice, activate_as_volunteer
):
    """Core approval logic, run by approve_application while it holds the per-application advisory lock.

    Split out of approve_application so the whole critical section (idempotency re-check through
    membership creation) runs under the lock. See approve_application for why a GET_LOCK advisory
    lock and a locking read are required. The core is keyed on the Member materialise_member created
    (or updated); its idempotency guard is what makes a retry after a partial failure safe.
    """
    # Idempotency check - if already approved, return success
    idempotent_result = _handle_idempotent_approval(member_name)
    if idempotent_result:
        return idempotent_result

    member = frappe.get_doc("Member", member_name)

    # Validate application can be approved
    if member.application_status not in ["Pending"]:
        frappe.throw(_("This application cannot be approved in its current state"))

    # #1544/#1548 follow-up: refuse rather than silently reactivate a member
    # who was terminated WHILE this application was still Pending.
    # validate_termination_request() does not block creating a termination
    # against a Pending member, so this is reachable: approval always resets
    # member_since to today, which (correctly, per #1544's own rule) makes
    # that termination look superseded to member_utils.
    # update_termination_status_display -- but it is NOT a genuine rejoin. A
    # genuine rejoin's application_date is set to now() by
    # materialise_member, strictly AFTER the termination it
    # responds to; here the application predates the termination, so this is
    # the SAME still-open application, not a new one. Whether it should
    # proceed with the member reactivated, left Quit, or something else is a
    # product decision nobody has made -- refuse instead of guessing.
    _refuse_if_terminated_after_application(member)

    # Chapter permission was already checked in approve_application, before
    # the advisory lock (#1414) -- do not re-check here.

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
    # Honor the caller's create_invoice flag. Historically this was hardcoded to
    # True, silently ignoring create_invoice=False (e.g. historic CSV imports or
    # approvals where billing is handled separately). The bug was masked while
    # invoice creation failed silently; thread the parameter through so the
    # documented flag actually takes effect.
    membership = member.create_membership_on_approval(
        create_invoice=create_invoice, approval_fields=approval_fields
    )

    # Activate any pre-existing pending Chapter Member rows. The application
    # form creates a Chapter Member row in status "Pending" when the applicant
    # chooses a chapter at submit time. The deprecated MemberLifecycleService
    # had this step; the canonical path needs it too so members don't lose
    # their chapter assignment on approval. T4.1 §2.3 - ported here before
    # the lifecycle service is deleted.
    _activate_pending_chapter_memberships(member)

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

    return _build_approval_response(
        member, invoice, billing_amount, user_creation_result, invoice_requested=create_invoice
    )


@frappe.whitelist()
@high_security_api()  # Application approval: creates the Member (#1765)
def approve_application(
    application_name: str,
    membership_type: str = None,
    chapter: str = None,
    notes: str = None,
    create_invoice: bool = True,
    activate_as_volunteer: bool = False,
):
    """Approve a Membership Application Submission: create (or update) the Member, then run the approval core.

    The permission check comes first and refuses an unknown application exactly like a foreign one
    (Ruling M: loading the application first would answer DoesNotExist for the unknown name only).

    Concurrency: the whole approval runs under a MySQL advisory lock per application (GET_LOCK), and the
    application is re-read with FOR UPDATE inside it. A row lock alone is not enough: the membership
    creation service and the account-creation pattern issue intermediate commits, which release any
    FOR UPDATE lock mid-operation, whereas an advisory lock is NOT released by a commit. The locking read
    matters because under REPEATABLE READ a plain read returns this transaction's snapshot, taken before a
    racing winner committed; a locking "current read" sees the latest committed status, so the loser is
    refused instead of approving the same application twice. (One Pending Review application per email can
    exist: a newer one supersedes the older, so the per-application lock also serialises the email.)
    """
    from verenigingen.services.chapter.chapter_security import validate_application_permission_or_throw
    from verenigingen.utils.db_advisory_lock import advisory_lock

    application_name = _sanitize_application_name(application_name, "approval")
    sanitized = _sanitize_text_fields(
        {"membership_type": (membership_type, 255), "chapter": (chapter, 255), "notes": (notes, 2000, False)}
    )
    validate_application_permission_or_throw(application_name, "approve")
    with advisory_lock(f"approve_application:{application_name}", timeout=30):
        return _approve_application_locked(
            application_name,
            sanitized["membership_type"],
            sanitized["chapter"],
            sanitized["notes"],
            create_invoice,
            activate_as_volunteer,
        )


def _approve_application_locked(
    application_name, membership_type, chapter, notes, create_invoice, activate_as_volunteer
):
    from verenigingen.services.member.application.application_materialiser import materialise_member

    application = _lock_pending_review_application(
        application_name, _("This application cannot be approved in its current state")
    )
    _refuse_unless_approvable(application, chapter)

    savepoint = f"approve_{frappe.generate_hash(length=10)}"
    frappe.db.savepoint(savepoint)
    try:
        member = materialise_member(application)
        # The outcome is written BEFORE the core: the core commits once (member_user_account_service,
        # Pattern 1) for a Member that already has a User, and that commit must find Member Active and
        # application Approved together, never Member Active with an application no retry can approve.
        # A failure in the core before that commit rolls both back through the savepoint; one after it
        # leaves the application Approved with a partly approved Member, as the member-keyed approval did.
        application.set_status("Approved")
        application.db_set(
            {
                "member": member.name,
                "reviewed_by": frappe.session.user,
                "review_date": now_datetime(),
                "review_notes": notes,
            }
        )
        response = _approve_membership_application_locked(
            member.name, membership_type, chapter, notes, create_invoice, activate_as_volunteer
        )
    except NON_RESUMABLE_DB_ERRORS:
        raise  # the server already discarded the transaction, and the savepoint with it
    except Exception:  # swallow-ok: re-raised below
        if not rollback_to_savepoint(savepoint):
            frappe.db.rollback()  # savepoint already gone (a nested commit): nothing was undone
        raise
    response["member"] = member.name
    response["application"] = application.name
    return response


def _lock_pending_review_application(application_name, refusal):
    """Row-lock the application (fresh read) and refuse unless it is Pending Review; shared by approve and reject."""
    try:
        application = frappe.get_doc("Membership Application Submission", application_name, for_update=True)
    except frappe.DoesNotExistError:
        # Only a caller whose chapter access is "all" reaches here for an unknown name (the permission check
        # refuses everyone else identically to a foreign one), so the distinguishable error tells them nothing new.
        from verenigingen.services.chapter.chapter_security import record_application_security_event

        record_application_security_event(
            "unauthorized_access_attempt",
            "error",
            f"Attempted review of non-existent application: {application_name}",
        )
        raise
    if application.status != "Pending Review":
        frappe.throw(refusal)
    return application


def _refuse_unless_approvable(application, chapter):
    from verenigingen.api.membership_application import _handle_existing_member
    from verenigingen.services.chapter.chapter_security import get_user_manageable_chapters

    # Only an admin may place the member in a chapter other than the one the application names.
    if chapter and chapter != application.chapter and get_user_manageable_chapters() != "all":
        frappe.throw(_("You don't have permission to approve this application"), frappe.PermissionError)
    existing = frappe.db.get_value(
        "Member", {"email": application.email}, ["name", "status", "application_status"], as_dict=True
    )
    if existing:
        _action, blocked = _handle_existing_member(existing, {})
        if blocked:  # became Active, or was terminated, since the application was confirmed
            frappe.throw(_("This application cannot be approved in its current state"))


@frappe.whitelist()
@standard_api()  # Read-only preview of what approving would change (#1765)
def get_application_changes(application_name: str) -> list[dict]:
    """Rows `{field, label, current, proposed}`: what approving this application would change on the
    existing Member ([] for a new applicant). Any active seat on the application's chapter may read it;
    the IBAN is shown in full only to a Verenigingen Administrator or System Manager, masked for everyone
    else, in both columns. The permission check comes first (Ruling M): an unknown application is refused
    exactly like a foreign one."""
    from verenigingen.services.chapter.chapter_security import validate_application_permission_or_throw
    from verenigingen.services.member.application.application_materialiser import application_changes
    from verenigingen.utils.error_handling import mask_iban

    application_name = _sanitize_application_name(application_name, "change preview")
    validate_application_permission_or_throw(application_name, "read")
    application = frappe.get_doc("Membership Application Submission", application_name)
    rows = application_changes(application)
    if not Roles.ADMIN_PAIR.intersection(frappe.get_roles()):
        for row in rows:
            if row["field"] == "iban":
                row["current"], row["proposed"] = mask_iban(row["current"]), mask_iban(row["proposed"])
    return rows


@frappe.whitelist()
@high_security_api()  # Application rejection: touches only the application (#1765)
def reject_application(
    application_name: str,
    reason: str,
    email_template: str = None,
    rejection_category: str = None,
    internal_notes: str = None,
):
    """Reject a Membership Application Submission. No Member is read or written, and nothing is refunded
    (an application never holds an invoice). Same permission order as approve_application (Ruling M)."""
    from verenigingen.services.chapter.chapter_security import validate_application_permission_or_throw
    from verenigingen.utils.db_advisory_lock import advisory_lock

    application_name = _sanitize_application_name(application_name, "rejection")
    sanitized = _sanitize_text_fields(
        {
            "reason": (reason, 1000, False),
            "email_template": (email_template, 255),
            "rejection_category": (rejection_category, 255),
            "internal_notes": (internal_notes, 2000, False),
        }
    )
    validate_application_permission_or_throw(application_name, "reject")
    if sanitized["email_template"] and not frappe.db.exists("Email Template", sanitized["email_template"]):
        frappe.throw(_("Invalid email template specified"))
    with advisory_lock(f"reject_application:{application_name}", timeout=30):
        application = _lock_pending_review_application(
            application_name, _("This application cannot be rejected in its current state")
        )
        application.set_status("Rejected")
        application.db_set(
            {
                "reviewed_by": frappe.session.user,
                "review_date": now_datetime(),
                "review_notes": _rejection_review_notes(sanitized),
                "rejection_category": sanitized["rejection_category"],
            }
        )
    if not _notify_rejection_reporting_failure(application, sanitized):
        message = _(
            "Application rejected, but the notification mail could not be sent. Contact the applicant."
        )
        frappe.msgprint(message, indicator="orange", alert=True)
        return {"success": True, "mail_sent": False, "message": message}
    return {
        "success": True,
        "mail_sent": True,
        "message": _("Application rejected. Notification sent to applicant."),
    }


@frappe.whitelist()
@high_security_api()  # Asks the applicant a question: touches no Member, changes no status (#1765, #1874)
def request_more_info(application_name: str, info_needed: str):
    """Ask the applicant for more information by mail, and record who asked and when on the application.

    The mail is a Communication referencing the application, so the thread (and the applicant's reply)
    attaches to it. There is no status for this: the application stays Pending Review and can still be
    approved or rejected. Same permission order as reject_application (Ruling M).
    """
    from verenigingen.services.chapter.chapter_security import validate_application_permission_or_throw
    from verenigingen.utils.db_advisory_lock import advisory_lock

    application_name = _sanitize_application_name(application_name, "information request")
    # allow_html: the text is kept raw and escaped once, where it is rendered (mail body, timeline note)
    info_needed = _sanitize_text_fields({"info_needed": (info_needed, 2000, True)})["info_needed"]
    validate_application_permission_or_throw(application_name, "manage")
    if not info_needed:
        frappe.throw(_("Describe the information you need from the applicant"))
    with advisory_lock(f"reject_application:{application_name}", timeout=30):
        application = _lock_pending_review_application(
            application_name, _("This application cannot be asked for more information in its current state")
        )
        application.add_comment(
            "Info",
            _("{0} asked the applicant for more information: {1}").format(
                frappe.utils.escape_html(frappe.session.user), frappe.utils.escape_html(info_needed)
            ),
        )
    if not _mail_information_request(application, info_needed):
        message = _("Request recorded, but the mail could not be sent. Contact the applicant another way.")
        frappe.msgprint(message, indicator="orange", alert=True)
        return {"success": True, "mail_sent": False, "message": message}
    return {"success": True, "mail_sent": True, "message": _("Request sent to the applicant.")}


def _mail_information_request(application, info_needed) -> bool:
    """Send the request as a Communication on the application; False (and an Error Log row) on failure.

    `_make` rather than `make`: `make` re-checks the Frappe "email" permission on the application, which a
    chapter board member does not hold; the application's own manage check has already passed. The call sits
    in a savepoint so a failure after the Communication was inserted leaves no "Sent" row behind.
    """
    from frappe.core.doctype.communication.email import _make

    escape = frappe.utils.escape_html
    content = "".join(
        (
            "<p>{}</p>".format(_("Dear {0},").format(escape(application.applicant_name))),
            "<p>{}</p>".format(
                _(
                    "Thank you for your membership application. We need some additional information to process it:"
                )
            ),
            "<p><strong>{}</strong></p>".format(escape(info_needed).replace("\n", "<br>")),
            "<p>{}</p>".format(_("Please reply to this email with the requested information.")),
            "<p>{}<br>{}</p>".format(_("Best regards,"), _("The Membership Team")),
        )
    )
    savepoint = f"info_request_{frappe.generate_hash(length=10)}"
    frappe.db.savepoint(savepoint)
    try:
        _make(
            doctype="Membership Application Submission",
            name=application.name,
            content=content,
            subject=_("Additional Information Required for Your Membership Application"),
            recipients=application.email,
            send_email=True,
        )
    except NON_RESUMABLE_DB_ERRORS:
        raise  # the server already discarded the transaction: the recorded request is gone, so do not report it
    except Exception:  # swallow-ok: caller-checks (False is reported to the reviewer; traceback logged)
        rollback_to_savepoint(savepoint)
        frappe.log_error(
            title=f"Information request mail failed for application {application.name}",
            message=frappe.get_traceback(),
        )
        return False
    return True


def _notify_rejection_reporting_failure(application, sanitized) -> bool:
    """Mail the applicant; False (and an Error Log row) when the mail failed or the service raised.

    The rejection stays committed either way: the decision is made, a mail is a side effect, and rolling
    back would make the reviewer redo a decision because an SMTP-side service failed. The reviewer is told
    instead (the caller turns False into a visible message).
    """
    try:
        result = send_application_rejection_notification(
            application, sanitized["reason"], sanitized["email_template"], sanitized["rejection_category"]
        )
    except NON_RESUMABLE_DB_ERRORS:
        raise  # the server already discarded the transaction: the rejection is gone, so do not report success
    except Exception:  # swallow-ok: caller-checks (False is reported to the reviewer; traceback logged)
        frappe.log_error(
            title=f"Rejection mail raised for application {application.name}", message=frappe.get_traceback()
        )
        return False
    if result.success:
        return True
    frappe.log_error(
        title=f"Rejection mail failed for application {application.name}",
        message="; ".join(result.errors or [])
        or result.error_message
        or "no error detail from the email service",
    )
    return False


def _rejection_review_notes(sanitized):
    notes = f"Rejection Category: {sanitized['rejection_category'] or 'Not specified'}\n"
    notes += f"Reason: {sanitized['reason']}\n"
    if sanitized["internal_notes"]:
        notes += f"Internal Notes: {sanitized['internal_notes']}\n"
    return notes + f"Email Template Used: {sanitized['email_template'] or 'Default'}"


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
                if level == "Admin" and position.parent not in user_chapters:
                    user_chapters.append(position.parent)

    # Check national chapter access
    national_access = False
    try:
        national_chapter = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        if national_chapter and national_chapter in user_chapters:
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
        frappe.log_error(
            title="Approval Notification Failed",
            message=f"Failed to send approval notification to {member.email}: {'; '.join(result.errors or [])}",
        )

    return result


def send_application_rejection_notification(
    application, reason, email_template=None, rejection_category=None
):
    """Rejection mail for a Membership Application Submission: no Member exists to read the names from (#1765)."""
    payload = json.loads(application.payload or "{}")
    applicant = frappe._dict(
        name=application.name,
        email=application.email,
        first_name=payload.get("first_name"),
        full_name=application.applicant_name,
    )
    return _send_rejection_email(
        applicant,
        reason,
        email_template,
        rejection_category,
        application_id=application.application_id or application.name,
        reference_doctype="Membership Application Submission",
        reference_name=application.name,
    )


def _send_rejection_email(
    member, reason, email_template, rejection_category, application_id, reference_doctype, reference_name
):
    from verenigingen.services.communication.email_service import get_email_service

    # Prepare context with all necessary variables
    context = {
        "member": member,
        "reason": reason,
        "rejection_category": rejection_category or "Not specified",
        "company": frappe.defaults.get_global_default("company"),
        "member_name": member.full_name,
        "first_name": member.first_name,
        "application_id": application_id,
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
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        notification_key="member_application_rejected",
    )

    return result


@frappe.whitelist()
@standard_api()  # Application listing - read-only
def get_pending_applications(chapter: str | None = None, days_overdue: int | None = None):
    """Pending Review applications (not Members) the caller may read (#1765).

    Rows: name, application_id, applicant_name, email, membership_type, chapter, application_date
    (the confirmation time), days_pending. The scope is the MAS permission query, applied by
    `frappe.get_list`: a board member sees the chapters they hold a seat in, an admin everything.
    """
    from verenigingen.services.member.application.pending_applications import pending_review_applications

    return pending_review_applications(chapter=chapter, days_overdue=days_overdue)


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
            # Pass the long detail as `message` (longtext) and keep a short `title`:
            # frappe.log_error maps the FIRST positional arg to the Error Log `method`
            # field (Data, max 140), so a long first arg raises CharacterLengthExceededError
            # under strict validation — defeating this swallow path.
            frappe.log_error(
                title="Payment History Update Error",
                message=(
                    f"Invoice {invoice_name} customer ({invoice.customer}) does not match "
                    f"member {member_name} customer ({member.customer})"
                ),
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
                title="Payment History Update Error",
                message=f"Failed to update payment history for member {member_name} with invoice {invoice_name}",
            )

    except Exception as e:
        frappe.log_error(
            title="Payment History Update Error",
            message=f"Error updating payment history for member {member_name} with invoice {invoice_name}: {str(e)}",
        )
