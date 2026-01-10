# Copyright (c) 2026, Verenigingen
# License: MIT

"""
ING Checkout (Pay.nl) Data Models

Dataclasses representing Pay.nl API resources for the ING Checkout integration.
Provides type-safe access to API response data and standardized transformations.

Usage:
    from verenigingen.verenigingen_payments.ing_checkout.models import (
        INGTransaction,
        INGMandate,
        INGDirectDebit,
        TransactionStatus,
        MandateStatus,
    )

    # Parse API response
    mandate = INGMandate.from_api_response(api_data)
    print(mandate.debtor_iban, mandate.status)

    # Convert to DocType dict
    doctype_values = mandate.to_doctype_dict()
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional


class TransactionStatus(str, Enum):
    """Pay.nl transaction/order status values."""

    PENDING = "Pending"
    PROCESSING = "Processing"
    PAID = "Paid"
    PAID_PE_FAILED = "Paid - Payment Entry Failed"
    CANCELLED = "Cancelled"
    EXPIRED = "Expired"
    DENIED = "Denied"
    REFUNDED = "Refunded"

    @classmethod
    def from_api_status(cls, api_status: str) -> "TransactionStatus":
        """
        Map Pay.nl API status to internal status.

        Pay.nl uses different status values in their API.
        """
        status_map = {
            "PENDING": cls.PENDING,
            "pending": cls.PENDING,
            "PROCESSING": cls.PROCESSING,
            "processing": cls.PROCESSING,
            "PAID": cls.PAID,
            "paid": cls.PAID,
            "CANCEL": cls.CANCELLED,
            "cancel": cls.CANCELLED,
            "CANCELLED": cls.CANCELLED,
            "cancelled": cls.CANCELLED,
            "EXPIRED": cls.EXPIRED,
            "expired": cls.EXPIRED,
            "DENIED": cls.DENIED,
            "denied": cls.DENIED,
            "REFUND": cls.REFUNDED,
            "refund": cls.REFUNDED,
            "REFUNDED": cls.REFUNDED,
            "refunded": cls.REFUNDED,
        }
        return status_map.get(api_status, cls.PENDING)


class MandateStatus(str, Enum):
    """Pay.nl SEPA mandate status values."""

    PENDING = "Pending"
    ACTIVE = "Active"
    USED = "Used"
    CANCELLED = "Cancelled"
    EXPIRED = "Expired"
    FAILED = "Failed"

    @classmethod
    def from_api_status(cls, api_status: str) -> "MandateStatus":
        """Map Pay.nl API mandate status to internal status."""
        status_map = {
            "PENDING": cls.PENDING,
            "pending": cls.PENDING,
            "ACTIVE": cls.ACTIVE,
            "active": cls.ACTIVE,
            "USED": cls.USED,
            "used": cls.USED,
            "CANCELLED": cls.CANCELLED,
            "cancelled": cls.CANCELLED,
            "EXPIRED": cls.EXPIRED,
            "expired": cls.EXPIRED,
            "FAILED": cls.FAILED,
            "failed": cls.FAILED,
        }
        return status_map.get(api_status, cls.PENDING)


class MandateType(str, Enum):
    """Pay.nl SEPA mandate types."""

    SINGLE = "single"
    RECURRING = "recurring"
    FLEXIBLE = "flexible"


class DirectDebitStatus(str, Enum):
    """Pay.nl direct debit status values."""

    PENDING = "Pending"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    FAILED = "Failed"
    REVERSED = "Reversed"

    @classmethod
    def from_api_status(cls, api_status: str) -> "DirectDebitStatus":
        """Map Pay.nl API direct debit status to internal status."""
        status_map = {
            "PENDING": cls.PENDING,
            "pending": cls.PENDING,
            "PROCESSING": cls.PROCESSING,
            "processing": cls.PROCESSING,
            "COMPLETED": cls.COMPLETED,
            "completed": cls.COMPLETED,
            "PAID": cls.COMPLETED,
            "paid": cls.COMPLETED,
            "FAILED": cls.FAILED,
            "failed": cls.FAILED,
            "REVERSED": cls.REVERSED,
            "reversed": cls.REVERSED,
        }
        return status_map.get(api_status, cls.PENDING)


@dataclass
class INGTransaction:
    """
    ING Checkout transaction (Pay.nl order) representation.

    Represents a payment order created through the Pay.nl API.

    Attributes:
        transaction_id: Pay.nl order ID (EX-xxxx-xxxx-xxxx)
        status: Transaction status
        payment_method: Payment method used (iDEAL, etc.)
        amount: Transaction amount
        currency: Currency code (EUR)
        customer_name: Payer name
        customer_iban: Payer IBAN (if available)
        customer_bic: Payer BIC (if available)
        reference_doctype: Linked document type (e.g., Sales Invoice)
        reference_name: Linked document name
        description: Payment description
        redirect_url: URL for payment page
        return_url: URL to redirect after payment
        exchange_url: Webhook notification URL
        raw_request: Original request JSON
        raw_response: Original response JSON
    """

    transaction_id: str
    status: TransactionStatus
    amount: Decimal
    currency: str = "EUR"
    payment_method: str = ""
    customer_name: str = ""
    customer_iban: str = ""
    customer_bic: str = ""
    reference_doctype: str = ""
    reference_name: str = ""
    description: str = ""
    redirect_url: str = ""
    return_url: str = ""
    exchange_url: str = ""
    raw_request: Optional[Dict[str, Any]] = field(default_factory=dict)
    raw_response: Optional[Dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "INGTransaction":
        """
        Create INGTransaction from Pay.nl API response.

        Args:
            data: Pay.nl order response

        Returns:
            INGTransaction instance
        """
        # Extract amount - Pay.nl uses {"value": cents, "currency": "EUR"}
        amount_data = data.get("amount", {})
        if isinstance(amount_data, dict):
            # Convert cents to decimal
            amount_cents = amount_data.get("value", 0)
            amount = Decimal(str(amount_cents)) / 100
            currency = amount_data.get("currency", "EUR")
        else:
            amount = Decimal(str(amount_data or 0))
            currency = "EUR"

        # Extract payment method
        payment_method = ""
        pm_data = data.get("paymentMethod", {})
        if isinstance(pm_data, dict):
            payment_method = pm_data.get("name", "") or str(pm_data.get("id", ""))
        elif pm_data:
            payment_method = str(pm_data)

        # Extract customer/debtor info
        customer = data.get("customer", {}) or data.get("debtor", {}) or {}

        # Extract links
        links = data.get("links", {}) or {}

        return cls(
            transaction_id=data.get("id", "") or data.get("orderId", ""),
            status=TransactionStatus.from_api_status(data.get("status", "pending")),
            amount=amount,
            currency=currency,
            payment_method=payment_method,
            customer_name=customer.get("name", ""),
            customer_iban=customer.get("iban", ""),
            customer_bic=customer.get("bic", ""),
            description=data.get("description", ""),
            redirect_url=links.get("redirect", "") or data.get("redirectUrl", ""),
            return_url=data.get("returnUrl", ""),
            exchange_url=data.get("exchangeUrl", ""),
            raw_response=data,
        )

    @property
    def is_paid(self) -> bool:
        """Check if transaction is successfully paid."""
        return self.status in (TransactionStatus.PAID, TransactionStatus.PAID_PE_FAILED)

    @property
    def is_pending(self) -> bool:
        """Check if transaction is pending/in progress."""
        return self.status in (TransactionStatus.PENDING, TransactionStatus.PROCESSING)

    @property
    def is_failed(self) -> bool:
        """Check if transaction failed."""
        return self.status in (
            TransactionStatus.CANCELLED,
            TransactionStatus.EXPIRED,
            TransactionStatus.DENIED,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "transaction_id": self.transaction_id,
            "status": self.status.value,
            "amount": str(self.amount),
            "currency": self.currency,
            "payment_method": self.payment_method,
            "customer_name": self.customer_name,
            "customer_iban": self.customer_iban,
            "customer_bic": self.customer_bic,
            "reference_doctype": self.reference_doctype,
            "reference_name": self.reference_name,
            "description": self.description,
            "redirect_url": self.redirect_url,
            "return_url": self.return_url,
            "exchange_url": self.exchange_url,
        }

    def to_doctype_dict(self) -> Dict[str, Any]:
        """
        Convert to dict format for ING Checkout Transaction DocType.

        Returns:
            Dict matching ING Checkout Transaction fields
        """
        return {
            "doctype": "ING Checkout Transaction",
            "transaction_id": self.transaction_id,
            "status": self.status.value,
            "amount": float(self.amount),
            "currency": self.currency,
            "payment_method": self.payment_method,
            "customer_name": self.customer_name,
            "customer_iban": self.customer_iban,
            "customer_bic": self.customer_bic,
            "reference_doctype": self.reference_doctype,
            "reference_name": self.reference_name,
            "redirect_url": self.redirect_url,
            "return_url": self.return_url,
        }


@dataclass
class INGMandate:
    """
    ING Checkout SEPA mandate representation.

    Represents a SEPA Direct Debit mandate created through Pay.nl.

    Attributes:
        mandate_id: Pay.nl mandate ID (IO-xxxx-xxxx-xxxx)
        mandate_type: Type of mandate (single, recurring, flexible)
        status: Mandate status
        debtor_name: Debtor/customer name
        debtor_iban: Debtor IBAN
        debtor_email: Debtor email
        debtor_bic: Debtor BIC (if available)
        amount: Authorized amount (for single/flexible)
        description: Mandate description
        created_date: When mandate was created
        first_collection_date: Date of first collection
        last_collection_date: Date of last collection
        expiry_date: When mandate expires
        reference_doctype: Linked document type
        reference_name: Linked document name
        raw_response: Original API response
    """

    mandate_id: str
    mandate_type: MandateType
    status: MandateStatus
    debtor_name: str = ""
    debtor_iban: str = ""
    debtor_email: str = ""
    debtor_bic: str = ""
    amount: Optional[Decimal] = None
    description: str = ""
    created_date: Optional[date] = None
    first_collection_date: Optional[date] = None
    last_collection_date: Optional[date] = None
    expiry_date: Optional[date] = None
    reference_doctype: str = ""
    reference_name: str = ""
    raw_response: Optional[Dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "INGMandate":
        """
        Create INGMandate from Pay.nl API response.

        Args:
            data: Pay.nl mandate response

        Returns:
            INGMandate instance
        """
        # Parse mandate type
        mandate_type_str = data.get("type", "single").lower()
        try:
            mandate_type = MandateType(mandate_type_str)
        except ValueError:
            mandate_type = MandateType.SINGLE

        # Parse amount if present
        amount = None
        amount_data = data.get("amount", {})
        if isinstance(amount_data, dict) and amount_data.get("value"):
            amount = Decimal(str(amount_data["value"])) / 100
        elif amount_data and not isinstance(amount_data, dict):
            amount = Decimal(str(amount_data))

        # Extract debtor info
        debtor = data.get("debtor", {}) or {}

        # Parse dates
        created_date = cls._parse_date(data.get("createdAt") or data.get("created"))
        first_collection = cls._parse_date(data.get("firstCollectionDate"))
        last_collection = cls._parse_date(data.get("lastCollectionDate"))
        expiry_date = cls._parse_date(data.get("expiryDate") or data.get("validUntil"))

        return cls(
            mandate_id=data.get("mandateId", "") or data.get("id", ""),
            mandate_type=mandate_type,
            status=MandateStatus.from_api_status(data.get("status", "pending")),
            debtor_name=debtor.get("name", ""),
            debtor_iban=debtor.get("iban", ""),
            debtor_email=debtor.get("email", ""),
            debtor_bic=debtor.get("bic", ""),
            amount=amount,
            description=data.get("description", ""),
            created_date=created_date,
            first_collection_date=first_collection,
            last_collection_date=last_collection,
            expiry_date=expiry_date,
            raw_response=data,
        )

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[date]:
        """Parse ISO date string to date object."""
        if not date_str:
            return None
        try:
            if "T" in date_str:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
            return date.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None

    @property
    def is_active(self) -> bool:
        """Check if mandate is active and can be used."""
        return self.status == MandateStatus.ACTIVE

    @property
    def is_usable(self) -> bool:
        """Check if mandate can be used for a direct debit."""
        return self.status in (MandateStatus.ACTIVE, MandateStatus.PENDING)

    @property
    def is_recurring(self) -> bool:
        """Check if mandate is for recurring payments."""
        return self.mandate_type in (MandateType.RECURRING, MandateType.FLEXIBLE)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "mandate_id": self.mandate_id,
            "mandate_type": self.mandate_type.value,
            "status": self.status.value,
            "debtor_name": self.debtor_name,
            "debtor_iban": self.debtor_iban,
            "debtor_email": self.debtor_email,
            "debtor_bic": self.debtor_bic,
            "amount": str(self.amount) if self.amount else None,
            "description": self.description,
            "created_date": self.created_date.isoformat() if self.created_date else None,
            "first_collection_date": (
                self.first_collection_date.isoformat() if self.first_collection_date else None
            ),
            "last_collection_date": (
                self.last_collection_date.isoformat() if self.last_collection_date else None
            ),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
        }

    def to_doctype_dict(self) -> Dict[str, Any]:
        """
        Convert to dict format for ING Checkout Mandate DocType.

        Returns:
            Dict matching ING Checkout Mandate fields
        """
        return {
            "doctype": "ING Checkout Mandate",
            "mandate_id": self.mandate_id,
            "mandate_type": self.mandate_type.value,
            "status": self.status.value,
            "debtor_name": self.debtor_name,
            "debtor_iban": self.debtor_iban,
            "debtor_email": self.debtor_email,
            "debtor_bic": self.debtor_bic,
            "amount": float(self.amount) if self.amount else None,
            "description": self.description,
            "created_date": self.created_date,
            "first_collection_date": self.first_collection_date,
            "last_collection_date": self.last_collection_date,
            "expiry_date": self.expiry_date,
            "reference_doctype": self.reference_doctype,
            "reference_name": self.reference_name,
        }


@dataclass
class INGDirectDebit:
    """
    ING Checkout direct debit execution representation.

    Represents a direct debit collection executed against a mandate.

    Attributes:
        reference_id: Pay.nl direct debit reference (IL-xxxx)
        mandate_id: Associated mandate ID
        status: Direct debit status
        amount: Collection amount
        currency: Currency code
        description: Collection description
        process_date: Scheduled processing date
        execution_date: Actual execution date
        raw_response: Original API response
    """

    reference_id: str
    mandate_id: str
    status: DirectDebitStatus
    amount: Decimal
    currency: str = "EUR"
    description: str = ""
    process_date: Optional[date] = None
    execution_date: Optional[date] = None
    raw_response: Optional[Dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "INGDirectDebit":
        """
        Create INGDirectDebit from Pay.nl API response.

        Args:
            data: Pay.nl direct debit response

        Returns:
            INGDirectDebit instance
        """
        # Parse amount
        amount_data = data.get("amount", {})
        if isinstance(amount_data, dict):
            amount = Decimal(str(amount_data.get("value", 0))) / 100
            currency = amount_data.get("currency", "EUR")
        else:
            amount = Decimal(str(amount_data or 0))
            currency = "EUR"

        # Parse dates
        process_date = cls._parse_date(data.get("processDate"))
        execution_date = cls._parse_date(data.get("executionDate"))

        return cls(
            reference_id=data.get("referenceId", "") or data.get("id", ""),
            mandate_id=data.get("mandateId", ""),
            status=DirectDebitStatus.from_api_status(data.get("status", "pending")),
            amount=amount,
            currency=currency,
            description=data.get("description", ""),
            process_date=process_date,
            execution_date=execution_date,
            raw_response=data,
        )

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[date]:
        """Parse ISO date string to date object."""
        if not date_str:
            return None
        try:
            if "T" in date_str:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
            return date.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None

    @property
    def is_completed(self) -> bool:
        """Check if direct debit completed successfully."""
        return self.status == DirectDebitStatus.COMPLETED

    @property
    def is_pending(self) -> bool:
        """Check if direct debit is pending."""
        return self.status in (DirectDebitStatus.PENDING, DirectDebitStatus.PROCESSING)

    @property
    def is_failed(self) -> bool:
        """Check if direct debit failed."""
        return self.status in (DirectDebitStatus.FAILED, DirectDebitStatus.REVERSED)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "reference_id": self.reference_id,
            "mandate_id": self.mandate_id,
            "status": self.status.value,
            "amount": str(self.amount),
            "currency": self.currency,
            "description": self.description,
            "process_date": self.process_date.isoformat() if self.process_date else None,
            "execution_date": self.execution_date.isoformat() if self.execution_date else None,
        }


# Export public API
__all__ = [
    # Enums
    "TransactionStatus",
    "MandateStatus",
    "MandateType",
    "DirectDebitStatus",
    # Dataclasses
    "INGTransaction",
    "INGMandate",
    "INGDirectDebit",
]
