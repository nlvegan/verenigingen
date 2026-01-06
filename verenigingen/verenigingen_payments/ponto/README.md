# Ponto Banking Integration

Bank account aggregation and payment initiation via Ponto Connect API (by Isabel Group).

## Architecture

```
verenigingen/verenigingen_payments/ponto/
├── api/                        # HTTP endpoints
│   ├── oauth2_callback.py      # OAuth2 authorization callback
│   ├── webhook.py              # Bank transaction webhooks
│   ├── payment_callback.py     # Payment status callbacks
│   └── betaalverzoek_callback.py # Payment request callbacks
├── core/                       # Core components
│   ├── ponto_client.py         # Base REST client with OAuth2
│   └── ponto_models.py         # Data models (Account, Transaction, etc.)
├── clients/                    # Domain-specific clients
│   ├── accounts_client.py      # Bank account operations
│   ├── transactions_client.py  # Transaction retrieval
│   ├── transaction_importer.py # Import to Bank Transaction DocType
│   ├── sync_client.py          # Synchronization operations
│   ├── payment_client.py       # Payment initiation
│   └── betaalverzoek_client.py # Payment request (Betaalverzoek) operations
├── services/                   # Business logic layer
│   ├── oauth2_service.py       # OAuth2 token management
│   ├── configuration_service.py # Settings and configuration
│   ├── transaction_import_service.py # Transaction import orchestration
│   └── payment_initiation_service.py # Payment initiation workflows
├── utils/                      # Utilities
│   ├── token_manager.py        # Token storage and refresh
│   ├── webhook_security.py     # Webhook signature verification
│   ├── secure_cert_manager.py  # Certificate management
│   └── bank_account_creator.py # Bank Account DocType creation
├── exceptions/                 # Custom exceptions
│   └── __init__.py             # Exception hierarchy
└── tests/                      # Test suites
```

## Related DocTypes

- **Ponto Settings**: API configuration, OAuth credentials, certificate paths
- **Ponto Bank Account Mapping**: Links Ponto accounts to Frappe Bank Accounts
- **Ponto Payment Request**: Outgoing payment requests
- **Ponto Payment Link**: Betaalverzoek (payment request links)
- **Ponto Sync Log**: Transaction synchronization history

## Key Features

### Bank Account Aggregation
- **Multi-bank Support**: Connect accounts from any PSD2-compliant bank
- **Real-time Sync**: Transaction retrieval via webhooks or polling
- **Account Mapping**: Link Ponto accounts to Frappe Bank Accounts

### Transaction Import
- **Automatic Import**: Transactions imported as Bank Transaction documents
- **Duplicate Detection**: Prevents re-importing existing transactions
- **Metadata Preservation**: Full transaction details stored

### Payment Initiation (PIS)
- **SEPA Credit Transfer**: Initiate outgoing payments
- **Payment Requests**: Generate payment request links (Betaalverzoek)
- **Status Tracking**: Monitor payment execution status

### OAuth2 Authentication
- **Authorization Code Flow**: Secure bank account authorization
- **Token Management**: Automatic refresh of expired tokens
- **Certificate Authentication**: mTLS for API security

## Core Components

### PontoClient
Base REST client with OAuth2 authentication.

```python
from verenigingen.verenigingen_payments.ponto import get_ponto_client

client = get_ponto_client()
# Make authenticated API calls
response = client.get("/accounts")
```

### PontoAccountsClient
Bank account operations.

```python
from verenigingen.verenigingen_payments.ponto import get_accounts_client

client = get_accounts_client()
accounts = client.list_accounts()
account = client.get_account(account_id)
```

### PontoTransactionsClient
Transaction retrieval.

```python
from verenigingen.verenigingen_payments.ponto import get_transactions_client

client = get_transactions_client()
transactions = client.list_transactions(account_id)
```

### PontoTransactionImporter
Import transactions to Frappe.

```python
from verenigingen.verenigingen_payments.ponto import get_transaction_importer

importer = get_transaction_importer()
result = importer.import_transactions()
print(f"Imported: {result.imported_count}, Skipped: {result.skipped_count}")
```

## Services

### OAuth2Service
Token management and authorization.

```python
from verenigingen.verenigingen_payments.ponto.services.oauth2_service import get_oauth2_service

service = get_oauth2_service()
# Get valid access token (refreshes if expired)
token = service.get_access_token()
# Initiate authorization flow
auth_url = service.get_authorization_url(redirect_uri)
```

### PontoConfigurationService
Cached settings access.

```python
from verenigingen.verenigingen_payments.ponto import get_ponto_config

config = get_ponto_config()
client_id = config.get_client_id()
is_sandbox = config.is_sandbox_mode()
```

### PaymentInitiationService
Outgoing payment workflows.

```python
from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import PaymentInitiationService

service = PaymentInitiationService()
payment = service.initiate_payment(
    account_id=account_id,
    amount=100.00,
    creditor_iban="NL91ABNA0417164300",
    creditor_name="Recipient",
    remittance_info="Invoice 12345"
)
```

## API Endpoints

### OAuth2 Authorization
```
GET /api/method/verenigingen.verenigingen_payments.ponto.api.oauth2_callback.handle_callback
```

### Webhooks
```
POST /api/method/verenigingen.verenigingen_payments.ponto.api.webhook.handle_ponto_webhook
```

### Payment Callbacks
```
POST /api/method/verenigingen.verenigingen_payments.ponto.api.payment_callback.handle_payment_callback
POST /api/method/verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback.handle_betaalverzoek_callback
```

## Exception Hierarchy

```python
from verenigingen.verenigingen_payments.ponto.exceptions import (
    PontoIntegrationError,      # Base exception
    PontoAPIError,              # API communication errors
    PontoAuthenticationError,   # OAuth2 authentication failures
    PontoTokenExpiredError,     # Token refresh required
    PontoRateLimitError,        # API rate limiting
    PontoConfigurationError,    # Settings misconfiguration
    PontoSyncError,             # Synchronization failures
    PontoTransactionImportError, # Import failures
    PontoWebhookError,          # Webhook processing errors
)
```

## Data Models

### PontoAccount
```python
from verenigingen.verenigingen_payments.ponto import PontoAccount

# Represents a connected bank account
account.id
account.iban
account.currency
account.description
account.holder_name
```

### PontoTransaction
```python
from verenigingen.verenigingen_payments.ponto import PontoTransaction

# Represents a bank transaction
transaction.id
transaction.amount
transaction.currency
transaction.execution_date
transaction.counterpart_name
transaction.counterpart_reference
transaction.remittance_information
```

## Testing

### Run Tests
```bash
# All Ponto tests
bench --site dev.veganisme.net run-tests --module verenigingen.verenigingen_payments.ponto

# Test OAuth2 flow
bench --site dev.veganisme.net run-tests --module verenigingen.verenigingen_payments.ponto.tests.test_oauth2
```

### Test Token Retrieval
```python
from verenigingen.verenigingen_payments.ponto.services.oauth2_service import get_oauth2_service

service = get_oauth2_service()
try:
    token = service.get_access_token()
    print(f"Token acquired, length: {len(token)}")
except Exception as e:
    print(f"Authentication failed: {e}")
```

## Configuration

Configuration managed through **Ponto Settings** DocType:
- Client ID and Client Secret
- Organization ID
- Certificate paths (for mTLS)
- Sandbox/production mode
- Webhook secret

Access via: Verenigingen Payments > Ponto Settings

## API Documentation

Ponto Connect API: https://documentation.ibanity.com/ponto-connect
