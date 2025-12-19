# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Payment Client

Handles SEPA payment initiation through Ponto Connect API.

Payment Flow:
1. Create payment request via API
2. Receive redirect URL to Ponto authorization portal
3. User signs payment with bank authentication
4. Payment is executed by the bank
5. Track status via polling or webhook

Usage:
    from verenigingen.verenigingen_payments.ponto.clients.payment_client import (
        PontoPaymentClient,
    )

    client = PontoPaymentClient()
    result = client.create_payment(
        account_id="ponto-account-uuid",
        amount=100.00,
        currency="EUR",
        creditor_name="Supplier Name",
        creditor_iban="NL91ABNA0417164300",
        remittance_info="Invoice INV-2025-001",
        redirect_uri="https://your-site.com/payment-callback",
    )

    # Redirect user to result["redirect_url"] for signing
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
class PaymentRequest:
    """Represents a Ponto payment request."""

    id: str
    status: str
    amount: Decimal
    currency: str
    creditor_name: str
    creditor_iban: str
    creditor_agent: Optional[str]  # BIC
    creditor_agent_type: Optional[str]
    remittance_info: str
    remittance_info_type: str
    requested_execution_date: Optional[date]
    redirect_uri: Optional[str]
    redirect_link: Optional[str]  # URL to redirect user for signing

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "PaymentRequest":
        """
        Create PaymentRequest from Ponto API response.

        Args:
            data: JSON:API response data object

        Returns:
            PaymentRequest instance
        """
        attrs = data.get("attributes", {})

        # Parse requested execution date if present
        exec_date = None
        if attrs.get("requestedExecutionDate"):
            try:
                exec_date = date.fromisoformat(attrs["requestedExecutionDate"])
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
            creditor_agent_type=attrs.get("creditorAgentType", ""),
            remittance_info=attrs.get("remittanceInformation", ""),
            remittance_info_type=attrs.get("remittanceInformationType", "unstructured"),
            requested_execution_date=exec_date,
            redirect_uri=attrs.get("redirectUri", ""),
            redirect_link=data.get("links", {}).get("redirect", ""),
        )


class PontoPaymentClient:
    """
    Client for Ponto Payment Initiation Service (PIS).

    Handles creating SEPA credit transfer payment requests
    and tracking their status.
    """

    def __init__(self):
        """Initialize the payment client."""
        self._client = PontoClient()

    def create_payment(
        self,
        account_id: str,
        amount: float,
        currency: str,
        creditor_name: str,
        creditor_iban: str,
        remittance_info: str,
        redirect_uri: str = None,
        creditor_bic: str = None,
        requested_execution_date: date = None,
        end_to_end_id: str = None,
    ) -> PaymentRequest:
        """
        Create a SEPA credit transfer payment request.

        The payment will have status "pending" until signed by the user
        via the Ponto authorization portal.

        Args:
            account_id: Ponto account UUID to pay from
            amount: Payment amount (positive number)
            currency: Currency code (must be EUR for SEPA)
            creditor_name: Beneficiary name
            creditor_iban: Beneficiary IBAN
            remittance_info: Payment reference/description
            redirect_uri: URL to redirect after signing (optional)
            creditor_bic: Beneficiary BIC/SWIFT code (optional)
            requested_execution_date: Future date for payment (optional)
            end_to_end_id: End-to-end transaction ID (optional)

        Returns:
            PaymentRequest with redirect_link for user signing

        Raises:
            PontoAPIError: If payment creation fails
        """
        if currency != "EUR":
            raise PontoIntegrationError(
                message="Only EUR currency is supported for SEPA payments",
                details={"currency": currency},
            )

        if amount <= 0:
            raise PontoIntegrationError(
                message="Payment amount must be positive",
                details={"amount": amount},
            )

        # Build payment request payload (JSON:API format)
        attributes = {
            "amount": float(amount),
            "currency": currency,
            "creditorName": creditor_name,
            "creditorAccountReference": creditor_iban,
            "creditorAccountReferenceType": "IBAN",
            "remittanceInformation": remittance_info,
            "remittanceInformationType": "unstructured",
        }

        if redirect_uri:
            attributes["redirectUri"] = redirect_uri

        if creditor_bic:
            attributes["creditorAgent"] = creditor_bic
            attributes["creditorAgentType"] = "BIC"

        if requested_execution_date:
            attributes["requestedExecutionDate"] = requested_execution_date.isoformat()

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
                f"/accounts/{account_id}/payment-initiation-requests",
                data=payload,
            )

            data = response.get("data", {})
            payment = PaymentRequest.from_api_response(data)

            frappe.logger().info(
                f"Created Ponto payment request {payment.id} for {amount} {currency} "
                f"to {creditor_name} ({creditor_iban})"
            )

            return payment

        except Exception as e:
            frappe.logger().error(f"Failed to create Ponto payment: {e}")
            raise PontoAPIError(
                message=f"Failed to create payment: {e}",
                details={
                    "account_id": account_id,
                    "amount": amount,
                    "creditor_iban": creditor_iban,
                },
            )

    def get_payment(self, account_id: str, payment_id: str) -> PaymentRequest:
        """
        Get payment request details and current status.

        Args:
            account_id: Ponto account UUID
            payment_id: Payment request ID

        Returns:
            PaymentRequest with current status

        Raises:
            PontoAPIError: If request fails
        """
        try:
            response = self._client.get(f"/accounts/{account_id}/payment-initiation-requests/{payment_id}")

            data = response.get("data", {})
            return PaymentRequest.from_api_response(data)

        except Exception as e:
            frappe.logger().error(f"Failed to get Ponto payment {payment_id}: {e}")
            raise PontoAPIError(
                message=f"Failed to get payment status: {e}",
                details={"payment_id": payment_id},
            )

    def list_payments(
        self,
        account_id: str,
        limit: int = 25,
    ) -> List[PaymentRequest]:
        """
        List payment requests for an account.

        Args:
            account_id: Ponto account UUID
            limit: Maximum number of results

        Returns:
            List of PaymentRequest objects

        Raises:
            PontoAPIError: If request fails
        """
        try:
            response = self._client.get(
                f"/accounts/{account_id}/payment-initiation-requests",
                params={"limit": limit},
            )

            payments = []
            for item in response.get("data", []):
                payments.append(PaymentRequest.from_api_response(item))

            return payments

        except Exception as e:
            frappe.logger().error(f"Failed to list Ponto payments: {e}")
            raise PontoAPIError(
                message=f"Failed to list payments: {e}",
                details={"account_id": account_id},
            )

    def delete_payment(self, account_id: str, payment_id: str) -> bool:
        """
        Delete/cancel an unsigned payment request.

        Only works for payments that haven't been signed yet.

        Args:
            account_id: Ponto account UUID
            payment_id: Payment request ID

        Returns:
            True if deleted successfully

        Raises:
            PontoAPIError: If deletion fails
        """
        try:
            self._client.delete(f"/accounts/{account_id}/payment-initiation-requests/{payment_id}")

            frappe.logger().info(f"Deleted Ponto payment request {payment_id}")
            return True

        except Exception as e:
            frappe.logger().error(f"Failed to delete Ponto payment {payment_id}: {e}")
            raise PontoAPIError(
                message=f"Failed to delete payment: {e}",
                details={"payment_id": payment_id},
            )


def get_payment_client() -> PontoPaymentClient:
    """
    Factory function to get PontoPaymentClient instance.

    Returns:
        PontoPaymentClient instance
    """
    return PontoPaymentClient()
