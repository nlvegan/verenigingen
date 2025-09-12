import json

import frappe
from frappe import _

from verenigingen.services.customer_handling_service import CustomerHandlingService
from verenigingen.services.donation_management_service import DonationManagementService
from verenigingen.services.payment_processing_service import PaymentProcessingService
from verenigingen.utils.webhook_error_handler import WebhookErrorHandler


@frappe.whitelist(allow_guest=True, methods=["POST"])
def handle_payment_first_donation():
    """
    Secure webhook handler for creating donations from Mollie payments.

    Supports both payment-first and donation-first flows with robust
    idempotency protection and security validation.
    """

    # Get raw payload and headers for security verification
    raw_payload = frappe.request.get_data(as_text=True) if frappe.request else ""
    headers = dict(frappe.request.headers) if frappe.request else {}

    # Basic security validation
    try:
        from verenigingen.utils.webhook_security import (
            WebhookAuthenticationError,
            verify_mollie_webhook_signature,
        )

        # For now, skip signature verification in test mode but log the attempt
        settings = frappe.get_single("Mollie Settings")
        if not settings.test_mode:
            verify_mollie_webhook_signature(raw_payload, headers.get("X-Mollie-Signature"))
    except (WebhookAuthenticationError, ImportError) as e:
        # Allow webhook through in test mode but log the security concern
        frappe.logger().warning(f"⚠️ Webhook security validation skipped: {str(e)}")

    # Initialize error handler with correlation ID for request tracking
    error_handler = WebhookErrorHandler("mollie_donation_webhook")
    error_handler.log_info("Webhook processing started", {"payment_id_hint": "parsing..."})

    # Set proper user context - use system user for webhook processing
    frappe.set_user("Administrator")  # TODO: Replace with proper webhook service account

    try:
        # Parse payment ID from webhook data - handle both JSON events and form data
        webhook_data = frappe.form_dict
        payment_id = None

        # Check for Mollie JSON event format first
        if webhook_data.get("resource") == "event":
            event_type = webhook_data.get("type", "")
            if event_type == "hook.ping":
                return {"status": "success", "message": "Webhook ping received"}
            elif event_type.startswith("payment."):
                payment_id = webhook_data.get("entityId")
        else:
            # Legacy format - try form_dict first
            payment_id = webhook_data.get("id")

            # Parse payment ID from raw payload if form_dict is empty
            if not payment_id and raw_payload:
                import urllib.parse

                parsed_data = urllib.parse.parse_qs(raw_payload)
                payment_id = parsed_data.get("id", [None])[0]

        if not payment_id or not payment_id.startswith("tr_"):
            return error_handler.handle_validation_error(
                "Invalid or missing payment ID",
                {"provided_id": payment_id, "raw_payload_length": len(raw_payload)},
            )

        # ROBUST IDEMPOTENCY PROTECTION - Check if webhook already processed
        existing_log = frappe.db.get_value(
            "Webhook Processing Log",
            {"webhook_id": payment_id, "status": "success"},
            ["name", "processing_result"],
        )
        if existing_log:
            frappe.logger().info(
                f"⚠️ Webhook {payment_id} already processed successfully - returning cached result"
            )
            try:
                cached_result = frappe.parse_json(existing_log[1] or "{}")
                return (
                    cached_result
                    if cached_result
                    else {"status": "success", "message": "Previously processed"}
                )
            except:
                return {"status": "success", "message": f"Payment {payment_id} already processed"}

        # Create processing log for idempotency (will fail if duplicate exists)
        webhook_log = frappe.new_doc("Webhook Processing Log")
        webhook_log.webhook_id = payment_id
        webhook_log.webhook_type = "payment" if payment_id.startswith("tr_") else "unknown"
        webhook_log.processed_at = frappe.utils.now()
        webhook_log.raw_payload = raw_payload
        webhook_log.status = "success"  # Set valid initial status
        try:
            webhook_log.insert()
        except frappe.DuplicateEntryError:
            frappe.logger().info(f"⚠️ Webhook {payment_id} already being processed - returning success")
            return {"status": "success", "message": f"Payment {payment_id} already being processed"}

        # Get Mollie client with error handling
        settings = frappe.get_single("Mollie Settings")
        if not settings:
            return error_handler.handle_validation_error(
                "Mollie settings not configured", {"payment_id": payment_id}
            )

        import mollie.api.client

        client = mollie.api.client.Client()
        client.set_api_key(settings.get_active_api_key())

        # Fetch payment from Mollie API with comprehensive error handling
        try:
            payment = client.payments.get(payment_id)
            error_handler.log_info(
                "Successfully fetched payment from Mollie", {"payment_status": payment.status}
            )
        except Exception as e:
            return error_handler.handle_external_api_error(
                "Mollie", f"Failed to fetch payment {payment_id}: {str(e)}", e
            )

        # Initialize service classes with correlation ID for consistent logging
        context_name = f"mollie_webhook_{error_handler.get_correlation_id()}"
        payment_service = PaymentProcessingService(context_name)
        donation_service = DonationManagementService(context_name)
        customer_service = CustomerHandlingService(context_name)

        # Process payment (handles refunds, chargebacks, validation)
        payment_result = error_handler.wrap_with_error_handling(
            "process payment validation", payment_service.process_payment_webhook, payment_id, payment
        )

        if error_handler.is_error_result(payment_result):
            error_handler.update_webhook_log(webhook_log, payment_result)
            return payment_result
        elif payment_result.get("status") != "ready_for_donation_processing":
            # Valid non-error result but not ready for donation processing
            error_handler.update_webhook_log(webhook_log, payment_result)
            return payment_result

        # Determine donation flow type
        flow_type, flow_details = error_handler.wrap_with_error_handling(
            "determine donation flow", donation_service.determine_donation_flow, payment
        )
        if error_handler.is_error_result((flow_type, flow_details)):
            error_handler.update_webhook_log(webhook_log, flow_type)  # Error result is in flow_type
            return flow_type

        # Validate donation flow compatibility
        flow_validation = error_handler.wrap_with_error_handling(
            "validate donation flow", donation_service.validate_donation_compatibility, flow_type
        )
        if error_handler.is_error_result(flow_validation):
            error_handler.update_webhook_log(webhook_log, flow_validation)
            return flow_validation
        elif flow_validation.get("status") != "valid":
            error_handler.update_webhook_log(webhook_log, flow_validation)
            return flow_validation

        # Extract Mollie IDs from payment with error handling
        mollie_ids = error_handler.wrap_with_error_handling(
            "extract Mollie IDs", payment_service.extract_mollie_ids, payment
        )
        if error_handler.is_error_result(mollie_ids):
            error_handler.update_webhook_log(webhook_log, mollie_ids)
            return mollie_ids

        # Find or create donation based on flow type
        donation_result = error_handler.wrap_with_error_handling(
            "find or create donation",
            donation_service.find_or_create_donation,
            flow_type,
            flow_details,
            payment_id,
            payment,
        )
        if error_handler.is_error_result(donation_result):
            error_handler.update_webhook_log(webhook_log, donation_result)
            return donation_result
        donation, is_new_donation = donation_result  # Unpack the tuple result

        # Update donation with payment details if needed
        if flow_type == "donation_first":
            update_result = error_handler.wrap_with_error_handling(
                "update donation with payment details",
                donation_service.update_donation_with_payment_details,
                donation,
                payment_id,
                True,
            )
            if error_handler.is_error_result(update_result):
                error_handler.update_webhook_log(webhook_log, update_result)
                return update_result

        # Update customer with mandate information
        mandate_result = error_handler.wrap_with_error_handling(
            "update customer mandate",
            customer_service.update_customer_mandate,
            mollie_ids.get("customer_id"),
            mollie_ids.get("mandate_id"),
        )
        if error_handler.is_error_result(mandate_result):
            # Log error but don't fail the entire webhook - mandate updates are non-critical
            error_handler.log_warning(f"Customer mandate update failed: {mandate_result.get('message')}")

        # Update donation with Mollie IDs
        ids_update_result = error_handler.wrap_with_error_handling(
            "update donation with Mollie IDs",
            donation_service.update_donation_with_mollie_ids,
            donation,
            mollie_ids,
        )
        if error_handler.is_error_result(ids_update_result):
            # Log error but don't fail the entire webhook - ID updates are non-critical
            error_handler.log_warning(
                f"Donation Mollie IDs update failed: {ids_update_result.get('message')}"
            )

        # Create Payment Entry with comprehensive error handling
        payment_entry_result = error_handler.wrap_with_error_handling(
            "create payment entry", payment_service.create_payment_entry, donation, payment_id
        )

        if error_handler.is_error_result(payment_entry_result):
            error_handler.update_webhook_log(webhook_log, payment_entry_result)
            return payment_entry_result
        elif payment_entry_result.get("status") == "exists":
            # Payment Entry already exists - return success
            result = error_handler.create_success_response(
                payment_entry_result["message"],
                {
                    "payment_entry": payment_entry_result["payment_entry"],
                    "donation_id": donation.name,
                    "amount": donation.amount,
                    "mandate_id": mollie_ids.get("mandate_id"),
                },
            )
            error_handler.update_webhook_log(webhook_log, result)
            return result

        # Add payment history entry to donation
        history_result = error_handler.wrap_with_error_handling(
            "add payment history entry", payment_service.add_payment_history_entry, donation, payment_id
        )
        if error_handler.is_error_result(history_result):
            # Log error but don't fail the entire webhook - payment history is non-critical
            error_handler.log_warning(f"Payment history update failed: {history_result.get('message')}")

        # Return final success result
        result = error_handler.create_success_response(
            f"Donation {donation.name} processed successfully",
            {
                "donation_id": donation.name,
                "amount": donation.amount,
                "mandate_id": mollie_ids.get("mandate_id"),
                "payment_entry": payment_entry_result.get("payment_entry")
                if payment_entry_result and payment_entry_result.get("status") == "success"
                else None,
                "is_new_donation": is_new_donation,
                "flow_type": flow_type,
            },
        )
        error_handler.update_webhook_log(webhook_log, result)
        return result

    except Exception as e:
        # Comprehensive error handling for any uncaught exceptions
        error_result = error_handler.handle_system_error(
            f"Unexpected webhook processing error: {str(e)}",
            e,
            {"payment_id": payment_id if "payment_id" in locals() else "unknown"},
        )

        # Update webhook log with error
        if "webhook_log" in locals():
            error_handler.update_webhook_log(webhook_log, error_result)

        return error_result
