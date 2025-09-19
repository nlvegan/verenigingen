"""
Mollie Integration Validation Utilities

Comprehensive validation system that restores all validation checks from the
original system while providing enhanced security and business rule validation.

This module implements:
- Webhook signature validation for security
- Payload structure validation
- Business rule validation for financial operations
- Idempotency protection validation
- Rate limiting and abuse prevention
"""

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime

from ..exceptions import MollieSecurityError, MollieValidationError
from .logging import MollieLogger


class MollieValidator:
    """
    Comprehensive validation service for Mollie integration.

    Restores and enhances all validation functionality from the original system.
    """

    def __init__(self):
        self.logger = MollieLogger("validator")

    def validate_webhook_signature(self, payload: str, signature: str) -> bool:
        """
        Validate webhook signature using Mollie webhook secret.

        Restores the comprehensive signature validation from the original system.

        Args:
            payload: Raw webhook payload string
            signature: X-Mollie-Signature header value

        Returns:
            Boolean indicating if signature is valid

        Raises:
            MollieSecurityError: When signature validation fails
        """
        try:
            # Get webhook secret from Mollie settings
            mollie_settings = frappe.get_single("Mollie Settings")

            # Choose appropriate webhook secret based on mode
            if mollie_settings.test_mode:
                webhook_secret = getattr(mollie_settings, "testing_webhook_secret_key", None)
            else:
                webhook_secret = getattr(mollie_settings, "live_webhook_secret_key", None)

            if not webhook_secret:
                self.logger.error(
                    "Mollie webhook secret not configured", {"test_mode": mollie_settings.test_mode}
                )
                raise MollieSecurityError("Mollie webhook secret not configured in settings")

            # Generate expected signature
            expected_signature = hmac.new(
                webhook_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
            ).hexdigest()

            # Compare signatures using constant-time comparison
            is_valid = hmac.compare_digest(signature, expected_signature)

            if is_valid:
                self.logger.info("Webhook signature validation successful")
            else:
                self.logger.error(
                    "Webhook signature validation failed",
                    {
                        "provided_signature_length": len(signature),
                        "expected_signature_length": len(expected_signature),
                    },
                )

            return is_valid

        except Exception as e:
            self.logger.error("Error validating webhook signature", error=e)
            raise MollieSecurityError(f"Webhook signature validation error: {e}")

    def validate_webhook_payload(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """
        Validate webhook payload structure and content.

        Restores comprehensive payload validation from the original system.

        Args:
            webhook_data: Parsed webhook data

        Returns:
            Error message if validation fails, None if valid
        """
        try:
            # Basic structure validation
            if not isinstance(webhook_data, dict):
                return "Webhook payload must be a JSON object"

            # Determine webhook type and validate accordingly
            if "payment" in webhook_data:
                return self._validate_payment_webhook_payload(webhook_data)
            elif "refund" in webhook_data:
                return self._validate_refund_webhook_payload(webhook_data)
            elif "chargeback" in webhook_data:
                return self._validate_chargeback_webhook_payload(webhook_data)
            else:
                return "Unknown webhook type - missing payment, refund, or chargeback data"

        except Exception as e:
            self.logger.error("Payload validation error", error=e)
            return f"Payload validation error: {str(e)}"

    def _validate_payment_webhook_payload(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """Validate payment-specific webhook payload."""
        payment_data = webhook_data.get("payment", {})

        if not payment_data.get("id"):
            return "Missing payment ID in webhook payload"

        # Validate payment ID format (Mollie payment IDs start with 'tr_')
        payment_id = payment_data.get("id")
        if not payment_id.startswith("tr_"):
            return f"Invalid payment ID format: {payment_id}"

        # Validate required fields
        if not payment_data.get("status"):
            return "Missing payment status in webhook payload"

        if not payment_data.get("amount"):
            return "Missing payment amount in webhook payload"

        return None

    def _validate_refund_webhook_payload(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """Validate refund-specific webhook payload."""
        refund_data = webhook_data.get("refund", {})

        if not refund_data.get("id"):
            return "Missing refund ID in webhook payload"

        # Validate refund ID format (Mollie refund IDs start with 're_')
        refund_id = refund_data.get("id")
        if not refund_id.startswith("re_"):
            return f"Invalid refund ID format: {refund_id}"

        # Validate payment reference
        payment_data = webhook_data.get("payment", {})
        if not payment_data.get("id"):
            return "Missing payment ID in refund webhook"

        return None

    def _validate_chargeback_webhook_payload(self, webhook_data: Dict[str, Any]) -> Optional[str]:
        """Validate chargeback-specific webhook payload."""
        chargeback_data = webhook_data.get("chargeback", {})

        if not chargeback_data.get("id"):
            return "Missing chargeback ID in webhook payload"

        # Validate chargeback ID format (Mollie chargeback IDs start with 'chb_')
        chargeback_id = chargeback_data.get("id")
        if not chargeback_id.startswith("chb_"):
            return f"Invalid chargeback ID format: {chargeback_id}"

        # Validate payment reference
        payment_data = webhook_data.get("payment", {})
        if not payment_data.get("id"):
            return "Missing payment ID in chargeback webhook"

        return None

    def validate_payment_amount(
        self, amount: Any, currency: str = "EUR"
    ) -> Tuple[bool, str, Optional[Decimal]]:
        """
        Validate payment amount for business rules.

        Args:
            amount: Amount to validate (can be string, float, or Decimal)
            currency: Currency code (default: EUR)

        Returns:
            Tuple of (is_valid, error_message, validated_amount)
        """
        try:
            # Convert to Decimal for precise validation
            if isinstance(amount, str):
                amount_decimal = Decimal(amount)
            elif isinstance(amount, (int, float)):
                amount_decimal = Decimal(str(amount))
            elif isinstance(amount, Decimal):
                amount_decimal = amount
            else:
                return False, f"Invalid amount type: {type(amount)}", None

            # Validate minimum amount (€0.01 for EUR)
            min_amount = Decimal("0.01")
            if amount_decimal < min_amount:
                return False, f"Amount {amount_decimal} is below minimum {min_amount} {currency}", None

            # Validate maximum amount (€10,000 for donations)
            max_amount = Decimal("10000.00")
            if amount_decimal > max_amount:
                return False, f"Amount {amount_decimal} exceeds maximum {max_amount} {currency}", None

            # Validate decimal places (max 2 for EUR)
            if amount_decimal.as_tuple().exponent < -2:
                return False, f"Amount {amount_decimal} has too many decimal places", None

            return True, "", amount_decimal

        except Exception as e:
            return False, f"Amount validation error: {e}", None

    def validate_mollie_id(self, mollie_id: str, id_type: str) -> Tuple[bool, str]:
        """
        Validate Mollie ID format and structure.

        Args:
            mollie_id: The Mollie ID to validate
            id_type: Expected type ('payment', 'refund', 'chargeback', 'customer', 'subscription')

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not mollie_id or not isinstance(mollie_id, str):
            return False, f"Invalid {id_type} ID: must be a non-empty string"

        # Define expected prefixes
        prefix_map = {
            "payment": "tr_",
            "refund": "re_",
            "chargeback": "chb_",
            "customer": "cst_",
            "subscription": "sub_",
        }

        expected_prefix = prefix_map.get(id_type)
        if not expected_prefix:
            return False, f"Unknown ID type: {id_type}"

        if not mollie_id.startswith(expected_prefix):
            return False, f"Invalid {id_type} ID format: expected to start with {expected_prefix}"

        # Validate ID length (Mollie IDs are typically 16-20 characters)
        if len(mollie_id) < 10 or len(mollie_id) > 25:
            return False, f"Invalid {id_type} ID length: {len(mollie_id)} characters"

        # Validate character set (alphanumeric + underscore)
        if not re.match(r"^[a-zA-Z0-9_]+$", mollie_id):
            return False, f"Invalid {id_type} ID format: contains invalid characters"

        return True, ""

    def validate_donation_eligibility(self, donation_id: str) -> Tuple[bool, str, Optional[Any]]:
        """
        Validate that a donation is eligible for payment processing.

        Args:
            donation_id: The donation document name

        Returns:
            Tuple of (is_valid, error_message, donation_doc)
        """
        try:
            # Check if donation exists
            if not frappe.db.exists("Donation", donation_id):
                return False, f"Donation {donation_id} does not exist", None

            # Get donation document
            donation = frappe.get_doc("Donation", donation_id)

            # Validate donation status
            if donation.status not in ["Draft", "Pending Payment"]:
                return (
                    False,
                    f"Donation {donation_id} status '{donation.status}' is not eligible for payment",
                    None,
                )

            # Validate donation amount
            if not donation.amount or donation.amount <= 0:
                return False, f"Donation {donation_id} has invalid amount: {donation.amount}", None

            # Check if already paid
            if hasattr(donation, "payment_status") and donation.payment_status == "Paid":
                return False, f"Donation {donation_id} is already paid", None

            # Validate donor information
            if not donation.donor_email:
                return False, f"Donation {donation_id} missing donor email", None

            return True, "", donation

        except Exception as e:
            self.logger.error(
                "Donation eligibility validation error", error=e, extra={"donation_id": donation_id}
            )
            return False, f"Validation error: {e}", None

    def validate_idempotency_protection(
        self, operation_type: str, reference_id: str
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Validate idempotency protection for financial operations.

        Args:
            operation_type: Type of operation ('payment', 'refund', 'chargeback')
            reference_id: Mollie reference ID

        Returns:
            Tuple of (is_duplicate, message, existing_record_id)
        """
        try:
            # Define search criteria based on operation type
            if operation_type == "payment":
                doctype = "Payment Entry"
                filters = {"reference_no": reference_id, "payment_type": "Receive"}
            elif operation_type == "refund":
                doctype = "Payment Entry"
                filters = {"reference_no": reference_id, "payment_type": "Pay"}
            elif operation_type == "chargeback":
                doctype = "Payment Entry"
                filters = {"reference_no": reference_id, "payment_type": "Pay"}
            else:
                return False, f"Unknown operation type: {operation_type}", None

            # Check for existing record
            existing_record = frappe.db.get_value(doctype, filters, "name")

            if existing_record:
                return True, f"{operation_type.title()} {reference_id} already processed", existing_record
            else:
                return False, f"{operation_type.title()} {reference_id} not yet processed", None

        except Exception as e:
            self.logger.error(
                "Idempotency validation error",
                error=e,
                extra={"operation_type": operation_type, "reference_id": reference_id},
            )
            return False, f"Idempotency validation error: {e}", None

    def validate_rate_limiting(self, client_identifier: str, operation_type: str) -> Tuple[bool, str]:
        """
        Validate rate limiting for webhook operations.

        Args:
            client_identifier: Client IP or identifier
            operation_type: Type of operation being rate limited

        Returns:
            Tuple of (is_allowed, error_message)
        """
        try:
            # Get rate limiting configuration
            rate_limit = 100  # Max 100 requests per hour per client
            time_window = 3600  # 1 hour in seconds

            # Create cache key
            cache_key = f"mollie_rate_limit:{operation_type}:{client_identifier}"

            # Get current count from cache
            current_count = frappe.cache().get(cache_key) or 0

            if current_count >= rate_limit:
                return False, f"Rate limit exceeded: {current_count}/{rate_limit} requests in last hour"

            # Increment counter
            frappe.cache().set(cache_key, current_count + 1, time_window)

            return True, ""

        except Exception as e:
            self.logger.error("Rate limiting validation error", error=e)
            # Allow request on validation error to prevent blocking legitimate traffic
            return True, f"Rate limiting validation error: {e}"

    def validate_business_rules(self, operation_data: Dict[str, Any], operation_type: str) -> List[str]:
        """
        Validate business rules for financial operations.

        Args:
            operation_data: Operation data to validate
            operation_type: Type of operation ('payment', 'refund', 'chargeback')

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        try:
            if operation_type == "payment":
                errors.extend(self._validate_payment_business_rules(operation_data))
            elif operation_type == "refund":
                errors.extend(self._validate_refund_business_rules(operation_data))
            elif operation_type == "chargeback":
                errors.extend(self._validate_chargeback_business_rules(operation_data))

        except Exception as e:
            self.logger.error("Business rules validation error", error=e)
            errors.append(f"Business rules validation error: {e}")

        return errors

    def _validate_payment_business_rules(self, payment_data: Dict[str, Any]) -> List[str]:
        """Validate payment-specific business rules."""
        errors = []

        # Validate payment method restrictions
        if "method" in payment_data:
            allowed_methods = ["ideal", "creditcard", "bancontact", "sofort", "giropay"]
            if payment_data["method"] not in allowed_methods:
                errors.append(f"Payment method '{payment_data['method']}' not allowed")

        # Validate currency
        if payment_data.get("currency") != "EUR":
            errors.append(f"Currency '{payment_data.get('currency')}' not supported")

        return errors

    def _validate_refund_business_rules(self, refund_data: Dict[str, Any]) -> List[str]:
        """Validate refund-specific business rules."""
        errors = []

        # Validate refund timing (refunds must be within 1 year of original payment)
        if "original_payment_date" in refund_data:
            try:
                payment_date = getdate(refund_data["original_payment_date"])
                max_refund_date = payment_date + timedelta(days=365)
                if getdate() > max_refund_date:
                    errors.append("Refund request exceeds maximum allowed timeframe (1 year)")
            except Exception:
                errors.append("Invalid original payment date format")

        return errors

    def _validate_chargeback_business_rules(self, chargeback_data: Dict[str, Any]) -> List[str]:
        """Validate chargeback-specific business rules."""
        errors = []

        # Validate chargeback reason codes
        valid_reason_codes = [
            "fraud",
            "unrecognized",
            "duplicate",
            "credit_not_processed",
            "cancelled_recurring",
        ]
        if "reason" in chargeback_data:
            reason_code = chargeback_data["reason"].get("code")
            if reason_code and reason_code not in valid_reason_codes:
                errors.append(f"Invalid chargeback reason code: {reason_code}")

        return errors
