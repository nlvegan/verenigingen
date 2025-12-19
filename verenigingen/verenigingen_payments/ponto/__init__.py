# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Banking Integration

Provides integration with Ponto (by Isabel Group) for bank transaction retrieval
and future payment initiation via the Ponto Connect API.

Main Components:
- PontoClient: Low-level REST client with OAuth2 authentication
- PontoAccountsClient: Bank account operations
- PontoTransactionsClient: Transaction retrieval
- PontoTransactionImporter: Import transactions as Bank Transactions
- PontoConfigurationService: Cached settings access

Usage:
    from verenigingen.verenigingen_payments.ponto import (
        PontoTransactionImporter,
        get_transaction_importer,
    )

    importer = get_transaction_importer()
    result = importer.import_transactions()
"""

# High-level clients
from .clients import (
    ImportError,
    ImportResult,
    PontoAccountsClient,
    PontoTransactionImporter,
    PontoTransactionsClient,
    get_accounts_client,
    get_transaction_importer,
    get_transactions_client,
)

# Core client and models
from .core import PontoAccount, PontoClient, PontoSynchronization, PontoTransaction, get_ponto_client

# Exceptions
from .exceptions import (
    PontoAPIError,
    PontoAuthenticationError,
    PontoConfigurationError,
    PontoIntegrationError,
    PontoRateLimitError,
    PontoSyncError,
    PontoTokenExpiredError,
    PontoTransactionImportError,
    PontoWebhookError,
)

# Services
from .services import PontoConfigurationService, get_ponto_config

# Utils
from .utils import PontoTokenManager, get_token_manager

__all__ = [
    # Core
    "PontoClient",
    "get_ponto_client",
    "PontoAccount",
    "PontoTransaction",
    "PontoSynchronization",
    # Clients
    "PontoAccountsClient",
    "get_accounts_client",
    "PontoTransactionsClient",
    "get_transactions_client",
    "PontoTransactionImporter",
    "get_transaction_importer",
    "ImportResult",
    "ImportError",
    # Exceptions
    "PontoIntegrationError",
    "PontoAPIError",
    "PontoAuthenticationError",
    "PontoTokenExpiredError",
    "PontoRateLimitError",
    "PontoWebhookError",
    "PontoConfigurationError",
    "PontoSyncError",
    "PontoTransactionImportError",
    # Services
    "PontoConfigurationService",
    "get_ponto_config",
    # Utils
    "PontoTokenManager",
    "get_token_manager",
]
