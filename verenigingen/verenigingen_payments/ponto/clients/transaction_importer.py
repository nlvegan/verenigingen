# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Transaction Importer

Imports Ponto bank transactions as ERPNext Bank Transactions.
Uses BankTransactionCreator for actual Bank Transaction creation.

Usage:
    from verenigingen.verenigingen_payments.ponto.clients.transaction_importer import (
        PontoTransactionImporter,
    )

    importer = PontoTransactionImporter()
    result = importer.import_transactions(
        account_id="ponto-account-uuid",
        from_date=date(2025, 1, 1),
        to_date=date(2025, 1, 31),
    )
    print(f"Imported: {result.imported}, Skipped: {result.skipped}")
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _

from verenigingen.e_boekhouden.utils.bank_transaction_parser import BankTransactionParser
from verenigingen.verenigingen_payments.ponto.clients.transactions_client import (
    PontoTransactionsClient,
    get_transactions_client,
)
from verenigingen.verenigingen_payments.ponto.core.ponto_models import PontoTransaction
from verenigingen.verenigingen_payments.ponto.exceptions import (
    PontoConfigurationError,
    PontoTransactionImportError,
)
from verenigingen.verenigingen_payments.ponto.services.configuration_service import get_ponto_config
from verenigingen.verenigingen_payments.services.bank_transaction_creator import get_bank_transaction_creator


@dataclass
class ImportError:
    """
    Single import error record.

    Attributes:
        transaction_id: Ponto transaction ID that failed
        error_type: Category of error (validation, creation, api, unknown)
        error_message: Human-readable error description
    """

    transaction_id: str
    error_type: str  # "validation", "creation", "api", "unknown"
    error_message: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "transaction_id": self.transaction_id,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass
class ImportResult:
    """
    Result of a transaction import operation.

    Attributes:
        imported: Number of successfully created Bank Transactions
        skipped: Number of skipped duplicates
        errors: List of ImportError records
        bank_transactions: List of created Bank Transaction names
    """

    imported: int = 0
    skipped: int = 0
    errors: List[ImportError] = field(default_factory=list)
    bank_transactions: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Check if import completed without errors."""
        return len(self.errors) == 0

    @property
    def total_processed(self) -> int:
        """Total transactions processed (imported + skipped + errors)."""
        return self.imported + self.skipped + len(self.errors)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization and logging."""
        return {
            "imported": self.imported,
            "skipped": self.skipped,
            "error_count": len(self.errors),
            "errors": [e.to_dict() for e in self.errors],
            "success": self.success,
            "total_processed": self.total_processed,
            "bank_transactions": self.bank_transactions,
        }


