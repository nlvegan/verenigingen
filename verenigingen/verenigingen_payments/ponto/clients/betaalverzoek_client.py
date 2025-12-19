# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Betaalverzoek Client

Handles incoming payment requests (betaalverzoek) through Ponto Connect API.
These are payment requests where customers authorize payments FROM their
bank account TO your organization's account.

Supports:
- One-time payment requests (Payment Initiation Request)
- Periodic payment requests (Periodic Payment Initiation Request / Standing Orders)

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

    # Create periodic payment request (standing order)
    result = client.create_periodic_payment_request(
        amount=25.00,
        creditor_name="Vegan Netwerk Nederland",
        creditor_iban="NL91ABNA0417164300",
        remittance_info="Monthly membership dues",
        frequency="monthly",
        redirect_uri="https://your-site.com/ponto/callback",
    )
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient
from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError, PontoIntegrationError


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

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "PaymentInitiationRequest":
        """
        Create PaymentInitiationRequest from Ponto API response.

        Args:
            data: JSON:API response data object

        Returns:
            PaymentInitiationRequest instance
        """
        attrs = data.get("attributes", {})

        return cls(
            id=data.get("id", ""),
            status=attrs.get("status", ""),
            amount=Decimal(str(attrs.get("amount", "0"))),
            currency=attrs.get("currency", "EUR"),
            creditor_name=attrs.get("creditorName", ""),
            creditor_iban=attrs.get("creditorAccountReference", ""),
            creditor_agent=attrs.get("creditorAgent", ""),
            remittance_info=attrs.get("remittanceInformation", ""),
            redirect_uri=attrs.get("redirectUri", ""),
            redirect_link=data.get("links", {}).get("redirect", ""),
            debtor_name=attrs.get("debtorName"),
            debtor_iban=attrs.get("debtorAccountReference"),
            debtor_bank=attrs.get("debtorAgent"),
            end_to_end_id=attrs.get("endToEndId"),
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
            redirect_link=data.get("links", {}).get("redirect", ""),
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
            response = self._client.post(
                "/payment-initiation-requests",
                data=payload,
            )

            data = response.get("data", {})
            request = PaymentInitiationRequest.from_api_response(data)

            frappe.logger().info(
                f"Created Ponto payment request {request.id} for {amount} EUR "
                f"to {creditor_name} ({creditor_iban})"
            )

            return request

        except Exception as e:
            frappe.logger().error(f"Failed to create Ponto payment request: {e}")
            raise PontoAPIError(
                message=f"Failed to create payment request: {e}",
                details={
                    "amount": amount,
                    "creditor_iban": creditor_iban,
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
        Create a periodic payment initiation request (standing order).

        The customer will receive a link to authorize recurring payments
        from their bank account to your creditor account.

        Args:
            amount: Payment amount per period (positive number, EUR)
            creditor_name: Your organization name (receiver)
            creditor_iban: Your organization IBAN (receiver)
            remittance_info: Payment description shown to customer
            frequency: Payment frequency (monthly, quarterly, annually)
            start_date: First payment date (optional, defaults to now)
            end_date: Last payment date (optional, None for open-ended)
            redirect_uri: URL to redirect after authorization (optional)
            creditor_bic: Your organization BIC/SWIFT code (optional)
            end_to_end_id: End-to-end transaction ID for tracking (optional)

        Returns:
            PeriodicPaymentInitiationRequest with redirect_link for customer

        Raises:
            PontoAPIError: If request creation fails
            PontoIntegrationError: If invalid parameters
        """
        if amount <= 0:
            raise PontoIntegrationError(
                message="Payment amount must be positive",
                details={"amount": amount},
            )

        # Map frequency to Ponto API value
        ponto_frequency = self.FREQUENCY_MAP.get(frequency.lower())
        if not ponto_frequency:
            raise PontoIntegrationError(
                message=f"Invalid frequency: {frequency}. Must be monthly, quarterly, or annually.",
                details={"frequency": frequency},
            )

        # Build periodic payment request payload (JSON:API format)
        attributes = {
            "amount": float(amount),
            "currency": "EUR",
            "creditorName": creditor_name,
            "creditorAccountReference": creditor_iban.replace(" ", "").upper(),
            "creditorAccountReferenceType": "IBAN",
            "remittanceInformation": remittance_info,
            "remittanceInformationType": "unstructured",
            "frequency": ponto_frequency,
        }

        if start_date:
            attributes["startDate"] = start_date.isoformat()

        if end_date:
            attributes["endDate"] = end_date.isoformat()
        # Note: if end_date is None, the standing order is open-ended

        if redirect_uri:
            attributes["redirectUri"] = redirect_uri

        if creditor_bic:
            attributes["creditorAgent"] = creditor_bic
            attributes["creditorAgentType"] = "BIC"

        if end_to_end_id:
            attributes["endToEndId"] = end_to_end_id

        payload = {
            "data": {
                "type": "periodicPaymentInitiationRequest",
                "attributes": attributes,
            }
        }

        try:
            response = self._client.post(
                "/periodic-payment-initiation-requests",
                data=payload,
            )

            data = response.get("data", {})
            request = PeriodicPaymentInitiationRequest.from_api_response(data)

            frappe.logger().info(
                f"Created Ponto periodic payment request {request.id} for {amount} EUR "
                f"{ponto_frequency} to {creditor_name} ({creditor_iban})"
            )

            return request

        except Exception as e:
            frappe.logger().error(f"Failed to create Ponto periodic payment request: {e}")
            raise PontoAPIError(
                message=f"Failed to create periodic payment request: {e}",
                details={
                    "amount": amount,
                    "frequency": frequency,
                    "creditor_iban": creditor_iban,
                },
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
            response = self._client.get(f"/payment-initiation-requests/{request_id}")

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
        Get periodic payment request details and current status.

        Args:
            request_id: Periodic payment initiation request ID

        Returns:
            PeriodicPaymentInitiationRequest with current status

        Raises:
            PontoAPIError: If request fails
        """
        try:
            response = self._client.get(f"/periodic-payment-initiation-requests/{request_id}")

            data = response.get("data", {})
            return PeriodicPaymentInitiationRequest.from_api_response(data)

        except Exception as e:
            frappe.logger().error(f"Failed to get Ponto periodic payment request {request_id}: {e}")
            raise PontoAPIError(
                message=f"Failed to get periodic payment request status: {e}",
                details={"request_id": request_id},
            )

    def list_payment_requests(self, limit: int = 25) -> List[PaymentInitiationRequest]:
        """
        List payment initiation requests.

        Args:
            limit: Maximum number of results

        Returns:
            List of PaymentInitiationRequest objects

        Raises:
            PontoAPIError: If request fails
        """
        try:
            response = self._client.get(
                "/payment-initiation-requests",
                params={"limit": limit},
            )

            requests = []
            for item in response.get("data", []):
                requests.append(PaymentInitiationRequest.from_api_response(item))

            return requests

        except Exception as e:
            frappe.logger().error(f"Failed to list Ponto payment requests: {e}")
            raise PontoAPIError(
                message=f"Failed to list payment requests: {e}",
            )

    def list_periodic_payment_requests(self, limit: int = 25) -> List[PeriodicPaymentInitiationRequest]:
        """
        List periodic payment initiation requests.

        Args:
            limit: Maximum number of results

        Returns:
            List of PeriodicPaymentInitiationRequest objects

        Raises:
            PontoAPIError: If request fails
        """
        try:
            response = self._client.get(
                "/periodic-payment-initiation-requests",
                params={"limit": limit},
            )

            requests = []
            for item in response.get("data", []):
                requests.append(PeriodicPaymentInitiationRequest.from_api_response(item))

            return requests

        except Exception as e:
            frappe.logger().error(f"Failed to list Ponto periodic payment requests: {e}")
            raise PontoAPIError(
                message=f"Failed to list periodic payment requests: {e}",
            )

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
            self._client.delete(f"/payment-initiation-requests/{request_id}")

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
        Delete/cancel an unauthorized periodic payment request.

        Only works for requests that haven't been authorized yet.

        Args:
            request_id: Periodic payment initiation request ID

        Returns:
            True if deleted successfully

        Raises:
            PontoAPIError: If deletion fails
        """
        try:
            self._client.delete(f"/periodic-payment-initiation-requests/{request_id}")

            frappe.logger().info(f"Deleted Ponto periodic payment request {request_id}")
            return True

        except Exception as e:
            frappe.logger().error(f"Failed to delete Ponto periodic payment request {request_id}: {e}")
            raise PontoAPIError(
                message=f"Failed to delete periodic payment request: {e}",
                details={"request_id": request_id},
            )


def get_betaalverzoek_client() -> PontoBetaalverzoekClient:
    """
    Factory function to get PontoBetaalverzoekClient instance.

    Returns:
        PontoBetaalverzoekClient instance
    """
    return PontoBetaalverzoekClient()
