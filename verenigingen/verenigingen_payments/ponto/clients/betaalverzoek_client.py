# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Betaalverzoek Client

Handles incoming payment requests (betaalverzoek) through Ponto Connect API.
These are payment requests where customers authorize payments FROM their
bank account TO your organization's account.

Supports:
- One-time payment requests (Payment Initiation Request)

NOTE: Periodic payment requests (standing orders) are NOT supported by Ponto Connect.
      The periodic payment methods in this module are deprecated and will raise
      NotImplementedError. For recurring payments, use SEPA Direct Debit or
      Mollie subscriptions instead.

Payment Flow:
1. Create payment request via API (provides redirect URL)
2. Customer clicks redirect URL and selects their bank
3. Customer authorizes payment at their bank
4. Bank executes payment to your creditor account
5. Track status via polling or webhook

Usage:
    from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import (
        get_betaalverzoek_client,
    )

    client = get_betaalverzoek_client()

    # Create one-time payment request
    result = client.create_payment_request(
        amount=25.00,
        creditor_name="Vegan Netwerk Nederland",
        creditor_iban="NL91ABNA0417164300",
        remittance_info="Membership dues - John Doe",
        redirect_uri="https://your-site.com/ponto/callback",
    )

    # Share result.redirect_link with customer
"""

import re
import unicodedata
import warnings
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.utils.validation.iban_validator import validate_iban
from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient
from verenigingen.verenigingen_payments.ponto.exceptions import (
    PontoAPIError,
    PontoConfigurationError,
    PontoIntegrationError,
)
from verenigingen.verenigingen_payments.ponto.services.configuration_service import get_ponto_config


def sanitize_sepa_text(text: str, field_name: str = "text") -> str:
    """
    Sanitize text for SEPA compliance.

    SEPA only allows a limited character set in remittance information:
    - Letters: a-z A-Z
    - Digits: 0-9
    - Special: / - ? : ( ) . , ' + and space

    Args:
        text: The text to sanitize
        field_name: Name of field for logging purposes

    Returns:
        Sanitized text with only SEPA-allowed characters
    """
    if not text:
        return text

    original = text

    # First, normalize unicode to ASCII equivalents where possible
    # This handles accented characters like é -> e, ñ -> n, ü -> u
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")

    # Replace common problematic characters with SEPA-safe equivalents
    replacements = {
        "—": "-",  # em-dash to hyphen
        "–": "-",  # en-dash to hyphen
        """: "'",  # smart double quote to apostrophe
        """: "'",  # smart double quote to apostrophe
        "'": "'",  # smart single quote to apostrophe
        "'": "'",  # smart single quote to apostrophe
        "€": "EUR",  # euro symbol to text
        "&": "+",  # ampersand to plus
        ";": ",",  # semicolon to comma
        "!": ".",  # exclamation to period
        "@": "",  # remove at sign
        "#": "",  # remove hash
        "$": "",  # remove dollar
        "%": "",  # remove percent
        "*": "",  # remove asterisk
        "=": "-",  # equals to hyphen
        "[": "(",  # brackets to parentheses
        "]": ")",
        "{": "(",
        "}": ")",
        "<": "(",
        ">": ")",
        "_": "-",  # underscore to hyphen
        "\\": "/",  # backslash to forward slash
        "|": "/",  # pipe to forward slash
        "\n": " ",  # newline to space
        "\r": " ",  # carriage return to space
        "\t": " ",  # tab to space
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    # Keep only SEPA-allowed characters: a-zA-Z0-9 and / - ? : ( ) . , ' + space
    text = re.sub(r"[^a-zA-Z0-9/\-?:().,'+\s]", "", text)

    # Collapse multiple spaces into single space
    text = re.sub(r"\s+", " ", text)

    # Trim whitespace
    text = text.strip()

    # Log if sanitization changed the text
    if text != original:
        frappe.logger().info(f"SEPA sanitized {field_name}: '{original[:50]}...' -> '{text[:50]}...'")

    return text


@dataclass
class PaymentInitiationRequest:
    """Represents a Ponto payment initiation request (incoming payment)."""

    id: str
    status: str
    amount: Decimal
    currency: str
    creditor_name: str
    creditor_iban: str
    creditor_agent: Optional[str]  # BIC
    remittance_info: str
    redirect_uri: Optional[str]
    redirect_link: Optional[str]  # URL for customer to authorize
    # Debtor info (filled after authorization)
    debtor_name: Optional[str]
    debtor_iban: Optional[str]
    debtor_bank: Optional[str]
    # Tracking
    end_to_end_id: Optional[str]
    # Timestamps for status inference (Ponto doesn't return a status field)
    signed_at: Optional[str] = None  # When customer authorized the payment
    closed_at: Optional[str] = None  # When payment reached final state

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "PaymentInitiationRequest":
        """
        Create PaymentInitiationRequest from Ponto API response.

        Args:
            data: JSON:API response data object

        Returns:
            PaymentInitiationRequest instance

        Raises:
            PontoAPIError: If required fields are missing from response
        """
        if not data:
            raise PontoAPIError(
                message="Empty response data from Ponto API",
                details={"received": data},
            )

        request_id = data.get("id")
        if not request_id:
            raise PontoAPIError(
                message="Missing 'id' field in Ponto API response",
                details={"received_keys": list(data.keys())},
            )

        attrs = data.get("attributes", {})
        if not attrs:
            raise PontoAPIError(
                message="Missing 'attributes' in Ponto API response",
                details={"id": request_id, "received_keys": list(data.keys())},
            )

        # The signing/authorization URL is in attributes.signingUri
        # This is the URL customers use to authorize the payment
        redirect_link = attrs.get("signingUri", "") or data.get("links", {}).get("redirect", "")

        # Extract timestamps for status inference
        signed_at = attrs.get("signedAt")
        closed_at = attrs.get("closedAt")

        # Infer status from timestamps since Ponto API doesn't return a status field
        # Priority: closedAt > signedAt > pending
        if attrs.get("status"):
            # If API returns explicit status, use it
            status = attrs.get("status")
        elif closed_at:
            # Payment has reached final state (executed, rejected, or expired)
            status = "closed"
        elif signed_at:
            # Customer has authorized but payment not yet executed
            status = "signed"
        else:
            # Waiting for customer authorization
            status = "pending"

        return cls(
            id=data.get("id", ""),
            status=status,
            amount=Decimal(str(attrs.get("amount", "0"))),
            currency=attrs.get("currency", "EUR"),
            creditor_name=attrs.get("creditorName", ""),
            creditor_iban=attrs.get("creditorAccountReference", ""),
            creditor_agent=attrs.get("creditorAgent", ""),
            remittance_info=attrs.get("remittanceInformation", ""),
            redirect_uri=attrs.get("redirectUri", ""),
            redirect_link=redirect_link,
            debtor_name=attrs.get("debtorName"),
            debtor_iban=attrs.get("debtorAccountReference"),
            debtor_bank=attrs.get("debtorAgent"),
            end_to_end_id=attrs.get("endToEndId"),
            signed_at=signed_at,
            closed_at=closed_at,
        )


@dataclass
class PeriodicPaymentInitiationRequest:
    """Represents a Ponto periodic payment initiation request (recurring payment)."""

    id: str
    status: str
    amount: Decimal
    currency: str
    creditor_name: str
    creditor_iban: str
    creditor_agent: Optional[str]  # BIC
    remittance_info: str
    frequency: str  # daily, weekly, monthly, quarterly, yearly
    start_date: Optional[date]
    end_date: Optional[date]  # None for open-ended
    redirect_uri: Optional[str]
    redirect_link: Optional[str]  # URL for customer to authorize
    # Debtor info (filled after authorization)
    debtor_name: Optional[str]
    debtor_iban: Optional[str]
    debtor_bank: Optional[str]
    # Tracking
    end_to_end_id: Optional[str]

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "PeriodicPaymentInitiationRequest":
        """
        Create PeriodicPaymentInitiationRequest from Ponto API response.

        Args:
            data: JSON:API response data object

        Returns:
            PeriodicPaymentInitiationRequest instance
        """
        attrs = data.get("attributes", {})

        # Parse dates
        start_date = None
        if attrs.get("startDate"):
            try:
                start_date = date.fromisoformat(attrs["startDate"])
            except (ValueError, TypeError):
                pass

        end_date = None
        if attrs.get("endDate"):
            try:
                end_date = date.fromisoformat(attrs["endDate"])
            except (ValueError, TypeError):
                pass

        # The signing/authorization URL is in attributes.signingUri
        redirect_link = attrs.get("signingUri", "") or data.get("links", {}).get("redirect", "")

        return cls(
            id=data.get("id", ""),
            status=attrs.get("status", ""),
            amount=Decimal(str(attrs.get("amount", "0"))),
            currency=attrs.get("currency", "EUR"),
            creditor_name=attrs.get("creditorName", ""),
            creditor_iban=attrs.get("creditorAccountReference", ""),
            creditor_agent=attrs.get("creditorAgent", ""),
            remittance_info=attrs.get("remittanceInformation", ""),
            frequency=attrs.get("frequency", ""),
            start_date=start_date,
            end_date=end_date,
            redirect_uri=attrs.get("redirectUri", ""),
            redirect_link=redirect_link,
            debtor_name=attrs.get("debtorName"),
            debtor_iban=attrs.get("debtorAccountReference"),
            debtor_bank=attrs.get("debtorAgent"),
            end_to_end_id=attrs.get("endToEndId"),
        )


class PontoBetaalverzoekClient:
    """
    Client for Ponto Betaalverzoek (incoming payment requests).

    Creates payment requests where customers authorize payments
    from their bank accounts to your organization's creditor account.

    Supports both one-time payments and periodic payments (standing orders).
    """

    # Map our frequency names to Ponto API values
    FREQUENCY_MAP = {
        "monthly": "monthly",
        "quarterly": "quarterly",
        "annually": "yearly",
        "yearly": "yearly",
        "annual": "yearly",
    }

    def __init__(self):
        """Initialize the betaalverzoek client."""
        self._client = PontoClient()
        self._config = get_ponto_config()

        # Verify mTLS is enabled - required for Payment Initiation Services (PIS)
        self._verify_pis_enabled()

    def _verify_pis_enabled(self) -> None:
        """
        Verify that Payment Initiation Services (PIS) are properly configured.

        PIS requires mTLS authentication with the Ibanity API.
        Raises PontoConfigurationError if not properly configured.
        """
        import frappe

        settings = frappe.get_single("Ponto Settings")

        if not settings.use_ibanity_mtls:
            raise PontoConfigurationError(
                message=(
                    "Payment Initiation Services (PIS) require mTLS authentication. "
                    "Please enable 'Use Ibanity mTLS' in Ponto Settings and configure "
                    "the required certificates."
                ),
                missing_fields=["use_ibanity_mtls"],
            )

        # Check for enabled bank account mappings
        enabled_mappings = self._config.get_enabled_account_mappings()
        if not enabled_mappings:
            raise PontoConfigurationError(
                message=(
                    "Payment Initiation Services (PIS) require a linked Ponto account. "
                    "Please configure and enable a bank account in Ponto Settings."
                ),
                missing_fields=["bank_account_mappings"],
            )

    def _get_account_id(self) -> str:
        """Get the first enabled Ponto account ID for PIS operations."""
        account_id = self._config.get_first_enabled_ponto_account_id()
        if not account_id:
            raise PontoConfigurationError(
                message="No enabled Ponto account configured for payment initiation.",
                missing_fields=["bank_account_mappings"],
            )
        return account_id

    def create_payment_request(
        self,
        amount: float,
        creditor_name: str,
        creditor_iban: str,
        remittance_info: str,
        redirect_uri: str = None,
        creditor_bic: str = None,
        end_to_end_id: str = None,
    ) -> PaymentInitiationRequest:
        """
        Create a one-time payment initiation request.

        The customer will receive a link to authorize the payment
        from their bank account to your creditor account.

        Args:
            amount: Payment amount (positive number, EUR)
            creditor_name: Your organization name (receiver)
            creditor_iban: Your organization IBAN (receiver)
            remittance_info: Payment description shown to customer
            redirect_uri: URL to redirect after authorization (optional)
            creditor_bic: Your organization BIC/SWIFT code (optional)
            end_to_end_id: End-to-end transaction ID for tracking (optional)

        Returns:
            PaymentInitiationRequest with redirect_link for customer

        Raises:
            PontoAPIError: If request creation fails
        """
        if amount <= 0:
            raise PontoIntegrationError(
                message="Payment amount must be positive",
                details={"amount": amount},
            )

        # SEPA amount limits and precision
        SEPA_MAX_AMOUNT = 999999999.99
        if amount > SEPA_MAX_AMOUNT:
            raise PontoIntegrationError(
                message=f"Payment amount exceeds SEPA maximum of {SEPA_MAX_AMOUNT:,.2f} EUR",
                details={"amount": amount, "max_allowed": SEPA_MAX_AMOUNT},
            )

        # Validate decimal precision (max 2 decimal places for EUR)
        amount_cents = round(amount * 100, 6)
        if abs(amount_cents - round(amount_cents)) > 0.0001:
            raise PontoIntegrationError(
                message="Payment amount must have at most 2 decimal places",
                details={"amount": amount},
            )

        # Validate creditor IBAN
        iban_validation = validate_iban(creditor_iban)
        if not iban_validation.get("valid"):
            raise PontoIntegrationError(
                message=f"Invalid creditor IBAN: {iban_validation.get('message', 'Validation failed')}",
                details={"creditor_iban": creditor_iban},
            )

        # Sanitize text fields for SEPA compliance
        creditor_name = sanitize_sepa_text(creditor_name, "creditorName")
        remittance_info = sanitize_sepa_text(remittance_info, "remittanceInformation")

        # Build payment request payload (JSON:API format)
        attributes = {
            "amount": float(amount),
            "currency": "EUR",
            "creditorName": creditor_name,
            "creditorAccountReference": creditor_iban.replace(" ", "").upper(),
            "creditorAccountReferenceType": "IBAN",
            "remittanceInformation": remittance_info,
            "remittanceInformationType": "unstructured",
        }

        if redirect_uri:
            attributes["redirectUri"] = redirect_uri

        if creditor_bic:
            attributes["creditorAgent"] = creditor_bic
            attributes["creditorAgentType"] = "BIC"

        if end_to_end_id:
            attributes["endToEndId"] = end_to_end_id

        payload = {
            "data": {
                "type": "paymentInitiationRequest",
                "attributes": attributes,
            }
        }

        try:
            # Payment requests are scoped to a specific Ponto account
            # Ponto Connect API uses "payment-requests" endpoint
            account_id = self._get_account_id()
            endpoint = f"/accounts/{account_id}/payment-requests"

            frappe.logger().debug(f"Creating payment initiation request at endpoint: {endpoint}")

            response = self._client.post(
                endpoint,
                data=payload,
            )

            # Log the full response for debugging redirect_link issues
            frappe.logger().debug(f"Ponto payment request response: {response}")

            data = response.get("data", {})

            # Check for redirect link in top-level links (JSON:API spec)
            # Some APIs return links at the top level, not inside data
            top_level_links = response.get("links", {})
            if top_level_links and not data.get("links"):
                data["links"] = top_level_links

            request = PaymentInitiationRequest.from_api_response(data)

            frappe.logger().info(
                f"Created Ponto payment request {request.id} for {amount} EUR "
                f"to {creditor_name} ({creditor_iban})"
            )

            return request

        except PontoAPIError:
            # Re-raise Ponto-specific errors directly to preserve error details
            raise
        except Exception as e:
            # Extract original error if wrapped by retry decorator
            original = getattr(e, "original_error", None) or e
            original_msg = str(original)

            # Extract status code and error code if available
            status_code = getattr(original, "status_code", None)
            error_code = getattr(original, "error_code", None)

            frappe.logger().error(
                f"Failed to create Ponto payment request: {original_msg}",
                exc_info=True,
            )
            raise PontoAPIError(
                message=f"Failed to create payment request: {original_msg}",
                status_code=status_code,
                error_code=error_code,
                details={
                    "amount": amount,
                    "creditor_iban": creditor_iban,
                    "original_error_type": type(original).__name__,
                },
            )

    def create_periodic_payment_request(
        self,
        amount: float,
        creditor_name: str,
        creditor_iban: str,
        remittance_info: str,
        frequency: str,
        start_date: date = None,
        end_date: date = None,
        redirect_uri: str = None,
        creditor_bic: str = None,
        end_to_end_id: str = None,
    ) -> PeriodicPaymentInitiationRequest:
        """
        DEPRECATED: Ponto Connect does not support periodic payment initiation.

        This method is deprecated and will raise NotImplementedError.
        For recurring payments, use SEPA Direct Debit or Mollie subscriptions.

        Raises:
            NotImplementedError: Always raised - periodic payments not supported
        """
        warnings.warn(
            "create_periodic_payment_request is deprecated. "
            "Ponto Connect does not support periodic payment initiation. "
            "Use SEPA Direct Debit or Mollie subscriptions for recurring payments.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise NotImplementedError(
            "Ponto Connect does not support periodic payment initiation requests. "
            "The periodic-payment-requests endpoint does not exist in the Ponto Connect API. "
            "For recurring payments, use SEPA Direct Debit or Mollie subscriptions."
        )

    def get_payment_request(self, request_id: str) -> PaymentInitiationRequest:
        """
        Get payment request details and current status.

        Args:
            request_id: Payment initiation request ID

        Returns:
            PaymentInitiationRequest with current status

        Raises:
            PontoAPIError: If request fails
        """
        try:
            account_id = self._get_account_id()
            endpoint = f"/accounts/{account_id}/payment-requests/{request_id}"
            response = self._client.get(endpoint)

            data = response.get("data", {})
            return PaymentInitiationRequest.from_api_response(data)

        except Exception as e:
            frappe.logger().error(f"Failed to get Ponto payment request {request_id}: {e}")
            raise PontoAPIError(
                message=f"Failed to get payment request status: {e}",
                details={"request_id": request_id},
            )

    def get_periodic_payment_request(self, request_id: str) -> PeriodicPaymentInitiationRequest:
        """
        DEPRECATED: Ponto Connect does not support periodic payment initiation.

        Raises:
            NotImplementedError: Always raised - periodic payments not supported
        """
        warnings.warn(
            "get_periodic_payment_request is deprecated. "
            "Ponto Connect does not support periodic payments.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise NotImplementedError("Ponto Connect does not support periodic payment initiation requests.")

    def list_payment_requests(
        self, limit: int = 25, max_pages: Optional[int] = None
    ) -> List[PaymentInitiationRequest]:
        """
        List payment initiation requests.

        Uses cursor-based pagination to fetch all requests across multiple pages.

        Args:
            limit: Items per page (default 25)
            max_pages: Maximum pages to fetch (None for unlimited)

        Returns:
            List of PaymentInitiationRequest objects

        Raises:
            PontoAPIError: If request fails
        """
        try:
            # List all payment requests across accounts with pagination
            data = self._client.get_paginated(
                "/payment-requests",
                limit=limit,
                max_pages=max_pages,
            )

            requests = []
            for item in data:
                requests.append(PaymentInitiationRequest.from_api_response(item))

            return requests

        except Exception as e:
            frappe.logger().error(f"Failed to list Ponto payment requests: {e}")
            raise PontoAPIError(
                message=f"Failed to list payment requests: {e}",
            )

    def list_periodic_payment_requests(self, limit: int = 25) -> List[PeriodicPaymentInitiationRequest]:
        """
        DEPRECATED: Ponto Connect does not support periodic payment initiation.

        Raises:
            NotImplementedError: Always raised - periodic payments not supported
        """
        warnings.warn(
            "list_periodic_payment_requests is deprecated. "
            "Ponto Connect does not support periodic payments.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise NotImplementedError("Ponto Connect does not support periodic payment initiation requests.")

    def delete_payment_request(self, request_id: str) -> bool:
        """
        Delete/cancel an unauthorized payment request.

        Only works for requests that haven't been authorized yet.

        Args:
            request_id: Payment initiation request ID

        Returns:
            True if deleted successfully

        Raises:
            PontoAPIError: If deletion fails
        """
        try:
            account_id = self._get_account_id()
            endpoint = f"/accounts/{account_id}/payment-requests/{request_id}"
            self._client.delete(endpoint)

            frappe.logger().info(f"Deleted Ponto payment request {request_id}")
            return True

        except Exception as e:
            frappe.logger().error(f"Failed to delete Ponto payment request {request_id}: {e}")
            raise PontoAPIError(
                message=f"Failed to delete payment request: {e}",
                details={"request_id": request_id},
            )

    def delete_periodic_payment_request(self, request_id: str) -> bool:
        """
        DEPRECATED: Ponto Connect does not support periodic payment initiation.

        Raises:
            NotImplementedError: Always raised - periodic payments not supported
        """
        warnings.warn(
            "delete_periodic_payment_request is deprecated. "
            "Ponto Connect does not support periodic payments.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise NotImplementedError("Ponto Connect does not support periodic payment initiation requests.")


def get_betaalverzoek_client() -> PontoBetaalverzoekClient:
    """
    Factory function to get PontoBetaalverzoekClient instance.

    Returns:
        PontoBetaalverzoekClient instance
    """
    return PontoBetaalverzoekClient()
