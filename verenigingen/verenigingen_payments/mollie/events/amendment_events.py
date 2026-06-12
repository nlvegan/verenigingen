"""
Mollie Amendment Event Handlers

Event-driven handlers for syncing Mollie subscriptions when membership amendments are applied.
"""

import frappe

from verenigingen.utils.constants import Roles


def _sync_status_update_for_result(result):
    """Map a sync-result dict to (mollie_sync_status, completed_flag, notify_admins).

    Errors always notify - the previous behavior (notify only with
    requires_admin_review, status left 'In Progress') hid every failure.
    """
    status = result.get("status")
    if status == "success":
        return "Completed", 1, False
    if status == "skipped":
        return "Skipped", 0, False
    if status == "warning":
        return "Needs Review", 0, bool(result.get("requires_admin_review"))
    return "Failed", 0, True


def sync_mollie_subscription_on_amendment_applied(doc, method=None):
    """
    Background job handler for syncing Mollie subscriptions when amendments are applied.

    Syncs Mollie subscription to match the new membership terms by:
    1. Creating a new subscription with updated amount/interval
    2. Canceling the old subscription
    3. Preserving the billing cycle (next_payment_date)
    4. Verifying the amounts match with retry logic

    This runs as a background job to ensure database transaction commits before
    making external API calls to Mollie.

    Args:
        doc: ContributionAmendmentRequest document (or dict from background job)
        method: Event method name (unused but required by Frappe hooks)
    """
    # Handle both Document object and dict from background job
    if isinstance(doc, dict):
        doc_name = doc.get("name")
        doc = frappe.get_doc("Contribution Amendment Request", doc_name)

    # IDEMPOTENCY: Check if already processed to prevent duplicate syncs
    if frappe.db.get_value("Contribution Amendment Request", doc.name, "mollie_sync_completed"):
        frappe.logger().info(f"⏭️ Amendment {doc.name} already synced to Mollie, skipping duplicate event")
        return

    frappe.logger().info(f"📋 Starting Mollie subscription sync for amendment {doc.name}")

    # Update status to In Progress
    frappe.db.set_value(
        "Contribution Amendment Request", doc.name, "mollie_sync_status", "In Progress", update_modified=False
    )
    frappe.db.commit()

    # Import here to avoid circular dependencies
    from ..services.mollie_subscription_sync_service import MollieSubscriptionSyncService

    try:
        # Initialize sync service
        sync_service = MollieSubscriptionSyncService()

        # Sync subscription (handles all logic including verification and retry)
        result = sync_service.sync_subscription_for_amendment(doc)

        status_value, completed, notify = _sync_status_update_for_result(result)

        log_fn = (
            frappe.logger().warning if status_value in ("Needs Review", "Failed") else frappe.logger().info
        )
        log_fn(
            f"Mollie subscription sync for amendment {doc.name}: "
            f"{result.get('status')} -> {status_value} ({result.get('message') or result.get('reason') or ''})"
        )

        frappe.db.set_value(
            "Contribution Amendment Request",
            doc.name,
            {"mollie_sync_completed": completed, "mollie_sync_status": status_value},
            update_modified=False,
        )
        frappe.db.commit()

        if notify:
            notify_administrators_of_sync_issue(doc, result)

    except Exception as e:
        error_message = str(e)
        frappe.log_error(
            f"Unexpected error in Mollie subscription sync event handler for amendment {doc.name}: {error_message}",
            "Mollie Amendment Event Handler Error",
        )

        # Call failure handler on document
        try:
            doc.handle_mollie_sync_failure(error_message)
        except Exception as handler_error:
            frappe.log_error(
                f"Failed to execute failure handler: {str(handler_error)}",
                "Mollie Sync Failure Handler Error",
            )

        # Re-raise to mark background job as failed
        raise


