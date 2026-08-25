# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Webhook Event Handlers

Event-specific handlers for Ponto webhook events.
Each handler processes a specific event type and returns a result dict.

Split from webhook.py as part of HIGH-4 (PSP Integration Consolidation Plan).
"""

import re
from typing import Any, Dict

import frappe

from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS, rollback_to_savepoint
from verenigingen.verenigingen_payments.ponto.services.payment_entry_service import (
    create_ponto_payment_entry,
)

from .webhook_utils import (
    extract_account_id,
    extract_debtor_info,
    extract_payment_link_id,
    extract_payment_request_id,
    extract_payment_status,
)


def _get_webhook_user() -> str:
    """
    Get the configured webhook user for background job execution.

    Returns:
        str: Username from Verenigingen Payments Settings
    """
    from verenigingen.utils.service_user import get_service_user

    return get_service_user(
        settings_doctype="Verenigingen Payments Settings",
        user_field="webhook_user",
        service_name="Ponto Webhook",
    )


def import_transactions_job(account_id: str) -> Dict[str, Any]:
    """Background entry point for webhook-triggered transaction import.

    Exists because the identity has to be set INSIDE the job. frappe.enqueue has no
    `user` parameter (frappe/utils/background_jobs.py:76-93) - anything outside its
    signature lands in **kwargs and execute_job passes it straight to the job function
    (`retval = method(**kwargs)`), so `user=...` raises TypeError in the worker rather
    than changing who it runs as. The worker adopts `queue_args["user"] =
    frappe.session.user`, i.e. the ENQUEUING session, which is Guest for these
    allow_guest webhooks.

    frappe.set_user cannot go inside import_new_transactions itself: it has interactive
    callers (ponto_settings.py trigger_manual_sync, import_all_accounts) whose identity
    must be left alone.
    """
    from verenigingen.verenigingen_payments.ponto.services.transaction_import_service import (
        import_new_transactions,
    )

    frappe.set_user(_get_webhook_user())
    return import_new_transactions(account_id=account_id)


def _safe_savepoint_name(prefix: str, doc_name: str) -> str:
    """
    Build a MariaDB-safe savepoint identifier.

    Frappe's ``frappe.db.savepoint()`` interpolates the name straight into
    ``SAVEPOINT <name>`` SQL without quoting. Document names contain hyphens
    (e.g. ``PONTO-PAY-6206``, ``PL-2026-00001``), which are illegal in an
    unquoted MariaDB savepoint identifier and raise a 1064 syntax error.
    Replace any non-alphanumeric character with an underscore so the savepoint
    can be created and rolled back to safely.
    """
    return re.sub(r"[^0-9A-Za-z_]", "_", f"{prefix}_{doc_name}")


# =============================================================================
# Synchronization Event Handlers
# =============================================================================


def handle_sync_succeeded(
    event_data: Dict[str, Any],
    update_account_sync_status_fn=None,
) -> Dict[str, Any]:
    """
    Handle synchronization succeeded event.

    Args:
        event_data: Parsed webhook payload
        update_account_sync_status_fn: Function to update account sync status
            (injected from webhook.py for dependency inversion)
    """
    account_id = extract_account_id(event_data)
    frappe.logger().info(f"Ponto sync succeeded for account {account_id}")

    # Update bank account mapping sync status
    if account_id and update_account_sync_status_fn:
        update_account_sync_status_fn(account_id, status="OK")

    # Trigger transaction import
    if account_id:
        # Queue transaction import job with proper user context
        frappe.enqueue(
            "verenigingen.verenigingen_payments.ponto.api.webhook_handlers.import_transactions_job",
            account_id=account_id,
            queue="short",
            timeout=300,
        )
        return {"handled": True, "action": "transaction_import_queued", "account_id": account_id}

    return {"handled": True, "action": "logged"}


def handle_sync_failed(
    event_data: Dict[str, Any],
    update_account_sync_status_fn=None,
) -> Dict[str, Any]:
    """
    Handle synchronization failed event.

    These failures occur when Ponto cannot sync with the bank (bank-side issue).
    Common causes:
    - Bank session expired (needs re-authorization in Ponto)
    - Bank API temporarily unavailable
    - Rate limiting by the bank
    - Network issues between Ponto and bank

    The sync_subtype indicates what was being synced:
    - accountDetails: Account balance/details
    - accountTransactionsWithUnsettled: Transactions including pending ones
    """
    account_id = extract_account_id(event_data)

    # Extract error details from Ponto's response
    error_info = {}
    if "data" in event_data and "attributes" in event_data["data"]:
        attrs = event_data["data"]["attributes"]
        error_info = {
            "error_code": attrs.get("errorCode"),
            "error_message": attrs.get("errorMessage"),
            "sync_subtype": attrs.get("synchronizationSubtype"),
        }

    frappe.logger().warning(f"Ponto sync failed for account {account_id}: {error_info}")

    # Determine if this is a re-authorization issue
    error_code = error_info.get("error_code") or ""
    error_message = error_info.get("error_message") or ""
    needs_reauth = any(
        term in str(error_code).lower() or term in str(error_message).lower()
        for term in ["authorization", "consent", "expired", "revoked", "reauthorization"]
    )

    # Update bank account mapping sync status
    if account_id and update_account_sync_status_fn:
        if needs_reauth:
            status = "Needs Re-authorization"
            error_text = "Bank connection expired. Please re-authorize in Ponto dashboard."
        else:
            status = "Failed"
            error_text = error_info.get("error_message") or "Sync failed - see Ponto dashboard for details"

        update_account_sync_status_fn(account_id, status=status, error=error_text)

    # Log error for monitoring
    frappe.log_error(
        title="Ponto Sync Failed",
        message=f"Account: {account_id}\nError: {error_info}",
    )

    return {
        "handled": True,
        "action": "sync_failure_logged",
        "account_id": account_id,
        "needs_reauthorization": needs_reauth,
        "error_info": error_info,
    }


def handle_sync_no_change(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle synchronization succeeded without change event."""
    account_id = extract_account_id(event_data)
    frappe.logger().debug(f"Ponto sync completed with no new transactions for account {account_id}")
    return {"handled": True, "action": "logged", "account_id": account_id}


