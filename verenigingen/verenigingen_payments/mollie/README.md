# Mollie Payment Integration

Service-oriented architecture for Mollie payment processing in the Verenigingen app.

## Architecture

```
verenigingen/verenigingen_payments/mollie/
├── api/                        # HTTP endpoints
│   ├── payment_webhook.py      # Webhook receiver
│   ├── unified_payment_api.py  # Payment operations API
│   ├── monitoring_api.py       # Health & metrics endpoints
│   ├── subscription_sync.py    # Subscription synchronization
│   ├── payment_sync_system.py  # Payment reconciliation
│   ├── payment_audit.py        # Audit and compliance
│   └── dashboard.py            # Status dashboard
├── core/                       # Core components
│   ├── client.py               # Primary Mollie API client
│   ├── mollie_client.py        # Alternative client implementation
│   ├── mollie_models.py        # Data models
│   └── mollie_exceptions.py    # Client-level exceptions
├── services/                   # Business logic layer
│   ├── webhook_service.py      # Webhook processing
│   ├── payment_service.py      # Core payment operations
│   ├── subscription_service.py # Subscription management
│   ├── dues_payment_processor.py    # Membership dues processing
│   ├── order_payment_processor.py   # Order payment handling
│   ├── payment_processors.py        # Payment type handlers
│   ├── payment_type_router.py       # Routes payments by type
│   ├── payment_context_resolver.py  # Resolves payment context
│   ├── payment_entry_factory.py     # Creates Payment Entry docs
│   ├── complete_payment_service.py  # Full workflow orchestration
│   ├── generic_webhook_service.py   # Generic webhook handling
│   ├── unified_idempotency_manager.py # Prevents duplicate processing
│   ├── bulk_payment_checker.py      # Batch payment verification
│   ├── mollie_subscription_sync_service.py # Subscription sync
│   └── handlers/               # Specialized handlers
│       ├── donation_lookup.py  # Donation resolution
│       └── refund_handler.py   # Refund processing
├── utils/                      # Utilities
│   ├── logging.py              # Structured logging
│   ├── monitoring.py           # Health checks & performance
│   ├── security.py             # Security utilities
│   ├── validation.py           # Input validation
│   ├── validators.py           # Business rule validators
│   ├── webhook_security.py     # Webhook signature verification
│   ├── webhook_parser.py       # Webhook payload parsing
│   ├── common_helpers.py       # Shared helper functions
│   ├── amount_helpers.py       # Currency/amount handling
│   ├── date_parser.py          # Date parsing utilities
│   ├── error_recovery.py       # Error recovery mechanisms
│   ├── audit.py                # Audit trail utilities
│   ├── relationship_manager.py # Customer/payment relationships
│   └── test_helpers.py         # Testing utilities
├── exceptions/                 # Custom exceptions
│   └── __init__.py             # Exception hierarchy
└── tests/                      # Test suites
    ├── integration/            # Integration tests
    └── [unit tests]
```

## Key Features

### Payment Processing
- **Donations**: Single payment processing with automatic matching
- **Subscriptions**: Recurring payment management for memberships
- **Dues Processing**: Automated membership dues collection
- **Order Payments**: E-commerce order payment handling
- **Refunds & Chargebacks**: Automatic handling with reconciliation

### Webhook Handling
- **Signature Verification**: Validates webhook authenticity
- **Idempotency**: Prevents duplicate processing of the same event
- **Type Routing**: Routes webhooks to appropriate handlers
- **Error Recovery**: Automatic retry with exponential backoff

### Monitoring & Observability
- **Health Checks**: API connectivity and service availability
- **Performance Metrics**: Operation duration and success rates
- **Structured Logging**: Consistent log format with security filtering
- **Alert Thresholds**: Warnings for slow operations (>2s)

### Security
- **API Key Management**: Secure storage and retrieval
- **Sensitive Data Filtering**: Automatic redaction in logs
- **Input Validation**: Comprehensive payload validation
- **Audit Trail**: Complete operation logging

## Service Layer

### PaymentService
Core payment operations.

```python
from verenigingen.verenigingen_payments.mollie.services import PaymentService

service = PaymentService()
payment = service.get_payment("tr_123")
```

### SubscriptionService
Subscription lifecycle management.

```python
from verenigingen.verenigingen_payments.mollie.services import SubscriptionService

service = SubscriptionService()
subscription = service.create_subscription(customer_id, subscription_data)
```

### DuesPaymentProcessor
Membership dues collection.

```python
from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import DuesPaymentProcessor

processor = DuesPaymentProcessor()
processor.process_payment_webhook(payment_id)
```

### CompletePaymentService
Full workflow orchestration.

