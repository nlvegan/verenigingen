"""
Generic Webhook Service

Payment-agnostic webhook service that uses the processor pattern to handle
different types of payments without being tied to specific payment types.
"""

import time
from typing import Any, Dict, Optional

import frappe

from ..exceptions import MollieWebhookError
from ..utils.logging import MollieLogger
from ..utils.monitoring import record_operation_performance
from .payment_context_resolver import PaymentContextResolver
from .payment_processors import PaymentProcessorFactory


class GenericWebhookService:
    """
    Generic webhook service that handles all payment types through processors.

    This service is payment-agnostic and routes payments to appropriate processors
    based on payment context, without hardcoding specific payment logic.
    """

    def __init__(self):
        self.logger = MollieLogger("generic_webhook")
        self.context_resolver = PaymentContextResolver()
        self.processor_factory = PaymentProcessorFactory()

        # Import refund service for financial reversals
        from .refund_chargeback_service import RefundChargebackService

        self.refund_service = RefundChargebackService()

    def process_webhook(self, payment_id: str, payment_data: Any = None) -> Dict[str, Any]:
        """
        Process a Mollie webhook for any payment type.

        Args:
            payment_id: The Mollie payment ID from the webhook
            payment_data: Optional full payment object from Mollie API

        Returns:
            Dict containing processing results

        Raises:
            MollieWebhookError: When webhook processing fails
        """
        start_time = time.time()

        try:
            self.logger.info("Starting generic webhook processing", {"payment_id": payment_id})

            # Get payment from Mollie if not provided
            if not payment_data:
                payment_data = self._fetch_payment_from_mollie(payment_id)

            # ALWAYS check for refunds first - refunds are new financial events
            refund_result = self._process_payment_refunds(payment_id, payment_data)
            if refund_result.get("refunds_processed"):
                processed_count = len(refund_result["refunds_processed"])
                duration = time.time() - start_time
                self.logger.success(
                    "Processed refunds for payment",
                    {"payment_id": payment_id, "refunds_processed": processed_count},
                    duration=duration,
                )
                record_operation_performance(
                    "webhook_processing", duration, True, {"refunds_processed": processed_count}
                )
                return {
                    "status": "success",
                    "message": f"Processed {processed_count} refunds for payment {payment_id}",
                    "payment_id": payment_id,
                    "data": refund_result,
                }

            # Resolve payment context
            context = self.context_resolver.resolve_context(payment_id, payment_data)
            if not context:
                duration = time.time() - start_time
                error_msg = f"Could not resolve payment context for {payment_id}"
                self.logger.error(error_msg, data={"payment_id": payment_id})
                record_operation_performance(
                    "webhook_processing", duration, False, {"error": "no_context_found"}
                )
                raise MollieWebhookError(error_msg, payment_id=payment_id)

            self.logger.info(f"Resolved payment context: {context}")

            # Get appropriate processor
            processor = self.processor_factory.get_processor(context)
            if not processor:
                duration = time.time() - start_time
                error_msg = f"No processor found for payment type: {context.payment_type}"
                self.logger.error(error_msg, data={"payment_id": payment_id, "context": str(context)})
                record_operation_performance(
                    "webhook_processing", duration, False, {"error": "no_processor_found"}
                )
                raise MollieWebhookError(error_msg, payment_id=payment_id)

            # Check idempotency
            idempotency_status = processor.check_idempotency(context, payment_id)
            if idempotency_status.get("all_complete"):
                duration = time.time() - start_time
                self.logger.success(
                    "Payment already processed (idempotent)",
                    {"payment_id": payment_id, "context": str(context), "components": idempotency_status},
                    duration=duration,
                )
                record_operation_performance("webhook_processing", duration, True, {"idempotent": True})
                return {
                    "status": "success",
                    "message": "Payment already processed",
                    "payment_id": payment_id,
                    "idempotent": True,
                    "components": idempotency_status,
                }

            # Extract Mollie data
            mollie_data = processor.extract_mollie_payment_data(payment_data)

            # Process payment based on status
            if payment_data.status == "paid":
                result = processor.process_successful_payment(context, payment_data, mollie_data)
            elif payment_data.status in ["failed", "expired", "canceled"]:
                result = processor.process_failed_payment(context, payment_data, mollie_data)
            else:
                # Handle other statuses (open, pending, authorized)
                duration = time.time() - start_time
                self.logger.info(
                    f"Payment status acknowledged but not processed",
                    {"payment_id": payment_id, "status": payment_data.status},
                    duration=duration,
                )
                record_operation_performance(
                    "webhook_processing", duration, True, {"status": payment_data.status, "processed": False}
                )
                return {"status": "success", "message": f"Payment status: {payment_data.status}"}

            # Check processing result
            if not result.success:
                duration = time.time() - start_time
                self.logger.error(
                    f"Payment processing failed: {result.message}",
                    data={"payment_id": payment_id, "context": str(context)},
                )
                record_operation_performance(
                    "webhook_processing", duration, False, {"error": "processing_failed"}
                )
                raise MollieWebhookError(result.message, payment_id=payment_id)

            # Success
            duration = time.time() - start_time
            self.logger.success(
                "Generic webhook processing completed successfully",
                {
                    "payment_id": payment_id,
                    "context": str(context),
                    "processor": processor.__class__.__name__,
                    "result_keys": list(result.data.keys()) if result.data else None,
                },
                duration=duration,
            )
            record_operation_performance(
                "webhook_processing",
                duration,
                True,
                {
                    "payment_type": context.payment_type,
                    "processor": processor.__class__.__name__,
                    "payment_processed": True,
                },
            )

            return {
                "status": "success",
                "message": result.message,
                "payment_id": payment_id,
                "context": str(context),
                "data": result.data,
            }

        except MollieWebhookError:
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"Generic webhook processing failed for {payment_id}: {str(e)}"
            self.logger.error(error_msg, error=e, data={"payment_id": payment_id})
            record_operation_performance(
                "webhook_processing",
                duration,
                False,
                {"error_type": type(e).__name__, "unexpected_error": True},
            )
            raise MollieWebhookError(error_msg, payment_id=payment_id, original_error=e)

    def _fetch_payment_from_mollie(self, payment_id: str) -> Any:
        """
        Fetch payment details from Mollie API.

        Args:
            payment_id: Mollie payment ID

        Returns:
            Mollie payment object

        Raises:
            Exception: When API call fails
        """
        try:
            mollie_settings = frappe.get_single("Mollie Settings")
            mollie = mollie_settings.get_mollie_client()
            return mollie.payments.get(payment_id)
        except Exception as e:
            self.logger.error(f"Failed to fetch payment {payment_id} from Mollie: {e}")
            frappe.log_error(f"Failed to fetch payment {payment_id} from Mollie: {e}", "Mollie API")
            raise

    def _process_payment_refunds(self, payment_id: str, payment_data: Any) -> Dict[str, Any]:
        """
        Process any refunds associated with this payment.

        Args:
            payment_id (str): Mollie payment ID
            payment_data: Mollie payment object

        Returns:
            dict: Processing results including any refunds processed
        """
        try:
            self.logger.info(f"Checking for refunds on payment {payment_id}")

            # Get Mollie client to fetch refunds
            mollie_settings = frappe.get_single("Mollie Settings")
            mollie = mollie_settings.get_mollie_client()

            # Fetch all refunds for this payment
            try:
                refunds = mollie.payment_refunds.with_parent_id(payment_id).list()
                self.logger.info(f"Found {len(refunds)} refunds for payment {payment_id}")
            except Exception as e:
                self.logger.warning(f"Could not fetch refunds for payment {payment_id}: {e}")
                return {"refunds_processed": []}

            if not refunds:
                self.logger.info(f"No refunds found for payment {payment_id}")
                return {"refunds_processed": []}

            processed_refunds = []

            # Process each refund
            for refund in refunds:
                self.logger.info(f"Processing refund {refund.id} with status {refund.status}")

                # Only process completed refunds
                if refund.status != "refunded":
                    self.logger.info(
                        f"Skipping refund {refund.id} - status is {refund.status}, not 'refunded'"
                    )
                    continue

                # DEBUG: Log that we're proceeding with this refund
                self.logger.info(f"DEBUG: Refund {refund.id} passed status check, proceeding...")

                # Check if this refund has already been processed (idempotency)
                existing_pe = frappe.db.exists(
                    "Payment Entry", {"reference_no": refund.id, "payment_type": "Pay"}
                )

                if existing_pe:
                    self.logger.info(f"Refund {refund.id} already processed (Payment Entry: {existing_pe})")
                    continue

                # Create webhook payload structure that the refund service expects
                # Handle both object and dict formats for refund.amount
                if hasattr(refund.amount, "value"):
                    # Object format: refund.amount.value, refund.amount.currency
                    amount_value = refund.amount.value
                    amount_currency = refund.amount.currency
                else:
                    # Dict format: refund.amount['value'], refund.amount['currency']
                    amount_value = refund.amount["value"]
                    amount_currency = refund.amount["currency"]

                refund_webhook_payload = {
                    "payment_id": payment_id,
                    "refund_id": refund.id,
                    "refund": {
                        "id": refund.id,
                        "status": refund.status,
                        "amount": {"value": amount_value, "currency": amount_currency},
                        "description": getattr(refund, "description", ""),
                        "created_at": refund.created_at.isoformat() if refund.created_at else None,
                    },
                    "payment": {"id": payment_id},
                }

                # Process the refund using the service
                import json

                result = self.refund_service.process_refund_webhook(json.dumps(refund_webhook_payload))

                if result.get("status") == "success":
                    processed_refunds.append(
                        {
                            "refund_id": refund.id,
                            "amount": amount_value,  # Use the extracted amount_value
                            "payment_entry": result.get("payment_entry_id"),
                            "status": "processed",
                        }
                    )
                    self.logger.info(f"Successfully processed refund {refund.id}")
                else:
                    self.logger.error(f"Failed to process refund {refund.id}: {result.get('message')}")
                    processed_refunds.append(
                        {
                            "refund_id": refund.id,
                            "amount": amount_value,  # Use the extracted amount_value
                            "status": "failed",
                            "error": result.get("message"),
                        }
                    )

            return {
                "refunds_processed": processed_refunds,
                "payment_id": payment_id,
                "total_refunds": len(refunds),
                "processed_count": len([r for r in processed_refunds if r["status"] == "processed"]),
            }

        except Exception as e:
            self.logger.error(f"Error processing refunds for payment {payment_id}: {e}")
            return {"refunds_processed": [], "error": str(e)}

    def get_supported_payment_types(self) -> list:
        """Get list of supported payment types"""
        return [processor.__class__.__name__ for processor in self.processor_factory.processors]

    def add_payment_processor(self, processor):
        """Add a new payment processor"""
        self.processor_factory.register_processor(processor)

    def _validate_webhook_signature(self, payload_json: str, signature: str) -> bool:
        """
        Validate webhook signature using HMAC-SHA256.
        Uses constant-time comparison to prevent timing attacks.

        Args:
            payload_json: Raw webhook payload as JSON string
            signature: Signature from webhook headers

        Returns:
            bool: True if signature is valid
        """
        import hashlib
        import hmac

        try:
            # Get webhook secret from settings
            mollie_settings = frappe.get_single("Mollie Settings")
            webhook_secret = getattr(mollie_settings, "webhook_secret", None)

            if not webhook_secret:
                self.logger.warning("No webhook secret configured")
                return False

            # Calculate expected signature
            expected_signature = hmac.new(
                webhook_secret.encode("utf-8"), payload_json.encode("utf-8"), hashlib.sha256
            ).hexdigest()
            expected_signature = f"sha256={expected_signature}"

            # Use constant-time comparison to prevent timing attacks
            return hmac.compare_digest(signature, expected_signature)

        except Exception as e:
            self.logger.error(f"Error validating webhook signature: {e}")
            return False

    def _validate_webhook_payload_json(self, payload_json: str) -> Optional[str]:
        """
        Validate webhook payload JSON format.

        Args:
            payload_json: Raw webhook payload as JSON string

        Returns:
            str: Error message if validation fails, None if valid
        """
        import json

        try:
            payload = json.loads(payload_json)
            return self._validate_webhook_payload(payload)
        except json.JSONDecodeError as e:
            return f"Invalid JSON payload: {str(e)}"
        except Exception as e:
            return f"Payload validation error: {str(e)}"

    def _validate_webhook_payload(self, payload: Dict[str, Any]) -> Optional[str]:
        """
        Validate webhook payload structure.

        Args:
            payload: Parsed webhook payload

        Returns:
            str: Error message if validation fails, None if valid
        """
        # Check required fields
        required_fields = ["id"]
        for field in required_fields:
            if field not in payload:
                return f"Missing required field: {field}"

        # Validate payload size (prevent oversized payloads)
        payload_str = str(payload)
        if len(payload_str) > 50000:  # 50KB limit
            return f"Payload too large: {len(payload_str)} characters"

        return None

    def process_payment_webhook(self, webhook_payload: str, signature: str) -> Dict[str, Any]:
        """
        Process payment webhook with signature validation.

        Args:
            webhook_payload: Raw webhook payload as JSON string
            signature: Webhook signature for validation

        Returns:
            Dict containing processing results
        """
        try:
            # Validate signature first
            if not self._validate_webhook_signature(webhook_payload, signature):
                return {"status": "error", "message": "Invalid webhook signature"}

            # Validate payload structure
            payload_error = self._validate_webhook_payload_json(webhook_payload)
            if payload_error:
                return {"status": "error", "message": payload_error}

            # Parse payload to get payment ID
            import json

            payload = json.loads(webhook_payload)
            payment_id = payload.get("id")

            if not payment_id:
                return {"status": "error", "message": "No payment ID in webhook payload"}

            # Process webhook
            return self.process_webhook(payment_id)

        except Exception as e:
            self.logger.error(f"Error processing payment webhook: {e}")
            return {"status": "error", "message": f"Webhook processing failed: {str(e)}"}

    def process_refund_webhook(self, webhook_payload: str, signature: str) -> Dict[str, Any]:
        """
        Process refund webhook with signature validation.

        Args:
            webhook_payload: Raw webhook payload as JSON string
            signature: Webhook signature for validation

        Returns:
            Dict containing processing results
        """
        try:
            # Validate signature first
            if not self._validate_webhook_signature(webhook_payload, signature):
                return {"status": "error", "message": "Invalid webhook signature"}

            # Parse payload and delegate to refund service
            import json

            payload = json.loads(webhook_payload)

            return self.refund_service.process_refund_webhook(webhook_payload)

        except Exception as e:
            self.logger.error(f"Error processing refund webhook: {e}")
            return {"status": "error", "message": f"Refund webhook processing failed: {str(e)}"}