# =============================================================================
# Transaction Event Handlers
# =============================================================================


def handle_transactions_created(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle new transactions created event."""
    account_id = extract_account_id(event_data)
    frappe.logger().info(f"Ponto transactions created for account {account_id}")

    # Queue transaction import job
    if account_id:
        frappe.enqueue(
            "verenigingen.verenigingen_payments.ponto.api.webhook_handlers.import_transactions_job",
            account_id=account_id,
            queue="short",
            timeout=300,
        )
        return {"handled": True, "action": "transaction_import_queued", "account_id": account_id}

    return {"handled": True, "action": "logged"}


def handle_transactions_updated(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle transactions updated event."""
    account_id = extract_account_id(event_data)
    frappe.logger().info(f"Ponto transactions updated for account {account_id}")
    return {"handled": True, "action": "logged", "account_id": account_id}


# =============================================================================
# Account Event Handlers
# =============================================================================


def handle_account_updated(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle account details updated event."""
    account_id = extract_account_id(event_data)
    frappe.logger().info(f"Ponto account details updated: {account_id}")
    return {"handled": True, "action": "logged", "account_id": account_id}


def handle_account_added(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle new account added to integration event."""
    account_id = extract_account_id(event_data)
    frappe.logger().info(f"Ponto account added to integration: {account_id}")
    return {"handled": True, "action": "logged", "account_id": account_id}


def handle_account_revoked(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle account revoked from integration event."""
    account_id = extract_account_id(event_data)
    frappe.logger().warning(f"Ponto account revoked from integration: {account_id}")

    # Log as error for visibility
    frappe.log_error(
        title="Ponto Account Revoked",
        message=f"Account {account_id} has been revoked. Please re-authorize if needed.",
    )

    return {"handled": True, "action": "logged", "account_id": account_id}


# =============================================================================
# Outgoing Payment Request Handlers
# =============================================================================


def handle_payment_request_closed(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle payment request closed event.

    This event is sent when a payment request reaches a final status
    (executed, rejected, failed, cancelled).

    Updates the corresponding Ponto Payment Request document status.
    Uses explicit transaction boundaries for data integrity.
    """
    payment_id = extract_payment_request_id(event_data)
    new_status = extract_payment_status(event_data)

    frappe.logger().info(f"Ponto payment request closed: {payment_id} with status {new_status}")

    if not payment_id:
        frappe.logger().warning("Payment request closed event without payment ID")
        return {"handled": True, "action": "logged", "reason": "no_payment_id"}

    # Find the Ponto Payment Request by ponto_payment_id
    payment_requests = frappe.get_all(
        "Ponto Payment Request",
        filters={"ponto_payment_id": payment_id},
        fields=["name"],
    )

    if not payment_requests:
        # Fallback: Check if this is a Ponto Payment Link (betaalverzoek/incoming payment)
        payment_links = frappe.get_all(
            "Ponto Payment Link",
            filters={"ponto_request_id": payment_id},
            fields=["name"],
        )

        if payment_links:
            # Route to payment initiation handler
            frappe.logger().info(
                f"Payment ID {payment_id} matched Ponto Payment Link, routing to initiation handler"
            )
            return handle_payment_initiation_closed(event_data)

        frappe.logger().warning(
            f"No Ponto Payment Request or Payment Link found for payment ID: {payment_id}"
        )
        return {"handled": True, "action": "logged", "reason": "payment_request_not_found"}

    # Map Ponto status to our status
    status_map = {
        "pending": "Pending",
        "unsigned": "Pending",
        "signed": "Signed",
        "executed": "Executed",
        "rejected": "Rejected",
        "failed": "Failed",
        "cancelled": "Cancelled",
    }

    mapped_status = status_map.get(new_status.lower() if new_status else "", None)

    if mapped_status:
        updated_requests = []
        failed_requests = []

        for pr in payment_requests:
            # Use savepoint for each update to isolate failures
            savepoint_name = _safe_savepoint_name("payment_status", pr.name)
            try:
                frappe.db.savepoint(savepoint_name)
                doc = frappe.get_doc("Ponto Payment Request", pr.name)
                doc.update_status_from_webhook(mapped_status)
                frappe.logger().info(f"Updated Ponto Payment Request {pr.name} to status {mapped_status}")
                updated_requests.append(pr.name)
            except NON_RESUMABLE_DB_ERRORS:
                # A 1205/1213 is not one bad row: the server has discarded or half-applied the
                # whole transaction, so the rows already marked failed and the rows still to come
                # are all being decided against state that is gone. The webhook must fail so Ponto
                # fail (the handler sets HTTP 500) rather than report a partial result as a
                # complete one. Whether Ponto retries a 500 is its policy, not verified here.
                raise
            except Exception as e:
                rollback_to_savepoint(savepoint_name)
                frappe.logger().error(f"Failed to update Ponto Payment Request {pr.name}: {e}")
                frappe.log_error(
                    title=f"Payment webhook status update failed: {pr.name}",
                    message=str(e),
                )
                failed_requests.append(pr.name)

        return {
            "handled": True,
            "action": "status_updated",
            "payment_id": payment_id,
            "new_status": mapped_status,
            "updated_requests": updated_requests,
            "failed_requests": failed_requests if failed_requests else None,
        }

    return {"handled": True, "action": "logged", "reason": "unknown_status"}


# =============================================================================
# Payment Initiation (Betaalverzoek) Handlers
# =============================================================================


def _update_payment_link_status(
    request_id: str,
    new_status: str,
    debtor_info: dict = None,
    is_periodic: bool = False,
) -> Dict[str, Any]:
    """
    Common helper to update Ponto Payment Link status.

    Uses explicit transaction boundaries (savepoints) for data integrity.
    Each payment link update is isolated so failures don't affect others.

    When status becomes "Executed":
    - Attempts to find matching Sales Invoice if not already linked
    - Creates Payment Entry for the payment
    - Links Payment Entry to the payment link

    Args:
        request_id: Ponto request ID
        new_status: New status value
        debtor_info: Optional debtor details
        is_periodic: Whether this is a periodic payment

    Returns:
        Dict with update result
    """
    # Find the Ponto Payment Link by ponto_request_id
    payment_links = frappe.get_all(
        "Ponto Payment Link",
        filters={"ponto_request_id": request_id},
        fields=["name"],
    )

    if not payment_links:
        frappe.logger().warning(f"No Ponto Payment Link found for request ID: {request_id}")
        return {"handled": True, "action": "logged", "reason": "payment_link_not_found"}

    # Map Ponto status to our status
    status_map = {
        "pending": "Pending Authorization",
        "unsigned": "Pending Authorization",
        "signed": "Authorized",
        "authorized": "Authorized",
        "executed": "Executed",
        "rejected": "Rejected",
        "failed": "Failed",
        "cancelled": "Cancelled",
        "expired": "Expired",
    }

    mapped_status = status_map.get(new_status.lower() if new_status else "", None)

    if mapped_status:
        updated_links = []
        failed_links = []
        payment_entries_queued = []

        for pl in payment_links:
            # Use savepoint for each update to isolate failures
            savepoint_name = _safe_savepoint_name("payment_link_status", pl.name)
            try:
                frappe.db.savepoint(savepoint_name)
                doc = frappe.get_doc("Ponto Payment Link", pl.name)
                doc.update_status_from_webhook(mapped_status, debtor_info)
                frappe.logger().info(f"Updated Ponto Payment Link {pl.name} to status {mapped_status}")
                updated_links.append(pl.name)

                # If payment is executed, find the invoice and create a Payment Entry -
                # as the configured webhook user, not inline in this Guest request.
                # handle_ponto_webhook is allow_guest=True and never elevates, and Guest
                # can neither insert a Payment Entry nor save its name back onto the
                # link, which is what leaves the guard below unlatched and lets a retry
                # post the payment twice.
                #
                # enqueue_after_commit stops the worker starting before this request
                # commits and reading the PRE-webhook row (status not yet Executed).
                # It does NOT rescue the savepoint path: db.rollback(save_point=...)
                # returns before after_commit.reset() (database.py:1196-1203), so a
                # savepoint rollback leaves the callback registered either way. Only a
                # full request rollback drops it.
                #
                # job_id + deduplicate collapse a redelivery that arrives while the
                # first job is still queued or running. They do NOT dedup two
                # concurrent uncommitted requests: the dedup lookup happens here, the
                # push happens later from after_commit, so both can pass. The real
                # protection against a double post is the reference_no check inside
                # _process_executed_payment.
                if mapped_status == "Executed" and not doc.payment_entry:
                    frappe.enqueue(
                        "verenigingen.verenigingen_payments.ponto.api.webhook_handlers."
                        "process_executed_payment_job",
                        payment_link_name=pl.name,
                        queue="short",
                        timeout=300,
                        enqueue_after_commit=True,
                        job_id=f"ponto_executed_{pl.name}",
                        deduplicate=True,
                    )
                    payment_entries_queued.append(pl.name)

            except NON_RESUMABLE_DB_ERRORS:
                # A 1205/1213 is not one bad row: the server has discarded or half-applied the
                # whole transaction, so the rows already marked failed and the rows still to come
                # are all being decided against state that is gone. The webhook must fail so Ponto
                # fail (the handler sets HTTP 500) rather than report a partial result as a
                # complete one. Whether Ponto retries a 500 is its policy, not verified here.
                raise
            except Exception as e:
                rollback_to_savepoint(savepoint_name)
                frappe.logger().error(f"Failed to update Ponto Payment Link {pl.name}: {e}")
                frappe.log_error(
                    title=f"Payment link webhook status update failed: {pl.name}",
                    message=str(e),
                )
                failed_links.append(pl.name)

        return {
            "handled": True,
            "action": "status_updated",
            "request_id": request_id,
            "new_status": mapped_status,
            "updated_links": updated_links,
            "failed_links": failed_links if failed_links else None,
            # Queued, not created: the Payment Entry is written by a background job
            # running as the webhook user, so its name is not known here.
            "payment_entries_queued": payment_entries_queued or None,
        }

    return {"handled": True, "action": "logged", "reason": "unknown_status"}


def process_executed_payment_job(payment_link_name: str) -> Dict[str, Any]:
    """Background entry point for the executed-payment branch.

    Sets the identity HERE rather than via an `enqueue(user=...)` kwarg: frappe.enqueue
    has no such parameter, so it would be forwarded to this function and raise TypeError
    in the worker (see import_transactions_job for the full mechanism).

    Re-checks status rather than trusting the enqueue. The job is queued after commit,
    but a link can still be re-read after some later change, and acting on a row that is
    no longer Executed would post money against pre-webhook state.

    Module-level (not underscore-private) because frappe.enqueue resolves it by dotted
    path.
    """
    frappe.set_user(_get_webhook_user())
    doc = frappe.get_doc("Ponto Payment Link", payment_link_name)

    if doc.status != "Executed":
        frappe.logger().info(
            f"Skipping Ponto Payment Link {payment_link_name}: status is {doc.status}, not Executed"
        )
        return {"payment_entry": None, "sales_invoice": None, "matched_by": None, "skipped": True}

    return _process_executed_payment(doc)


def _process_executed_payment(payment_link_doc) -> Dict[str, Any]:
    """
    Process an executed Ponto payment - find matching invoice and create Payment Entry.

    Uses the generalized invoice matching from coverage_calculator.

    Args:
        payment_link_doc: Ponto Payment Link document

    Returns:
        Dict with processing result including payment_entry name if created
    """
    from frappe.utils import flt, getdate, today

    from verenigingen.services.billing.coverage_calculator import find_invoice_for_payment

    result = {
        "payment_entry": None,
        "sales_invoice": None,
        "matched_by": None,
    }

    try:
        # Get member if linked
        member_name = payment_link_doc.member
        if not member_name:
            frappe.logger().info(
                f"Ponto Payment Link {payment_link_doc.name} has no member linked - "
                "cannot match invoice automatically"
            )
            return result

        # Get payment details
        amount = flt(payment_link_doc.amount)
        payment_date = getdate(today())  # Use today as the payment date
        description = payment_link_doc.description or ""

        # Check if invoice is already linked
        if payment_link_doc.sales_invoice:
            result["sales_invoice"] = payment_link_doc.sales_invoice
            result["matched_by"] = "pre_linked"
        else:
            # Use the generalized invoice matching service
            matched_invoice = find_invoice_for_payment(
                member_name=member_name,
                payment_date=payment_date,
                payment_amount=amount,
                remittance_info=description,
            )

            if matched_invoice:
                # Link the invoice to the payment link. ignore_permissions matches the
                # DocType's own webhook method (ponto_payment_link.py:450): this runs
                # from a webhook, and a silently-refused save here is what leaves the
                # link unlatched and lets a retry post the payment twice.
                payment_link_doc.sales_invoice = matched_invoice
                # Security: webhook-initiated write under the configured webhook user;
                # a refused save leaves the link unlatched and lets a retry post twice.
                payment_link_doc.save(ignore_permissions=True)
                result["sales_invoice"] = matched_invoice
                result["matched_by"] = "invoice_matcher"
                frappe.logger().info(
                    f"Matched Ponto Payment Link {payment_link_doc.name} to Sales Invoice {matched_invoice}"
                )
            else:
                # An EXECUTED payment that matches no invoice must not pass silently.
                # There is no else-branch below either, so without this the money is
                # received, nothing is written, and nothing is logged - the link simply
                # sits at Executed with no Payment Entry forever. Recorded as an Error
                # Log (not just a logger call) because it needs a human to reconcile.
                frappe.log_error(
                    title=f"Ponto payment matched no invoice: {payment_link_doc.name}",
                    message=(
                        f"Executed Ponto Payment Link {payment_link_doc.name} for member "
                        f"{member_name} (amount {amount}) matched no Sales Invoice. "
                        f"No Payment Entry was created - manual reconciliation required."
                    ),
                )

        # Create Payment Entry if we have an invoice
        if result.get("sales_invoice"):
            # Idempotency, independent of the link field. Writing payment_entry back is
            # a SECOND transaction-visible step after the entry is submitted, so the two
            # can diverge (a failed save-back, a crash between them) and the caller's
            # `not doc.payment_entry` guard would then let a retried webhook post the
            # same money again.
            #
            # Both keys are searched. The link name is included because the DocType's
            # former hand-rolled creator keyed reference_no on it; any entry it managed
            # to write on an older release would otherwise be invisible here and get
            # duplicated. New entries all use the request id.
            candidate_refs = [payment_link_doc.ponto_request_id, payment_link_doc.name]
            candidate_refs = [r for r in candidate_refs if r]
            existing_pe = frappe.db.get_value(
                "Payment Entry", {"reference_no": ("in", candidate_refs), "docstatus": 1}, "name"
            )
            if existing_pe:
                frappe.logger().info(
                    f"Payment Entry {existing_pe} already exists for Ponto link "
                    f"{payment_link_doc.name} - relinking rather than creating a second one"
                )
                result["payment_entry"] = existing_pe
                payment_link_doc.payment_entry = existing_pe
                # Security: webhook-initiated write under the configured webhook user;
                # relinking an existing entry is what prevents a duplicate posting.
                payment_link_doc.save(ignore_permissions=True)
                return result

            pe_name = create_ponto_payment_entry(
                payment_link_doc=payment_link_doc,
                invoice_name=result["sales_invoice"],
            )
            if pe_name:
                result["payment_entry"] = pe_name
                # Link payment entry back to payment link.
                # Security: webhook-initiated write under the configured webhook user;
                # this is the step whose silent failure enabled the double post.
                payment_link_doc.payment_entry = pe_name
                payment_link_doc.save(ignore_permissions=True)

        return result

    except Exception as e:
        frappe.logger().error(f"Failed to process executed payment {payment_link_doc.name}: {e}")
        frappe.log_error(
            title=f"Ponto payment processing failed: {payment_link_doc.name}",
            message=str(e),
        )
        return result


def handle_payment_initiation_updated(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle payment initiation request status updated event.

    This event is sent when a one-time betaalverzoek status changes.
    """
    request_id = extract_payment_link_id(event_data)
    new_status = extract_payment_status(event_data)
    debtor_info = extract_debtor_info(event_data)

    frappe.logger().info(f"Ponto payment initiation updated: {request_id} to status {new_status}")

    if not request_id:
        frappe.logger().warning("Payment initiation updated event without request ID")
        return {"handled": True, "action": "logged", "reason": "no_request_id"}

    return _update_payment_link_status(request_id, new_status, debtor_info, is_periodic=False)


def handle_payment_initiation_closed(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle payment initiation request closed event.

    This event is sent when a one-time betaalverzoek reaches final status.
    """
    request_id = extract_payment_link_id(event_data)
    new_status = extract_payment_status(event_data)
    debtor_info = extract_debtor_info(event_data)

    frappe.logger().info(f"Ponto payment initiation closed: {request_id} with status {new_status}")

    if not request_id:
        frappe.logger().warning("Payment initiation closed event without request ID")
        return {"handled": True, "action": "logged", "reason": "no_request_id"}

    return _update_payment_link_status(request_id, new_status, debtor_info, is_periodic=False)


# =============================================================================
# Periodic Payment (Recurring Betaalverzoek) Handlers
# =============================================================================


def handle_periodic_payment_updated(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle periodic payment initiation request status updated event.

    This event is sent when a recurring betaalverzoek status changes.
    """
    request_id = extract_payment_link_id(event_data)
    new_status = extract_payment_status(event_data)
    debtor_info = extract_debtor_info(event_data)

    frappe.logger().info(f"Ponto periodic payment updated: {request_id} to status {new_status}")

    if not request_id:
        frappe.logger().warning("Periodic payment updated event without request ID")
        return {"handled": True, "action": "logged", "reason": "no_request_id"}

    return _update_payment_link_status(request_id, new_status, debtor_info, is_periodic=True)


def handle_periodic_payment_closed(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle periodic payment initiation request closed event.

    This event is sent when a recurring betaalverzoek reaches final status.
    """
    request_id = extract_payment_link_id(event_data)
    new_status = extract_payment_status(event_data)
    debtor_info = extract_debtor_info(event_data)

    frappe.logger().info(f"Ponto periodic payment closed: {request_id} with status {new_status}")

    if not request_id:
        frappe.logger().warning("Periodic payment closed event without request ID")
        return {"handled": True, "action": "logged", "reason": "no_request_id"}

    return _update_payment_link_status(request_id, new_status, debtor_info, is_periodic=True)


def handle_periodic_payment_execution(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle periodic payment execution event.

    This event is sent each time a recurring payment is executed.
    Used to track individual payment executions in a standing order.

    Uses explicit transaction boundaries (savepoints) for data integrity.
    Each payment link update is atomic - counter, payment processing, and
    debtor info updates are committed together or rolled back together.
    """
    request_id = extract_payment_link_id(event_data)
    debtor_info = extract_debtor_info(event_data)

    frappe.logger().info(f"Ponto periodic payment executed: {request_id}")

    if not request_id:
        frappe.logger().warning("Periodic payment execution event without request ID")
        return {"handled": True, "action": "logged", "reason": "no_request_id"}

    # Find and update the payment link
    payment_links = frappe.get_all(
        "Ponto Payment Link",
        filters={"ponto_request_id": request_id},
        fields=["name"],
    )

    if not payment_links:
        frappe.logger().warning(f"No Ponto Payment Link found for request ID: {request_id}")
        return {"handled": True, "action": "logged", "reason": "payment_link_not_found"}

    updated_links = []
    failed_links = []

    for pl in payment_links:
        # Use savepoint for each payment link - all operations within are atomic
        savepoint_name = _safe_savepoint_name("periodic_payment", pl.name)
        try:
            frappe.db.savepoint(savepoint_name)

            doc = frappe.get_doc("Ponto Payment Link", pl.name)

            # Increment payment counter
            doc.increment_payment_count()

            # Process the individual payment
            doc.process_payment_received()

            # Update debtor info if provided
            if debtor_info:
                if debtor_info.get("name"):
                    doc.debtor_name = debtor_info["name"]
                if debtor_info.get("iban"):
                    doc.debtor_iban = debtor_info["iban"]
                if debtor_info.get("bank"):
                    doc.debtor_bank = debtor_info["bank"]
                doc.save()

            frappe.logger().info(
                f"Processed periodic payment execution for {pl.name}, "
                f"total payments: {doc.total_payments_collected}"
            )
            updated_links.append(pl.name)

        except NON_RESUMABLE_DB_ERRORS:
            # A 1205/1213 is not one bad row: the server has discarded or half-applied the
            # whole transaction, so the rows already marked failed and the rows still to come
            # are all being decided against state that is gone. The webhook must fail so Ponto
            # fail (the handler sets HTTP 500) rather than report a partial result as a
            # complete one. Whether Ponto retries a 500 is its policy, not verified here.
            raise
        except Exception as e:
            rollback_to_savepoint(savepoint_name)
            frappe.logger().error(f"Failed to process periodic payment execution for {pl.name}: {e}")
            frappe.log_error(
                title=f"Periodic payment execution failed: {pl.name}",
                message=str(e),
            )
            failed_links.append(pl.name)

    return {
        "handled": True,
        "action": "payment_processed",
        "request_id": request_id,
        "updated_links": updated_links,
        "failed_links": failed_links if failed_links else None,
    }


__all__ = [
    # Sync handlers
    "handle_sync_succeeded",
    "handle_sync_failed",
    "handle_sync_no_change",
    # Transaction handlers
    "handle_transactions_created",
    "handle_transactions_updated",
    # Account handlers
    "handle_account_updated",
    "handle_account_added",
    "handle_account_revoked",
    # Payment request handlers
    "handle_payment_request_closed",
    # Payment initiation handlers
    "handle_payment_initiation_updated",
    "handle_payment_initiation_closed",
    # Periodic payment handlers
    "handle_periodic_payment_updated",
    "handle_periodic_payment_closed",
    "handle_periodic_payment_execution",
]
