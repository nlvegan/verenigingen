# Copyright (c) 2025, Verenigingen
# License: MIT

"""
PaymentHook - Universal payment integration service.

Provides a unified interface for payment processing that can be used
by any form (donations, memberships, events) with consistent behavior.

Usage:
    from verenigingen.verenigingen_payments.hooks import PaymentHook

    # Get available methods for context
    methods = PaymentHook.get_available_methods(context={"recurring": True})

    # Initiate payment
    result = PaymentHook.initiate_payment(
        method="mollie",
        amount=50.00,
        reference_doctype="Donation",
        reference_name="DON-00001",
        payer_info={"email": "donor@example.com", "name": "John Doe"},
        redirect_urls={"success": "/thank-you", "cancel": "/donate"}
    )
"""

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt

from verenigingen.utils.settings_utils import get_payments_settings
from verenigingen.utils.validation.api_validators import APIValidator
from verenigingen.utils.validation.iban_validator import validate_iban
from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

# Payment amount limits
MAX_PAYMENT_AMOUNT = 100000.00  # €100k reasonable max for association payments


class PaymentAction:
    """Constants for payment action types."""

    REDIRECT = "redirect"  # Redirect to external payment page (Mollie)
    MANDATE_FORM = "mandate_form"  # Show SEPA mandate confirmation
    SHOW_INSTRUCTIONS = "show_instructions"  # Display payment instructions (Bank/Cash)


