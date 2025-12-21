"""
Ponto Payment Integration Test Data Factory.

Generates realistic test data for Ponto API responses, webhooks, and ERPNext documents.
Based on actual Ponto/Ibanity API documentation and JSON:API format.

Usage:
    from verenigingen.tests.fixtures.ponto_test_data_factory import PontoTestDataFactory

    # Generate OAuth2 token response
    token = PontoTestDataFactory.create_token_response(expires_in=1800)

    # Generate Ponto account
    account = PontoTestDataFactory.create_account(iban="NL91ABNA0417164300")

    # Generate webhook payload
    payload = PontoTestDataFactory.create_webhook_payload(
        event_type=PontoEventType.SYNC_SUCCEEDED,
        account_id="550e8400-e29b-41d4-a716-446655440000"
    )
"""

import hashlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

import frappe


class PontoEventType(str, Enum):
    """All 18 Ponto webhook event types."""

    # Synchronization events
    SYNC_SUCCEEDED = "pontoConnect.synchronization.succeeded"
    SYNC_FAILED = "pontoConnect.synchronization.failed"
    SYNC_NO_CHANGE = "pontoConnect.synchronization.succeededWithoutChange"

    # Account events
    ACCOUNT_DETAILS_UPDATED = "pontoConnect.account.detailsUpdated"
    ACCOUNT_TRANSACTIONS_CREATED = "pontoConnect.account.transactionsCreated"
    ACCOUNT_TRANSACTIONS_UPDATED = "pontoConnect.account.transactionsUpdated"

    # Integration events
    INTEGRATION_ACCOUNT_ADDED = "pontoConnect.integration.accountAdded"
    INTEGRATION_ACCOUNT_REVOKED = "pontoConnect.integration.accountRevoked"
    INTEGRATION_CREATED = "pontoConnect.integration.created"
    INTEGRATION_REVOKED = "pontoConnect.integration.revoked"

    # Organization events
    ORGANIZATION_BLOCKED = "pontoConnect.organization.blocked"
    ORGANIZATION_UNBLOCKED = "pontoConnect.organization.unblocked"

    # Payment request events (outgoing)
    PAYMENT_REQUEST_CLOSED = "pontoConnect.paymentRequest.closed"

    # Payment initiation events (incoming - betaalverzoek)
    PAYMENT_INITIATION_STATUS_UPDATED = "pontoConnect.paymentInitiationRequest.statusUpdated"
    PAYMENT_INITIATION_CLOSED = "pontoConnect.paymentInitiationRequest.closed"

    # Periodic payment events (recurring)
    PERIODIC_PAYMENT_STATUS_UPDATED = "pontoConnect.periodicPaymentInitiationRequest.statusUpdated"
    PERIODIC_PAYMENT_CLOSED = "pontoConnect.periodicPaymentInitiationRequest.closed"
    PERIODIC_PAYMENT_EXECUTION = "pontoConnect.periodicPaymentInitiationRequest.executed"


class PaymentStatus(str, Enum):
    """Ponto payment statuses."""

    PENDING = "pending"
    SIGNED = "signed"
    EXECUTED = "executed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class TestIBAN:
    """Dutch test IBANs with valid checksums."""

    # ABN AMRO
    ABN_AMRO_1 = "NL91ABNA0417164300"
    ABN_AMRO_2 = "NL02ABNA0123456789"

    # ING
    ING_1 = "NL20INGB0001234567"
    ING_2 = "NL39INGB0002222222"

    # Rabobank
    RABO_1 = "NL53RABO0123456789"
    RABO_2 = "NL17RABO0312841062"

    # SNS
    SNS_1 = "NL86SNSB0123456789"

    # Triodos
    TRIODOS_1 = "NL29TRIO0123456789"


