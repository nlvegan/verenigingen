# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Data Models

Dataclasses representing Ponto API resources.
Provides type-safe access to API response data.

Usage:
    from verenigingen.verenigingen_payments.ponto.core.ponto_models import (
        PontoAccount,
        PontoTransaction,
    )

    account = PontoAccount.from_api_response(api_data)
    print(account.iban, account.current_balance)
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class PontoAccount:
    """
    Ponto bank account representation.

    Attributes:
        id: Ponto account UUID
        reference: Account reference (typically IBAN)
        reference_type: Type of reference (e.g., "IBAN")
        currency: Account currency (ISO 4217)
        current_balance: Current account balance
        available_balance: Available balance
        description: Account description
        product: Account product type
        holder_name: Account holder name
        financial_institution_id: ID of the financial institution
        internal_reference: Internal reference (if available)
        deprecated: Whether account is deprecated
        authorization_expiration_expected_at: When authorization expires
    """

    id: str
    reference: str  # IBAN
    reference_type: str
    currency: str
    current_balance: Decimal
    available_balance: Decimal
    description: str = ""
    product: str = ""
    holder_name: str = ""
    financial_institution_id: str = ""
    internal_reference: str = ""
    deprecated: bool = False
    authorization_expiration_expected_at: Optional[datetime] = None

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "PontoAccount":
        """
        Create PontoAccount from JSON:API response data.

        Args:
            data: JSON:API resource object (with 'id', 'type', 'attributes')

        Returns:
            PontoAccount instance
        """
        attrs = data.get("attributes", {})

        # Parse authorization expiration if present
        auth_expiration = None
        if attrs.get("authorizationExpirationExpectedAt"):
            try:
                auth_expiration = datetime.fromisoformat(
                    attrs["authorizationExpirationExpectedAt"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        return cls(
            id=data.get("id", ""),
            reference=attrs.get("reference", ""),
            reference_type=attrs.get("referenceType", ""),
            currency=attrs.get("currency", "EUR"),
            current_balance=Decimal(str(attrs.get("currentBalance", 0))),
            available_balance=Decimal(str(attrs.get("availableBalance", 0))),
            description=attrs.get("description", ""),
            product=attrs.get("product", ""),
            holder_name=attrs.get("holderName", ""),
            financial_institution_id=attrs.get("financialInstitutionId", ""),
            internal_reference=attrs.get("internalReference", ""),
            deprecated=attrs.get("deprecated", False),
            authorization_expiration_expected_at=auth_expiration,
        )

    @property
    def iban(self) -> str:
        """Convenience property for account IBAN."""
        return self.reference if self.reference_type == "IBAN" else ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "reference": self.reference,
            "reference_type": self.reference_type,
            "currency": self.currency,
            "current_balance": str(self.current_balance),
            "available_balance": str(self.available_balance),
            "description": self.description,
            "product": self.product,
            "holder_name": self.holder_name,
            "financial_institution_id": self.financial_institution_id,
            "internal_reference": self.internal_reference,
            "deprecated": self.deprecated,
            "authorization_expiration_expected_at": (
                self.authorization_expiration_expected_at.isoformat()
                if self.authorization_expiration_expected_at
                else None
            ),
        }


@dataclass
class PontoTransaction:
    """
    Ponto bank transaction representation.

    Attributes:
        id: Ponto transaction UUID
        amount: Transaction amount (positive for credit, negative for debit)
        currency: Transaction currency (ISO 4217)
        value_date: Date the transaction affected the balance
        execution_date: Date the transaction was executed
        description: Transaction description/remittance info
        counterpart_name: Name of the counterparty
        counterpart_reference: Reference of counterparty (typically IBAN)
        reference: Transaction reference (structured reference if available)
        bank_transaction_code: Bank transaction code
        proprietary_bank_transaction_code: Proprietary code
        end_to_end_id: End-to-end identifier
        purpose_code: Purpose code
        mandate_id: SEPA mandate ID (for direct debits)
        creditor_id: SEPA creditor ID (for direct debits)
        additional_information: Additional transaction info
        fee: Transaction fee (if any)
        card_reference: Card reference (if card transaction)
        card_reference_type: Type of card reference
        digest: Transaction digest for deduplication
        internal_reference: Internal reference
        account_id: Parent account ID
    """

    id: str
    amount: Decimal
    currency: str
    value_date: date
    execution_date: date
    description: str = ""
    counterpart_name: str = ""
    counterpart_reference: str = ""
    reference: str = ""
    bank_transaction_code: str = ""
    proprietary_bank_transaction_code: str = ""
    end_to_end_id: str = ""
    purpose_code: str = ""
    mandate_id: str = ""
    creditor_id: str = ""
    additional_information: str = ""
    fee: Optional[Decimal] = None
    card_reference: str = ""
    card_reference_type: str = ""
    digest: str = ""
    internal_reference: str = ""
    account_id: str = ""

    @classmethod
    def from_api_response(cls, data: Dict[str, Any], account_id: str = "") -> "PontoTransaction":
        """
        Create PontoTransaction from JSON:API response data.

        Args:
            data: JSON:API resource object (with 'id', 'type', 'attributes')
            account_id: Parent account ID (from request context)

        Returns:
            PontoTransaction instance
        """
        attrs = data.get("attributes", {})

        # Parse dates
        value_date = cls._parse_date(attrs.get("valueDate"))
        execution_date = cls._parse_date(attrs.get("executionDate"))

        # Parse fee if present
        fee = None
        if attrs.get("fee") is not None:
            fee = Decimal(str(attrs["fee"]))

        return cls(
            id=data.get("id", ""),
            amount=Decimal(str(attrs.get("amount", 0))),
            currency=attrs.get("currency", "EUR"),
            value_date=value_date,
            execution_date=execution_date,
            description=attrs.get("description", "") or attrs.get("remittanceInformation", ""),
            counterpart_name=attrs.get("counterpartName", ""),
            counterpart_reference=attrs.get("counterpartReference", ""),
            reference=attrs.get("remittanceInformationStructured", "") or attrs.get("reference", ""),
            bank_transaction_code=attrs.get("bankTransactionCode", ""),
            proprietary_bank_transaction_code=attrs.get("proprietaryBankTransactionCode", ""),
            end_to_end_id=attrs.get("endToEndId", ""),
            purpose_code=attrs.get("purposeCode", ""),
            mandate_id=attrs.get("mandateId", ""),
            creditor_id=attrs.get("creditorId", ""),
            additional_information=attrs.get("additionalInformation", ""),
            fee=fee,
            card_reference=attrs.get("cardReference", ""),
            card_reference_type=attrs.get("cardReferenceType", ""),
            digest=attrs.get("digest", ""),
            internal_reference=attrs.get("internalReference", ""),
            account_id=account_id,
        )

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> date:
        """Parse ISO date string to date object."""
        if not date_str:
            return date.today()
        try:
            # Handle both date-only and datetime formats
            if "T" in date_str:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
            return date.fromisoformat(date_str)
        except (ValueError, TypeError):
            return date.today()

    @property
    def is_credit(self) -> bool:
        """Check if transaction is a credit (incoming money)."""
        return self.amount > 0

    @property
    def is_debit(self) -> bool:
        """Check if transaction is a debit (outgoing money)."""
        return self.amount < 0

    @property
    def counterpart_iban(self) -> str:
        """Convenience property for counterparty IBAN."""
        return self.counterpart_reference

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "amount": str(self.amount),
            "currency": self.currency,
            "value_date": self.value_date.isoformat(),
            "execution_date": self.execution_date.isoformat(),
            "description": self.description,
            "counterpart_name": self.counterpart_name,
            "counterpart_reference": self.counterpart_reference,
            "reference": self.reference,
            "bank_transaction_code": self.bank_transaction_code,
            "proprietary_bank_transaction_code": self.proprietary_bank_transaction_code,
            "end_to_end_id": self.end_to_end_id,
            "purpose_code": self.purpose_code,
            "mandate_id": self.mandate_id,
            "creditor_id": self.creditor_id,
            "additional_information": self.additional_information,
            "fee": str(self.fee) if self.fee else None,
            "card_reference": self.card_reference,
            "card_reference_type": self.card_reference_type,
            "digest": self.digest,
            "internal_reference": self.internal_reference,
            "account_id": self.account_id,
        }

    def to_bank_transaction_dict(self) -> Dict[str, Any]:
        """
        Convert to dict format expected by BankTransactionCreator.create_from_dict().

        This is the key transformation for importing transactions.

        Returns:
            Dict matching BankTransactionCreator format
        """
        return {
            "date": self.value_date,
            "amount": float(self.amount),
            "currency": self.currency,
            "reference_number": self.id,  # Critical for duplicate detection
            "description": self.description,
            "bank_party_name": self.counterpart_name,
            "bank_party_iban": self.counterpart_reference,
            # Custom Ponto fields
            "custom_ponto_transaction_id": self.id,
            "custom_ponto_account_id": self.account_id,
        }


