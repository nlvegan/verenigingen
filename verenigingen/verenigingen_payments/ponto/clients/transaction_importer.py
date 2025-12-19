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
from typing import Any, Dict, List, Optional

import frappe
from frappe import _

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

        frappe.logger().info(
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

        frappe.logger().info(f"Fetched {len(transactions)} transactions from Ponto")

        # Import each transaction
        result = ImportResult()

        for ponto_tx in transactions:
            try:
                bt_name = self._import_single_transaction(
                    ponto_tx=ponto_tx,
                    bank_account=bank_account,
                    company=company,
                )

                if bt_name:
                    # Check if this is a new transaction or existing
                    if self._is_existing_ponto_transaction(ponto_tx.id):
                        result.skipped += 1
                    else:
                        result.imported += 1
                        result.bank_transactions.append(bt_name)
                else:
                    # create_from_dict returned None but no exception
                    result.skipped += 1

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
    ) -> Optional[str]:
        """
        Import a single Ponto transaction.

        Args:
            ponto_tx: PontoTransaction to import
            bank_account: ERPNext Bank Account name
            company: Company name

        Returns:
            Bank Transaction name if created/exists, None on failure
        """
        # Check for existing transaction first (idempotency via custom field)
        existing = self._check_existing_ponto_transaction(ponto_tx.id)
        if existing:
            frappe.logger().debug(f"Ponto transaction {ponto_tx.id} already imported as {existing}")
            return existing

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

        return bt_name

    def _transform_transaction(self, ponto_tx: PontoTransaction) -> Dict[str, Any]:
        """
        Transform Ponto transaction to BankTransactionCreator format.

        Args:
            ponto_tx: PontoTransaction object

        Returns:
            Dict matching BankTransactionCreator.create_from_dict() expectations
        """
        return {
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

    def _is_existing_ponto_transaction(self, ponto_transaction_id: str) -> bool:
        """Check if transaction already exists."""
        return bool(self._check_existing_ponto_transaction(ponto_transaction_id))

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

        return self._import_single_transaction(
            ponto_tx=ponto_tx,
            bank_account=bank_account,
            company=company,
        )


def get_transaction_importer() -> PontoTransactionImporter:
    """
    Factory function to get PontoTransactionImporter instance.

    Returns:
        PontoTransactionImporter: Importer instance
    """
    return PontoTransactionImporter()
