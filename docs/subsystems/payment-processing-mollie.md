# Mollie Payment Processing Integration

## Overview

The Mollie Payment Processing Integration provides online payment capabilities for Dutch association management, supporting both one-time payments and recurring subscription-based membership dues. This system integrates Mollie's payment platform with the association's financial operations.

## Architecture Overview

### Module Structure

Mollie integration lives under `vereinigingen_payments/mollie/` with this structure:

- **`api/`** -- Whitelisted API endpoints (webhooks, payment sync, subscriptions, monitoring, dashboard, donation status, unified payment)
- **`core/`** -- Core client, models, and exceptions
- **`domain/`** -- Payment classification logic
- **`events/`** -- Amendment event handlers
- **`services/`** -- Business logic services
- **`utils/`** -- Utilities (security, validation, logging, monitoring, helpers)
- **`tests/`** -- Mollie-specific test suite

### Mollie Settings (`Mollie Settings`)

DocType at `vereinigingen_payments/doctype/mollie_settings/`:

- **API Access**: profile_id, test_secret_key, live_secret_key, test_mode
- **Subscription Management**: enable_subscriptions, default_subscription_interval
- **Webhook Security**: testing_webhook_url, live_webhook_url, webhook_secret_keys
- **Backend API**: organization_access_token, organization_id
- **Accounting**: mollie_bank_account, mollie_clearing_account, payment_processing_fees_account

### Core Layer (`mollie/core/`)

- `client.py` -- Mollie API client wrapper
- `mollie_models.py` -- Data models for Mollie objects
- `mollie_exceptions.py` -- Custom exception hierarchy

### API Layer (`mollie/api/`)

- `payment_webhook.py` -- Webhook endpoint for payment status updates
- `webhooks.py` -- Additional webhook handling
- `unified_payment_api.py` -- Unified API for creating payments
- `subscription_sync.py` -- Subscription status sync
- `monitoring_api.py` -- Integration monitoring
- `dashboard.py` -- Mollie dashboard data
- `payment_audit.py` -- Payment audit trail
- `donation_status_checker.py` -- Donation payment status
- `sync.py` -- General sync operations

### Services Layer (`mollie/services/`)

**Payment Processing:**

- `payment_service.py` -- Core payment operations
- `complete_payment_service.py` -- End-to-end payment completion
- `payment_processors.py` -- Payment type-specific processors
- `payment_type_router.py` -- Routes payments to correct processor
- `payment_context_resolver.py` -- Resolves payment context (member, invoice, donation)
- `order_payment_processor.py` -- Order-based payments
- `dues_payment_processor.py` -- Membership dues payments
- `bulk_payment_checker.py` -- Bulk payment status verification

**Subscription Management:**

- `subscription_service.py` -- Subscription CRUD and lifecycle
- `mollie_subscription_sync_service.py` -- Syncs subscription status

**Webhook Processing:**

- `generic_webhook_service.py` -- Generic webhook event processing
- `webhook_wrapper_service_unified.py` -- Unified webhook wrapper

**Shared:**

- `shared/payment_entry_factory.py` -- Creates ERPNext Payment Entry from Mollie data
- `shared/cost_center_resolver.py` -- Resolves cost centers for payments

**Other:**

- `unified_idempotency_manager.py` -- Prevents duplicate processing
- `handlers/refund_handler.py` -- Per-refund-ID idempotency (replaced cumulative amountRefunded)
- `handlers/donation_lookup.py` -- Donation record lookup

### Utils Layer (`mollie/utils/`)

**Security and Validation:**

- `security.py` -- Mollie-specific security checks
- `webhook_security.py` -- Webhook signature verification using Mollie secret keys
- `webhook_parser.py` -- Parses webhook payloads
- `validation.py` -- Payment validation rules
- `validators.py` -- Input validators
- `data_validator.py` -- Validates Mollie customer data (registered as Customer doc_event)

**Payment Utilities:**

- `amount_helpers.py` -- Amount formatting and conversion
- `date_parser.py` -- Date parsing for Mollie formats
- `common_helpers.py` -- Shared utility functions
- `unified_payment_entry_creator.py` -- Creates payment entries
- `member_payment_matcher.py` -- Matches payments to members
- `mollie_relationship_manager.py` -- Manages Mollie-member relationships
- `relationship_manager.py` -- General relationship management
- `transaction_manager.py` -- Transaction lifecycle management

**Monitoring and Debugging:**

- `logging.py` -- Mollie-specific logging
- `monitoring.py` -- Integration health monitoring
- `audit.py` -- Audit trail utilities
- `error_recovery.py` -- Error recovery logic
- `webhook_utilities.py` -- Webhook helper functions

### Payment Processing Workflows

#### One-Time Payment Flow

1. **Payment Initiation**: Member selects amount and payment method
2. **Mollie Payment Creation**: API call via `unified_payment_api.py`
3. **Redirect to Mollie**: Secure redirect to Mollie payment interface
4. **Payment Processing**: Member completes payment on Mollie platform
5. **Webhook Notification**: Mollie calls `payment_webhook.py`
6. **Invoice Reconciliation**: `mollie_reconciliation_service.py` matches to pending invoices
7. **Member History Update**: Payment recorded in member payment history

#### Subscription Lifecycle

1. **Customer Creation**: Mollie customer record via `subscription_service.py`
2. **Mandate Setup**: First payment for subscription authorization
3. **Subscription Creation**: Recurring payment schedule established
4. **Automatic Processing**: Mollie handles recurring collection
5. **Webhook Processing**: `generic_webhook_service.py` processes status updates
6. **Invoice Integration**: `dues_payment_processor.py` matches to invoices
7. **Failure Handling**: `error_recovery.py` manages retry logic

#### Idempotency

`unified_idempotency_manager.py` prevents duplicate processing of webhooks and payments. Refund handling uses per-refund-ID idempotency via `refund_handler.py`, replacing the earlier cumulative amountRefunded approach.

### Document Event Hooks

From `hooks/doc_events.py`:

**Customer `validate`:** `validate_mollie_customer_data` ensures Mollie customer data consistency

### Reconciliation Services

- `services/payment/mollie_reconciliation_service.py` -- Reconciles Mollie payments with invoices
- `services/payment/mollie_webhook_service.py` -- Webhook processing at payment service level

### Payment Method Support

- **iDEAL**: Primary Dutch online banking
- **Bancontact**: Belgian payment method
- **SEPA Direct Debit**: Recurring payments
- **Credit Cards**: Visa, Mastercard, American Express
- **Digital Wallets**: PayPal, Apple Pay, Google Pay

### Accounting Integration

- **Mollie Bank Account**: Final settlement destination
- **Mollie Clearing Account**: Temporary reconciliation account
- **Payment Processing Fees Account**: Transaction fee recording

### Testing

Mollie test suite at `vereinigingen_payments/mollie/tests/`:

- API integration, core integration, webhook security tests
- Subscription tests (creation, sync, persona-based)
- Payment processor, refund/chargeback tests
- Payment context resolver, payment entry factory tests
- Customer creation concurrency, failed payment tests

Test runner: `run_mollie_e2e_tests.sh`
Contract tests: `tests/contracts/mollie-contracts.json`

## Key File Locations

- **Mollie module**: `vereinigingen_payments/mollie/`
- **Mollie Settings**: `vereinigingen_payments/doctype/mollie_settings/`
- **Payment services**: `services/payment/mollie_reconciliation_service.py`, `mollie_webhook_service.py`
- **Hooks**: `hooks/doc_events.py` (Customer validate section)
- **Tests**: `vereinigingen_payments/mollie/tests/`, `tests/payment/`