def notify_administrators_of_sync_issue(amendment_doc, sync_result):
    """
    Notify administrators when subscription sync encounters issues.

    Uses EmailService for secure, templated notifications.

    Args:
        amendment_doc: ContributionAmendmentRequest document
        sync_result: Result dict from sync service
    """
    try:
        # Get membership and member details
        membership = frappe.get_doc("Membership", amendment_doc.membership)
        member = frappe.get_doc("Member", membership.member)

        # Get administrator emails
        admin_roles = [Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_ADMIN, "Verenigingen Financial Manager"]

        admin_emails = frappe.get_all(
            "Has Role",
            filters={"role": ["in", admin_roles], "parenttype": "User"},
            fields=["parent"],
            distinct=True,
        )

        recipients = [admin["parent"] for admin in admin_emails]

        if not recipients:
            frappe.logger().warning("No administrators found to notify about Mollie sync issue")
            return

        # Use EmailService for secure templated emails
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        # Prepare context for template
        context = {
            "amendment": amendment_doc,
            "member": member,
            "membership": membership,
            "sync_result": sync_result,
            "member_url": f"{frappe.utils.get_url()}/app/member/{member.name}",
            "amendment_url": f"{frappe.utils.get_url()}/app/contribution-amendment-request/{amendment_doc.name}",
        }

        # Send notification using EmailService
        result = email_service.send_email(
            recipients=recipients,
            subject=f"Mollie Subscription Sync Issue: {member.full_name}",
            message=_build_sync_issue_message(context),
            reference_doctype="Contribution Amendment Request",
            reference_name=amendment_doc.name,
        )

        if result["success"]:
            frappe.logger().info(
                f"📧 Sent Mollie subscription sync issue notification to {len(recipients)} administrators"
            )
        else:
            frappe.logger().error(f"Failed to send notification: {result.get('errors', 'Unknown error')}")

    except Exception as e:
        frappe.log_error(
            f"Failed to send administrator notification for amendment {amendment_doc.name}: {str(e)}",
            "Mollie Amendment Notification Error",
        )


def _build_sync_issue_message(context):
    """Build email message with proper escaping."""
    amendment = context["amendment"]
    member = context["member"]
    membership = context["membership"]
    sync_result = context["sync_result"]

    message = f"""
    <h3>Mollie Subscription Sync Issue Detected</h3>

    <p>A Mollie subscription sync encountered an issue that requires administrator review.</p>

    <h4>Amendment Details:</h4>
    <ul>
        <li><strong>Amendment:</strong> {frappe.utils.escape_html(amendment.name)}</li>
        <li><strong>Type:</strong> {frappe.utils.escape_html(amendment.amendment_type)}</li>
        <li><strong>Member:</strong> {frappe.utils.escape_html(member.full_name)} ({frappe.utils.escape_html(member.name)})</li>
        <li><strong>Membership:</strong> {frappe.utils.escape_html(membership.name)}</li>
    </ul>

    <h4>Sync Result:</h4>
    <ul>
        <li><strong>Status:</strong> {frappe.utils.escape_html(sync_result['status'])}</li>
        <li><strong>Message:</strong> {frappe.utils.escape_html(sync_result.get("message", ""))}</li>
    </ul>
    """

    if sync_result.get("subscription_id"):
        message += f"""
        <h4>Subscription Details:</h4>
        <ul>
            <li><strong>New Subscription ID:</strong> {frappe.utils.escape_html(sync_result['subscription_id'])}</li>
            <li><strong>Old Subscription ID:</strong> {frappe.utils.escape_html(sync_result.get('old_subscription_id', 'N/A'))}</li>
        </ul>
        """

    if sync_result.get("mollie_amount") and sync_result.get("expected_amount"):
        message += f"""
        <h4>Amount Mismatch:</h4>
        <ul>
            <li><strong>Mollie Amount:</strong> €{sync_result['mollie_amount']}</li>
            <li><strong>Expected Amount:</strong> €{sync_result['expected_amount']}</li>
        </ul>
        """

    message += f"""
    <p>
        <strong>Action Required:</strong> Please review the member's Mollie subscription
        and membership dues schedule to ensure they are correctly synchronized.
    </p>

    <p>
        <a href="{context['member_url']}">View Member Record</a> |
        <a href="{context['amendment_url']}">View Amendment</a>
    </p>
    """

    return message
