# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Transactions Client

High-level client for working with Ponto bank transactions.

Usage:
    from verenigingen.verenigingen_payments.ponto.clients.transactions_client import (
        PontoTransactionsClient,
    )

    client = PontoTransactionsClient()
    transactions = client.list_transactions(account_id)
    transaction = client.get_transaction(account_id, transaction_id)
"""

from datetime import date, datetime
from typing import List, Optional

import frappe

from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient, get_ponto_client
from verenigingen.verenigingen_payments.ponto.core.ponto_models import PontoTransaction
from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError


class PontoTransactionsClient:
    """
    High-level client for Ponto transaction operations.

    Provides methods for:
    - Listing transactions for an account
    - Getting transaction details
    - Filtering transactions by date range
    """

    def __init__(self, client: Optional[PontoClient] = None):
        """
        Initialize transactions client.

        Args:
            client: Optional PontoClient instance (creates new if not provided)
        """
        self._client = client or get_ponto_client()

    def list_transactions(
        self,
        account_id: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        limit: int = 100,
        max_pages: Optional[int] = None,
    ) -> List[PontoTransaction]:
        """
        List transactions for an account.

        Args:
            account_id: Ponto account UUID
            from_date: Only return transactions on or after this date
            to_date: Only return transactions on or before this date
            limit: Items per page (default 100)
            max_pages: Maximum pages to fetch (None for unlimited)

        Returns:
            List of PontoTransaction objects (newest first)

        Raises:
            PontoAPIError: If API call fails
        """
        if not account_id:
            raise PontoAPIError(
                "Account ID is required",
                details={"account_id": account_id},
            )

        frappe.logger().debug(
            f"Fetching Ponto transactions for account {account_id}"
            + (f" from {from_date}" if from_date else "")
            + (f" to {to_date}" if to_date else "")
        )

        endpoint = f"/accounts/{account_id}/transactions"
        params = {}

        # Note: Ponto API may not support direct date filtering
        # We'll filter client-side if needed

        data = self._client.get_paginated(
            endpoint,
            params=params if params else None,
            limit=limit,
            max_pages=max_pages,
        )

        transactions = [PontoTransaction.from_api_response(item, account_id=account_id) for item in data]

        # Apply date filtering client-side
        if from_date or to_date:
            transactions = self._filter_by_date(transactions, from_date, to_date)

        frappe.logger().debug(f"Found {len(transactions)} Ponto transactions for account {account_id}")

        return transactions

    def _filter_by_date(
        self,
        transactions: List[PontoTransaction],
        from_date: Optional[date],
        to_date: Optional[date],
    ) -> List[PontoTransaction]:
        """
        Filter transactions by date range.

        Args:
            transactions: List of transactions to filter
            from_date: Minimum date (inclusive)
            to_date: Maximum date (inclusive)

        Returns:
            Filtered list of transactions
        """
        filtered = []
        for tx in transactions:
            if from_date and tx.value_date < from_date:
                continue
            if to_date and tx.value_date > to_date:
                continue
            filtered.append(tx)
        return filtered

    def get_transaction(
        self,
        account_id: str,
        transaction_id: str,
    ) -> PontoTransaction:
        """
        Get details for a specific transaction.

        Args:
            account_id: Ponto account UUID
            transaction_id: Ponto transaction UUID

        Returns:
            PontoTransaction object

        Raises:
            PontoAPIError: If transaction not found or API call fails
        """
        if not account_id or not transaction_id:
            raise PontoAPIError(
                "Account ID and Transaction ID are required",
                details={
                    "account_id": account_id,
                    "transaction_id": transaction_id,
                },
            )

        frappe.logger().debug(f"Fetching Ponto transaction: {transaction_id} from account {account_id}")

        response = self._client.get(f"/accounts/{account_id}/transactions/{transaction_id}")
        data = response.get("data", {})

        return PontoTransaction.from_api_response(data, account_id=account_id)

    def get_latest_transaction(self, account_id: str) -> Optional[PontoTransaction]:
        """
        Get the most recent transaction for an account.

        Args:
            account_id: Ponto account UUID

        Returns:
            Most recent PontoTransaction, or None if no transactions
        """
        transactions = self.list_transactions(account_id, limit=1, max_pages=1)
        return transactions[0] if transactions else None


def get_transactions_client() -> PontoTransactionsClient:
    """
    Factory function to get PontoTransactionsClient instance.

    Returns:
        PontoTransactionsClient: Client instance
    """
    return PontoTransactionsClient()