@dataclass
class PontoSynchronization:
    """
    Ponto synchronization request representation.

    Represents the state of a manual sync request.

    Attributes:
        id: Synchronization UUID
        subtype: Type of sync (e.g., "accountDetails", "accountTransactions")
        status: Sync status (pending, running, success, error)
        resource_type: Resource being synced
        resource_id: ID of resource being synced
        errors: List of error messages
        created_at: When sync was created
        updated_at: When sync was last updated
    """

    id: str
    subtype: str
    status: str
    resource_type: str = ""
    resource_id: str = ""
    errors: List[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "PontoSynchronization":
        """
        Create PontoSynchronization from JSON:API response data.

        Args:
            data: JSON:API resource object

        Returns:
            PontoSynchronization instance
        """
        attrs = data.get("attributes", {})

        # Parse timestamps
        created_at = None
        updated_at = None
        if attrs.get("createdAt"):
            try:
                created_at = datetime.fromisoformat(attrs["createdAt"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass
        if attrs.get("updatedAt"):
            try:
                updated_at = datetime.fromisoformat(attrs["updatedAt"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        # Parse errors
        errors = []
        if attrs.get("errors"):
            for error in attrs["errors"]:
                if isinstance(error, dict):
                    errors.append(error.get("detail", str(error)))
                else:
                    errors.append(str(error))

        return cls(
            id=data.get("id", ""),
            subtype=attrs.get("subtype", ""),
            status=attrs.get("status", ""),
            resource_type=attrs.get("resourceType", ""),
            resource_id=attrs.get("resourceId", ""),
            errors=errors,
            created_at=created_at,
            updated_at=updated_at,
        )

    @property
    def is_pending(self) -> bool:
        """Check if sync is pending."""
        return self.status == "pending"

    @property
    def is_running(self) -> bool:
        """Check if sync is running."""
        return self.status == "running"

    @property
    def is_success(self) -> bool:
        """Check if sync completed successfully."""
        return self.status == "success"

    @property
    def is_error(self) -> bool:
        """Check if sync failed."""
        return self.status == "error"

    @property
    def is_complete(self) -> bool:
        """Check if sync is complete (success or error)."""
        return self.status in ("success", "error")


# Export all models
__all__ = [
    "PontoAccount",
    "PontoTransaction",
    "PontoSynchronization",
]
