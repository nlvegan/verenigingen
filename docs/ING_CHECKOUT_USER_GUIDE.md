# ING Checkout Integration - User Guide

## Table of Contents

1. [Introduction & Overview](#introduction--overview)
2. [Prerequisites & Requirements](#prerequisites--requirements)
3. [Initial Setup Guide](#initial-setup-guide)
4. [Daily Operations Guide](#daily-operations-guide)
5. [Troubleshooting Guide](#troubleshooting-guide)
6. [Technical Reference](#technical-reference)

---

## Introduction & Overview

### What is ING Checkout?

ING Checkout is a payment solution powered by Pay.nl that provides iDEAL payments and SEPA Direct Debit capabilities for Dutch associations. This integration enables members to pay via the most popular Dutch payment method (iDEAL) and allows associations to set up recurring direct debit collections.

### Business Benefits

**Dutch Payment Methods**

- iDEAL integration for instant bank payments
- SEPA Direct Debit for recurring collections
- Familiar payment experience for Dutch members

**Mandate Management**

- Digital mandate signing for direct debit authorization
- Mandate status tracking and validation
- Automatic mandate expiry handling

**Simplified Collections**

- Direct debit execution against active mandates
- Automated payment reconciliation
- Integration with Sales Invoice workflow

### How It Works

1. **Member Setup**: Members sign a SEPA Direct Debit mandate through a secure online form
2. **Mandate Creation**: System stores mandate details and links to member record
3. **Invoice Generation**: Membership Dues Schedules create Sales Invoices
4. **Debit Execution**: System initiates direct debit against active mandates
5. **Webhook Processing**: Pay.nl sends status updates via webhooks
6. **Reconciliation**: Payments automatically create Payment Entries and update invoices

---

## Prerequisites & Requirements

### System Requirements

**Technical Prerequisites**

- ERPNext/Frappe Framework v15+
- Verenigingen app installed and configured
- Internet connectivity for API communication
- SSL certificate for webhook endpoints

**Pay.nl Account Requirements**

- Active Pay.nl merchant account
- ING Checkout service enabled
- Completed KYC verification
- SEPA Direct Debit feature activated (for mandates)

**Permissions Required**

- System Manager or Verenigingen Administrator role
- Access to ING Checkout Settings
- Permission to create and manage mandates

### Pay.nl Account Setup

**Getting Your Credentials**

1. **Create Pay.nl Account**: Visit [admin.pay.nl](https://admin.pay.nl) and register
2. **Complete Verification**: Submit required business documents
3. **Enable ING Checkout**: Request ING Checkout service activation
4. **Get API Credentials**:
   - **Service ID**: Admin Panel → Settings → Sales Locations (format: SL-xxxx-xxxx)
   - **Token Code**: Admin Panel → Merchant → Company Information (format: AT-xxxx-xxxx)
   - **API Token**: Admin Panel → Merchant → Company Information (40-character hash)

---

## Initial Setup Guide

### Step 1: Configure ING Checkout Settings

**Accessing Configuration**

1. Navigate to **Verenigingen Payments** workspace
2. Click **ING Checkout Settings**
3. Enable the integration

**Basic Configuration**

```
Enabled: ✓
Sandbox Mode: ✓ (Enable for initial testing)

API Credentials:
  Service ID: SL-xxxx-xxxx
  Token Code: AT-xxxx-xxxx
  API Token: [Your 40-character API token]
```

**URL Configuration**

```
Default Return URL: https://yoursite.nl/payment-complete
Terms and Conditions URL: https://yoursite.nl/terms
Webhook URL: [Auto-generated]
```

Click **Save** and use the **Test Connection** button to validate credentials.

### Step 2: Configure Webhooks

**Webhook URLs**

The system provides three webhook endpoints for Pay.nl notifications:

- **Payment Webhook**: For iDEAL and other payment updates
- **Mandate Webhook**: For mandate status changes
- **Direct Debit Webhook**: For direct debit execution results

**Pay.nl Dashboard Configuration**

1. Log into Pay.nl Admin Panel
2. Go to **Settings** → **Exchange Notifications**
3. Add the webhook URLs provided in ING Checkout Settings
4. Enable notifications for: Orders, Mandates, Direct Debits

### Step 3: Test the Integration

**Test Connection**

```python
# In ERPNext Console
from verenigingen.verenigingen_payments.ing_checkout.client import PayNLClient

client = PayNLClient()
# If no exception, connection is working
```

**Create Test Payment**

Use sandbox mode to create a test iDEAL payment and verify the complete flow.

### Step 4: Go Live

1. Return to **ING Checkout Settings**
2. Uncheck **Sandbox Mode**
3. Verify all credentials are production values
4. Save and test with a small transaction

---

## Daily Operations Guide

### Creating iDEAL Payments

**For One-Time Payments**

iDEAL payments can be initiated from Sales Invoices or custom payment pages:

```python
from verenigingen.verenigingen_payments.ing_checkout.api.payment import create_ideal_payment

result = create_ideal_payment(
    reference_doctype="Sales Invoice",
    reference_name="SINV-00001",
    amount=25.00,
    description="Membership dues January 2026"
)

# Redirect member to result['payment_url']
```

### Managing SEPA Direct Debit Mandates

**Creating a Mandate**

1. Navigate to the Member record
2. Use the **Create Mandate** action
3. Member receives a link to sign the mandate digitally
4. Mandate status updates automatically via webhook

```python
from verenigingen.verenigingen_payments.ing_checkout.api.mandate import create_mandate_for_member

result = create_mandate_for_member(
    member_name="MEM-00001",
    iban="NL91ABNA0417164300",
    account_holder="Jan de Vries"
)
```

**Mandate Statuses**

- **Pending**: Awaiting member signature
- **Active**: Signed and ready for debits
- **Used**: Mandate has been used for a debit (single-use mandates)
- **Cancelled**: Revoked by member or admin
- **Expired**: Past validity period
- **Failed**: Signature process failed

**Viewing Member Mandates**

```python
from verenigingen.verenigingen_payments.ing_checkout.api.mandate import get_member_mandates

mandates = get_member_mandates("MEM-00001")
```

### Executing Direct Debits

**For Individual Invoices**

```python
from verenigingen.verenigingen_payments.ing_checkout.api.mandate import execute_debit_for_invoice

result = execute_debit_for_invoice(
    mandate_name="ING-MANDATE-00001",
    invoice_name="SINV-00001"
)
```

**Batch Processing**

For bulk direct debit collection, use the scheduled job or manual batch trigger from the Verenigingen Payments workspace.

### Payment Status Tracking

**Check Payment Status**

```python
from verenigingen.verenigingen_payments.ing_checkout.api.payment import get_payment_status

status = get_payment_status("ING-TXN-00001")
print(f"Status: {status['state']}")
```

**Transaction States**

| Status | Meaning |
|--------|---------|
| Pending | Payment initiated, awaiting completion |
| Processing | Payment is being processed |
| Paid | Payment successful |
| Paid - Payment Entry Failed | Payment received but ERPNext Payment Entry creation failed (requires manual intervention) |
| Cancelled | Payment cancelled by user |
| Expired | Payment link expired |
| Denied | Payment denied by bank or payment provider |
| Refunded | Payment refunded |

---

## Troubleshooting Guide

### Common Setup Issues

**"Invalid credentials" Error**

- Verify Service ID format (SL-xxxx-xxxx)
- Verify Token Code format (AT-xxxx-xxxx)
- Ensure API Token is complete (40 characters)
- Check sandbox/production mode matches credentials

**Webhook Not Receiving Updates**

- Verify webhook URL is publicly accessible
- Check SSL certificate is valid
- Review Pay.nl exchange notification logs
- Ensure firewall allows Pay.nl IP ranges

**Mandate Creation Fails**

- IBAN must be valid Dutch or EU IBAN
- Terms and Conditions URL must be configured
- Member must have valid email address

### Payment Issues

**Payment Stuck in Pending**

- Check Pay.nl dashboard for actual status
- Webhook may have failed - check Error Log
- Manually sync status using `get_payment_status()`

**Direct Debit Rejected**

- Check mandate is still active
- Verify sufficient time since last debit (SDD timing rules)
- Account may have insufficient funds
- IBAN may be closed or blocked

### Mandate Issues

**Member Cannot Sign Mandate**

- Verify mandate link is still valid (check expiry)
- Check Terms and Conditions URL is accessible
- Try regenerating the mandate

**Mandate Shows Wrong Status**

```python
from verenigingen.verenigingen_payments.ing_checkout.api.mandate import sync_mandate_status

# Force sync from Pay.nl
sync_mandate_status("ING-MANDATE-00001")
```

---

## Technical Reference

### DocTypes

**ING Checkout Settings**

```
enabled: Enable/disable integration
sandbox_mode: Use test environment
service_id: Pay.nl Service ID (SL-xxxx-xxxx)
token_code: Pay.nl Token Code (AT-xxxx-xxxx)
api_token: Pay.nl API Token (encrypted)
default_return_url: Post-payment redirect URL
terms_and_conditions_url: Terms page for mandates
webhook_url: Auto-generated webhook endpoint
connection_status: Last connection test result
```

**ING Checkout Transaction** (naming: ICT-####)

```
transaction_id: Pay.nl Order ID (format: EX-xxxx-xxxx-xxxx, unique, required)
status: Pending / Processing / Paid / Paid - Payment Entry Failed / Cancelled / Expired / Denied / Refunded
payment_method: iDEAL / Bancontact / Credit Card / Direct Debit / Other
amount: Transaction amount (Currency, required)
currency: Currency code, e.g. EUR (Link to Currency)
reference_doctype: Linked document type (e.g. Sales Invoice)
reference_name: Linked document name
payment_entry: Created Payment Entry (auto-populated after reconciliation)
customer_name: Customer/member name
customer_iban: Customer bank account IBAN
customer_bic: Customer bank BIC code
redirect_url: Payment redirect URL
return_url: Post-payment return URL
raw_request: Raw API request data (for debugging)
raw_response: Raw API response data (for debugging)
```

**ING Checkout Mandate** (naming: ICM-####)

```
mandate_id: Pay.nl Mandate ID (format: IO-xxxx-xxxx-xxxx, unique, required)
mandate_type: single / recurring / flexible (default: flexible)
status: Pending / Active / Used / Cancelled / Expired / Failed
amount: Mandate amount (Currency)
currency: Currency code, e.g. EUR (Link to Currency)
description: Mandate description
debtor_name: Debtor (payer) name
debtor_iban: Debtor bank account IBAN
debtor_email: Debtor email address
debtor_bic: Debtor bank BIC code
reference_doctype: Linked document type
reference_name: Linked document name
member: Linked Member
sepa_mandate: Linked SEPA Mandate (if applicable)
created_date: Mandate creation date
first_collection_date: First direct debit collection date
last_collection_date: Last direct debit collection date
expiry_date: Mandate expiry date
terms_url: URL to terms and conditions page
raw_response: Raw API response data (for debugging)
```

### API Endpoints

**Payment Operations**

```
POST /api/method/verenigingen.verenigingen_payments.ing_checkout.api.payment.create_ideal_payment
GET  /api/method/verenigingen.verenigingen_payments.ing_checkout.api.payment.get_payment_status
GET  /api/method/verenigingen.verenigingen_payments.ing_checkout.api.payment.test_connection
```

**Mandate Operations**

```
POST /api/method/verenigingen.verenigingen_payments.ing_checkout.api.mandate.create_mandate_for_member
POST /api/method/verenigingen.verenigingen_payments.ing_checkout.api.mandate.execute_debit_for_invoice
GET  /api/method/verenigingen.verenigingen_payments.ing_checkout.api.mandate.get_mandate_status
POST /api/method/verenigingen.verenigingen_payments.ing_checkout.api.mandate.sync_mandate_status
POST /api/method/verenigingen.verenigingen_payments.ing_checkout.api.mandate.cancel_mandate
GET  /api/method/verenigingen.verenigingen_payments.ing_checkout.api.mandate.get_member_mandates
```

**Webhooks**

```
POST /api/method/verenigingen.verenigingen_payments.ing_checkout.api.webhook.handle_payment
POST /api/method/verenigingen.verenigingen_payments.ing_checkout.api.webhook.handle_mandate
POST /api/method/verenigingen.verenigingen_payments.ing_checkout.api.webhook.handle_direct_debit
```

### Webhook Security

Webhooks are validated using:

1. **HMAC-SHA256 Signature**: Validates payload authenticity
2. **IP Whitelist**: Optional restriction to Pay.nl IP ranges
3. **Idempotency**: Hash-based duplicate detection

```python
from verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security import (
    verify_webhook_signature,
    is_ip_whitelisted,
)
```

### Error Handling

```python
from verenigingen.verenigingen_payments.ing_checkout.client import (
    PayNLError,
    PayNLAuthenticationError,
    PayNLValidationError,
)

try:
    client.create_order(order_data)
except PayNLAuthenticationError:
    # Invalid credentials
    pass
except PayNLValidationError as e:
    # Invalid request data
    print(e.message)
except PayNLError as e:
    # Other API error
    print(f"Status: {e.status_code}, Message: {e.message}")
```

### Testing

```bash
# Run ING Checkout tests
bench --site dev.veganisme.net run-tests --module verenigingen.verenigingen_payments.ing_checkout.tests

# Specific test files
bench --site dev.veganisme.net run-tests --module verenigingen.verenigingen_payments.ing_checkout.tests.test_webhook_security
```

---

**Document Version**: 1.1
**Last Updated**: March 2026
**System Compatibility**: ERPNext v15+, Verenigingen App v2.0+