class PaymentHook:
    """
    Universal payment integration hook.

    Provides a unified interface for initiating payments across different
    gateways while handling configuration checks and response normalization.
    """

    # Method identifiers (internal)
    MOLLIE = "mollie"
    PONTO = "ponto"
    SEPA = "sepa"
    BANK_TRANSFER = "bank_transfer"
    CASH = "cash"

    # Mapping from internal IDs to gateway names
    _METHOD_TO_GATEWAY = {
        MOLLIE: "Mollie",
        PONTO: "Ponto",
        SEPA: "SEPA Direct Debit",
        BANK_TRANSFER: "Bank Transfer",
        CASH: "Cash",
    }

    @classmethod
    def get_available_methods(cls, context: dict | None = None) -> list[dict[str, Any]]:
        """
        Get payment methods available for the given context.

        Args:
            context: Optional context for filtering. Supported keys:
                - recurring: bool - Only return methods supporting recurring
                - form_type: str - Form type (donation, membership, event)
                - amount: float - Filter by amount thresholds

        Returns:
            List of available payment methods with metadata:
            [
                {
                    "id": "mollie",
                    "label": "Online Payment",
                    "description": "Pay with iDEAL, credit card, or other methods",
                    "supports_recurring": True,
                    "type": "redirect"
                },
                ...
            ]
        """
        context = context or {}
        methods = []

        # Check Mollie availability
        mollie_config = cls._get_mollie_config()
        if mollie_config.get("available"):
            mollie_method = {
                "id": cls.MOLLIE,
                "label": _("Online Payment"),
                "description": _("Pay with iDEAL, credit card, or other methods"),
                "supports_recurring": mollie_config.get("subscriptions_enabled", False),
                "type": PaymentAction.REDIRECT,
            }

            # Filter by recurring requirement
            if context.get("recurring") and not mollie_method["supports_recurring"]:
                pass  # Skip if recurring required but not supported
            else:
                methods.append(mollie_method)

        # Check Ponto availability
        ponto_config = cls._get_ponto_config()
        if ponto_config.get("available"):
            # Ponto doesn't support recurring (only one-time betaalverzoeken)
            if not context.get("recurring"):
                methods.append(
                    {
                        "id": cls.PONTO,
                        "label": _("Bank Payment (Ponto)"),
                        "description": _("Pay directly from your bank account"),
                        "supports_recurring": False,
                        "type": PaymentAction.REDIRECT,
                    }
                )

        # Check SEPA Direct Debit availability
        sepa_config = cls._get_sepa_config()
        if sepa_config.get("available"):
            methods.append(
                {
                    "id": cls.SEPA,
                    "label": _("SEPA Direct Debit"),
                    "description": _("Authorize automatic collection from your bank account"),
                    "supports_recurring": True,
                    "type": PaymentAction.MANDATE_FORM,
                }
            )

        # Check Bank Transfer availability
        bank_config = cls._get_bank_transfer_config()
        if bank_config.get("available"):
            # Bank transfer doesn't support recurring in the automated sense
            if not context.get("recurring"):
                methods.append(
                    {
                        "id": cls.BANK_TRANSFER,
                        "label": _("Bank Transfer"),
                        "description": _("Transfer directly to our bank account"),
                        "supports_recurring": False,
                        "type": PaymentAction.SHOW_INSTRUCTIONS,
                    }
                )

        # Cash is always available (unless explicitly disabled later)
        if not context.get("recurring"):
            methods.append(
                {
                    "id": cls.CASH,
                    "label": _("Cash"),
                    "description": _("Pay in cash at our office or events"),
                    "supports_recurring": False,
                    "type": PaymentAction.SHOW_INSTRUCTIONS,
                }
            )

        return methods

    @classmethod
    def initiate_payment(
        cls,
        method: str,
        amount: float,
        reference_doctype: str,
        reference_name: str,
        payer_info: dict,
        redirect_urls: dict | None = None,
        recurring: bool = False,
        interval: str | None = None,
    ) -> dict[str, Any]:
        """
        Initiate payment via the specified method.

        Args:
            method: Payment method ID (mollie, sepa, bank_transfer, cash)
            amount: Payment amount
            reference_doctype: DocType being paid for (Donation, Membership, etc.)
            reference_name: Document name
            payer_info: Payer details {"email": "...", "name": "...", "iban": "..."}
            redirect_urls: URLs for redirects {"success": "...", "cancel": "..."}
            recurring: Whether this is a recurring payment setup
            interval: Recurring interval (e.g., "1 month", "3 months", "1 year")

        Returns:
            Standardized response:
            {
                "success": True/False,
                "action": "redirect" | "mandate_form" | "show_instructions",
                "data": {...},  # Action-specific data
                "payment_id": "...",  # If applicable
                "message": "..."
            }
        """
        # === Input Validation ===

        # Validate amount (with min/max bounds)
        try:
            validated_amount = APIValidator.validate_amount(
                amount, min_amount=0.01, max_amount=MAX_PAYMENT_AMOUNT
            )
        except Exception:
            return {
                "success": False,
                "action": None,
                "data": {},
                "message": _("Invalid payment amount"),
            }

        amount = validated_amount

        # Validate email if provided
        email = payer_info.get("email")
        if email:
            try:
                email = APIValidator.validate_email(email, required=False)
            except Exception:
                return {
                    "success": False,
                    "action": None,
                    "data": {},
                    "message": _("Invalid email address format"),
                }

        # Validate IBAN if provided (for SEPA payments)
        iban = payer_info.get("iban")
        if iban:
            iban_result = validate_iban(iban)
            if not iban_result.get("valid"):
                return {
                    "success": False,
                    "action": None,
                    "data": {},
                    "message": iban_result.get("message", _("Invalid IBAN")),
                }

        gateway_name = cls._METHOD_TO_GATEWAY.get(method)
        if not gateway_name:
            return {
                "success": False,
                "action": None,
                "data": {},
                "message": _("Unknown payment method: {0}").format(method),
            }

        # Verify method is available
        available_methods = cls.get_available_methods({"recurring": recurring})
        if not any(m["id"] == method for m in available_methods):
            return {
                "success": False,
                "action": None,
                "data": {},
                "message": _("Payment method {0} is not available").format(method),
            }

        try:
            # Get the reference document
            ref_doc = frappe.get_doc(reference_doctype, reference_name)

            # Build form_data for gateway
            form_data = frappe._dict(
                {
                    "amount": amount,
                    "email": payer_info.get("email"),
                    "name": payer_info.get("name"),
                    "iban": payer_info.get("iban"),
                    "account_holder": payer_info.get("account_holder") or payer_info.get("name"),
                    "recurring": recurring,
                    "interval": interval,
                    "redirect_url": redirect_urls.get("success") if redirect_urls else None,
                    "cancel_url": redirect_urls.get("cancel") if redirect_urls else None,
                }
            )

            # Get gateway and process
            gateway = PaymentGatewayFactory.get_gateway(gateway_name)
            result = gateway.process_payment(ref_doc, form_data)

            # Normalize response to standard format
            return cls._normalize_gateway_response(method, result)

        except Exception as e:
            # Log detailed error for administrators, return generic message to users
            error_id = frappe.generate_hash(length=8)
            frappe.log_error(
                f"PaymentHook error [{error_id}] for {reference_doctype}/{reference_name}: {e}\n{frappe.get_traceback()}",
                "Payment Hook Error",
            )
            return {
                "success": False,
                "action": None,
                "data": {"error_id": error_id},
                "message": _(
                    "Payment processing failed. Please try again or contact support. (Reference: {0})"
                ).format(error_id),
            }

    @classmethod
    def get_payment_status(cls, method: str, payment_id: str) -> dict[str, Any]:
        """
        Check payment status for tracking.

        Args:
            method: Payment method ID
            payment_id: Payment identifier from gateway

        Returns:
            {
                "status": "pending" | "paid" | "failed" | "expired",
                "data": {...}
            }
        """
        gateway_name = cls._METHOD_TO_GATEWAY.get(method)
        if not gateway_name:
            return {"status": "unknown", "data": {}, "message": _("Unknown payment method")}

        try:
            gateway = PaymentGatewayFactory.get_gateway(gateway_name)
            result = gateway.get_payment_status(payment_id)
            return {"status": result.get("status", "unknown"), "data": result}
        except Exception as e:
            # Log detailed error, return generic message to users
            error_id = frappe.generate_hash(length=8)
            frappe.log_error(
                f"Payment status check error [{error_id}] for {payment_id}: {e}",
                "Payment Status Error",
            )
            return {
                "status": "error",
                "data": {"error_id": error_id},
                "message": _("Unable to check payment status. Please try again later."),
            }

    # --- Configuration helpers ---

    @classmethod
    def _get_mollie_config(cls) -> dict:
        """Check if Mollie is properly configured."""
        try:
            settings = frappe.get_single("Mollie Settings")
            has_api_key = bool(settings.test_secret_key if settings.test_mode else settings.live_secret_key)
            return {
                "available": has_api_key,
                "subscriptions_enabled": bool(getattr(settings, "enable_subscriptions", False)),
                "test_mode": bool(settings.test_mode),
            }
        except Exception as e:
            error_id = frappe.generate_hash(length=8)
            frappe.log_error(
                f"[{error_id}] Mollie config check failed: {e}", "Payment Configuration - Mollie"
            )
            return {"available": False, "reason": f"Configuration error (ref: {error_id})"}

    @classmethod
    def _get_sepa_config(cls) -> dict:
        """Check if SEPA Direct Debit is properly configured."""
        try:
            # Check the enable flag in Verenigingen Payments Settings
            payment_settings = get_payments_settings()
            if not getattr(payment_settings, "enable_sepa_direct_debit", False):
                return {"available": False, "reason": "SEPA not enabled"}

            # Check required fields in Verenigingen Settings
            settings = frappe.get_single("Verenigingen Settings")
            has_iban = bool(getattr(settings, "company_iban", None))
            has_creditor_id = bool(getattr(settings, "sepa_creditor_id", None))

            return {
                "available": has_iban and has_creditor_id,
                "has_iban": has_iban,
                "has_creditor_id": has_creditor_id,
                "reason": None if (has_iban and has_creditor_id) else "Missing IBAN or Creditor ID",
            }
        except Exception as e:
            error_id = frappe.generate_hash(length=8)
            frappe.log_error(f"[{error_id}] SEPA config check failed: {e}", "Payment Configuration - SEPA")
            return {"available": False, "reason": f"Configuration error (ref: {error_id})"}

    @classmethod
    def _get_bank_transfer_config(cls) -> dict:
        """Check if Bank Transfer is available."""
        try:
            settings = frappe.get_single("Verenigingen Settings")
            has_iban = bool(getattr(settings, "company_iban", None))
            return {"available": has_iban}
        except Exception as e:
            error_id = frappe.generate_hash(length=8)
            frappe.log_error(
                f"[{error_id}] Bank Transfer config check failed: {e}",
                "Payment Configuration - Bank Transfer",
            )
            return {"available": False, "reason": f"Configuration error (ref: {error_id})"}

    @classmethod
    def _get_ponto_config(cls) -> dict:
        """Check if Ponto is properly configured for payment requests."""
        try:
            ponto_settings = frappe.get_single("Ponto Settings")
            sandbox_mode = bool(getattr(ponto_settings, "sandbox_mode", True))

            # Check mode-specific Ibanity credentials
            # Must match active mode - consistent with ponto_settings.validate_credentials_configured()
            if sandbox_mode:
                has_credentials = bool(ponto_settings.sandbox_client_id)
                env = "Sandbox"
            else:
                has_credentials = bool(ponto_settings.production_client_id)
                env = "Production"

            if not has_credentials:
                return {"available": False, "reason": f"No {env} Ibanity credentials configured"}

            # Check if payment requests are activated (Ponto feature flag)
            payment_requests_activated = bool(getattr(ponto_settings, "payment_requests_activated", False))
            if not payment_requests_activated:
                return {"available": False, "reason": "Payment requests not activated in Ponto"}

            # Check for company IBAN (needed as creditor)
            ver_settings = frappe.get_single("Verenigingen Settings")
            has_iban = bool(getattr(ver_settings, "company_iban", None))
            if not has_iban:
                return {"available": False, "reason": "Company IBAN not configured"}

            return {
                "available": True,
                "sandbox_mode": sandbox_mode,
                "has_credentials": has_credentials,
                "has_iban": has_iban,
                "payment_requests_activated": payment_requests_activated,
            }
        except Exception as e:
            error_id = frappe.generate_hash(length=8)
            frappe.log_error(f"[{error_id}] Ponto config check failed: {e}", "Payment Configuration - Ponto")
            return {"available": False, "reason": f"Configuration error (ref: {error_id})"}

    # --- Response normalization ---

    @classmethod
    def _normalize_gateway_response(cls, method: str, result: dict) -> dict[str, Any]:
        """
        Normalize gateway-specific responses to standard format.

        Gateway responses vary:
        - Mollie: {"status": "redirect_required", "payment_url": "..."}
        - SEPA: {"status": "mandate_created", "mandate_id": "..."}
        - Bank: {"status": "awaiting_transfer", "bank_details": {...}}
        - Cash: {"status": "cash_pending", ...}

        Standard format:
        {
            "success": True,
            "action": "redirect" | "mandate_form" | "show_instructions",
            "data": {...},
            "payment_id": "...",
            "message": "..."
        }
        """
        status = result.get("status", "")

        # Mollie redirect
        if status in ("redirect_required", "subscription_redirect_required"):
            return {
                "success": True,
                "action": PaymentAction.REDIRECT,
                "data": {
                    "url": result.get("payment_url") or result.get("checkout_url"),
                    "expires_at": result.get("expires_at"),
                },
                "payment_id": result.get("payment_id"),
                "message": result.get("message", _("Redirecting to payment provider...")),
            }

        # SEPA mandate
        if status == "mandate_created":
            return {
                "success": True,
                "action": PaymentAction.MANDATE_FORM,
                "data": {
                    "mandate_id": result.get("mandate_id"),
                    "collection_date": result.get("collection_date"),
                },
                "payment_id": result.get("mandate_id"),
                "message": result.get("message", _("SEPA mandate created successfully")),
            }

        # Bank transfer instructions
        if status == "awaiting_transfer":
            return {
                "success": True,
                "action": PaymentAction.SHOW_INSTRUCTIONS,
                "data": {
                    "bank_details": result.get("bank_details", {}),
                    "payment_reference": result.get("payment_reference"),
                    "instructions": result.get("instructions"),
                    "expected_days": result.get("expected_days", 3),
                },
                "payment_id": result.get("payment_reference"),
                "message": result.get("message", _("Please complete the bank transfer")),
            }

        # Cash instructions
        if status == "cash_pending":
            return {
                "success": True,
                "action": PaymentAction.SHOW_INSTRUCTIONS,
                "data": {
                    "reference": result.get("reference"),
                    "instructions": result.get("instructions"),
                    "contact_email": result.get("contact_email"),
                    "office_hours": result.get("office_hours"),
                },
                "payment_id": result.get("reference"),
                "message": result.get("message", _("Please bring cash to complete payment")),
            }

        # Error or unknown status
        if status == "error" or not status:
            return {
                "success": False,
                "action": None,
                "data": result,
                "payment_id": None,
                "message": result.get("message", _("Payment processing failed")),
            }

        # Fallback for any other status
        return {
            "success": True,
            "action": PaymentAction.SHOW_INSTRUCTIONS,
            "data": result,
            "payment_id": result.get("payment_id"),
            "message": result.get("message", _("Payment initiated")),
        }
