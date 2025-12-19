# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Accounts Client

High-level client for working with Ponto bank accounts.

Usage:
    from verenigingen.verenigingen_payments.ponto.clients.accounts_client import (
        PontoAccountsClient,
    )

    client = PontoAccountsClient()
    accounts = client.list_accounts()
    account = client.get_account(account_id)
"""

from typing import Dict, List, Optional

import frappe
from frappe import _

from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient, get_ponto_client
from verenigingen.verenigingen_payments.ponto.core.ponto_models import PontoAccount
from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError


class PontoAccountsClient:
    """
    High-level client for Ponto account operations.

    Provides methods for:
    - Listing linked bank accounts
    - Getting account details
    - Fetching account balances
    """

    def __init__(self, client: Optional[PontoClient] = None):
        """
        Initialize accounts client.

        Args:
            client: Optional PontoClient instance (creates new if not provided)
        """
        self._client = client or get_ponto_client()

    def list_accounts(self) -> List[PontoAccount]:
        """
        List all linked bank accounts.

        Returns:
            List of PontoAccount objects

        Raises:
            PontoAPIError: If API call fails
        """
        frappe.logger().info("Fetching Ponto accounts list")

        data = self._client.get_paginated("/accounts")

        accounts = [PontoAccount.from_api_response(item) for item in data]

        frappe.logger().info(f"Found {len(accounts)} Ponto accounts")

        return accounts

    def get_account(self, account_id: str) -> PontoAccount:
        """
        Get details for a specific account.

        Args:
            account_id: Ponto account UUID

        Returns:
            PontoAccount object

        Raises:
            PontoAPIError: If account not found or API call fails
        """
        if not account_id:
            raise PontoAPIError(
                "Account ID is required",
                details={"account_id": account_id},
            )

        frappe.logger().debug(f"Fetching Ponto account: {account_id}")

        response = self._client.get(f"/accounts/{account_id}")
        data = response.get("data", {})

        return PontoAccount.from_api_response(data)

    def get_account_balance(self, account_id: str) -> Dict[str, str]:
        """
        Get current and available balance for an account.

        Args:
            account_id: Ponto account UUID

        Returns:
            Dict with 'current_balance', 'available_balance', 'currency'

        Raises:
            PontoAPIError: If account not found or API call fails
        """
        account = self.get_account(account_id)

        return {
            "current_balance": str(account.current_balance),
            "available_balance": str(account.available_balance),
            "currency": account.currency,
        }

    def find_account_by_iban(self, iban: str) -> Optional[PontoAccount]:
        """
        Find account by IBAN.

        Args:
            iban: IBAN to search for (spaces will be normalized)

        Returns:
            PontoAccount if found, None otherwise
        """
        # Normalize IBAN (remove spaces)
        normalized_iban = iban.replace(" ", "").upper()

        accounts = self.list_accounts()
        for account in accounts:
            if account.reference.replace(" ", "").upper() == normalized_iban:
                return account

        return None


def get_accounts_client() -> PontoAccountsClient:
    """
    Factory function to get PontoAccountsClient instance.

    Returns:
        PontoAccountsClient: Client instance
    """
    return PontoAccountsClient()