# Test RSA key pair for JWT signing (2048-bit, for testing only)
TEST_JWT_PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF8PbnGy0AHB7MkeP8HVchNPV8ksv
TAB1LmXpPhUzEU7k3fR+o2V7Lm0HAfTlFt8qxadCf+3W2A0u8XSzLsg7k3bvlT8H
i0NY71dn7JaQyVFAHjLs+Ku/ZRO4z8xyaWf8ef3GgN4xfp8WNnPjOv1N0o7lMBzj
Fk3zT/OjPn0JLHZ7QoR2a7zl7Q7N9xQdF7gRKLg7d1d7vvd4mHr5EG1HQU0LyNMl
bQC+H3K+O4xcPVA0H8b/3t/PDmnJI/qE8LvW1y7Z7BG5qYoab8v7h8F3kQGLrT8v
K/mPjqPAZxbwN8htF+7PzQy7vp2Ml5J7q8OQVwIDAQABAoIBAF5f0hz7DdL0Nfz8
GgF5dCR4JWl9k7x5fVWxf0t8Q2HdS5d7nPjXMuFjU3X8P9a7dn3l7g0cK6WsJqB7
N2bXm6X5hK3M6Y5b3W9Yn3l6h4P9E5I7k3x5fVWxf0t8Q2HdS5d7nPjXMuFjU3X8
P9a7dn3l7g0cK6WsJqB7N2bXm6X5hK3M6Y5b3W9Yn3l6h4P9E5I7k3x5fVWxf0t8
Q2HdS5d7nPjXMuFjU3X8P9a7dn3l7g0cK6WsJqB7N2bXm6X5hK3M6Y5b3W9Yn3l6
h4P9E5I7k3x5fVWxf0t8Q2HdS5d7nPjXMuFjU3X8P9a7dn3l7g0cK6WsJqB7N2bX
m6X5hK3M6Y5b3W9Yn3l6h4ECgYEA7W8k3x5fVWxf0t8Q2HdS5d7nPjXMuFjU3X8P
9a7dn3l7g0cK6WsJqB7N2bXm6X5hK3M6Y5b3W9Yn3l6h4P9E5I7k3x5fVWxf0t8Q
2HdS5d7nPjXMuFjU3X8P9a7dn3l7g0cK6WsJqB7N2bXm6X5hK3M6Y5b3W9Yn3l6h
4P9E5I7k3ECgYEA4Xm6X5hK3M6Y5b3W9Yn3l6h4P9E5I7k3x5fVWxf0t8Q2HdS5d7
nPjXMuFjU3X8P9a7dn3l7g0cK6WsJqB7N2bXm6X5hK3M6Y5b3W9Yn3l6h4P9E5I7
k3x5fVWxf0t8Q2HdS5d7nPjXMuFjU3X8P9a7dn3l7g0cK6WsJqB7N2bXm6X5hK3M
-----END RSA PRIVATE KEY-----"""

TEST_JWT_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0Z3VS5JJcds3xfn/ygWy
F8PbnGy0AHB7MkeP8HVchNPV8ksvTAB1LmXpPhUzEU7k3fR+o2V7Lm0HAfTlFt8q
xadCf+3W2A0u8XSzLsg7k3bvlT8Hi0NY71dn7JaQyVFAHjLs+Ku/ZRO4z8xyaWf8
ef3GgN4xfp8WNnPjOv1N0o7lMBzjFk3zT/OjPn0JLHZ7QoR2a7zl7Q7N9xQdF7gR
KLg7d1d7vvd4mHr5EG1HQU0LyNMlbQC+H3K+O4xcPVA0H8b/3t/PDmnJI/qE8LvW
1y7Z7BG5qYoab8v7h8F3kQGLrT8vK/mPjqPAZxbwN8htF+7PzQy7vp2Ml5J7q8OQ
VwIDAQAB
-----END PUBLIC KEY-----"""


