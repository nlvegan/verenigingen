# Ponto Banking Integration - User Guide

## Table of Contents

1. [Introduction & Overview](#introduction--overview)
2. [Prerequisites & Requirements](#prerequisites--requirements)
3. [Initial Setup Guide](#initial-setup-guide)
4. [Daily Operations Guide](#daily-operations-guide)
5. [Troubleshooting Guide](#troubleshooting-guide)
6. [Technical Reference](#technical-reference)

---

## Introduction & Overview

### What is Ponto?

Ponto (by Isabel Group/Ibanity) is a PSD2-compliant open banking platform that provides secure access to bank accounts across Europe. This integration enables Dutch associations to:

- **Import bank transactions** automatically from connected bank accounts
- **Initiate payments** (SEPA Credit Transfers) directly from ERPNext
- **Send payment requests** (Betaalverzoeken) to members via payment links
- **Reconcile payments** by matching imported transactions to invoices

### Business Benefits

**Automated Bank Reconciliation**

- Real-time or scheduled transaction import
- Automatic matching of payments to Sales Invoices
- Reduced manual data entry and errors

**Payment Initiation**

- Initiate outgoing payments without logging into bank portal
- Bulk payment processing for supplier invoices
- Full audit trail of all payment activities

**Payment Requests (Betaalverzoeken)**

- Generate payment request links for members
- Members pay via their own bank (iDEAL-like experience)
- Automatic status tracking and reconciliation

**Multi-Bank Support**

- Connect accounts from any PSD2-compliant European bank
- Single dashboard for all connected accounts
- Consolidated financial overview

### How It Works

1. **Authorization**: Administrator authorizes Ponto to access bank accounts via OAuth2
2. **Account Discovery**: System retrieves list of available bank accounts
3. **Transaction Import**: Transactions are imported as Bank Transaction documents
4. **Payment Matching**: Imported transactions are matched to Sales Invoices
5. **Payment Initiation**: Outgoing payments initiated via Ponto API
6. **Payment Requests**: Betaalverzoek links sent to members for payment

---

## Prerequisites & Requirements

### System Requirements

**Technical Prerequisites**

- ERPNext/Frappe Framework v15+
- Verenigingen app installed and configured
- Internet connectivity for API communication
- SSL certificate for OAuth2 callbacks

**Ponto Account Requirements**

- Active Ponto Connect subscription
- Completed onboarding process
- Bank account(s) connected in Ponto portal
- mTLS certificates (for production)

**Permissions Required**

- System Manager or Verenigingen Administrator role
- Access to Ponto Settings
- Bank account management permissions

### Ponto Account Setup

**Getting Started with Ponto**

1. **Sign Up**: Visit [myponto.com](https://myponto.com) and create an account
2. **Complete Onboarding**: Verify your organization details
3. **Connect Banks**: Add your bank accounts through the Ponto portal
4. **Get API Credentials**:
   - **Client ID**: From Ponto developer portal
   - **Client Secret**: From Ponto developer portal
   - **Organization ID**: Your Ponto organization identifier

**For Production Use**

Production requires mTLS (mutual TLS) authentication:
- Generate or obtain SSL certificates
- Register certificate with Ibanity
- Configure certificate paths in Ponto Settings

---

## Initial Setup Guide

### Step 1: Configure Ponto Settings

**Accessing Configuration**

1. Navigate to **Verenigingen Payments** workspace
2. Click **Ponto Settings**
3. Configure environment and credentials

**Environment Configuration**

```
Sandbox Mode: ✓ (Enable for initial testing)
Organization ID: [Your Ponto Organization ID]
```

**Sandbox Credentials**

```
Sandbox Client ID: [Your sandbox client ID]
Sandbox Client Secret: [Your sandbox client secret]
```

**Production Credentials** (when ready)

```
Production Client ID: [Your production client ID]
Production Client Secret: [Your production client secret]
```

### Step 2: Configure Ibanity mTLS (Production Only)

**Certificate Configuration**

Certificates are entered as inline PEM content (not file paths). Copy and paste the full PEM certificate text into each field.

```
Use Ibanity mTLS: ✓
Ibanity API URL: https://api.ibanity.com
Ibanity Client ID: [Your Ibanity client ID]
Ibanity Client Secret: [Your Ibanity client secret]

mTLS Certificates (paste PEM content):
  Client Certificate (PEM): [Paste full certificate PEM text]
  Private Key (PEM): [Paste full private key PEM text]
  Private Key Passphrase: [If applicable]

Signature Certificate (for payment initiation):
  Signature Certificate ID: [From Ibanity portal]
  Signature Certificate (PEM): [Paste signature certificate PEM text]
  Signature Private Key (PEM): [Paste signature private key PEM text]
  Signature Key Passphrase: [If applicable]
```

### Step 3: Authorize Ponto Access

**OAuth2 Authorization Flow**

1. In Ponto Settings, click **Authorize with Ibanity**
2. You'll be redirected to Ponto login
3. Log in and grant access to your bank accounts
4. You'll be redirected back to ERPNext
5. Authorization status should show "Connected"

```python
# Programmatic authorization check
from verenigingen.verenigingen_payments.ponto.api.oauth2_callback import check_authorization_status

status = check_authorization_status()
print(f"Authorized: {status['authorized']}")
```

### Step 4: Configure Bank Account Mappings

**Fetch Available Accounts**

1. Click **Fetch Accounts** in Ponto Settings
2. System retrieves all connected bank accounts
3. Map each Ponto account to an ERPNext Bank Account

**Account Mapping**

For each bank account:
- **Ponto Account ID**: Auto-populated from Ponto
- **IBAN**: Bank account IBAN
- **ERPNext Bank Account**: Select matching Bank Account document
- **Auto Import**: Enable for automatic transaction import

### Step 5: Configure Sync Settings

**Automatic Synchronization**

```
Auto Sync Enabled: ✓
Sync Interval (hours): 4

Webhook Settings:
  Enable Webhooks: ✓
  Require Webhook Signature: ✓
  Webhook URL: [Auto-generated]
```

### Step 6: Test the Integration

**Test Transaction Import**

1. Click **Trigger Sync** in Ponto Settings
2. Check that transactions appear in Bank Transaction list
3. Verify account mappings are correct

```python
# Manual sync test
from verenigingen.verenigingen_payments.ponto import get_transaction_importer

importer = get_transaction_importer()
result = importer.import_transactions()
print(f"Imported: {result.imported_count}, Skipped: {result.skipped_count}")
```

---

## Daily Operations Guide

### Importing Bank Transactions

**Automatic Import**

When auto-sync is enabled, transactions are imported automatically at the configured interval.

**Manual Import**

1. Go to **Ponto Settings**
2. Click **Trigger Sync**
3. View imported transactions in Bank Transaction list

```python
from verenigingen.verenigingen_payments.ponto import get_transaction_importer

importer = get_transaction_importer()
result = importer.import_transactions()

print(f"Imported: {result.imported_count}")
print(f"Skipped (duplicates): {result.skipped_count}")
if result.errors:
    print(f"Errors: {result.errors}")
```

**Transaction Data Imported**

Each imported transaction includes:
- Transaction date and booking date
- Amount and currency
- Counterparty name and account
- Remittance information (payment reference)
- Bank-specific reference numbers

### Reconciling Payments

**Automatic Matching**

The system attempts to match imported transactions to Sales Invoices based on:
1. Remittance information containing invoice number
2. Amount matching outstanding invoice amount
3. Customer/Member matching

**Manual Reconciliation**

For unmatched transactions:
1. Open the Bank Transaction
2. Click **Match** or **Create Payment Entry**
3. Select the corresponding Sales Invoice
4. Submit to create the Payment Entry

### Creating Payment Requests (Betaalverzoeken)

**Generate Payment Link**

```python
from verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client import BetaalverzoekClient

client = BetaalverzoekClient()
result = client.create_payment_request(
    amount=25.00,
    reference="SINV-00001",
    description="Membership dues January 2026",
    member_email="member@example.nl"
)

print(f"Payment link: {result['payment_url']}")
```

**Payment Request Workflow**

1. System creates Ponto Payment Link record
2. Member receives email with payment link
3. Member clicks link and pays via their bank
4. Ponto webhook notifies of payment completion
5. System creates Payment Entry and marks invoice as paid

**Tracking Payment Requests**

View all payment requests in: **Verenigingen Payments** → **Ponto Payment Links**

### Initiating Outgoing Payments

**Single Payment**

```python
from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import PaymentInitiationService

service = PaymentInitiationService()
payment = service.initiate_payment(
    account_id="ponto-account-id",
    amount=500.00,
    creditor_iban="NL91ABNA0417164300",
    creditor_name="Supplier BV",
    remittance_info="Purchase Invoice PI-00001"
)
```

**Payment Status Tracking**

Outgoing payments go through these states:
- **pending**: Payment initiated, awaiting authorization
- **authorized**: Authorized, awaiting execution
- **executed**: Successfully sent to bank
- **rejected**: Bank rejected the payment
- **error**: Technical error occurred

### Viewing Account Balances

**Check Connected Accounts**

```python
from verenigingen.verenigingen_payments.ponto import get_accounts_client

client = get_accounts_client()
accounts = client.list_accounts()

for account in accounts:
    print(f"{account.description}: {account.current_balance} {account.currency}")
```

---

## Troubleshooting Guide

### Authorization Issues

**"Authorization Failed" Error**

- Verify Client ID and Client Secret are correct
- Check that you're using sandbox credentials in sandbox mode
- Ensure redirect URI is properly configured in Ponto portal
- Try clearing browser cookies and re-authorizing

**Token Expired**

The system automatically refreshes tokens. If issues persist:

```python
from verenigingen.verenigingen_payments.ponto.services.oauth2_service import get_oauth2_service

service = get_oauth2_service()
try:
    token = service.get_access_token()
    print("Token valid")
except Exception as e:
    print(f"Token error: {e}")
    # May need to re-authorize
```

**Re-Authorization Required**

1. Go to Ponto Settings
2. Click **Revoke Authorization**
3. Click **Authorize with Ibanity** again

### Sync Issues

**No Transactions Imported**

- Verify bank account mappings exist
- Check that accounts are enabled for auto-import
- Verify authorization is still valid
- Check Ponto portal for account status

**Duplicate Transactions**

The system uses transaction IDs to prevent duplicates. If duplicates occur:
- Check that transaction IDs are unique in source data
- Review Bank Transaction list for duplicate detection

**Sync Errors**

Check the Error Log for detailed error messages:
1. Go to **Settings** → **Error Log**
2. Filter by "Ponto" to see integration-specific errors

### Certificate Issues (Production)

**mTLS Connection Failed**

- Verify certificate paths are correct
- Check certificate is not expired
- Ensure private key matches certificate
- Verify certificate is registered with Ibanity

**Signature Verification Failed**

- Check signature certificate ID matches Ibanity portal
- Verify signature private key is accessible
- Ensure key passphrase is correct (if applicable)

### Payment Request Issues

**Payment Link Not Working**

- Verify member email is correct
- Check payment link hasn't expired
- Review Ponto Payment Link status for errors

**Payment Not Reconciled**

- Check webhook is receiving notifications
- Verify Payment Link has correct invoice reference
- Manually trigger sync if webhook failed

---

## Technical Reference

### DocTypes

**Ponto Settings**

```
sandbox_mode: Use test environment (boolean)
organization_id: Ponto organization ID
organization_name: Organization display name
onboarding_complete: Whether Ponto onboarding is done (boolean)
payments_activated: Whether outbound payments are enabled (boolean)
payment_requests_activated: Whether payment requests are enabled (boolean)
sandbox_client_id: Sandbox API Client ID
sandbox_client_secret: Sandbox API Client Secret (encrypted)
production_client_id: Production API Client ID
production_client_secret: Production API Client Secret (encrypted)
use_ibanity_mtls: Enable mTLS authentication for production (boolean)
ibanity_api_url: Ibanity API base URL
ibanity_client_id: Ibanity client ID for mTLS
ibanity_client_secret: Ibanity client secret for mTLS (encrypted)
ibanity_certificate: Client certificate - inline PEM content (Code field)
ibanity_private_key: Private key - inline PEM content (Code field)
ibanity_key_passphrase: Private key passphrase (encrypted)
signature_certificate_id: Signature certificate ID from Ibanity portal
signature_certificate: Signature certificate - inline PEM content (Code field)
signature_private_key: Signature private key - inline PEM content (Code field)
signature_key_passphrase: Signature key passphrase (encrypted)
ibanity_access_token: Current OAuth2 access token (encrypted, auto-managed)
ibanity_refresh_token: Current OAuth2 refresh token (encrypted, auto-managed)
access_token_expiry: Access token expiry timestamp (auto-managed)
bank_account_mappings: Table of Ponto Bank Account Mapping records
auto_sync_enabled: Enable automatic transaction import (boolean)
sync_interval_hours: Hours between automatic syncs (integer)
last_sync_time: Last successful sync timestamp (auto-managed)
enable_webhooks: Enable Ponto webhook notifications (boolean)
require_webhook_signature: Validate webhook signatures (boolean)
webhook_application_id: Webhook application ID from Ponto
webhook_url: Auto-generated webhook endpoint URL
```

**Ponto Bank Account Mapping** (child table of Ponto Settings)

```
enabled: Enable sync for this account (boolean, default: enabled)
ponto_account_id: Ponto account UUID from API (read-only)
ponto_account_name: Account name/description from Ponto (read-only)
ponto_iban: Bank account IBAN (read-only)
ponto_currency: Account currency, e.g. EUR (read-only, Link to Currency)
bank_account: Linked ERPNext Bank Account (Link)
last_sync_time: Last successful sync time for this account
transactions_imported: Count of transactions imported
sync_status: Current sync status
last_sync_failure_time: Time of last sync failure
last_sync_error: Error message from last failed sync
```

**Ponto Payment Link** (naming: PONTO-LINK-####)

```
payment_type: Payment type (One-Time only; periodic not supported by Ponto Connect)
amount: Payment amount (Currency, required)
currency: Currency code, e.g. EUR (Link to Currency, required)
description: Payment description shown to customer (required)
status: Draft / Pending Authorization / Authorized / Executed / Rejected / Cancelled / Expired / Failed
ponto_request_id: Ponto payment request ID (auto-populated)
redirect_link: Payment URL for the member to complete payment (auto-populated)
frequency: Payment frequency (for future periodic support)
start_date / end_date: Scheduling dates (for future periodic support)
next_payment_date: Next scheduled payment date
total_payments_collected: Running total of collected payments
debtor_name: Debtor (payer) name
debtor_iban: Debtor bank account IBAN
debtor_bank: Debtor bank name
creditor_name: Creditor (association) name
creditor_iban: Creditor bank account IBAN
creditor_account: Creditor ERPNext account
reference_doctype: Linked document type (e.g. Sales Invoice)
reference_name: Linked document name
member: Linked Member (optional)
sales_invoice: Linked Sales Invoice (optional)
payment_entry: Created Payment Entry (auto-populated after payment)
```

**Ponto Payment Request** (naming: PONTO-PAY-####)

Used for outgoing payment initiation (SEPA Credit Transfers):

```
ponto_account: Ponto account ID to pay from (required)
ponto_account_name: Display name of the source account
amount: Payment amount (Currency, required)
currency: Currency code (Link to Currency, required)
status: Draft / Pending Authorization / Authorized / Executed / Rejected / Cancelled / Expired / Failed
ponto_payment_id: Ponto payment ID (auto-populated)
requested_execution_date: Desired execution date
creditor_name: Recipient name
creditor_iban: Recipient IBAN
creditor_bic: Recipient BIC code
remittance_info: Payment reference/description
redirect_uri: Authorization redirect URI
redirect_link: Authorization link for payment approval
reference_doctype: Linked document type
reference_name: Linked document name
payment_entry: Created Payment Entry (auto-populated)
```

**Ponto Sync Log** (naming: PONTO-SYNC-YYYY-MM-DD-####)

```
sync_type: Manual / Automatic / Webhook
account_id: Ponto account UUID
status: Pending / In Progress / Completed / Failed
ponto_sync_id: Ponto synchronization ID (for manual syncs)
start_time: Sync start timestamp
end_time: Sync end timestamp
duration_seconds: Duration of sync in seconds
transactions_imported: Count of new transactions
transactions_skipped: Count of duplicate/already-imported transactions
transactions_failed: Count of transactions that failed to import
error_summary: Brief error description
error_details: Detailed error information (Long Text)
bank_transactions: Table of linked Bank Transaction documents
```

### API Endpoints

**OAuth2 Authorization**

```
GET  /api/method/verenigingen.verenigingen_payments.ponto.api.oauth2_callback.handle_callback
POST /api/method/verenigingen.verenigingen_payments.ponto.api.oauth2_callback.get_authorization_url
POST /api/method/verenigingen.verenigingen_payments.ponto.api.oauth2_callback.check_authorization_status
POST /api/method/verenigingen.verenigingen_payments.ponto.api.oauth2_callback.revoke_authorization
```

**Webhooks**

```
POST /api/method/verenigingen.verenigingen_payments.ponto.api.webhook.handle_ponto_webhook
```

**Payment Callbacks**

```
GET /api/method/verenigingen.verenigingen_payments.ponto.api.payment_callback.payment_callback
GET /api/method/verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback.payment_link_callback
GET /api/method/verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback.payment_page
```

### Client Classes

**PontoClient** - Base API client

```python
from verenigingen.verenigingen_payments.ponto import get_ponto_client

client = get_ponto_client()
response = client.get("/accounts")
```

**PontoAccountsClient** - Bank account operations

```python
from verenigingen.verenigingen_payments.ponto import get_accounts_client

client = get_accounts_client()
accounts = client.list_accounts()
account = client.get_account(account_id)
```

**PontoTransactionsClient** - Transaction retrieval

```python
from verenigingen.verenigingen_payments.ponto import get_transactions_client

client = get_transactions_client()
transactions = client.list_transactions(account_id)
```

**PontoTransactionImporter** - Import to ERPNext

```python
from verenigingen.verenigingen_payments.ponto import get_transaction_importer

importer = get_transaction_importer()
result = importer.import_transactions()
```

### Exception Hierarchy

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

### Data Models

**PontoAccount**

```python
from verenigingen.verenigingen_payments.ponto import PontoAccount

account.id              # Ponto account UUID
account.iban            # IBAN
account.currency        # EUR, etc.
account.description     # Account name
account.holder_name     # Account holder
account.current_balance # Available balance
```

**PontoTransaction**

```python
from verenigingen.verenigingen_payments.ponto import PontoTransaction

transaction.id                    # Transaction UUID
transaction.amount                # Transaction amount
transaction.currency              # Currency code
transaction.execution_date        # When executed
transaction.value_date            # Value date
transaction.counterpart_name      # Other party name
transaction.counterpart_reference # Other party account
transaction.remittance_information # Payment reference
```

### Testing

```bash
# Run all Ponto tests
bench --site dev.veganisme.net run-tests --module verenigingen.verenigingen_payments.ponto

# Test OAuth2 flow
python -c "
from verenigingen.verenigingen_payments.ponto.services.oauth2_service import get_oauth2_service
service = get_oauth2_service()
print(service.get_access_token())
"
```

### Webhook Security

Webhooks are validated using:

1. **JWT Signature Verification**: Webhooks are signed using JWT with JWKS public keys from Ibanity (not HMAC). Signature verification can be enabled via "Require Webhook Signature" in Ponto Settings
2. **Idempotency**: Duplicate event detection
3. **Payload Validation**: Schema validation of webhook content

```python
from verenigingen.verenigingen_payments.ponto.utils.webhook_security import (
    verify_webhook_signature,
)
```

---

**Document Version**: 1.1
**Last Updated**: March 2026
**System Compatibility**: ERPNext v15+, Verenigingen App v2.0+
**Ponto API Version**: Ponto Connect API v2