class PontoTransactionImporter:
    """
    Imports Ponto transactions as Bank Transactions.

    Uses PontoTransactionsClient to fetch transactions and
    BankTransactionCreator.create_from_dict() for Bank Transaction creation.

    The importer:
    - Handles duplicate detection via custom_ponto_transaction_id
    - Transforms Ponto data to BankTransactionCreator format
    - Tracks import results with detailed error information
    - Uses Ponto Settings for default bank account and company
    """

    def __init__(
        self,
        transactions_client: Optional[PontoTransactionsClient] = None,
    ):
        """
        Initialize importer.

        Args:
            transactions_client: Optional transactions client instance
        """
        self._transactions_client = transactions_client or get_transactions_client()
        self._bank_tx_creator = get_bank_transaction_creator()
        self._config = get_ponto_config()
        self._party_parser = BankTransactionParser()

    def import_transactions(
        self,
        account_id: Optional[str] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        company: Optional[str] = None,
        bank_account: Optional[str] = None,
        limit: int = 100,
        max_pages: Optional[int] = None,
    ) -> ImportResult:
        """
        Import Ponto transactions as Bank Transactions.

        Args:
            account_id: Ponto account UUID (uses configured account if not provided)
            from_date: Only import transactions on or after this date
            to_date: Only import transactions on or before this date
            company: Company for Bank Transactions (uses configured default if not provided)
            bank_account: Bank Account for transactions (uses configured account if not provided)
            limit: Transactions per page
            max_pages: Maximum pages to fetch (None for unlimited)

        Returns:
            ImportResult with counts and error details

        Raises:
            PontoConfigurationError: If required settings not configured
        """
        # Get configuration defaults
        account_id = account_id or self._config.get_linked_account_id()
        bank_account = bank_account or self._config.get_bank_account()
        company = company or self._config.get_default_company()

        frappe.logger().debug(
            f"Starting Ponto transaction import for account {account_id}"
            + (f" from {from_date}" if from_date else "")
            + (f" to {to_date}" if to_date else "")
        )

        # Fetch transactions from Ponto
        transactions = self._transactions_client.list_transactions(
            account_id=account_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            max_pages=max_pages,
        )

        frappe.logger().debug(f"Fetched {len(transactions)} transactions from Ponto")

        # Import each transaction
        result = ImportResult()

        for ponto_tx in transactions:
            try:
                bt_name, was_created = self._import_single_transaction(
                    ponto_tx=ponto_tx,
                    bank_account=bank_account,
                    company=company,
                )

                if bt_name:
                    if was_created:
                        result.imported += 1
                        result.bank_transactions.append(bt_name)
                    else:
                        # Transaction already existed
                        result.skipped += 1
                else:
                    # create_from_dict returned None - this is a creation failure, not a skip
                    frappe.logger().warning(
                        f"Bank Transaction creation returned None for Ponto transaction {ponto_tx.id} "
                        "(no exception raised)"
                    )
                    result.errors.append(
                        ImportError(
                            transaction_id=ponto_tx.id,
                            error_type="creation",
                            error_message="Bank Transaction creation failed without exception",
                        )
                    )

            except Exception as e:
                frappe.logger().error(f"Failed to import Ponto transaction {ponto_tx.id}: {e}")
                result.errors.append(
                    ImportError(
                        transaction_id=ponto_tx.id,
                        error_type=self._classify_error(e),
                        error_message=str(e),
                    )
                )

        frappe.logger().info(
            f"Ponto import complete: {result.imported} imported, "
            f"{result.skipped} skipped, {len(result.errors)} errors"
        )

        return result

    def _import_single_transaction(
        self,
        ponto_tx: PontoTransaction,
        bank_account: str,
        company: str,
    ) -> Tuple[Optional[str], bool]:
        """
        Import a single Ponto transaction.

        Args:
            ponto_tx: PontoTransaction to import
            bank_account: ERPNext Bank Account name
            company: Company name

        Returns:
            Tuple of (Bank Transaction name, was_created)
            - (name, False) if transaction already existed
            - (name, True) if newly created
            - (None, False) if creation failed
        """
        # Check for existing transaction first (idempotency via custom field)
        existing = self._check_existing_ponto_transaction(ponto_tx.id)
        if existing:
            frappe.logger().debug(f"Ponto transaction {ponto_tx.id} already imported as {existing}")
            return (existing, False)  # Already existed

        # Transform to BankTransactionCreator format
        transaction_data = self._transform_transaction(ponto_tx)

        # Create Bank Transaction
        bt_name = self._bank_tx_creator.create_from_dict(
            transaction_data=transaction_data,
            bank_account=bank_account,
            company=company,
            source_type="Ponto Import",
        )

        if bt_name:
            frappe.logger().debug(f"Created Bank Transaction {bt_name} from Ponto transaction {ponto_tx.id}")
            return (bt_name, True)  # Newly created

        return (None, False)  # Creation failed

    def _transform_transaction(self, ponto_tx: PontoTransaction) -> Dict[str, Any]:
        """
        Transform Ponto transaction to BankTransactionCreator format.

        Includes party matching/creation based on counterparty information.

        Args:
            ponto_tx: PontoTransaction object

        Returns:
            Dict matching BankTransactionCreator.create_from_dict() expectations
        """
        transaction_data = {
            "date": ponto_tx.value_date,
            "amount": float(ponto_tx.amount),
            "currency": ponto_tx.currency,
            "reference_number": ponto_tx.id,  # Critical for duplicate detection
            "description": self._build_description(ponto_tx),
            "bank_party_name": ponto_tx.counterpart_name,
            "bank_party_iban": ponto_tx.counterpart_reference,
            # Custom Ponto fields for tracking
            "custom_ponto_transaction_id": ponto_tx.id,
            "custom_ponto_account_id": ponto_tx.account_id,
        }

        # Match or create party based on counterparty information
        if ponto_tx.counterpart_name:
            try:
                party_type, party = self._match_or_create_party(ponto_tx)
                if party:
                    transaction_data["party_type"] = party_type
                    transaction_data["party"] = party
            except Exception as e:
                # Log but don't fail transaction import if party matching fails
                frappe.logger().warning(f"Party matching failed for transaction {ponto_tx.id}: {e}")

        return transaction_data

    def _match_or_create_party(self, ponto_tx: PontoTransaction) -> Tuple[Optional[str], Optional[str]]:
        """
        Match or create party based on Ponto transaction counterparty.

        Uses BankTransactionParser.find_or_create_party() for intelligent matching:
        - IBAN match (strongest signal)
        - Exact name match
        - Case-insensitive name match
        - Fuzzy name match
        - Create new party if no match

        Party type is determined by transaction amount:
        - Positive (deposit): Customer (income received)
        - Negative (withdrawal): Supplier (expense paid)

        Args:
            ponto_tx: PontoTransaction with counterparty info

        Returns:
            Tuple of (party_type, party_name) or (None, None) if no counterparty
        """
        if not ponto_tx.counterpart_name:
            return None, None

        # Determine party type based on amount sign
        # Positive amount = money coming IN = Customer
        # Negative amount = money going OUT = Supplier
        party_type = "Customer" if ponto_tx.amount > 0 else "Supplier"

        # Use BankTransactionParser for party matching/creation
        party_name, was_created = self._party_parser.find_or_create_party(
            party_name=ponto_tx.counterpart_name,
            party_type=party_type,
            iban=ponto_tx.counterpart_reference,
        )

        if was_created:
            frappe.logger().info(
                f"Created new {party_type} '{party_name}' from Ponto transaction "
                f"(counterpart: {ponto_tx.counterpart_name}, IBAN: {ponto_tx.counterpart_reference})"
            )
        else:
            frappe.logger().debug(
                f"Matched {party_type} '{party_name}' for Ponto transaction "
                f"(counterpart: {ponto_tx.counterpart_name})"
            )

        return party_type, party_name

    def _build_description(self, ponto_tx: PontoTransaction) -> str:
        """
        Build transaction description from Ponto data.

        Args:
            ponto_tx: PontoTransaction object

        Returns:
            Description string
        """
        parts = []

        if ponto_tx.description:
            parts.append(ponto_tx.description)

        if ponto_tx.reference and ponto_tx.reference != ponto_tx.description:
            parts.append(f"Ref: {ponto_tx.reference}")

        if ponto_tx.counterpart_name and ponto_tx.counterpart_name not in parts[0] if parts else True:
            parts.append(f"From/To: {ponto_tx.counterpart_name}")

        return " | ".join(parts) if parts else "Ponto Import"

    def _check_existing_ponto_transaction(self, ponto_transaction_id: str) -> Optional[str]:
        """
        Check if a Ponto transaction was already imported.

        Args:
            ponto_transaction_id: Ponto transaction UUID

        Returns:
            Bank Transaction name if exists, None otherwise
        """
        return frappe.db.get_value(
            "Bank Transaction",
            {"custom_ponto_transaction_id": ponto_transaction_id},
            "name",
        )

    def _classify_error(self, error: Exception) -> str:
        """
        Classify error type for reporting.

        Args:
            error: Exception that occurred

        Returns:
            Error type string
        """
        error_type = type(error).__name__

        if "validation" in error_type.lower():
            return "validation"
        if "api" in error_type.lower() or "ponto" in error_type.lower():
            return "api"
        if "database" in str(error).lower() or "frappe" in error_type.lower():
            return "creation"

        return "unknown"

    def import_single(
        self,
        ponto_transaction_id: str,
        account_id: Optional[str] = None,
        company: Optional[str] = None,
        bank_account: Optional[str] = None,
    ) -> Optional[str]:
        """
        Import a single transaction by ID.

        Useful for webhook processing or manual imports.

        Args:
            ponto_transaction_id: Ponto transaction UUID
            account_id: Ponto account UUID
            company: Company name
            bank_account: Bank Account name

        Returns:
            Bank Transaction name if created/exists, None on failure
        """
        account_id = account_id or self._config.get_linked_account_id()
        bank_account = bank_account or self._config.get_bank_account()
        company = company or self._config.get_default_company()

        # Fetch the specific transaction
        ponto_tx = self._transactions_client.get_transaction(
            account_id=account_id,
            transaction_id=ponto_transaction_id,
        )

        bt_name, _was_created = self._import_single_transaction(
            ponto_tx=ponto_tx,
            bank_account=bank_account,
            company=company,
        )
        return bt_name


def get_transaction_importer() -> PontoTransactionImporter:
    """
    Factory function to get PontoTransactionImporter instance.

    Returns:
        PontoTransactionImporter: Importer instance
    """
    return PontoTransactionImporter()