class PontoTestDataFactory:
    """
    Factory for generating realistic Ponto test data.

    All data structures match the actual Ponto/Ibanity API specification
    with JSON:API format for responses.
    """

    # -------------------------------------------------------------------------
    # OAuth2 Token Responses
    # -------------------------------------------------------------------------

    @staticmethod
    def create_token_response(
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        expires_in: int = 1800,
        scope: str = "ai pi name offline_access",
    ) -> Dict[str, Any]:
        """
        Generate realistic OAuth2 token response.

        Args:
            access_token: Access token value (auto-generated if None)
            refresh_token: Refresh token value (auto-generated if None)
            expires_in: Token lifetime in seconds (default 30 minutes)
            scope: OAuth2 scopes

        Returns:
            Token response matching Ponto OAuth2 spec
        """
        return {
            "access_token": access_token or f"pat_live_{secrets.token_hex(32)}",
            "refresh_token": refresh_token or f"prt_live_{secrets.token_hex(32)}",
            "expires_in": expires_in,
            "token_type": "Bearer",
            "scope": scope,
        }

    @staticmethod
    def create_expired_token_response() -> Dict[str, Any]:
        """Generate token response that's already expired."""
        return PontoTestDataFactory.create_token_response(expires_in=-1)

    @staticmethod
    def create_token_with_expiry_buffer() -> Dict[str, Any]:
        """Generate token that expires within the 5-minute buffer."""
        return PontoTestDataFactory.create_token_response(expires_in=240)  # 4 minutes

    # -------------------------------------------------------------------------
    # Ponto Account Responses (JSON:API format)
    # -------------------------------------------------------------------------

    @staticmethod
    def create_account(
        iban: str = TestIBAN.ABN_AMRO_1,
        account_id: Optional[str] = None,
        balance: float = 5000.00,
        holder_name: str = "Test Organization BV",
        currency: str = "EUR",
        subtype: str = "checking",
    ) -> Dict[str, Any]:
        """
        Generate realistic Ponto account in JSON:API format.

        Args:
            iban: Account IBAN (must be valid format)
            account_id: UUID for the account (auto-generated if None)
            balance: Available balance
            holder_name: Account holder name
            currency: Currency code
            subtype: Account subtype (checking, savings, etc.)

        Returns:
            Account data matching Ponto API response format
        """
        return {
            "type": "account",
            "id": account_id or str(uuid.uuid4()),
            "attributes": {
                "reference": iban,
                "referenceType": "IBAN",
                "description": f"Test Account {iban[-4:]}",
                "availableBalance": balance,
                "currentBalance": balance,
                "currency": currency,
                "holderName": holder_name,
                "subtype": subtype,
                "internalReference": f"INT-{iban[-8:]}",
                "product": "Business Current Account",
                "authorizationExpirationExpectedAt": (
                    datetime.now() + timedelta(days=90)
                ).isoformat(),
            },
            "relationships": {
                "financialInstitution": {
                    "data": {"type": "financialInstitution", "id": "test-bank-001"}
                }
            },
            "links": {"self": f"https://api.myponto.com/accounts/{account_id}"},
        }

    @staticmethod
    def create_accounts_response(
        accounts: Optional[List[Dict[str, Any]]] = None,
        next_page_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate paginated accounts list response.

        Args:
            accounts: List of account dicts (auto-generated if None)
            next_page_url: URL for next page (None if last page)

        Returns:
            Paginated response with meta and links
        """
        if accounts is None:
            accounts = [
                PontoTestDataFactory.create_account(iban=TestIBAN.ABN_AMRO_1),
                PontoTestDataFactory.create_account(iban=TestIBAN.ING_1),
            ]

        response = {
            "data": accounts,
            "meta": {"paging": {"after": "cursor123" if next_page_url else None}},
            "links": {"self": "https://api.myponto.com/accounts"},
        }

        if next_page_url:
            response["links"]["next"] = next_page_url

        return response

    # -------------------------------------------------------------------------
    # Ponto Transaction Responses
    # -------------------------------------------------------------------------

    @staticmethod
    def create_transaction(
        transaction_id: Optional[str] = None,
        amount: float = -25.00,
        counterpart_name: str = "Supplier BV",
        counterpart_iban: str = TestIBAN.RABO_1,
        remittance_info: str = "Invoice payment INV-2025-001",
        execution_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate realistic Ponto transaction.

        Args:
            transaction_id: UUID (auto-generated if None)
            amount: Transaction amount (negative for outgoing)
            counterpart_name: Name of counterparty
            counterpart_iban: IBAN of counterparty
            remittance_info: Payment reference/description
            execution_date: Date of transaction (today if None)

        Returns:
            Transaction data matching Ponto API format
        """
        if execution_date is None:
            execution_date = datetime.now().strftime("%Y-%m-%d")

        return {
            "type": "transaction",
            "id": transaction_id or str(uuid.uuid4()),
            "attributes": {
                "amount": amount,
                "currency": "EUR",
                "counterpartName": counterpart_name,
                "counterpartReference": counterpart_iban,
                "remittanceInformation": remittance_info,
                "remittanceInformationType": "unstructured",
                "executionDate": execution_date,
                "valueDate": execution_date,
                "description": remittance_info[:50],
                "bankTransactionCode": "PMNT-RCDT-ESCT",
                "proprietaryBankTransactionCode": "54",
                "additionalInformation": "",
                "fee": 0.0,
            },
        }

    # -------------------------------------------------------------------------
    # Webhook Payloads
    # -------------------------------------------------------------------------

    @staticmethod
    def create_webhook_payload(
        event_type: PontoEventType,
        account_id: Optional[str] = None,
        payment_id: Optional[str] = None,
        request_id: Optional[str] = None,
        status: Optional[str] = None,
        webhook_id: Optional[str] = None,
        debtor_info: Optional[Dict[str, Any]] = None,
        sync_data: Optional[Dict[str, Any]] = None,
        **extra_attributes,
    ) -> bytes:
        """
        Generate realistic Ponto webhook payload.

        Supports all 18 event types with appropriate structure.

        Args:
            event_type: PontoEventType enum value
            account_id: Related account UUID
            payment_id: Related payment request UUID
            request_id: Related payment initiation request UUID
            status: Payment status (executed, rejected, etc.)
            webhook_id: Unique webhook ID (auto-generated if None)
            debtor_info: Debtor information for payment webhooks
            sync_data: Synchronization metadata
            **extra_attributes: Additional attributes to include

        Returns:
            JSON-encoded bytes ready for webhook handler
        """
        payload: Dict[str, Any] = {
            "data": {
                "type": event_type.value if isinstance(event_type, PontoEventType) else event_type,
                "id": webhook_id or str(uuid.uuid4()),
                "attributes": {},
            }
        }

        # Add relationships based on event type
        relationships = {}

        if account_id:
            relationships["account"] = {"data": {"type": "account", "id": account_id}}

        if relationships:
            payload["data"]["relationships"] = relationships

        # Add event-specific attributes
        attributes = payload["data"]["attributes"]

        if status:
            attributes["status"] = status

        if debtor_info:
            attributes.update(debtor_info)

        if sync_data:
            attributes.update(sync_data)

        # Override ID for payment-related webhooks
        if payment_id:
            payload["data"]["id"] = payment_id

        if request_id:
            payload["data"]["id"] = request_id

        # Add any extra attributes
        attributes.update(extra_attributes)

        return json.dumps(payload).encode("utf-8")

    @staticmethod
    def create_sync_succeeded_webhook(
        account_id: str,
        sync_subtype: str = "accountTransactionsWithUnsettled",
        updated_count: int = 5,
    ) -> bytes:
        """Create synchronization.succeeded webhook payload."""
        return PontoTestDataFactory.create_webhook_payload(
            event_type=PontoEventType.SYNC_SUCCEEDED,
            account_id=account_id,
            sync_data={
                "synchronizationSubtype": sync_subtype,
                "resourceId": account_id,
                "updatedTransactionsCount": updated_count,
            },
        )

    @staticmethod
    def create_payment_request_closed_webhook(
        payment_id: str,
        status: str = PaymentStatus.EXECUTED,
    ) -> bytes:
        """Create paymentRequest.closed webhook payload."""
        return PontoTestDataFactory.create_webhook_payload(
            event_type=PontoEventType.PAYMENT_REQUEST_CLOSED,
            payment_id=payment_id,
            status=status.value if isinstance(status, PaymentStatus) else status,
        )

    @staticmethod
    def create_payment_initiation_closed_webhook(
        request_id: str,
        status: str = PaymentStatus.EXECUTED,
        debtor_name: str = "Jan de Vries",
        debtor_iban: str = TestIBAN.RABO_1,
    ) -> bytes:
        """Create paymentInitiationRequest.closed webhook payload."""
        return PontoTestDataFactory.create_webhook_payload(
            event_type=PontoEventType.PAYMENT_INITIATION_CLOSED,
            request_id=request_id,
            status=status.value if isinstance(status, PaymentStatus) else status,
            debtor_info={
                "debtorName": debtor_name,
                "debtorAccountReference": debtor_iban,
                "debtorAccountReferenceType": "IBAN",
            },
        )

    @staticmethod
    def create_periodic_payment_executed_webhook(
        request_id: str,
        execution_number: int = 1,
    ) -> bytes:
        """Create periodicPaymentInitiationRequest.executed webhook payload."""
        return PontoTestDataFactory.create_webhook_payload(
            event_type=PontoEventType.PERIODIC_PAYMENT_EXECUTION,
            request_id=request_id,
            executionNumber=execution_number,
        )

    # -------------------------------------------------------------------------
    # JWT Signature Generation
    # -------------------------------------------------------------------------

    @staticmethod
    def sign_webhook_payload(
        payload: bytes,
        private_key: Optional[str] = None,
        issuer: str = "https://api.ibanity.com",
        audience: str = "ponto_webhook",
        expires_in: int = 300,
    ) -> str:
        """
        Generate JWT signature for webhook payload.

        Args:
            payload: Webhook payload bytes
            private_key: RSA private key PEM (uses test key if None)
            issuer: JWT issuer claim
            audience: JWT audience claim
            expires_in: Token lifetime in seconds

        Returns:
            JWT string for Authorization header
        """
        try:
            import jwt
        except ImportError:
            frappe.throw("PyJWT library required for webhook signature generation")

        if private_key is None:
            private_key = TEST_JWT_PRIVATE_KEY

        now = int(time.time())
        claims = {
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + expires_in,
            "digest": hashlib.sha256(payload).hexdigest(),
        }

        return jwt.encode(claims, private_key, algorithm="RS256")

    @staticmethod
    def create_signed_webhook(
        event_type: PontoEventType,
        **kwargs,
    ) -> tuple:
        """
        Create webhook payload with valid signature.

        Returns:
            Tuple of (payload_bytes, signature_string)
        """
        payload = PontoTestDataFactory.create_webhook_payload(event_type, **kwargs)
        signature = PontoTestDataFactory.sign_webhook_payload(payload)
        return payload, signature

    # -------------------------------------------------------------------------
    # SEPA Payment Request Data
    # -------------------------------------------------------------------------

    @staticmethod
    def create_sepa_payment_data(
        amount: float = 100.00,
        creditor_name: str = "Supplier BV",
        creditor_iban: str = TestIBAN.ABN_AMRO_1,
        remittance_info: str = "Invoice INV-2025-001",
        execution_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate SEPA payment request data.

        Args:
            amount: Payment amount in EUR
            creditor_name: Recipient name
            creditor_iban: Recipient IBAN
            remittance_info: Payment reference
            execution_date: Requested execution date

        Returns:
            Payment data for payment initiation service
        """
        return {
            "amount": amount,
            "currency": "EUR",
            "creditorName": creditor_name,
            "creditorAccountReference": creditor_iban,
            "creditorAccountReferenceType": "IBAN",
            "remittanceInformation": remittance_info,
            "remittanceInformationType": "unstructured",
            "requestedExecutionDate": execution_date or datetime.now().strftime("%Y-%m-%d"),
        }

    # -------------------------------------------------------------------------
    # ERPNext Document Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def create_ponto_settings(
        client_id: str = "test_client_id",
        client_secret: str = "test_client_secret",
        use_sandbox: bool = True,
        use_mtls: bool = False,
    ) -> "frappe.Document":
        """
        Create or update Ponto Settings for testing.

        Returns:
            Ponto Settings document
        """
        settings = frappe.get_single("Ponto Settings")
        settings.ibanity_client_id = client_id
        settings.set_password("ibanity_client_secret", client_secret)
        settings.use_sandbox = 1 if use_sandbox else 0
        settings.use_ibanity_mtls = 1 if use_mtls else 0
        settings.save()
        return settings

    @staticmethod
    def create_ponto_payment_request(
        amount: float = 100.00,
        creditor_name: str = "Test Supplier BV",
        creditor_iban: str = TestIBAN.ABN_AMRO_1,
        remittance_info: str = "Test payment",
        status: str = "Pending",
        ponto_payment_id: Optional[str] = None,
    ) -> "frappe.Document":
        """
        Create Ponto Payment Request document.

        Returns:
            Ponto Payment Request document
        """
        doc = frappe.new_doc("Ponto Payment Request")
        doc.amount = amount
        doc.creditor_name = creditor_name
        doc.creditor_iban = creditor_iban
        doc.remittance_information = remittance_info
        doc.status = status

        if ponto_payment_id:
            doc.ponto_payment_id = ponto_payment_id

        doc.insert()
        return doc

    @staticmethod
    def create_ponto_payment_link(
        amount: float = 25.00,
        description: str = "Membership dues",
        member: Optional[str] = None,
        sales_invoice: Optional[str] = None,
        status: str = "Draft",
        ponto_request_id: Optional[str] = None,
    ) -> "frappe.Document":
        """
        Create Ponto Payment Link document.

        Returns:
            Ponto Payment Link document
        """
        doc = frappe.new_doc("Ponto Payment Link")
        doc.amount = amount
        doc.description = description
        doc.status = status

        if member:
            doc.member = member
        if sales_invoice:
            doc.sales_invoice = sales_invoice
        if ponto_request_id:
            doc.ponto_request_id = ponto_request_id

        doc.insert()
        return doc

    # -------------------------------------------------------------------------
    # Error Response Generators
    # -------------------------------------------------------------------------

    @staticmethod
    def create_api_error_response(
        status_code: int = 400,
        error_code: str = "invalidRequest",
        error_detail: str = "The request was invalid",
    ) -> Dict[str, Any]:
        """Generate Ponto API error response."""
        return {
            "errors": [
                {
                    "code": error_code,
                    "detail": error_detail,
                    "status": str(status_code),
                }
            ]
        }

    @staticmethod
    def create_rate_limit_response(retry_after: int = 60) -> tuple:
        """
        Generate rate limit (429) response.

        Returns:
            Tuple of (status_code, headers, body)
        """
        return (
            429,
            {"Retry-After": str(retry_after)},
            PontoTestDataFactory.create_api_error_response(
                status_code=429,
                error_code="rateLimitExceeded",
                error_detail=f"Rate limit exceeded. Retry after {retry_after} seconds.",
            ),
        )
