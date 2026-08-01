# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Webhook Event Handlers

Event-specific handlers for Ponto webhook events.
Each handler processes a specific event type and returns a result dict.

Split from webhook.py as part of HIGH-4 (PSP Integration Consolidation Plan).
"""

import re
from typing import Any, Dict, Optional

import frappe

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
            "verenigingen.verenigingen_payments.ponto.services.transaction_import_service.import_new_transactions",
            account_id=account_id,
            queue="short",
            timeout=300,
            user=_get_webhook_user(),
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
            "verenigingen.verenigingen_payments.ponto.services.transaction_import_service.import_new_transactions",
            account_id=account_id,
            queue="short",
            timeout=300,
            user=_get_webhook_user(),
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
            except Exception as e:
                frappe.db.rollback(save_point=savepoint_name)
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
                # but as the configured webhook user, not inline in this request.
                #
                # This handler is reached from handle_ponto_webhook, which is
                # allow_guest=True and never elevates, so an inline call ran as Guest.
                # Guest cannot insert a Payment Entry (Document.insert checks permission
                # itself), and - more dangerously - cannot save the Payment Entry name
                # back onto the link either, so the `not doc.payment_entry` guard below
                # would never latch and a retried webhook would post the payment twice.
                # The sibling sync/transaction handlers already enqueue with this user;
                # the executed-payment branch was the odd one out.
                if mapped_status == "Executed" and not doc.payment_entry:
                    frappe.enqueue(
                        "verenigingen.verenigingen_payments.ponto.api.webhook_handlers."
                        "process_executed_payment_job",
                        payment_link_name=pl.name,
                        queue="short",
                        timeout=300,
                        user=_get_webhook_user(),
                    )
                    payment_entries_queued.append(pl.name)

            except Exception as e:
                frappe.db.rollback(save_point=savepoint_name)
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

    Enqueued by handle_payment_initiation_* with user=_get_webhook_user() so the
    Payment Entry is created and linked back under a real, permissioned identity
    instead of the Guest session the webhook request carries.

    Module-level (not underscore-private) because frappe.enqueue resolves it by
    dotted path.
    """
    return _process_executed_payment(frappe.get_doc("Ponto Payment Link", payment_link_name))


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

        # Create Payment Entry if we have an invoice
        if result.get("sales_invoice"):
            # Idempotency, independent of the link field. Writing payment_entry back is
            # a SECOND transaction-visible step after the entry is submitted, so the two
            # can diverge (a failed save-back, a crash between them) and the caller's
            # `not doc.payment_entry` guard would then let a retried webhook post the
            # same money again. Keyed on reference_no, which carries the Ponto request id.
            reference_no = payment_link_doc.ponto_request_id or payment_link_doc.name
            existing_pe = frappe.db.get_value(
                "Payment Entry", {"reference_no": reference_no, "docstatus": 1}, "name"
            )
            if existing_pe:
                frappe.logger().info(
                    f"Payment Entry {existing_pe} already exists for Ponto reference {reference_no} - "
                    f"relinking rather than creating a second one"
                )
                result["payment_entry"] = existing_pe
                payment_link_doc.payment_entry = existing_pe
                # Security: webhook-initiated write under the configured webhook user;
                # relinking an existing entry is what prevents a duplicate posting.
                payment_link_doc.save(ignore_permissions=True)
                return result

            pe_name = _create_ponto_payment_entry(
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


def _create_ponto_payment_entry(payment_link_doc, invoice_name: str) -> Optional[str]:
    """
    Create a Payment Entry for a Ponto payment.

    Args:
        payment_link_doc: Ponto Payment Link document
        invoice_name: Sales Invoice to allocate payment to

    Returns:
        Payment Entry name if created, None otherwise
    """
    from frappe.utils import flt, getdate, today

    try:
        # Get invoice document
        invoice_doc = frappe.get_doc("Sales Invoice", invoice_name)

        if invoice_doc.outstanding_amount <= 0:
            frappe.logger().info(
                f"Sales Invoice {invoice_name} already paid (outstanding: {invoice_doc.outstanding_amount})"
            )
            return None

        # Get settings
        settings = frappe.get_single("Verenigingen Settings")
        company = invoice_doc.company or settings.company

        # Get Ponto bank account from settings. ponto_bank_account_parent lives
        # on Verenigingen Payments Settings.
        from verenigingen.utils.settings_utils import get_payments_settings

        ponto_bank_account = getattr(get_payments_settings(), "ponto_bank_account_parent", None)
        if not ponto_bank_account:
            # Try to find a Ponto account
            ponto_bank_account = frappe.db.get_value(
                "Account",
                {"company": company, "account_name": ["like", "%Ponto%"], "is_group": 0},
                "name",
            )
        if not ponto_bank_account:
            ponto_bank_account = frappe.get_cached_value("Company", company, "default_bank_account")

        if not ponto_bank_account:
            frappe.logger().error(f"No Ponto bank account configured for company {company}")
            return None

        # Calculate allocation amount. Capped at what the invoice still owes: ERPNext
        # rejects a reference allocating more than the outstanding amount.
        amount = flt(payment_link_doc.amount)
        allocation_amount = min(amount, flt(invoice_doc.outstanding_amount))

        # Delegate to PaymentEntryCreationService so this path shares one payment-entry
        # contract with the rest of the app. The service sets custom_remarks alongside
        # the remarks text, without which Payment Entry.validate() regenerates the field
        # and the payment-link reference below never reaches the saved document.
        from decimal import Decimal

        from verenigingen.verenigingen_payments.services.payment import payment_entry_service

        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice_name,
            amount=Decimal(str(allocation_amount)),
            posting_date=getdate(today()),
            reference_no=payment_link_doc.ponto_request_id or payment_link_doc.name,
            reference_date=getdate(today()),
            mode_of_payment="Bank Transfer",
            bank_account=ponto_bank_account,
            remarks=(
                f"Ponto payment via payment link {payment_link_doc.name}. "
                f"Description: {payment_link_doc.description or 'N/A'}"
            ),
            custom_fields=({"custom_member": payment_link_doc.member} if payment_link_doc.member else None),
        )

        frappe.logger().info(
            f"Created Payment Entry {payment_entry.name} for Ponto Payment Link {payment_link_doc.name} "
            f"(amount: {allocation_amount}, invoice: {invoice_name})"
        )

        return payment_entry.name

    except Exception as e:
        frappe.logger().error(f"Failed to create Payment Entry for {payment_link_doc.name}: {e}")
        frappe.log_error(
            title=f"Ponto Payment Entry creation failed: {payment_link_doc.name}",
            message=str(e),
        )
        return None


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

        except Exception as e:
            frappe.db.rollback(save_point=savepoint_name)
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
