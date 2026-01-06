# ING Checkout Integration

Payment integration with ING Checkout (powered by Pay.nl) for iDEAL payments and SEPA Direct Debit.

## Architecture

```
verenigingen/verenigingen_payments/ing_checkout/
├── api/                        # HTTP endpoints
│   ├── payment.py              # Payment initiation API
│   ├── mandate.py              # SEPA mandate management
│   └── webhook.py              # Webhook receiver
├── client.py                   # Pay.nl API client
├── services/                   # Business logic layer
│   └── mandate_service.py      # Mandate lifecycle management
├── utils/                      # Utilities
│   └── webhook_security.py     # Webhook signature verification
└── tests/                      # Test suites
    ├── test_api.py             # API endpoint tests
    ├── test_client.py          # Client tests
    ├── test_transaction.py     # Transaction handling tests
    ├── test_webhook_handlers.py # Webhook processing tests
    └── test_webhook_security.py # Security tests
```

## Related DocTypes

- **ING Checkout Settings**: API configuration and credentials
- **ING Checkout Transaction**: Payment transaction records
- **ING Checkout Mandate**: SEPA Direct Debit mandates

## Key Features

### Payment Methods
- **iDEAL**: Dutch online banking payments
- **SEPA Direct Debit**: Single debit requests for recurring collections

### Mandate Management
- Create and manage SEPA Direct Debit mandates
- Track mandate status and validity
- Link mandates to members for automated collections

### Webhook Processing
- **Signature Verification**: HMAC-SHA256 validation
- **IP Whitelisting**: Configurable allowed source IPs
- **Idempotency**: Hash-based duplicate detection
- **Logging**: Webhook payload logging with truncation

### Security
- **API Key Management**: Secure credential storage
- **Request Signing**: All API calls signed
- **Webhook Security**: Multi-layer verification (signature + IP)

## API Client

### INGCheckoutClient
Direct Pay.nl API access.

```python
from verenigingen.verenigingen_payments.ing_checkout.client import INGCheckoutClient

client = INGCheckoutClient()
# Create payment
payment = client.create_payment(amount=25.00, description="Membership dues")
# Get payment status
status = client.get_payment_status(transaction_id)
```

## Services

### MandateService
SEPA mandate lifecycle management.

```python
from verenigingen.verenigingen_payments.ing_checkout.services.mandate_service import MandateService

service = MandateService()
# Create mandate
mandate = service.create_mandate(member_name, iban, bic)
# Get mandate status
status = service.get_mandate_status(mandate_id)
```

## API Endpoints

### Payment Operations
```
POST /api/method/verenigingen.verenigingen_payments.ing_checkout.api.payment.create_payment
GET  /api/method/verenigingen.verenigingen_payments.ing_checkout.api.payment.get_payment_status
```

### Mandate Operations
```
POST /api/method/verenigingen.verenigingen_payments.ing_checkout.api.mandate.create_mandate
GET  /api/method/verenigingen.verenigingen_payments.ing_checkout.api.mandate.get_mandate_status
```

### Webhook
```
POST /api/method/verenigingen.verenigingen_payments.ing_checkout.api.webhook.handle_webhook
```

## Webhook Security

### Signature Verification
```python
from verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security import verify_webhook_signature

is_valid = verify_webhook_signature(
    payload=request_body,
    signature=request.headers.get("X-Pay-Signature"),
    secret=webhook_secret
)
```

### IP Whitelist
Configurable in ING Checkout Settings. Fail-closed behavior: requests from unknown IPs are rejected.

### Idempotency
Duplicate webhooks detected via payload hash. Previously processed webhooks return success without reprocessing.

## Transaction Status Mapping

Pay.nl status codes mapped to internal states:

| Pay.nl Status | Internal Status |
|---------------|-----------------|
| PAID          | Paid            |
| PENDING       | Pending         |
| CANCELLED     | Cancelled       |
| EXPIRED       | Expired         |
| FAILED        | Failed          |
| REFUNDED      | Refunded        |

## Testing

### Run Tests
```bash
# All ING Checkout tests
bench --site dev.veganisme.net run-tests --module verenigingen.verenigingen_payments.ing_checkout.tests

# Specific test file
bench --site dev.veganisme.net run-tests --module verenigingen.verenigingen_payments.ing_checkout.tests.test_webhook_security
```

## Configuration

Configuration managed through **ING Checkout Settings** DocType:
- API Token and Service ID
- Webhook secret for signature verification
- IP whitelist for webhook validation
- Test/production mode toggle

Access via: Verenigingen Payments > ING Checkout Settings

## API Documentation

Pay.nl Platform API: https://developer.pay.nl/docs/platform
