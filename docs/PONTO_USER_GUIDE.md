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

```
Use Ibanity mTLS: ✓
Ibanity API URL: https://api.ibanity.com
Ibanity Client ID: [Your Ibanity client ID]
Ibanity Client Secret: [Your Ibanity client secret]

mTLS Certificates:
  Certificate Path: /path/to/certificate.pem
  Private Key Path: /path/to/private_key.pem
  Key Passphrase: [If applicable]

Signature Certificate (for payment initiation):
  Signature Certificate ID: [From Ibanity portal]
  Signature Certificate Path: /path/to/signature_cert.pem
  Signature Private Key Path: /path/to/signature_key.pem
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
sandbox_mode: Use test environment
organization_id: Ponto organization ID
sandbox_client_id/secret: Sandbox API credentials
production_client_id/secret: Production API credentials
ibanity_certificate: mTLS certificate path
ibanity_private_key: mTLS private key path
signature_certificate_id: Signature certificate ID
auto_sync_enabled: Enable automatic transaction import
sync_interval_hours: Hours between syncs
enable_webhooks: Enable webhook notifications
```

**Ponto Bank Account Mapping**

```
ponto_account_id: Ponto account UUID
iban: Bank account IBAN
bank_account: Linked ERPNext Bank Account
enabled: Enable for sync
last_sync: Last successful sync time
```

**Ponto Payment Link**

```
payment_link_id: Ponto payment request ID
payment_url: URL for member to pay
amount: Payment amount
reference: Invoice or payment reference
status: pending/paid/expired/cancelled
member: Linked Member (optional)
sales_invoice: Linked Sales Invoice (optional)
```

**Ponto Sync Log**

```
sync_type: manual/scheduled/webhook
start_time: Sync start timestamp
end_time: Sync end timestamp
transactions_imported: Count of new transactions
transactions_skipped: Count of duplicates
status: success/partial/failed
error_message: Error details if failed
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

1. **Signature Verification**: HMAC signature validation (if enabled)
2. **Idempotency**: Duplicate event detection
3. **Payload Validation**: Schema validation of webhook content

```python
from verenigingen.verenigingen_payments.ponto.utils.webhook_security import (
    verify_webhook_signature,
    validate_webhook_payload,
)
```

---

**Document Version**: 1.0
**Last Updated**: January 2026
**System Compatibility**: ERPNext v15+, Verenigingen App v2.0+
**Ponto API Version**: Ponto Connect API v2