```python
from verenigingen.verenigingen_payments.mollie.services import CompletePaymentService

service = CompletePaymentService()
result = service.create_donation_payment(donation_doc, form_data)
```

### MollieClient
Direct API access.

```python
from verenigingen.verenigingen_payments.mollie.core import MollieClient

client = MollieClient()
payment = client.get_payment("tr_123")
new_payment = client.create_payment(payment_data)
```

## API Endpoints

### Webhook Processing
```
POST /api/method/verenigingen.verenigingen_payments.mollie.api.payment_webhook.handle_mollie_webhook
POST /api/method/verenigingen.verenigingen_payments.mollie.api.unified_payment_api.handle_payment_webhook
```

### Payment Operations
```
POST /api/method/verenigingen.verenigingen_payments.mollie.api.unified_payment_api.create_donation_payment
POST /api/method/verenigingen.verenigingen_payments.mollie.api.unified_payment_api.create_subscription
```

### Monitoring
```
GET /api/method/verenigingen.verenigingen_payments.mollie.api.monitoring_api.get_integration_health
GET /api/method/verenigingen.verenigingen_payments.mollie.api.monitoring_api.get_performance_metrics
GET /api/method/verenigingen.verenigingen_payments.mollie.api.monitoring_api.get_service_status
```

### Synchronization
```
POST /api/method/verenigingen.verenigingen_payments.mollie.api.subscription_sync.sync_subscriptions
POST /api/method/verenigingen.verenigingen_payments.mollie.api.payment_sync_system.reconcile_payments
```

## Logging

### Structured Format
```python
from verenigingen.verenigingen_payments.mollie.utils.logging import log_payment_processing

log_payment_processing(payment_id, "webhook_received", "success", {
    "donation_name": "DON-001",
    "amount": 25.00
})
```

### Security Filtering
Sensitive data (API keys, tokens) is automatically redacted from logs.

### Performance Tracking
```python
from verenigingen.verenigingen_payments.mollie.utils.logging import mollie_operation_logger

@mollie_operation_logger("payment_creation")
def create_payment(data):
    # Operation timing captured automatically
    return result
```

## Error Handling

### Exception Hierarchy
```python
from verenigingen.verenigingen_payments.mollie.exceptions import (
    MollieWebhookError,
    MolliePaymentError,
    MollieValidationError,
    MollieSecurityError
)

try:
    service.process_webhook(payment_id)
except MollieWebhookError as e:
    logger.error(f"Webhook failed: {e}")
except MolliePaymentError as e:
    logger.error(f"Payment failed: {e}")
```

### Structured Error Responses
```python
{
    "status": "error",
    "error_type": "MollieWebhookError",
    "message": "No donation found for payment",
    "payment_id": "tr_123",
    "context": {
        "operation": "find_donation",
        "timestamp": "2024-01-01T12:00:00Z"
    }
}
```

## Monitoring

### Health Status
```python
from verenigingen.verenigingen_payments.mollie.utils.monitoring import get_mollie_health_status

health = get_mollie_health_status()
print(f"Status: {health['health_check']['overall_status']}")
print(f"API latency: {health['health_check']['details'][0]['latency']}ms")
```

### Performance Metrics
```python
from verenigingen.verenigingen_payments.mollie.utils.monitoring import performance_monitor

stats = performance_monitor.get_operation_stats("webhook_processing", hours=24)
print(f"Success rate: {stats['success_rate']:.1f}%")
print(f"Average duration: {stats['avg_duration']:.2f}s")
```

### Alert Thresholds
- **Slow Operations**: Warning when operation exceeds 2 seconds
- **Error Rates**: Alert when success rate drops below 85%
- **Service Degradation**: Notification when health checks fail

## Testing

### Run Tests
```bash
# Unit tests
bench --site dev.veganisme.net run-tests --module verenigingen.verenigingen_payments.mollie.tests

# Integration tests
bench --site dev.veganisme.net run-tests --module verenigingen.verenigingen_payments.mollie.tests.integration
```

### Test Helpers
```python
from verenigingen.verenigingen_payments.mollie.utils.test_helpers import (
    create_test_member_with_subscription,
    test_mollie_subscription_creation,
    test_mollie_webhook_simulation,
)

# Create test data
member = create_test_member_with_subscription("Test", "User")

# Test subscription flow
test_mollie_subscription_creation(member.name, 25.0, "1 month")

# Simulate webhook
test_mollie_webhook_simulation(member.name, 25.0)
```

## Configuration

Configuration is managed through **Mollie Settings** DocType:
- API keys (test/live)
- Webhook endpoints
- Default payment methods
- Subscription settings

Access via: Verenigingen Payments > Mollie Settings
